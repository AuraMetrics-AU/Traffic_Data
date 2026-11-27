"""Match crash locations locally against public Queensland spatial downloads."""
import argparse
from collections import defaultdict
from datetime import date
from gzip import open as gzip_open
from hashlib import file_digest
import json
import re
from pathlib import Path
from zipfile import ZipFile

import ijson
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree
import shapefile
from shapely import STRtree, get_coordinates, get_parts, line_merge, transform, union_all
from shapely.geometry import Point, shape
from shapely.ops import nearest_points

BASE = 'https://spatial-gis.information.qld.gov.au/arcgis/rest/services'
LOCALITY = BASE + '/Basemaps/FoundationData/MapServer/6'
POSTAL = 'https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/POA/MapServer/0'
POLICE = 'https://open-crime-data.s3-ap-southeast-2.amazonaws.com/document/QPS_REGIONS.zip'
FORWARD = Transformer.from_crs(4326, 9473, always_xy=True).transform
INVERSE = Transformer.from_crs(9473, 4326, always_xy=True).transform
ID = 'Crash_Ref_Number'
LAT, LON = 'Crash_Latitude', 'Crash_Longitude'
STREET, CROSS = 'Crash_Street', 'Crash_Street_Intersecting'
ROADWAY = 'Crash_Roadway_Feature'
ROAD_FIELDS = 'road_name_full,segment_id,ground_rel'
PUBLIC_METHOD = 'public road network estimate'
SECOND_PASS_METHOD = 'public second-pass estimate'
ROAD_DOWNLOAD = 'https://queensland.opendatasoft.com/explore/assets/roads-and-tracks/'
GNAF_FILE = 'G-NAF Queensland 2026-08.parquet'
GNAF_SOURCE = 'https://github.com/minus34/gnaf-loader#option-4---geoparquet-files-in-s3'

ABBREVIATIONS = {
    'RD': 'ROAD', 'ST': 'STREET', 'AVE': 'AVENUE', 'AV': 'AVENUE', 'DR': 'DRIVE',
    'HWY': 'HIGHWAY', 'PDE': 'PARADE', 'CT': 'COURT', 'CL': 'CLOSE', 'LN': 'LANE',
    'CCT': 'CIRCUIT', 'CRES': 'CRESCENT', 'TCE': 'TERRACE', 'BLVD': 'BOULEVARD',
    'PL': 'PLACE', 'PKWY': 'PARKWAY', 'ESP': 'ESPLANADE', 'TRK': 'TRACK',
}


def road_spellings(name):
    if pd.isna(name):
        return set()
    original = ' '.join(name.upper().strip().split())
    if original in {'', 'UNKNOWN', 'NOT STATED', 'NOT APPLICABLE', 'NO ROAD NAME'}:
        return set()
    if original.startswith(('UNNAMED', 'INVALID STREET', 'UN-NAMED')):
        return set()
    words = original.split()
    words[-1] = ABBREVIATIONS.get(words[-1], words[-1])
    return {original, ' '.join('CREEK' if word == 'CK' else word for word in words)}


def canonical_street(value):
    if not road_spellings(value):
        return ''
    words = re.sub(r'[^A-Z0-9]+', ' ', str(value).upper().replace("'", '').replace('’', '')).split()
    if not words:
        return ''
    street_types = ABBREVIATIONS | {'CR': 'CRESCENT', 'LA': 'LANE', 'BVD': 'BOULEVARD', 'CIR': 'CIRCUIT'}
    suffix_index = -2 if len(words) > 2 and words[-1] in ('NORTH', 'SOUTH', 'EAST', 'WEST') else -1
    words[suffix_index] = street_types.get(words[suffix_index], words[suffix_index])
    return ' '.join('CREEK' if word == 'CK' else word for word in words)


def second_pass_streets(path, accepted_names):
    import pyarrow.parquet as pq

    groups = defaultdict(set)
    columns = [
        'street_name', 'street_type', 'street_suffix', 'latitude', 'longitude',
        'geocode_type', 'number_first', 'confidence',
    ]
    for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=120_000):
        frame = batch.to_pandas()
        eligible = (
            frame[['latitude', 'longitude', 'street_name', 'number_first']].notna().all(axis=1)
            & frame['confidence'].gt(0)
            & frame['geocode_type'].fillna('').str.contains(r'CENTROID|FRONTAGE|ENTRANCE|ACCESS|BUILDING')
        )
        frame = frame.loc[eligible]
        labels = (frame['street_name'] + ' ' + frame['street_type'].fillna('') + ' '
                  + frame['street_suffix'].fillna('')).str.strip()
        canonical = labels.map({label: canonical_street(label) for label in labels.unique()})
        subset = frame.loc[canonical.isin(accepted_names)]
        x, y = FORWARD(subset['longitude'].to_numpy(), subset['latitude'].to_numpy())
        for name, east, north in zip(canonical.loc[subset.index], x, y):
            if np.isfinite(east) and np.isfinite(north):
                groups[name].add((east, north))
    return groups


def has_opposing_approaches(nodes, junction):
    directions = []
    for _, geometry in nodes:
        for part in get_parts(geometry):
            for line in (part, part.reverse()):
                endpoint = line.interpolate(0)
                if endpoint.distance(junction) > 3 or line.length < 3:
                    continue
                away = line.interpolate(min(10, line.length))
                direction = np.array([away.x - endpoint.x, away.y - endpoint.y])
                norm = np.linalg.norm(direction)
                if norm:
                    directions.append(direction / norm)
    return any(first @ second <= -.5 for i, first in enumerate(directions) for second in directions[i + 1:])


def second_pass_junction(first_segments, second_segments):
    matches = []
    cross_tree = STRtree([line for _, line in second_segments])
    for props, line in first_segments:
        for idx in cross_tree.query(line):
            other, cross_line = second_segments[idx]
            grades = {props['ground_rel'], other['ground_rel']}
            if not grades <= {'Ground', 'Unknown'} or 'Ground' not in grades:
                continue
            intersection = line.intersection(cross_line)
            if (not intersection.is_empty and intersection.geom_type == 'Point'
                    and line.boundary.distance(intersection) <= 2
                    and cross_line.boundary.distance(intersection) <= 2):
                matches.append((intersection, props['segment_id'], other['segment_id']))
    if not matches:
        return None, [], None, 'no shared ground-level node for the recorded junction'
    point = union_all([item[0] for item in matches]).centroid
    radius = max(point.distance(item[0]) for item in matches)
    if radius > 3:
        return None, [], None, 'multiple geographically distinct junction candidates'
    if not all(has_opposing_approaches(segments, point) for segments in [first_segments, second_segments]):
        return None, [], None, 'mapped approaches do not confirm a cross intersection'
    segments = {segment_id for _, first, second in matches for segment_id in (first, second)}
    return point, segments, radius, 'mapped four-arm cross intersection'


def second_pass_location(first, second, roadway, catalogue, addresses):
    if not first:
        return {'Second_pass_status': 'no usable primary street name'}
    first_segments = catalogue.get(first, [])
    if not first_segments:
        return {'Second_pass_status': 'normalized street absent from road network'}
    support = None
    if second:
        if first == second:
            return {'Second_pass_status': 'recorded street pair repeats the same name'}
        if roadway != 'Intersection - Cross':
            return {'Second_pass_status': 'recorded junction type does not establish a cross intersection'}
        point, segments, radius, basis = second_pass_junction(first_segments, catalogue.get(second, []))
        if point is None:
            return {'Second_pass_status': basis}
    else:
        merged = union_all([geometry for _, geometry in first_segments])
        xmin, ymin, xmax, ymax = merged.bounds
        if np.hypot(xmax - xmin, ymax - ymin) > 3000 or merged.buffer(30).geom_type != 'Polygon':
            return {'Second_pass_status': 'street spans over 3 km or has disconnected corridors'}
        sites = addresses.get(first, set())
        if len(sites) < 3 or any(merged.distance(Point(x, y)) > 120 for x, y in sites):
            return {'Second_pass_status': 'insufficient or conflicting G-NAF support for one corridor'}
        midpoint = Point((xmin + xmax) / 2, (ymin + ymax) / 2)
        point = nearest_points(midpoint, merged)[1]
        radius = float(np.linalg.norm(get_coordinates(merged) - (point.x, point.y), axis=1).max())
        if radius > 1500:
            return {'Second_pass_status': 'candidate road extends more than 1.5 km from the estimate'}
        segments = [props['segment_id'] for props, _ in first_segments]
        support = len(sites)
        basis = 'G-NAF corroborated road corridor'
    lon, lat = INVERSE(point.x, point.y)
    return {
        'Second_pass_status': 'estimated', 'Public_latitude': lat, 'Public_longitude': lon,
        'Public_coordinate_basis': basis, 'Public_road_segments': sorted({str(value) for value in segments}),
        'Second_pass_road_extent_m': round(radius, 1), 'Second_pass_address_sites': support,
    }


def historical_corroboration(estimate, donors, excluded_id=None):
    if estimate.get('Second_pass_status') != 'estimated':
        return estimate
    donors = donors.loc[donors.index != excluded_id]
    corridor = estimate['Public_coordinate_basis'] == 'G-NAF corroborated road corridor'
    minimum = 3 if corridor else 1
    extent = estimate['Second_pass_road_extent_m']
    if corridor and extent > 500:
        reason = 'candidate corridor is too long for automatic estimation'
    elif len(donors) < minimum:
        reason = 'insufficient observed crashes on the candidate road or junction'
    else:
        coordinates = np.column_stack(FORWARD(donors[LON].to_numpy(), donors[LAT].to_numpy()))
        point = np.asarray(FORWARD(estimate['Public_longitude'], estimate['Public_latitude']))
        distances = np.linalg.norm(coordinates - point, axis=1)
        limit = extent + 100 if corridor else 75
        if distances.max() <= limit:
            return estimate | {'Second_pass_crash_donors': len(donors)}
        reason = 'observed crashes disagree with the candidate location'
    return {
        'Second_pass_status': reason,
        'Second_pass_review_latitude': estimate['Public_latitude'],
        'Second_pass_review_longitude': estimate['Public_longitude'],
        'Second_pass_review_basis': estimate['Public_coordinate_basis'],
    }


def forward_location(row, catalogue):
    first, second = (road_spellings(row[column]) for column in (STREET, CROSS))
    if not first:
        return {'Forward_status': 'no usable recorded street name'}
    first_segments = [segment for name in first for segment in catalogue.get(name, [])]
    if not first_segments:
        return {'Forward_status': 'recorded street name absent from road catalogue'}
    second_segments = [segment for name in second for segment in catalogue.get(name, [])]
    if second:
        points = []
        segment_ids = set()
        cross_tree = STRtree([geometry for _, geometry in second_segments])
        for properties, line in first_segments:
            for idx in cross_tree.query(line):
                cross_properties, cross_line = second_segments[idx]
                if properties['ground_rel'] not in ('Ground', 'Unknown') or cross_properties['ground_rel'] not in ('Ground', 'Unknown'):
                    continue
                intersection = line.intersection(cross_line)
                if intersection.geom_type != 'Point' or intersection.is_empty:
                    continue
                if line.boundary.distance(intersection) <= 2 and cross_line.boundary.distance(intersection) <= 2:
                    points.append(intersection)
                    segment_ids.update((properties['segment_id'], cross_properties['segment_id']))
        if not points:
            return {'Forward_status': 'no shared road junction for the recorded street pair'}
        point = union_all(points).centroid
        if max(point.distance(p) for p in points) > 12.5:
            return {'Forward_status': 'multiple possible road junctions'}
        method = 'QLD road network shared junction'
    else:
        combined = line_merge(union_all([line for _, line in first_segments]))
        if combined.geom_type != 'LineString' or not 0 < combined.length <= 1500:
            return {'Forward_status': 'street name has multiple components or spans over 1.5 km'}
        point = combined.interpolate(.5, normalized=True)
        segment_ids = {properties['segment_id'] for properties, _ in first_segments}
        method = 'QLD road network short-street midpoint'
    lon, lat = INVERSE(point.x, point.y)
    return {'Forward_status': 'estimated', 'Public_longitude': lon, 'Public_latitude': lat,
            'Public_coordinate_basis': method, 'Public_road_segments': sorted(str(v) for v in segment_ids)}


def features(path):
    opener = gzip_open if path.suffix == '.gz' else open
    with opener(path, 'rb') as handle:
        yield from ijson.items(handle, 'features.item', use_float=True)


def polygons(records):
    attributes = []
    geometries = []
    for values, geometry in records:
        if geometry is not None and not geometry.is_empty:
            attributes.append(values)
            geometries.append(geometry)
    assert geometries
    index = STRtree(geometries)

    def lookup(point):
        found = {attributes[i] for i in index.query(point, predicate='covered_by')}
        return next(iter(found)) if len(found) == 1 else None

    return lookup


def shapefile_polygons(path, fields):
    with ZipFile(path) as archive:
        shp = next(name for name in archive.namelist() if name.lower().endswith('.shp'))
        stem = shp[:-4]
        crs = CRS.from_wkt(archive.read(stem + '.prj').decode())
        project = Transformer.from_crs(crs, 4326, always_xy=True).transform
        with shapefile.Reader(shp=archive.open(shp), dbf=archive.open(stem+'.dbf')) as layer:
            for feature in layer.iterShapeRecords():
                values = tuple(feature.record[field] for field in fields)
                if feature.shape.shapeType != shapefile.NULL:
                    yield values, transform(shape(feature.shape.__geo_interface__), project, interleaved=False)


def road_catalogue(path, names, reverse_targets, normalized_names):
    catalogue = defaultdict(list)
    normalized_catalogue = defaultdict(list)
    nearby = []
    # The downloaded road layer covers the state. These bounds filter it locally.
    envelopes = [(row[LON]-.0015, row[LAT]-.0015, row[LON]+.0015, row[LAT]+.0015)
                 for row in reverse_targets.to_dict('records')]
    count = 0
    for feature in features(path):
        count += 1
        props, geometry = feature['properties'], feature['geometry']
        title = props['road_name_full']
        if not title or not geometry:
            continue
        labels = (title, props.get('alias_1_name_full'), props.get('alias_2_name_full'))
        matched = {str(value).upper() for value in labels if value} & names
        normalized_matches = {canonical_street(value) for value in labels if value} & normalized_names
        paths = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']
        vertices = [point for path in paths for point in path]
        if not vertices:
            continue
        x, y = zip(*(point[:2] for point in vertices))
        xmin, xmax, ymin, ymax = min(x), max(x), min(y), max(y)
        near_target = any(xmin <= right and xmax >= left and ymin <= top and ymax >= bottom
                          for left, bottom, right, top in envelopes)
        if matched or normalized_matches or near_target:
            line = transform(shape(geometry), FORWARD, interleaved=False)
            for name in matched:
                catalogue[name].append((props, line))
            for name in normalized_matches:
                normalized_catalogue[name].append((props, line))
            if near_target:
                nearby.append((props, line))
    assert count > 100_000, f'Unexpected Queensland road feature count: {count}'
    print(f'Processed {count:,} public road segments locally.', flush=True)
    return catalogue, normalized_catalogue, nearby, count


def reverse_road(lon, lat, candidates, index):
    point = Point(*FORWARD(lon, lat))
    nearest = {}
    for position in index.query(point, predicate='dwithin', distance=120):
        props, line = candidates[position]
        road = props['road_name_full']
        if not road_spellings(road):
            continue
        distance = point.distance(line)
        key = road.casefold()
        if key not in nearest or distance < nearest[key][0]:
            nearest[key] = (distance, road, str(props['segment_id']))
    ranked = sorted(nearest.values())
    if ranked and ranked[0][0] <= 35 and (len(ranked) == 1 or ranked[1][0] - ranked[0][0] >= 10):
        distance, road, segment = ranked[0]
        return {'Public_street': road, 'Public_street_distance_m': round(distance, 1),
                'Public_street_segment': segment, 'Reverse_street_status': 'matched'}
    return {'Reverse_street_status': ('ambiguous nearby roads' if ranked and ranked[0][0] <= 35
                                     else 'no named road within 35 m')}


def missing(value):
    return pd.isna(value) or str(value).strip().casefold() in {'', 'unknown', 'not stated', 'not applicable'}


def address_references(path, targets, spatial_records):
    """Add references for recorded points only, keeping road and property evidence distinct."""
    import pyarrow.parquet as pq

    if targets.empty:
        return
    target_xy = np.column_stack(FORWARD(targets[LON].to_numpy(), targets[LAT].to_numpy()))
    tree = cKDTree(target_xy)
    nearby = defaultdict(list)
    columns = [
        'gnaf_pid', 'address', 'number_first', 'street_name', 'street_type', 'street_suffix',
        'locality_name', 'postcode', 'latitude', 'longitude', 'geocode_type', 'confidence',
        'primary_secondary',
    ]
    for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=100_000):
        frame = batch.to_pandas()
        eligible = (
            frame[['latitude', 'longitude', 'address', 'street_name', 'number_first']].notna().all(axis=1)
            & frame['geocode_type'].fillna('').str.upper().str.contains(r'CENTROID|FRONTAGE|ENTRANCE|ACCESS|BUILDING')
            & frame['confidence'].gt(0)
            & ~frame['primary_secondary'].fillna('').str.upper().isin(['S', 'SECONDARY'])
        )
        frame = frame.loc[eligible]
        if frame.empty:
            continue
        address_xy = np.column_stack(FORWARD(frame['longitude'].to_numpy(), frame['latitude'].to_numpy()))
        distances, _ = tree.query(address_xy, distance_upper_bound=50)
        for row, point in zip(frame.loc[np.isfinite(distances)].to_dict('records'),
                              address_xy[np.isfinite(distances)]):
            for i in tree.query_ball_point(point, r=50):
                nearby[i].append((float(np.linalg.norm(point - target_xy[i])), row))

    for i, (crash_id, crash) in enumerate(targets.iterrows()):
        result = spatial_records[int(crash_id)]
        expected_street = road_spellings(crash[STREET]) or road_spellings(result.get('Public_street'))
        expected_locality = (
            crash['Loc_Suburb'] if not missing(crash['Loc_Suburb']) else result.get('Public_suburb')
        )
        candidates = []
        for distance, address in nearby[i]:
            if expected_locality and str(address['locality_name']).casefold() != str(expected_locality).casefold():
                continue
            street = ' '.join(str(address[field]) for field in ('street_name', 'street_type', 'street_suffix')
                              if not missing(address[field]))
            names = road_spellings(street)
            if names and (not expected_street or names & expected_street):
                candidates.append((distance, names, street, address))
        if not candidates:
            result['GNAF_lookup_status'] = 'no eligible nearby address on the expected street and locality'
            continue
        distance, names, street, address = min(candidates, key=lambda item: (item[0], item[3]['gnaf_pid']))
        if not expected_street:
            distinct_sites = {(item[3]['longitude'], item[3]['latitude']) for item in candidates}
            if len(distinct_sites) < 3 or any(not names & item[1] for item in candidates):
                result['GNAF_lookup_status'] = 'nearby address points do not resolve the street name'
                continue
        postcode = address['postcode']
        result.update({
            'GNAF_lookup_status': 'nearby same-street reference' if expected_street
                                  else 'nearby addresses agree on one candidate street',
            'GNAF_reference_address': address['address'], 'GNAF_reference_street': street,
            'GNAF_reference_locality': address['locality_name'],
            'GNAF_reference_postcode': str(postcode).zfill(4) if not missing(postcode) else None,
            'GNAF_reference_distance_m': round(distance, 1), 'GNAF_address_id': address['gnaf_pid'],
        })


def main(layers):
    raw_path = Path('Road crash locations.csv')
    cleaned_path = Path('Road crash locations - cleaned V3.csv')
    fields = [ID, LAT, LON, STREET, CROSS, 'Loc_Suburb', 'Loc_Local_Government_Area',
              'Loc_Post_Code', 'Loc_Police_Region', ROADWAY]
    raw = pd.read_csv(raw_path, usecols=fields).set_index(ID)
    base = pd.read_csv(cleaned_path, usecols=[ID, LAT, LON, 'Coordinate_Method']).set_index(ID)
    assert raw.index.equals(base.index)
    records = {}
    missing_coords = raw[[LAT, LON]].isna().any(axis=1)
    prior_public = base['Coordinate_Method'].isin([PUBLIC_METHOD, SECOND_PASS_METHOD])
    coordinate_donors = ~prior_public & base[[LAT, LON]].notna().all(axis=1)
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
        with_junction.sample(n=min(2000, len(with_junction)), random_state=42),
        without_junction.sample(n=min(3000, len(without_junction)), random_state=42),
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
    addresses = second_pass_streets(address_path, target_names) if address_path.exists() else {}
    second_results = {}
    observed = raw.loc[~missing_coords, [LAT, LON]]
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

    localities = polygons(((f['properties']['locality'], f['properties']['lga']),
                           shape(f['geometry'])) for f in features(layers / 'locality.geojson.gz') if f['geometry'])
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

    if address_path.exists():
        address_targets = raw.loc[~missing_coords & (locations_missing | street_missing)]
        address_references(address_path, address_targets, records)

    with raw_path.open('rb') as file:
        checksum = file_digest(file, 'sha256').hexdigest()
    snapshot = {'retrieved': date.today().isoformat(), 'raw_sha256': checksum,
                'sources': {'roads': ROAD_DOWNLOAD, 'localities': LOCALITY,
                            'postal_areas_2021': POSTAL, 'police_regions': POLICE},
                'police_archive_last_modified': '2026-10-26', 'public_road_feature_count': road_count,
                'second_pass_validation': validation, 'records': records}
    if address_path.exists():
        snapshot['sources']['gnaf_august_2026'] = GNAF_SOURCE
    target = Path('Traffic spatial matches V3.json')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot, indent=2) + '\n')
    temporary.replace(target)
    print(pd.DataFrame.from_dict(records, orient='index').count().to_string())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layers', nargs='?', type=Path, default=Path('Public spatial data'),
                        help='Directory with the retained Queensland spatial layers')
    main(parser.parse_args().layers)
