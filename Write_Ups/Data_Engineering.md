# Data engineering — Queensland road crash analysis

*Covers the data work behind `Traffic_Incidents_V6.ipynb` (27 November 2026), including the V5 steps V6 inherits. Each section says where the step runs: a notebook section or one of the three helper modules. The notebook follows the six CRISP-ML(Q) phases, and most of this document belongs to **Phase 2 · Data preparation and quality assurance**. Feature preparation for the models is in Phase 3, and the export and release steps are in Phase 5.*

---

## Contents

1. [Principles](#1-principles)
2. [Source inventory](#2-source-inventory)
3. [Integrating the six files](#3-integrating-the-six-files)
4. [Reconciliation checks](#4-reconciliation-checks)
5. [Recording changes and the outcome definition](#5-recording-changes-and-the-outcome-definition)
6. [Location cleansing and recovery](#6-location-cleansing-and-recovery)
7. [Road-network sites for screening](#7-road-network-sites-for-screening)
8. [Derived fields and feature preparation](#8-derived-fields-and-feature-preparation)
9. [Aggregation and standardisation patterns](#9-aggregation-and-standardisation-patterns)
10. [Outputs](#10-outputs)
11. [Reproducibility, caching and code layout](#11-reproducibility-caching-and-code-layout)
12. [Known limitations and open items](#12-known-limitations-and-open-items)
13. [Appendix — columns added to the cleaned crash table](#appendix--columns-added-to-the-cleaned-crash-table)

---

## 1. Principles

These rules apply to every step below.

- **The source is never modified.** `raw` is read once and stays read-only. All cleaning happens on a copy (`cleaned`). An assertion checks that every recorded value in `raw` is unchanged in `cleaned`, column by column, and that crash IDs and row order are identical.
- **Estimates fill blanks only.** An estimate is written only where the source is missing, and it always comes with its method and supporting evidence (donor counts, distances, G-NAF references). Recorded values are always preferred to derived ones.
- **Observed and estimated values stay distinguishable.** `Coordinate_Method` and the `*_Method` columns let any analysis use observed data only. The hotspot screening and the density maps do exactly that.
- **Each source keeps its own denominator.** Grouped files are aggregated within each source before any join, and numerators and denominators are pooled before dividing.
- **Counts must tally.** Every aggregation is checked against the source totals with assertions, so a broken join stops the run instead of giving a wrong number.
- **Exports are atomic.** Files are written to a temporary file in the target folder and then renamed, so a failed run never leaves a half-written export.
- **Runs are deterministic.** One seed (`SEED = 42`) drives every sample, split and model. Package versions and file checksums are recorded in the release manifest.

---

## 2. Source inventory

### Crash and casualty files (Queensland Government open data)

| File | Grain | Rows | Count column | Notes |
|---|---|---|---|---|
| `Road crash locations.csv` | One row per crash | 415,407 | — (one row = one crash) | 53 fields, 2001–2025. `Crash_Ref_Number` is unique and complete. Holds coordinates, location labels, conditions, DCA codes, unit counts and casualty counts. |
| `Factors in road crashes.csv` | Year × police region × severity × factor flags | 5,523 | `Count_Crashes` | Drink driving, speed, fatigue, defective vehicle |
| `Vehicle types.csv` | Year × region × severity × vehicle flags | 3,764 | `Count_Crashes` | Motorcycle/moped, truck, bus only. **No car flag.** |
| `Driver demographics.csv` | Year × region × severity × driver flags | 22,699 | `Count_Crashes` | Male, female, young, senior, provisional, overseas-licensed, unlicensed |
| `Road casualties.csv` | Year × region × severity × age × gender × road user | 38,893 | `Casualty_Count` | Drivers and passengers separate |
| `Seatbelt restraints and helmet use.csv` | Same as casualties, plus restraint/helmet status | 42,787 | `Casualty_Count` | Drivers and passengers combined as "Vehicle Occupant". No pedestrians or "Other". |

**No crash date.** The locations file gives year, month, day of week and hour, but not the day of the month, so each crash could fall on any of 4–5 dates. We checked whether the date could be reconstructed from record order. `Crash_Ref_Number` and `_id` are not assigned in date order:
- Their rank correlation with year-month is 0.35.
- Within a month, records in reference order imply about 3 days between each other on average, the pattern of random order. Date order would imply about 30 days in total.
- None of the 294 year-months fits date order, and only 81 of 2,157 region-month groups do, mostly very small ones.

Short runs of same-weekday records exist, but they are too fragmented to rebuild dates, so this is not pursued. Exact dates would have to come from Transport and Main Roads on request. Linking to outside records such as news reports is avoided because the date was withheld for privacy.

### Spatial reference layers (`Public spatial data/`, documented in `sources.json`)

| File | Content | Features | Use |
|---|---|---|---|
| `roads.geojson.gz` | Queensland Roads and Tracks | 564,950 segments | Street matching, junction/corridor estimates, road-site network |
| `locality.geojson.gz` | Queensland locality boundaries | 3,359 | Suburb and LGA for estimated or unlabelled points |
| `postal.geojson.gz` | ABS 2021 Postal Areas intersecting Queensland | 455 | Approximate postcode |
| `police.zip` | QPS regions (archive dated 2026-10-26) | — | Police region for estimated or unlabelled points; region polygons for maps |
| `G-NAF Queensland 2026-08.parquet` | Geoscape G-NAF address principals, QLD | 3,116,786 | Address corroboration of road corridors and street names |

### Not yet used

`Bureau of Meteorology Rainfall QLD.csv` is BoM product IDCJMC0014, a fixed-width **list of 4,028 rainfall stations** (site, name, latitude, longitude, start, end, years, % complete, AWS flag). It holds no rainfall amounts. 848 stations were open for all of 2001–2025. See §12.

---

## 3. Integrating the six files

*Notebook: Phase 1 "Audit the six files and test merge keys". Phase 2 "Combine all six sources by crash year and police region".*

**Key audit.**
- Only `Crash_Year` and `_id` appear in all six files.
- `_id` is a row number within each file, not a shared crash key. Where the same `_id` appears in two files, the crash year usually differs (for example 37,463 of 38,893 casualty rows).
- No file other than the locations file carries `Crash_Ref_Number`.
- **Conclusion:** the grouped files cannot be joined to individual crashes. Analyses that combine files are restricted to the grain all six share, **crash year × police region**.

**Region alignment.**
- The police-region column is renamed to one shared name, `Police_Region`. It is `Loc_Police_Region` in the locations file, `Crash_Police_Region` in four files and `Crash_PoliceRegion` in the restraint file.
- The resulting `regional_sources` dictionary is the basis for all year-region work.

**Joining.**
- Each source is aggregated to one row per year × region using its own count column, then the six totals are aligned with an outer join.
- Missing groups stay blank, never zero. A zero means the source reports the group with no qualifying records.
- 186 year-region groups exist, and 184 are present in all six files. The exceptions are `Unknown` region in 2009 (7 crashes) and 2010 (36 crashes), which the two casualty files do not report.

**Road-user alignment.**
- The casualty file separates drivers and passengers. The restraint file combines them.
- For any comparison between the two, `Driver` and `Passenger` are mapped to `Vehicle Occupant`.

---

## 4. Reconciliation checks

*Notebook: Phase 2 "Check that source counts tally". Flat-file and unit-count sections.*

| Check | Result |
|---|---|
| Crash counts: locations vs factors, vehicles, demographics | 415,407 in each file; identical in all 186 year-region groups |
| Casualty counts: locations vs factors, vehicles, demographics, casualties | 437,355 in each; casualties file matches in all 184 groups it reports |
| Restraint file vs casualty file | 417,148 vs 437,355. The 20,207 difference is exactly the pedestrians (18,635) and "Other" road users (1,572) outside the restraint file's scope. |
| Restraint vs casualty at the detailed grain (year, region, age, gender, road user, severity) | All 23,375 comparable groups agree |
| Crash-level unit counts vs grouped vehicle table (V6) | Motorcycle 38,830, truck 29,943, bus 7,048 crashes; exact match |
| Flat-file totals vs sources | Assertions on casualty, equipment, weather-crash and weather-fatality totals |
| Tableau tables vs sources | Assertions on crash, injury, serious, fatal, fatality and casualty totals |

---

## 5. Recording changes and the outcome definition

*Notebook: Phase 2 "Check for recording changes over time" and "Check whether the severity mix drifts".*

Four changes in how data was recorded decide what each analysis can use.

1. **Property-damage-only crashes end after 2010.** They were 35.6–40.8% of records each year to 2010 and are absent from 2011. **Rule:** any series or share that crosses 2010 uses injury crashes only. `last_pdo_year = 2010` is derived from the data, not typed in.
2. **The overseas-licensed driver flag stops.** It covers all severities to 2013, fatal crashes only to 2016, then nothing. **Rule:** excluded from all flag comparisons.
3. **Minor-injury casualties dip and recover** (6,089 in 2007, 2,029 in 2015, 4,253 in 2024) with no explanation in the sources. **Rule:** minor-injury trends carry a caution.
4. **Severity grading drifts (found in V6).** The hospitalisation share of injury crashes rose from 30.5% (2001) to 49.1% (2024), and fatal or hospitalisation from 32.6% to 51.0%. The fatal share stayed within 1.5–2.3%.
   - **Rule — the stable window:** start at the latest complete year and work back, keeping each year whose hospitalisation share and fatal-or-hospitalisation share are both within **3 percentage points** of that year. Stop at the first year that fails. The result is **2020–2024** (66,624 injury crashes), stored as `stable_years` and in the manifest.
   - Serious-share comparisons, association rules, models and adjusted odds use this window. Long-run trends use the fatal share. Site screening uses year-specific expected shares, so the drift cancels out (§7).

**Other definitions used throughout.**

| Term | Definition |
|---|---|
| Injury crash | `Crash_Severity` in Fatal, Hospitalisation, Medical treatment, Minor injury |
| Serious outcome | Fatal or Hospitalisation, as a share of injury crashes |
| Complete year | A year with crashes in all 12 months. 2025 is partial, scored separately and excluded wherever complete years are needed. |
| Recent / comparison years | The latest five complete years, which currently equal the stable window |

---

## 6. Location cleansing and recovery

*Code: `traffic_location_recovery.py`, which uses helpers from `traffic_spatial_lookup.py`. Notebook: Phase 2 "Run the location recovery". V6 moved this from V5 cells 16–41 into the module unchanged. Its outputs are byte-identical to V5's.*

### 6.1 Label normalisation

- **Placeholders:** location labels are lower-cased and trimmed. `''`, `unknown`, `not stated`, `not applicable` and `no road name`, and names starting `unnamed`, `invalid street` or `un-named`, become missing.
- **Intersection keys:** the two road names are stored in alphabetical order, so "A / B" and "B / A" match.
- **Street names:** abbreviations are expanded for comparison (RD→ROAD, ST→STREET, CK→CREEK, PDE→PARADE and so on), with punctuation and apostrophes removed and directional suffixes handled.
- **Council names:** the "Regional"/"Region" suffix is aligned, and the 2023 Moreton Bay Region→City change is mapped. Both source labels are kept.

### 6.2 Missing values in the source

| Field | Missing | Treatment |
|---|---|---|
| Latitude / longitude | 598 pairs | Donor medians, then public layers (below) |
| `Crash_Speed_Limit` | 5 | Inferred where ≥2 crashes on the same street, suburb and LGA within 25 m and ±2 years agree (1 filled) |
| `Crash_Road_Horiz_Align` / `Vert_Align` | 1 / 2 | Inferred where ≥3 crashes at the identical coordinates on the same street agree (1 vertical filled) |
| `Crash_Street` | 15 | Filled from the public reverse-street lookup where matched |
| `Crash_Street_Intersecting`, `State_Road_Name` | 234,997 / 224,003 | Left blank. Often not applicable (midblock crash, local road). |
| `DCA_Key_Approach_Dir` | 8,021 | Left blank. Specific to each crash and not inferable. |

All 598 records missing coordinates also have suburb and LGA coded `Unknown`.

### 6.3 Step 1 — donor-median coordinates

- **Labelled records:** use the median coordinates of observed crashes in the most specific group with at least three donors. The groups are tried in order: intersection within suburb, then street within suburb, then suburb, then LGA.
- **Records without usable locality:** a street fallback uses exact intersection, street + state-road segment, or street statewide.
  - A **compact** match needs all donors to agree on one known suburb and LGA, with a donor bounding-box diagonal of 1 km or less.
  - A **coarse** match allows up to 3 km where all donors agree on the LGA.
  - An inferred suburb is recorded only when all donors agree on it.
- **Validation on 10,000 withheld observed locations:**

| Method | Estimated | Median error | 90th pct error |
|---|---|---|---|
| V2-style suburb/LGA median | 10,000 | 0.866 km | 2.909 km |
| V3 named-locality hierarchy | 10,000 | 0.234 km | 2.100 km |
| V3 street fallback (locality withheld) | 3,690 | 0.011 km | 0.476 km |

- **Result:** 83 coordinate pairs estimated (60 coarse street, 21 compact street, 2 compact intersection).

### 6.4 Step 2 — public spatial layers

All distance work uses **EPSG:9473 (GDA2020 / Australian Albers)**, which is metre-based. GeoJSON layers are streamed feature by feature (`ijson`) so they never load fully into memory, and spatial indexes (`STRtree`, `cKDTree`) handle the nearest-feature queries.

| Pass | Rule | Outcome |
|---|---|---|
| **First pass — road network** | For a crash with no coordinates, match the recorded street (and alias) names exactly. Estimate either one shared ground-level junction of the two named roads (all candidates within 12.5 m) or the midpoint of one connected named street up to 1.5 km long. | 43 pairs |
| **Second pass — corridor and junction** | Normalised names. **Junction:** two different streets, recorded cross-intersection type, one mapped four-arm ground-level junction, and at least one corroborating crash on the same two streets within 75 m. **Corridor:** every road vertex within 500 m of the estimate, ≥3 distinct G-NAF address sites, ≥3 observed crashes on the street, all agreeing with the corridor. Plausible but unsupported candidates are kept only as review coordinates. | 1 pair (+5 review-only) |
| **Second-pass validation** | 5,441 withheld crashes on comparable streets, each excluded from its own evidence | 4-arm junctions: median 9.3 m error. Corridors: median 41.7 m. |
| **Reverse street lookup** | For a recorded point with a blank or generic street: a named road within 35 m, at least 10 m closer than the next differently named road | 124 matched, 41 ambiguous, 112 none within 35 m |
| **Suburb-only recovery** | For a crash still without coordinates or suburb: an exact named road or street pair that maps to one locality, backed by ≥2 recorded crashes or ≥3 G-NAF sites. A conflicting recorded suburb blocks the estimate. | 28 suburbs. Holdout: 294 of 295 correct. |
| **Point-in-polygon** | Locality (suburb, LGA), 2021 Postal Area and QPS region for estimated points or points with missing labels. Kept in separate `Public_*` columns. | — |
| **G-NAF references** | Numbered, primary, property- or building-geocoded addresses within 50 m of recorded points. Locality and street must agree where known; ≥3 sites must agree on one street where it is unknown. | 22 references, all with the same postcode as recorded |

### 6.5 Step 3 — reconciled fields

`Reconciled_Street`, `Reconciled_Suburb` and `Reconciled_Local_Government_Area` take the recorded value first, then the public-layer value, then the donor estimate, then the suburb-only estimate. Boundary comparison columns record whether the donor and polygon labels agree. There were no disagreements after name normalisation in 59 suburb and 83 council comparisons.

| Field | Missing or unknown in source | Supplied | Still unresolved |
|---|---|---|---|
| Coordinate pair | 598 | 127 | 471 |
| Street name | 386 | 124 | 262 |
| Suburb | 599 | 156 | 443 |
| Council area | 599 | 128 | 471 |
| Postcode or Postal Area | 600 | 127 | 473 |
| Police region | 598 | 127 | 471 |

The most common reason a record stays unresolved is a street that spans over 3 km or has disconnected corridors (243). Next are no usable street name (109) and a street absent from the road network (91).

### 6.6 Stacked coordinates (V6)

- 9,485 crash records sit on coordinate pairs shared by 10 or more crashes, up to 58 at one point.
- The V6 site screening shows these are almost all at junctions: 26% of crashes at junction sites against 0.5% on links. That matches intersection crashes being geocoded to the intersection point.
- **Rule:** stacked points are kept. Each screened site reports its distinct crash points and stacked crash count so snapping can be told apart from a genuine cluster.

---

## 7. Road-network sites for screening

*Code: `traffic_road_sites.py`. Notebook: Phase 3 "Screen road sites for excess serious crashes".*

1. **Parse.** Every segment of the roads layer is read (564,950 features). Multi-part lines are split into parts, and all coordinates are projected to EPSG:9473 in one vectorised call.
2. **Nodes.** Segment end points are snapped to a 0.5 m grid so touching ends share a node, and each node's degree (segment ends meeting there) is counted.
3. **Links.** Two parts are merged into one link when they share a node where only they meet and both have the same non-empty road name (case-insensitive). A link therefore runs junction to junction or to a name change. The result is 513,336 links, median 134 m, 90th percentile 1.1 km.
4. **Junctions.** Nodes with three or more segment ends are junction nodes. Nodes within 25 m of each other are merged, which handles dual carriageways and staggered junctions. The result is 251,021 junctions, each labelled with up to three road names by frequency.
5. **Snapping crashes.** The input is observed coordinates only: injury crashes in the latest ten complete years after 2010 (2015–2024).
   - Crashes coded with an `Intersection - *` roadway feature go to the nearest junction node within **40 m**.
   - All others, and intersection crashes with no junction in range, go to the nearest segment within **30 m** and take its link.
   - **Result:** 56.4% to links, 43.0% to junctions, 0.7% unassigned. 96.2% of intersection-coded crashes reached a junction.
6. **Expected values.** Each crash gets the statewide serious share for its **year × site type × speed zone × remoteness** stratum. Site totals sum observed serious crashes, expected serious crashes and binomial variance.
7. **Shrinkage constant.** Overdispersion ρ is estimated by method of moments across sites with two or more crashes (ρ = 0.0446, k = (1 − ρ)/ρ = 21.4). Shrunk excess = (observed − expected) × n/(n + k).

The network is cached (`.cache/road_network_<digest>.pkl`, about 10 s to rebuild). Assigning sites takes about 1 s.

---

## 8. Derived fields and feature preparation

### 8.1 Crash-level indicators and groupings

| Field | Derivation |
|---|---|
| Injury / serious / fatal indicators | From `Crash_Severity`. Serious and fatal are blank for property-damage-only records in the Tableau export, so their average is always a share of injury crashes. |
| Time band | Night = 22:00–04:59 (`night_hours`); weekend = Saturday or Sunday. Combined into four time-of-week levels for the odds model. |
| Involvement flags (V6) | From `Count_Unit_*` > 0: pedestrian, bicycle, motorcycle/moped, truck, bus, car. Single vehicle = exactly one vehicle unit and no pedestrian. Two or more vehicles = vehicle units ≥ 2. |
| Crash type (V6) | One mutually exclusive type per crash, first match in this order: pedestrian struck; single car; two or more cars only; car + motorcycle; car + bicycle; car + truck; car + bus; car + other vehicle; motorcycle, no car; bicycle, no car; truck or bus, no car; other. Cars are in 91% of injury crashes, so a car flag alone is uninformative. |
| Seasonal index (V6) | Injury crashes per day: monthly counts divided by the actual days in that month and year, then indexed to that year's mean (= 100) |
| Council area label | Normalised council name (§6.1), title-cased, for the funnel plots |
| Point key | Latitude and longitude rounded to 6 decimals, for distinct-point counts per site |

### 8.2 Model inputs (Phase 3)

- **Rows:** injury crashes from the raw table. Train 2020–2022 (38,644), validation 2023 (13,622), test 2024 (14,358), partial 2025 (7,029) scored separately.
- **Targets:** binary. Fatal or hospitalisation, and fatal.
- **Categorical fields (16):** crash nature, type, day of week, speed zone, lighting, weather, surface, traffic control, remoteness, DCA group, roadway feature, horizontal and vertical alignment, controlling authority, month, police region.
  - Blanks become `Unknown`.
  - Each field gets **one fixed `CategoricalDtype` built from all injury crashes**, so every split encodes a label with the same code. Without this, gradient boosting would mis-read categories between splits.
- **Numeric fields:** crash hour, and the seven unit counts with blanks set to 0.
- **Logistic regression:** one-hot encoding (`handle_unknown='infrequent_if_exist'`, `min_frequency=30`), hour treated as a category, unit counts standardised.
- **Gradient boosting:** native categorical handling, no encoding.

### 8.3 Adjusted-odds design matrix (Phase 3)

- **Rows:** stable-window injury crashes.
- **Columns:**
  - The six involvement flags.
  - Ten categorical fields one-hot encoded with the reference level dropped. Speed zone, remoteness, lighting, surface, horizontal alignment, roadway feature, traffic control, time of week, police region and year.
  - The reference is each field's most common category.
  - Categories with fewer than 100 crashes are pooled. If the pool itself is still under 100, it joins the reference level.
- **Deliberately excluded:** crash nature and DCA group, because they absorb the road-user effects.

### 8.4 Association-rule transactions (Phase 3)

Seven fields (crash nature, lighting, speed zone, remoteness, roadway feature, horizontal alignment, traffic control) are one-hot encoded as boolean items, with blanks set to `Unknown`. A serious-outcome item is added, using stable-window injury crashes only.

---

## 9. Aggregation and standardisation patterns

These are the techniques behind the reported shares and comparisons.

- **Pool, then divide.** Rates are built from separate numerator and denominator columns per group (`grouped_rate`). Periods are summed before dividing, never averaged as percentages.
- **Weighted grouped data.** Grouped files are always summed by their count column, never row-counted.
- **Wilson 95% intervals** on every share, defined once in the Phase 2 severity-mix check. Exact Poisson intervals are used for weather fatality rates.
- **Indirect standardisation.** Expected serious crashes come from statewide shares by remoteness × speed zone (regions, council areas, districts and electorates) or by year × site type × speed × remoteness (road sites). Results are reported as recorded ÷ expected, with funnel limits at 95% and 99.8%.
- **Direct standardisation.** Wet and dry sealed-road severity is reweighted to a common region × speed-zone mix.
- **Matched strata.** Mantel–Haenszel odds ratios within year × police region for the grouped flags.
- **Partial-year handling.** 2025 is excluded wherever complete years are needed and reported separately elsewhere.

---

## 10. Outputs

| Output | Content | Size |
|---|---|---|
| `Road crash locations - cleaned V6.csv` | All 415,407 crashes, 53 source columns plus 47 method, evidence and reconciled columns (appendix) | 264 MB, 100 columns |
| `Traffic location and suburb reconciliation V6.csv` | Every crash eligible for a public-layer lookup, its outcome and remaining gaps | 877 rows |
| `Traffic casualty restraint and crash context V6.csv` | One row per year × police region. Prefixed blocks from each source: `casualty_`, `seatbelt_`, `bicycle_helmet_`, `motorcycle_helmet_`, `driver_`, `factor_`, `weather_`, plus `Complete_Year_in_Locations`. Zero = reported with none; blank = group not in the source. | 186 rows, 169 columns |
| `Tableau data V6/` | 27 tables. `crashes.csv` (415,407 rows, 57 readable fields, including the stable-window flag and road site), the five grouped sources with aligned names and injury/serious/fatal count columns, and 21 result tables | — |
| `Queensland Traffic V6 - Esri Maps.html` | Four Folium/Esri map views in one tabbed page | 1.8 MB |
| `Traffic release manifest V6.json` | Inputs, the three helper modules, exports and analysis exports, each with size and SHA-256. Also package versions, seed, recording breaks, stable window, model years and thresholds, and site-screening constants. | — |

**Tableau shaping.**
- Ordered categories get a position prefix (`1 · Major Cities`, `01 · Jan`) so they sort correctly without manual sorting.
- Count fields are ready to sum.
- Each result table carries its period in a column.
- `build_tableau_workbook.py` packages the V6 tables into `Queensland Traffic V6.twbx` and writes the linked `Queensland Traffic V6.twb`.

---

## 11. Reproducibility, caching and code layout

| Component | Role |
|---|---|
| `Traffic_Incidents_V6.ipynb` | The analysis, in CRISP-ML(Q) order. Every code cell is preceded by **In this cell** and followed by **What this achieved**. Runs top to bottom in about a minute with warm caches. |
| `traffic_spatial_lookup.py` | Public-layer helpers (road names, junction and corridor tests, G-NAF lookups, polygon lookups). Also a stand-alone CLI. |
| `traffic_location_recovery.py` | §6 end to end: `recover_locations(raw, spatial_dir, seed, cache_dir)` returns the cleaned table, audit and validation tables |
| `traffic_road_sites.py` | §7: `load_network()`, `assign_sites()`, labels and geometry for maps |
| `.cache/` (git-ignored) | `location_recovery_<digest>.pkl` and `road_network_<digest>.pkl`. The keys hash the crash data, the spatial layers and the module source, so any change triggers a rebuild. Safe to delete; the cold run adds about 40 s. |
| `.cache/build_v6/` | The script that assembled V6 from V5 and the executor used to run it (`jupyter_client`; `nbconvert` is not installed). Scratch tooling. Move it out of `.cache/` if it should be kept. |

**Environment.** Python 3.14.4, pandas 3.1.1, NumPy 2.5.5, SciPy 1.18.1, scikit-learn 1.9.1, Shapely 2.2.0, PyProj 3.8.0, pyshp 3.1.9, ijson 3.6.0, PyArrow 26.0.1, Matplotlib 3.11.2, Folium 1.0.0, mlxtend 0.25.0. `imbalanced-learn` was dropped in V6.

---

## 12. Known limitations and open items

- **Unresolved locations.** 471 crashes still lack coordinates, and 443 of those also lack a suburb. They are excluded from maps and site screening.
- **No exposure data.** There are no traffic volumes, kilometres travelled or population, so all comparisons are shares or counts, not risk.
  - SA2 and LGA codes are ready to join to ABS population estimates.
  - The site screening would benefit from traffic volumes. Without them, busy sites sit 3–4 points below their stratum's expected share.
- **Cause of the severity drift.** Unconfirmed. It should be checked with the data custodian before the stable window is extended or the 3-point tolerance changed.
- **Unchecked labels.** Recorded police region and suburb have not yet been cross-checked against the polygon assignments for all observed points.
- **Rainfall (next).** The BoM file in the project is only the station list. Joining rainfall needs actual rainfall values:
  - **SILO** gridded data at each crash location (recommended; needs a free registration with an email address), or
  - **BoM station monthly totals** for the nearest station with good coverage.

  The crash file has year, month, weekday and hour but **no date**, and the date cannot be reconstructed (§2). The join is therefore limited to **month × location**, or to the 4–5 candidate days per crash. Recorded `Crash_Atmospheric_Condition` and `Crash_Road_Surface_Condition` already describe conditions at each crash.

---

## Appendix — columns added to the cleaned crash table

| Group | Columns |
|---|---|
| Coordinate estimate | `Coordinate_Method`, `Coordinate_Donor_Count`, `Estimated_Suburb`, `Estimated_Local_Government_Area` |
| Road-attribute inference | `Crash_Speed_Limit_Method`, `Crash_Speed_Limit_Donor_Count`, `Crash_Road_Horiz_Align_Method`, `Crash_Road_Horiz_Align_Donor_Count`, `Crash_Road_Vert_Align_Method`, `Crash_Road_Vert_Align_Donor_Count` |
| First pass | `Forward_status`, `Public_coordinate_basis`, `Public_road_segments` |
| Second pass | `Second_pass_status`, `Second_pass_road_extent_m`, `Second_pass_address_sites`, `Second_pass_crash_donors`, `Second_pass_review_latitude`, `Second_pass_review_longitude`, `Second_pass_review_basis` |
| Suburb-only recovery | `Suburb_Only_Status`, `Suburb_Only_Name`, `Suburb_Only_Method`, `Suburb_Only_Crash_Donors`, `Suburb_Only_GNAF_Sites` |
| Polygon lookups | `Public_suburb`, `Public_lga`, `Public_postal_area_2021`, `Public_police_region` |
| Reverse street lookup | `Public_street`, `Public_street_distance_m`, `Public_street_segment`, `Reverse_street_status` |
| G-NAF references | `GNAF_lookup_status`, `GNAF_reference_address`, `GNAF_reference_street`, `GNAF_reference_locality`, `GNAF_reference_postcode`, `GNAF_reference_distance_m`, `GNAF_address_id`, `GNAF_Postcode_Comparison`, `GNAF_Postcode_Comparison_Source` |
| Reconciled values | `Reconciled_Street`, `Reconciled_Suburb`, `Reconciled_Local_Government_Area`, `Suburb_Boundary_Comparison`, `Council_Area_Boundary_Comparison` |

---

<!-- project-docs-nav -->
**Project documentation:** [Index](Documentation_Index.md) · [Goals and tasks](Analytical_Goals_and_Tasks.md) · [Data and resources](Data_and_Resources.md) · **Data engineering** · [Analytics methods](Analytics_Methods.md) · [Model engineering](Model_Engineering.md) · [Implementation design](Implementation_Design.md) · [System architecture](Analytical_System_Architecture.md) · [Timeline and milestones](Timeline_and_Milestones.md) · [Risk management](Risk_Management.md)
