"""Location recovery for the Queensland crash notebook (V6 onwards).

This module holds the coordinate and locality recovery that V5 ran inline (V5 cells 16-41).
The logic is unchanged. The public-layer helpers it relies on are imported from
`traffic_spatial_lookup.py`, which already defined them identically, so there is one copy of each.

`recover_locations()` runs the whole sequence and returns a `LocationRecovery` with the
cleaned crash table, the reconciliation audit and the validation tables the notebook displays.
The slow statewide public-layer pass is cached under `cache_dir`. The cache key covers the crash
data, the spatial layers and the source of both modules, so any change re-runs it.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from shapely import STRtree, get_parts, make_valid, transform
from shapely.geometry import Point, shape

import traffic_spatial_lookup as spatial
from traffic_spatial_lookup import (
    CROSS, FORWARD, GNAF_FILE, ID, INVERSE, LAT, LON, ROADWAY, STREET,
    address_references, canonical_street, features, forward_location, historical_corroboration,
    missing, polygons, reverse_road, road_catalogue, road_spellings, second_pass_location,
    second_pass_streets, shapefile_polygons,
)

CRASH_ID = ID
COORDS = [LAT, LON]
LGA = 'Loc_Local_Government_Area'
SUBURB = 'Loc_Suburb'
CROSS_STREET = CROSS
STATE_ROAD = 'State_Road_Name'
YEAR = 'Crash_Year'
SPATIAL_FILES = ['roads.geojson.gz', 'locality.geojson.gz', 'postal.geojson.gz', 'police.zip', GNAF_FILE]
ESTIMATED_LOCALITY_COLUMNS = ['Estimated_Suburb', 'Estimated_Local_Government_Area']
SECOND_PASS_FIELDS = [
    'Second_pass_status', 'Second_pass_road_extent_m', 'Second_pass_address_sites',
    'Second_pass_crash_donors', 'Second_pass_review_latitude', 'Second_pass_review_longitude',
    'Second_pass_review_basis',
]
GNAF_FIELDS = [
    'GNAF_lookup_status', 'GNAF_reference_address', 'GNAF_reference_street',
    'GNAF_reference_locality', 'GNAF_reference_postcode', 'GNAF_reference_distance_m',
    'GNAF_address_id',
]
SUBURB_FIELDS = [
    'Suburb_Only_Status', 'Suburb_Only_Name', 'Suburb_Only_Method',
    'Suburb_Only_Crash_Donors', 'Suburb_Only_GNAF_Sites',
]


# ---------------------------------------------------------------------------------------------
# Distances and labels
# ---------------------------------------------------------------------------------------------
def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle (Haversine) distance in kilometres between two sets of points."""
    lat1, lon1, lat2, lon2 = (np.radians(value) for value in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2
    a += np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def normalized_label(values):
    """Lower-case and trim labels, turning placeholders such as 'unknown' or 'unnamed' into missing values."""
    values = values.str.strip().str.casefold()
    placeholders = values.isin(['', 'unknown', 'not stated', 'not applicable', 'no road name'])
    generic = values.str.match(r'^(unnamed|invalid street|un-named)', na=False)
    return values.mask(placeholders | generic)


def build_geography(raw):
    """Normalised location keys, with each intersection's two roads in alphabetical order."""
    geography = raw[[LGA, SUBURB, STREET, CROSS_STREET, STATE_ROAD]].apply(normalized_label)
    road, cross = geography[STREET], geography[CROSS_STREET]
    valid_intersection = (road.notna() & cross.notna() & road.ne(cross)).fillna(False)
    swap_roads = road.gt(cross).fillna(False)
    geography['Road A'] = road.where(~swap_roads, cross).where(valid_intersection)
    geography['Road B'] = cross.where(~swap_roads, road).where(valid_intersection)
    return geography


# Donor groups to try in order when locality labels are usable.
LOCATION_LEVELS = [
    ('intersection median', [LGA, SUBURB, 'Road A', 'Road B']),
    ('street within suburb median', [LGA, SUBURB, STREET]),
    ('suburb median', [LGA, SUBURB]),
    ('LGA median', [LGA]),
]
# Fallback groups for records without locality labels, each with its own spread limit (km).
STREET_LEVELS = [
    ('compact statewide intersection', ['Road A', 'Road B'], 1, True),
    ('compact street and state-road segment', [STREET, STATE_ROAD], 1, True),
    ('compact statewide street', [STREET], 1, True),
    ('coarse statewide street', [STREET], 3, False),
]


# ---------------------------------------------------------------------------------------------
# Step 1: donor-median coordinates (V5 cell 16)
# ---------------------------------------------------------------------------------------------
def estimate_coordinates(raw, geography, donor_rows, target_rows, levels, minimum_donors, compact_levels=()):
    """Median of matching donor crashes, trying each level until one has enough donors."""
    estimates = pd.DataFrame(index=target_rows, columns=COORDS, dtype=float)
    locality = pd.DataFrame(index=target_rows, columns=ESTIMATED_LOCALITY_COLUMNS, dtype='string')
    method = pd.Series('unresolved', index=target_rows, dtype='string')
    donor_count = pd.Series(0, index=target_rows, dtype='int64')
    donors = geography.loc[donor_rows].join(raw.loc[donor_rows, COORDS])
    donors[ESTIMATED_LOCALITY_COLUMNS] = raw.loc[donor_rows, [SUBURB, LGA]].to_numpy()
    donors['known_locality'] = donors[[SUBURB, LGA]].notna().all(axis=1)

    named_levels = [(label, keys, None, False) for label, keys in levels]
    for label, keys, max_spread, require_suburb in [*named_levels, *compact_levels]:
        remaining = method.index[method.eq('unresolved')]
        if not len(remaining):
            break
        groups = donors.groupby(keys)
        medians = groups[COORDS].median()
        medians['donor_count'] = groups.size()
        eligible = medians['donor_count'].ge(minimum_donors)

        if max_spread is not None:
            bounds = groups[COORDS].agg(['min', 'max'])
            spread = distance_km(
                bounds[(COORDS[0], 'min')], bounds[(COORDS[1], 'min')],
                bounds[(COORDS[0], 'max')], bounds[(COORDS[1], 'max')],
            )
            suburb_agrees = groups[SUBURB].nunique().eq(1)
            eligible &= groups[LGA].nunique().eq(1) & groups['known_locality'].all() & spread.le(max_spread)
            if require_suburb:
                eligible &= suburb_agrees
            medians = medians.join(groups[ESTIMATED_LOCALITY_COLUMNS].first())
            medians['Estimated_Suburb'] = medians['Estimated_Suburb'].where(suburb_agrees)

        matched = geography.loc[remaining, keys].join(medians.loc[eligible], on=keys).dropna(subset=COORDS)
        estimates.loc[matched.index, COORDS] = matched[COORDS]
        method.loc[matched.index] = label
        donor_count.loc[matched.index] = matched['donor_count'].astype(int)
        if max_spread is not None:
            locality.loc[matched.index, ESTIMATED_LOCALITY_COLUMNS] = matched[ESTIMATED_LOCALITY_COLUMNS]
    return estimates, method, donor_count, locality


def validate_donor_rules(raw, geography, observed, seed, holdout_size=10_000):
    """Withhold known locations and measure the error of each donor rule."""
    holdout = raw.loc[observed].sample(n=min(holdout_size, len(observed)), random_state=seed).index
    rows = []
    for label, levels, minimum, fallback in [
        ('V2-style suburb/LGA', [('suburb median', [SUBURB]), ('LGA median', [LGA])], 1, []),
        ('V3 named-locality hierarchy', LOCATION_LEVELS, 3, []),
        ('V3 street fallback, locality withheld', [], 3, STREET_LEVELS),
    ]:
        predicted, methods, _, _ = estimate_coordinates(
            raw, geography, observed.difference(holdout), holdout, levels, minimum, fallback
        )
        matched = methods.index[methods.ne('unresolved')]
        errors = distance_km(
            raw.loc[matched, COORDS[0]], raw.loc[matched, COORDS[1]],
            predicted.loc[matched, COORDS[0]], predicted.loc[matched, COORDS[1]],
        )
        rows.append({
            'Method': label, 'Test locations': len(holdout), 'Estimated': len(matched),
            'Median error (km)': errors.median(), '90th percentile error (km)': errors.quantile(.90),
        })
    # The last loop iteration is the street fallback; break its errors down by rule.
    fallback_errors = pd.DataFrame({'Method': methods.loc[matched], 'Error (km)': errors})
    fallback_table = fallback_errors.groupby('Method')['Error (km)'].agg(
        Estimated='size', Median='median', P90=lambda values: values.quantile(.90)
    )
    return pd.DataFrame(rows).set_index('Method'), fallback_table


# ---------------------------------------------------------------------------------------------
# Step 2: road attributes from agreeing neighbours (V5 cell 20)
# ---------------------------------------------------------------------------------------------
def infer_road_attribute(raw, cleaned, geography, column, method_name, minimum_donors, radius_km,
                         year_window=None):
    """Fill a missing road attribute only where nearby crashes on the same road agree on one value."""
    method_column = f'{column}_Method'
    count_column = f'{column}_Donor_Count'
    cleaned[method_column] = pd.Series(
        np.where(raw[column].notna(), 'observed', 'unresolved'), index=raw.index, dtype='string'
    )
    cleaned[count_column] = pd.Series(pd.NA, index=raw.index, dtype='Int64')
    complete_coordinates = raw[COORDS].notna().all(axis=1)
    for index in raw.index[raw[column].isna() & complete_coordinates]:
        keys = [LGA, SUBURB, STREET]
        road_key = geography.loc[index, keys]
        if road_key.isna().any():
            continue
        same_road = geography[keys].eq(road_key).all(axis=1, skipna=False).fillna(False)
        eligible = same_road & complete_coordinates & raw[column].notna()
        if year_window is not None:
            eligible &= raw[YEAR].sub(raw.at[index, YEAR]).abs().le(year_window)
        donors = raw.loc[eligible, [*COORDS, column]]
        if radius_km == 0:
            donors = donors.loc[donors[COORDS].eq(raw.loc[index, COORDS]).all(axis=1)]
        else:
            distances = distance_km(
                raw.at[index, COORDS[0]], raw.at[index, COORDS[1]],
                donors[COORDS[0]], donors[COORDS[1]],
            )
            donors = donors.loc[distances.le(radius_km)]
        if len(donors) >= minimum_donors and donors[column].nunique() == 1:
            cleaned.at[index, column] = donors[column].iloc[0]
            cleaned.at[index, method_column] = method_name
            cleaned.at[index, count_column] = len(donors)


# ---------------------------------------------------------------------------------------------
# Step 3: suburb recovery helpers and the public-layer passes (V5 cells 33 and 37)
# ---------------------------------------------------------------------------------------------
def suburb_key(value):
    return '' if missing(value) else ' '.join(str(value).strip().casefold().split())


def suburb_name_lookup(locality_records, catalogue):
    """Match complete statewide road geometries to localities, retaining alternate same-name roads."""
    projected = [transform(geom, FORWARD, interleaved=False) for _, geom in locality_records]
    projected = [geom if geom.is_valid else make_valid(geom) for geom in projected]
    locality_tree = STRtree(projected)

    @lru_cache(maxsize=None)
    def road_suburbs(name):
        touched = set()
        segments = catalogue.get(name, [])
        if not segments:
            return touched
        for _, segment in segments:
            candidates = locality_tree.query(segment, predicate='intersects')
            overlaps = {int(i): projected[i].intersection(segment).length for i in candidates}
            overlaps = {i: length for i, length in overlaps.items() if length > .05}
            if not overlaps or sum(overlaps.values()) < .95 * segment.length:
                return set()
            touched.update(overlaps)
        return {locality_records[i][0][0] for i in touched if locality_records[i][0][0]}

    @lru_cache(maxsize=None)
    def candidates(first, second):
        if not first:
            return None, 'no usable street name'
        if second and second != first:
            first_roads = catalogue.get(first, [])
            cross_roads = [line for _, line in catalogue.get(second, [])]
            cross_index = STRtree(cross_roads)
            suburbs = set()
            for _, road in first_roads:
                for position in cross_index.query(road, predicate='intersects'):
                    crossing = road.intersection(cross_roads[position])
                    for part in get_parts(crossing):
                        if part.is_empty:
                            continue
                        if part.geom_type != 'Point':
                            return None, 'named roads overlap beyond an intersection'
                        matches = locality_tree.query(part, predicate='covered_by')
                        if not len(matches):
                            return None, 'a mapped crossing lacks a locality'
                        suburbs.update(locality_records[int(i)][0][0] for i in matches)
            if len(suburbs) == 1:
                return next(iter(suburbs)), 'recorded street pair'
            return None, 'street pair does not identify one mapped suburb'
        suburbs = road_suburbs(first)
        if len(suburbs) == 1:
            return next(iter(suburbs)), 'all mapped segments of recorded street'
        return None, ('street occurs in multiple suburbs' if suburbs
                      else 'street has no complete locality match')
    return candidates


def infer_suburb(candidate, donors, address_sites, localities):
    """Assign a suburb without coordinates only when recorded crashes or address sites agree with it."""
    suburb, method = candidate
    if suburb is None:
        return {'Suburb_Only_Status': method}
    labels = donors['Loc_Suburb'].map(suburb_key)
    known = labels[labels.ne('')]
    if known.ne(suburb_key(suburb)).any():
        return {'Suburb_Only_Status': 'recorded crash suburbs disagree with mapped suburb'}
    if len(known) >= 2:
        return {'Suburb_Only_Status': 'estimated', 'Suburb_Only_Name': suburb,
                'Suburb_Only_Method': method + ' + recorded crashes', 'Suburb_Only_Crash_Donors': len(known)}

    checked = [localities(Point(*INVERSE(x, y))) for x, y in address_sites]
    if len(checked) >= 3 and all(area and suburb_key(area[0]) == suburb_key(suburb) for area in checked):
        return {'Suburb_Only_Status': 'estimated', 'Suburb_Only_Name': suburb,
                'Suburb_Only_Method': method + ' + G-NAF sites', 'Suburb_Only_GNAF_Sites': len(checked),
                'Suburb_Only_Crash_Donors': len(known)}
    return {'Suburb_Only_Status': 'mapped suburb lacks agreeing crash or G-NAF evidence'}


def match_public_layers(raw_crashes, prepared_crashes, layers, seed):
    """Run both public-layer passes for every eligible crash and return the matches with validation results."""
    fields = [ID, LAT, LON, STREET, CROSS, 'Loc_Suburb', 'Loc_Local_Government_Area',
              'Loc_Post_Code', 'Loc_Police_Region', ROADWAY]
    raw = raw_crashes[fields].set_index(ID)
    base = prepared_crashes.set_index(ID)[[LAT, LON]]
    assert raw.index.equals(base.index)
    records = {}
    missing_coords = raw[[LAT, LON]].isna().any(axis=1)
    coordinate_donors = base[[LAT, LON]].notna().all(axis=1)
    need_forward = raw.loc[missing_coords & ~coordinate_donors]
    names = set().union(*(road_spellings(value) for column in (STREET, CROSS) for value in need_forward[column]))
    street_missing = ~raw[STREET].map(lambda street: bool(road_spellings(street)))
    reverse_targets = raw.loc[~missing_coords & street_missing]
    normalized = raw[[STREET, CROSS]].apply(lambda column: column.map({
        value: canonical_street(value) for value in column.dropna().unique()
    }).fillna(''))
    target_names = set(normalized.loc[need_forward.index, STREET]) - {''}
    comparable = normalized[STREET].isin(target_names) & ~missing_coords
    with_junction = raw.loc[comparable & normalized[CROSS].ne('')]
    without_junction = raw.loc[comparable & normalized[CROSS].eq('')]
    holdout = pd.concat([
        with_junction.sample(n=min(2000, len(with_junction)), random_state=seed),
        without_junction.sample(n=min(3000, len(without_junction)), random_state=seed),
    ])
    named_street_counts = normalized.loc[comparable, STREET].value_counts()
    rare = named_street_counts.index[named_street_counts.le(15)]
    rare_observed = raw.loc[comparable & normalized[STREET].isin(rare)]
    holdout = pd.concat([holdout, rare_observed.loc[~rare_observed.index.isin(holdout.index)]])
    for column in [STREET, CROSS]:
        names.update(name for value in holdout[column].unique() for name in road_spellings(value))
    normalized_names = set(normalized.loc[need_forward.index.union(holdout.index)].to_numpy().ravel()) - {''}
    catalogue, normalized_catalogue, road_candidates, road_count = road_catalogue(
        layers / 'roads.geojson.gz', names, reverse_targets, normalized_names
    )
    road_index = STRtree([geometry for _, geometry in road_candidates])
    print(f'Comparing {len(need_forward):,} unlocated crashes to exact road names and aliases.', flush=True)
    for crash_id, row in need_forward.iterrows():
        records[int(crash_id)] = forward_location(row, catalogue)

    address_path = layers / GNAF_FILE
    addresses = second_pass_streets(address_path, target_names)
    second_results = {}
    observed = raw.loc[~missing_coords, [LAT, LON, 'Loc_Suburb']]
    observed_labels = normalized.loc[observed.index, [STREET, CROSS]]
    observed_roads = pd.concat([
        observed.loc[observed_labels[column].isin(target_names)].assign(name=observed_labels[column])
        for column in [STREET, CROSS]
    ])
    donors_by_street = {
        name: donor_rows.loc[~donor_rows.index.duplicated()]
        for name, donor_rows in observed_roads.groupby('name')
    }
    junction_rows = observed_labels[
        observed_labels[STREET].ne('') & observed_labels[CROSS].ne('')
        & (observed_labels[STREET].isin(target_names) | observed_labels[CROSS].isin(target_names))
    ]
    junction_keys = pd.Series(
        [tuple(sorted(pair)) for pair in junction_rows.itertuples(index=False, name=None)],
        index=junction_rows.index,
    )
    donors_by_junction = {
        pair: donor_rows for pair, donor_rows in observed.loc[junction_rows.index].groupby(junction_keys)
    }
    no_donors = observed.iloc[:0]

    # Second-pass estimate for one crash. Results are cached by street pair and roadway type.
    def estimate_again(crash_id, withheld=False):
        first, second = normalized.loc[crash_id, [STREET, CROSS]]
        roadway = raw.at[crash_id, ROADWAY]
        key = (first, second, roadway if second else None)
        if key not in second_results:
            second_results[key] = second_pass_location(*key, normalized_catalogue, addresses)
        estimate = second_results[key]
        if estimate.get('Second_pass_status') != 'estimated':
            return estimate
        if second:
            donors = donors_by_junction.get(tuple(sorted((first, second))), no_donors)
        else:
            donors = donors_by_street.get(first, no_donors)
        return historical_corroboration(estimate, donors, excluded_id=crash_id if withheld else None)

    errors = defaultdict(list)
    eligible = 0
    first_pass_cache = {}
    for crash_id, row in holdout.iterrows():
        key = tuple(frozenset(road_spellings(row[column])) for column in [STREET, CROSS])
        if key not in first_pass_cache:
            first_pass_cache[key] = forward_location(row, catalogue)['Forward_status']
        if first_pass_cache[key] == 'estimated':
            continue
        eligible += 1
        estimate = estimate_again(crash_id, withheld=True)
        if estimate['Second_pass_status'] == 'estimated':
            a = np.asarray(FORWARD(row[LON], row[LAT]))
            b = np.asarray(FORWARD(estimate['Public_longitude'], estimate['Public_latitude']))
            errors[estimate['Public_coordinate_basis']].append(float(np.linalg.norm(a - b)))
    validation = {
        'sample_rows': len(holdout), 'first_pass_unresolved': eligible,
        'methods': {method: {'estimates': len(values), 'median_error_m': round(float(np.median(values)), 1),
                            'p90_error_m': round(float(np.quantile(values, .90)), 1)}
                    for method, values in errors.items()},
    }
    for crash_id in need_forward.index:
        if records[int(crash_id)]['Forward_status'] != 'estimated':
            records[int(crash_id)].update(estimate_again(crash_id))
    print('Second-pass withheld-coordinate check:', validation, flush=True)

    locality_records = [
        ((f['properties']['locality'], f['properties']['lga']), shape(f['geometry']))
        for f in features(layers / 'locality.geojson.gz') if f['geometry']
    ]
    localities = polygons(iter(locality_records))
    suburb_candidates = suburb_name_lookup(locality_records, normalized_catalogue)
    suburb_tests, suburb_correct, suburb_eligible = 0, 0, 0
    for crash_id, row in holdout.iterrows():
        first, second = normalized.loc[crash_id, [STREET, CROSS]]
        observed_suburb = suburb_key(row['Loc_Suburb'])
        first_key = tuple(frozenset(road_spellings(row[column])) for column in [STREET, CROSS])
        if (not observed_suburb or first_pass_cache[first_key] == 'estimated'
                or estimate_again(crash_id, withheld=True).get('Second_pass_status') == 'estimated'):
            continue
        suburb_eligible += 1
        labels = (donors_by_junction.get(tuple(sorted((first, second))), no_donors)
                  if second else donors_by_street.get(first, no_donors))
        result = infer_suburb(suburb_candidates(first, second), labels.drop(index=crash_id, errors='ignore'),
                              addresses.get(first, ()), localities)
        if 'Suburb_Only_Name' in result:
            suburb_tests += 1
            suburb_correct += suburb_key(result['Suburb_Only_Name']) == observed_suburb

    for crash_id in need_forward.index:
        existing = records[int(crash_id)]
        if ('Public_latitude' in existing or not missing(raw.at[crash_id, 'Loc_Suburb'])):
            continue
        first, second = normalized.loc[crash_id, [STREET, CROSS]]
        labels = (donors_by_junction.get(tuple(sorted((first, second))), no_donors)
                  if second else donors_by_street.get(first, no_donors))
        existing.update(infer_suburb(suburb_candidates(first, second), labels, addresses.get(first, ()), localities))
    postal = polygons(((f['properties']['POA_CODE21'],), shape(f['geometry']))
                      for f in features(layers / 'postal.geojson.gz'))
    police = polygons(shapefile_polygons(layers / 'police.zip', ('REGION',)))
    locations_missing = raw[fields[3:]].drop(columns=[CROSS, ROADWAY]).map(missing).any(axis=1)
    for crash_id, row in raw.loc[missing_coords | locations_missing | street_missing].iterrows():
        existing = records.setdefault(int(crash_id), {})
        estimated = bool(missing_coords.at[crash_id])
        if estimated and (existing.get('Forward_status') == 'estimated'
                          or existing.get('Second_pass_status') == 'estimated'):
            lat, lon = existing['Public_latitude'], existing['Public_longitude']
        elif coordinate_donors.at[crash_id]:
            lat, lon = base.loc[crash_id, [LAT, LON]]
        else:
            continue
        point = Point(lon, lat)
        if estimated or missing(row['Loc_Suburb']) or missing(row['Loc_Local_Government_Area']):
            locality = localities(point)
            if locality:
                existing['Public_suburb'], existing['Public_lga'] = locality
        if estimated or missing(row['Loc_Post_Code']):
            area = postal(point)
            if area:
                existing['Public_postal_area_2021'] = area[0]
        if estimated or missing(row['Loc_Police_Region']):
            region = police(point)
            if region:
                existing['Public_police_region'] = region[0].title()
        if not estimated and street_missing.at[crash_id]:
            existing.update(reverse_road(lon, lat, road_candidates, road_index))

    address_targets = raw.loc[~missing_coords & (locations_missing | street_missing)]
    address_references(address_path, address_targets, records)

    return {
        'public_road_feature_count': road_count,
        'second_pass_validation': validation,
        'suburb_validation': {'eligible': suburb_eligible, 'estimated': suburb_tests,
                              'matching_recorded_suburb': int(suburb_correct)},
        'records': records,
    }


# ---------------------------------------------------------------------------------------------
# Step 4: apply the matches and reconcile (V5 cell 41)
# ---------------------------------------------------------------------------------------------
def has_value(values):
    return normalized_label(values.astype('string')).notna()


def council_name(values):
    """Align council naming differences between the crash file and the boundary layer."""
    return normalized_label(values).str.replace(r' regional$', ' region', regex=True).replace({
        'moreton bay region': 'moreton bay city',
    })


def apply_public_matches(raw, cleaned, snapshot):
    """Join the public-layer results to the crash table and build the reconciliation audit."""
    tables, messages = {}, []
    public_matches = pd.DataFrame.from_dict(
        {int(crash_id): values for crash_id, values in snapshot['records'].items()}, orient='index'
    )
    assert public_matches.index.is_unique and public_matches.index.isin(raw[CRASH_ID]).all()
    lookup = public_matches.reindex(raw[CRASH_ID]).set_axis(raw.index)
    if 'Public_road_segments' in lookup:
        lookup['Public_road_segments'] = lookup['Public_road_segments'].map(
            lambda segments: ', '.join(segments) if isinstance(segments, list) else pd.NA
        )
    for column in ['Public_latitude', 'Public_longitude']:
        if column not in lookup:
            lookup[column] = float('nan')
    for column in ['Public_street', 'Public_suburb', 'Public_lga', 'Public_postal_area_2021',
                   'Public_police_region', 'Public_coordinate_basis']:
        if column not in lookup:
            lookup[column] = pd.NA
        lookup[column] = lookup[column].astype('string')

    # Apply public coordinate estimates only where coordinates are still unresolved.
    public_pairs = lookup[['Public_latitude', 'Public_longitude']].notna().all(axis=1)
    assert cleaned.loc[public_pairs, 'Coordinate_Method'].eq('unresolved').all()
    cleaned.loc[public_pairs, COORDS] = lookup.loc[public_pairs, ['Public_latitude', 'Public_longitude']].to_numpy(dtype=float)
    second_pass = lookup.get('Second_pass_status', pd.Series(index=raw.index, dtype='string')).eq('estimated').fillna(False)
    cleaned.loc[public_pairs, 'Coordinate_Method'] = 'public road network estimate'
    cleaned.loc[second_pass, 'Coordinate_Method'] = 'public second-pass estimate'
    for column in SECOND_PASS_FIELDS:
        if column not in lookup:
            lookup[column] = pd.NA
    cleaned.loc[public_pairs, 'Coordinate_Donor_Count'] = pd.NA
    cleaned[STREET] = cleaned[STREET].fillna(lookup['Public_street'])
    cleaned = cleaned.join(lookup.drop(columns=['Public_latitude', 'Public_longitude']))

    for column in GNAF_FIELDS:
        if column not in cleaned:
            cleaned[column] = pd.NA
    recorded_postcode = raw['Loc_Post_Code'].astype('string')
    recorded_postcode = recorded_postcode.where(recorded_postcode.str.fullmatch(r'\d{4}', na=False))
    comparison_postcode = recorded_postcode.fillna(cleaned['Public_postal_area_2021'])
    postal_comparison = cleaned['GNAF_reference_postcode'].notna() & comparison_postcode.notna()
    postal_agreement = cleaned.loc[postal_comparison, 'GNAF_reference_postcode'].eq(
        comparison_postcode.loc[postal_comparison]
    )
    cleaned['GNAF_Postcode_Comparison'] = postal_agreement.map(
        {True: 'same code', False: 'different code'}
    ).reindex(cleaned.index)
    cleaned['GNAF_Postcode_Comparison_Source'] = pd.Series(
        np.where(recorded_postcode.notna(), 'recorded postcode', 'ABS 2021 Postal Area'), index=raw.index,
        dtype='string',
    ).where(postal_comparison)

    # Reconciled fields keep the recorded value and fall back to the public-layer value.
    cleaned['Reconciled_Street'] = raw[STREET].where(has_value(raw[STREET])).fillna(cleaned['Public_street'])
    for column in SUBURB_FIELDS:
        if column not in cleaned:
            cleaned[column] = pd.NA
    suburb_validation = snapshot['suburb_validation']
    messages.append(f"Suburb-only holdout: {suburb_validation['matching_recorded_suburb']:,} matches "
                    f"among {suburb_validation['estimated']:,} estimates "
                    f"from {suburb_validation['eligible']:,} eligible records.")
    cleaned['Reconciled_Suburb'] = raw[SUBURB].where(has_value(raw[SUBURB])).fillna(
        cleaned['Public_suburb']
    ).fillna(cleaned['Estimated_Suburb']).fillna(cleaned['Suburb_Only_Name'])
    cleaned['Reconciled_Local_Government_Area'] = raw[LGA].where(has_value(raw[LGA])).fillna(
        cleaned['Public_lga']
    ).fillna(cleaned['Estimated_Local_Government_Area'])

    # For each location field: what the source recorded, and what is available after estimation.
    recorded = {
        'Coordinate pair': raw[COORDS].notna().all(axis=1),
        'Street name': has_value(raw[STREET]),
        'Suburb': has_value(raw[SUBURB]),
        'Council area': has_value(raw[LGA]),
        'Postcode or Postal Area': has_value(raw['Loc_Post_Code']),
        'Police region': has_value(raw['Loc_Police_Region']),
    }
    available = {
        'Coordinate pair': cleaned[COORDS].notna().all(axis=1),
        'Street name': cleaned['Reconciled_Street'].notna(),
        'Suburb': cleaned['Reconciled_Suburb'].notna(),
        'Council area': cleaned['Reconciled_Local_Government_Area'].notna(),
        'Postcode or Postal Area': recorded['Postcode or Postal Area'] | cleaned['Public_postal_area_2021'].notna(),
        'Police region': recorded['Police region'] | cleaned['Public_police_region'].notna(),
    }
    tables['Location field reconciliation'] = pd.DataFrame([
        {'Field': name, 'Missing or unknown in source': int((~source).sum()),
         'Added or supplied as fallback': int((~source & available[name]).sum()),
         'Still unresolved': int((~available[name]).sum())}
        for name, source in recorded.items()
    ]).set_index('Field')
    messages.append(f"Matched against {snapshot['public_road_feature_count']:,} local Queensland road segments.")
    tables['Coordinate method after public matching'] = (
        cleaned['Coordinate_Method'].value_counts().rename('Crashes').to_frame())
    tables['Reverse street lookup'] = (
        cleaned['Reverse_street_status'].value_counts().rename('Recorded locations').to_frame())
    if cleaned['GNAF_lookup_status'].notna().any():
        tables['G-NAF address references'] = (
            cleaned['GNAF_lookup_status'].value_counts().rename('Recorded locations').to_frame())
        tables['G-NAF postcode comparison'] = (
            cleaned.groupby(['GNAF_Postcode_Comparison_Source', 'GNAF_Postcode_Comparison'])
            .size().rename('Address references').to_frame())
    validation = snapshot.get('second_pass_validation')
    if validation:
        messages.append(f"Second-pass holdout: {validation['first_pass_unresolved']:,} of "
                        f"{validation['sample_rows']:,} sampled crashes were unresolved by the first road-network pass.")
        if validation['methods']:
            tables['Second-pass withheld-coordinate errors'] = (
                pd.DataFrame.from_dict(validation['methods'], orient='index')
                .rename_axis('Second-pass method').rename(columns={
                    'estimates': 'Holdout estimates', 'median_error_m': 'Median error (m)',
                    'p90_error_m': '90th percentile error (m)',
                }))
    tables['Crashes still missing coordinates'] = (
        cleaned.loc[~available['Coordinate pair'], 'Second_pass_status']
        .fillna('no usable match').value_counts().rename('Crashes still missing coordinates').to_frame())

    for label, old, new, normalize in [
        ('Suburb', 'Estimated_Suburb', 'Public_suburb', normalized_label),
        ('Council_Area', 'Estimated_Local_Government_Area', 'Public_lga', council_name),
    ]:
        both = cleaned[[old, new]].notna().all(axis=1)
        original_match = normalized_label(cleaned.loc[both, old]).eq(normalized_label(cleaned.loc[both, new]))
        match = normalize(cleaned.loc[both, old]).eq(normalize(cleaned.loc[both, new]))
        statuses = pd.Series('different location labels', index=match.index, dtype='string')
        statuses.loc[match] = 'same location after name normalization'
        statuses.loc[original_match] = 'same location label'
        cleaned[f'{label}_Boundary_Comparison'] = statuses.reindex(cleaned.index)
        messages.append(f"{label.replace('_', ' ')}: {int((~match).sum())} disagreements after name "
                        f"normalization among {int(both.sum())} donor/boundary comparisons.")

    # The reconciliation table lists every crash that was eligible for a public lookup.
    workflow_rows = raw[CRASH_ID].isin([int(crash_id) for crash_id in snapshot['records']])
    gap_audit = cleaned.loc[workflow_rows, [
        CRASH_ID, YEAR, STREET, CROSS_STREET, STATE_ROAD, *COORDS, 'Coordinate_Method',
        'Coordinate_Donor_Count', SUBURB, LGA, 'Loc_Post_Code', 'Loc_Police_Region',
        'Estimated_Suburb', 'Estimated_Local_Government_Area',
        'Reconciled_Street', 'Reconciled_Suburb', 'Reconciled_Local_Government_Area', 'Public_street',
        'Public_street_distance_m', 'Public_suburb', 'Public_lga',
        'Suburb_Boundary_Comparison', 'Council_Area_Boundary_Comparison', 'Public_postal_area_2021',
        'Public_police_region', 'Public_coordinate_basis', 'Public_road_segments', 'Forward_status',
        'Reverse_street_status', *SECOND_PASS_FIELDS, *SUBURB_FIELDS,
        *GNAF_FIELDS, 'GNAF_Postcode_Comparison_Source', 'GNAF_Postcode_Comparison',
    ]].copy()
    gap_audit['Recorded_Street'] = raw.loc[workflow_rows, STREET]
    gap_audit['Missing_Location_Fields'] = [
        ', '.join(name for name, valid in available.items() if not valid.at[index])
        for index in gap_audit.index
    ]
    return cleaned, gap_audit, recorded, available, second_pass, tables, messages


# ---------------------------------------------------------------------------------------------
# Whole pipeline with a cache for the slow public-layer pass
# ---------------------------------------------------------------------------------------------
@dataclass
class LocationRecovery:
    cleaned: pd.DataFrame
    gap_audit: pd.DataFrame
    targets: pd.Index
    recorded: dict
    available: dict
    second_pass: pd.Series
    missing_audit: pd.DataFrame
    snapshot: dict
    cache_file: Path | None
    cache_hit: bool
    tables: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)


def _file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cache_key(raw, prepared, spatial_dir):
    """Digest of everything the public-layer pass depends on."""
    digest = hashlib.sha256()
    for frame in (raw, prepared[[CRASH_ID, *COORDS]]):
        digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    for name in SPATIAL_FILES:
        digest.update(name.encode() + _file_digest(Path(spatial_dir) / name).encode())
    for module in (spatial.__file__, __file__):
        digest.update(_file_digest(module).encode())
    return digest.hexdigest()[:20]


def recover_locations(raw, spatial_dir, seed=42, cache_dir=None, refresh=False):
    """Run the V5 location recovery sequence and return its results.

    raw: the crash-level source table, never modified.
    spatial_dir: folder holding the public layers listed in SPATIAL_FILES.
    cache_dir: where to keep the public-layer snapshot. None disables the cache.
    refresh: True ignores an existing snapshot and recomputes it.
    """
    spatial_dir = Path(spatial_dir)
    tables, messages = {}, []
    geography = build_geography(raw)
    observed = raw.index[raw[COORDS].notna().all(axis=1)]
    targets = raw.index[raw[COORDS].isna().any(axis=1)]

    coordinate_validation, fallback_table = validate_donor_rules(raw, geography, observed, seed)
    tables['Donor-rule validation on withheld locations'] = coordinate_validation
    tables['Street-fallback errors by rule'] = fallback_table

    # `cleaned` starts as a copy of the source. Estimates fill blanks only and keep their method and donor count.
    cleaned = raw.copy()
    estimated, methods, donor_count, inferred_locality = estimate_coordinates(
        raw, geography, observed, targets, LOCATION_LEVELS, 3, STREET_LEVELS
    )
    for column in COORDS:
        cleaned[column] = raw[column].fillna(estimated[column])
    cleaned['Coordinate_Method'] = pd.Series('observed', index=raw.index, dtype='string')
    cleaned.loc[targets, 'Coordinate_Method'] = methods
    cleaned['Coordinate_Donor_Count'] = pd.Series(pd.NA, index=raw.index, dtype='Int64')
    cleaned.loc[targets, 'Coordinate_Donor_Count'] = donor_count.astype('Int64')
    cleaned[ESTIMATED_LOCALITY_COLUMNS] = inferred_locality.reindex(raw.index)
    tables['Coordinate method after donor medians'] = (
        cleaned['Coordinate_Method'].value_counts().rename('Crashes').to_frame())

    # Speed limit: two or more agreeing reports within 25 m and two crash years.
    infer_road_attribute(raw, cleaned, geography, 'Crash_Speed_Limit', 'same road within 25 m and 2 years',
                         2, .025, year_window=2)
    # Alignment: three or more agreeing reports at exactly the same coordinates.
    for column in ['Crash_Road_Horiz_Align', 'Crash_Road_Vert_Align']:
        infer_road_attribute(raw, cleaned, geography, column, 'same road and recorded coordinates', 3, 0)
    missing_audit = pd.DataFrame({
        'Missing before': raw.isna().sum(),
        'Missing after': cleaned[raw.columns].isna().sum(),
    })
    missing_audit['Values inferred'] = missing_audit['Missing before'] - missing_audit['Missing after']
    missing_audit = missing_audit.loc[missing_audit['Missing before'].gt(0)]
    tables['Missing values before and after local inference'] = missing_audit

    cache_file, cache_hit = None, False
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f'location_recovery_{cache_key(raw, cleaned, spatial_dir)}.pkl'
    if cache_file is not None and cache_file.is_file() and not refresh:
        with cache_file.open('rb') as stream:
            snapshot = pickle.load(stream)
        cache_hit = True
    else:
        # This is the slowest step: it reads the statewide road, boundary and address layers.
        snapshot = match_public_layers(raw, cleaned, spatial_dir, seed)
        if cache_file is not None:
            temporary = cache_file.with_suffix('.tmp')
            with temporary.open('wb') as stream:
                pickle.dump(snapshot, stream)
            temporary.replace(cache_file)

    cleaned, gap_audit, recorded, available, second_pass, apply_tables, apply_messages = (
        apply_public_matches(raw, cleaned, snapshot))
    tables.update(apply_tables)
    messages.extend(apply_messages)
    return LocationRecovery(
        cleaned=cleaned, gap_audit=gap_audit, targets=targets, recorded=recorded, available=available,
        second_pass=second_pass, missing_audit=missing_audit, snapshot=snapshot, cache_file=cache_file,
        cache_hit=cache_hit, tables=tables, messages=messages,
    )
