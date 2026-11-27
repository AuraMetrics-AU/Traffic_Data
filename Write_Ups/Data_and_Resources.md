# Data and resources — Queensland road crash analysis

*Describes the data used by the project: its sources, attributes, volumes and quality. Also covers the computing, software and people resources, and the plan for collecting and refreshing data, including the sources still to obtain. State as of 27 November 2026 (V6). The preparation steps applied to this data are in [`Data_Engineering.md`](Data_Engineering.md).*

---

## Contents

1. [Data at a glance](#1-data-at-a-glance)
2. [Crash and casualty data](#2-crash-and-casualty-data)
3. [Spatial reference data](#3-spatial-reference-data)
4. [Supporting resources already held](#4-supporting-resources-already-held)
5. [Data produced by the project](#5-data-produced-by-the-project)
6. [Data collection and refresh plan](#6-data-collection-and-refresh-plan)
7. [Data still to collect](#7-data-still-to-collect)
8. [Data quality summary](#8-data-quality-summary)
9. [Computing, software and people resources](#9-computing-software-and-people-resources)
10. [Licensing, privacy and attribution](#10-licensing-privacy-and-attribution)
11. [Appendix — attribute profile of every source field](#appendix--attribute-profile-of-every-source-field)

---

## 1. Data at a glance

| Dataset | Provider | Grain | Rows | Columns | Size | Period |
|---|---|---|---|---|---|---|
| Road crash locations | Queensland Government (Department of Transport and Main Roads), open data | One row per crash | 415,407 | 53 | 216 MB | 2001 – mid-2025 |
| Factors in road crashes | Same | Year × police region × severity × 4 factor flags | 5,523 | 14 | 0.3 MB | 2001–2025 |
| Vehicle types | Same | Year × region × severity × 3 vehicle flags | 3,764 | 13 | 0.2 MB | 2001–2025 |
| Driver demographics | Same | Year × region × severity × 7 driver flags | 22,699 | 17 | 1.7 MB | 2001–2025 |
| Road casualties | Same | Year × region × casualty severity × age × gender × road user | 38,893 | 8 | 2.4 MB | 2001–2025 |
| Seatbelt restraints and helmet use | Same | As casualties, plus restraint/helmet status; occupants, motorcyclists, cyclists only | 42,787 | 9 | 3.6 MB | 2001–2025 |
| Queensland Roads and Tracks | Queensland Government | Road segment | 564,950 | 5 properties + geometry | 108 MB (gzip GeoJSON) | Current |
| Locality boundaries | Queensland Government | Suburb/locality polygon | 3,359 | locality, LGA + geometry | 11 MB | Current |
| ABS Postal Areas 2021 | Australian Bureau of Statistics | Postal area polygon | 455 | POA code + geometry | 8 MB | ASGS Ed. 3 |
| QPS regions | Queensland Police Service | Police region polygon | 7 named regions | REGION + geometry | 1 MB (zipped shapefile) | Archive dated 2026-10-26 |
| G-NAF Queensland | Geoscape Australia | Address point | 3,116,786 | 15 retained | 72 MB (parquet) | Release 2026-08 |
| BoM rainfall station list (IDCJMC0014) | Bureau of Meteorology | Rainfall station | 4,028 | 9 | 0.4 MB | Produced 26 Nov 2026 |

**Totals.** About 425 MB of source data: 415,407 crashes × 53 fields, 113,666 grouped rows, and about 3.7 million spatial features (road segments, polygons and address points).

**Volume by year.**
- 2001–2010: about 22,000–23,500 records a year, including property-damage-only crashes.
- From 2011: 12,000–14,400 injury crashes a year.
- 2025 is partial (7,029 injury crashes to the latest release).
- Total injury crashes: 327,975.

---

## 2. Crash and casualty data

### 2.1 Road crash locations (crash level)

One row per reported crash, identified by `Crash_Ref_Number` (unique and complete). The 53 attributes fall into ten groups. The full profile is in the appendix.

| Group | Attributes | Content | Used for |
|---|---|---|---|
| Identity | `_id`, `Crash_Ref_Number` | Row number; crash reference | Keys, audit |
| Outcome | `Crash_Severity` | Fatal, Hospitalisation, Medical treatment, Minor injury, Property damage only (to 2010) | Severity measures, model targets |
| Time | `Crash_Year`, `Crash_Month`, `Crash_Day_Of_Week`, `Crash_Hour` | No day of month (see §2.3) | Trends, seasonality, time bands |
| Crash description | `Crash_Nature` (15), `Crash_Type` (4), `Crash_DCA_Code` / `Crash_DCA_Description` (89), `Crash_DCA_Group_Description` (22), `DCA_Key_Approach_Dir` | What happened, using the DCA movement classification | Movement analysis, model inputs |
| Coordinates | `Crash_Latitude`, `Crash_Longitude` (WGS84) | Point location; 598 missing | Maps, site screening, spatial joins |
| Street | `Crash_Street`, `Crash_Street_Intersecting`, `State_Road_Name` | Road names | Location recovery, site labels |
| Administrative areas | `Loc_Suburb` (3,064), `Loc_Local_Government_Area` (79), `Loc_Post_Code`, police division (338) / district (16) / region (8), Transport (6) and Main Roads (7) regions, ABS SA2 (529) / SA3 (83) / SA4 (20), `Loc_ABS_Remoteness` (5 + Unknown), state (94) and federal (31) electorates | Where, by several geographies | Area comparisons, funnels, strata |
| Road setting | `Crash_Controlling_Authority`, `Crash_Roadway_Feature` (16), `Crash_Traffic_Control` (17), `Crash_Speed_Limit` (5 bands), `Crash_Road_Horiz_Align`, `Crash_Road_Vert_Align` | Road environment | Strata, model inputs, odds |
| Conditions | `Crash_Road_Surface_Condition`, `Crash_Atmospheric_Condition`, `Crash_Lighting_Condition` | Surface, weather and light at the crash | Wet/dry, weather, lighting analyses |
| Casualties | `Count_Casualty_Fatality`, `_Hospitalised`, `_MedicallyTreated`, `_MinorInjury`, `_Total` | People injured in the crash | Fatalities per site, tallies |
| Units | `Count_Unit_Car`, `_Motorcycle_Moped`, `_Truck`, `_Bus`, `_Bicycle`, `_Pedestrian`, `_Other` | Vehicles and pedestrians involved | Involvement flags, crash types, model inputs |

### 2.2 Grouped files

The five grouped files are pre-aggregated by the publisher. Their row identifiers (`_id`) do not link to crashes. They join to the crash file only at **year × police region** (`Data_Engineering.md` §3).

| File | Dimensions | Flags or categories | Counts |
|---|---|---|---|
| Factors in road crashes | Year, police region, crash severity | Drink driving, driver speed, fatigued driver, defective vehicle (Yes/No) | Crashes; fatalities, hospitalised, medically treated, minor injury, all casualties |
| Vehicle types | Year, police region, crash severity | Motorcycle/moped, truck, bus (Yes/No). **No car flag.** | Crashes; casualties by severity |
| Driver demographics | Year, police region, crash severity | Male, female, young (16–24), senior (60+), provisional, overseas-licensed (ends 2016), unlicensed | Crashes; casualties by severity |
| Road casualties | Year, police region, casualty severity, age group (9), gender (3), road user (6) | — | Casualties |
| Seatbelt restraints and helmet use | As road casualties, but road user is vehicle occupant, motorcyclist or bicyclist | Restraint/helmet status (7 categories incl. "not determined", "not applicable") | Casualties |

### 2.3 Known structural limits

| Limit | Consequence |
|---|---|
| Property-damage-only crashes recorded only to 2010 | Analyses use injury crashes |
| Overseas-licensed flag stops after 2016 | Flag excluded |
| Hospitalisation share drifts upwards (30.5% → 49.1%) | Stable severity window 2020–2024 for serious shares |
| **No crash date**, and it cannot be reconstructed from record order (tested: `Analytics_Methods.md` E22) | Weather joins limited to month × location or candidate days |
| Grouped files don't link to crashes | Speed, drink-driving, fatigue and driver flags analysed only at year × region |
| No exposure (traffic, population, travel) | Shares and counts only, not risk rates |

---

## 3. Spatial reference data

All layers are stored in `Public spatial data/` with providers, URLs, feature counts and attribution in `sources.json`.

| Layer | Attributes used | Role |
|---|---|---|
| `roads.geojson.gz` | `road_name_full`, `alias_1_name_full`, `alias_2_name_full`, `segment_id`, `ground_rel`, line geometry | Street-name matching, junction and corridor estimates, the 513k-link / 251k-junction screening network |
| `locality.geojson.gz` | `locality`, `lga`, polygon | Suburb and council for estimated or unlabelled points |
| `postal.geojson.gz` | `POA_CODE21`, polygon | Approximate postcode |
| `police.zip` | `REGION`, polygon | Police region for points; region maps |
| `G-NAF Queensland 2026-08.parquet` | `gnaf_pid`, address, number, street name/type/suffix, locality, postcode, latitude, longitude, geocode type, confidence, primary/secondary | Address corroboration of streets and corridors |

Coordinates are WGS84 longitude/latitude in the sources. Distance work projects them to EPSG:9473 (GDA2020 / Australian Albers, metres).

---

## 4. Supporting resources already held

| Resource | Content | Use |
|---|---|---|
| `ML Model Cheat Sheet.xlsx` | Model families, metrics, deployment strategies, definitions | Framework for model selection and evaluation (`Model_Engineering.md`) |
| `Bureau of Meteorology Rainfall QLD.csv` | 4,028 rainfall stations: site number, name, latitude, longitude, start and end month, years of record, % complete, AWS flag. 848 open for all of 2001–2025, of which 560 are ≥90% complete. | Station metadata for the planned rainfall join (§7) |
| `Archive/` | V2–V5 notebooks, exports and workbooks | Version history, method comparisons |
| Tableau workbook and Esri map pages (V5) | Published visual products | Reference for V6 outputs |

---

## 5. Data produced by the project

| Output | Rows × columns | Size | Content |
|---|---|---|---|
| `Road crash locations - cleaned V6.csv` | 415,407 × 100 | 253 MiB (264 MB) | Source plus 47 recovery, evidence and reconciled fields |
| `Traffic location and suburb reconciliation V6.csv` | 877 × 53 | 0.3 MB | Crashes eligible for public lookup, with outcomes |
| `Traffic casualty restraint and crash context V6.csv` | 186 × 169 | 0.1 MB | Year × police region flat file |
| `Tableau data V6/` | 35 tables; `crashes.csv` 415,407 × 57 | 243 MB | Tableau inputs and all result tables, including the reliability experiments |
| `Queensland Traffic V6 - Esri Maps.html` | 4 map views | 1.8 MB | Interactive maps |
| `Traffic release manifest V6.json` | — | 9 KB | Fingerprints and run constants |
| `.cache/` | 2 pickles | — | Location-recovery snapshot, road network |

---

## 6. Data collection and refresh plan

| Step | Detail |
|---|---|
| **Crash data acquisition** | Download the six CSVs from the Queensland Government Open Data Portal (the Department of Transport and Main Roads crash-data collection, "Crash data from Queensland roads") whenever an update is published, and at least annually. Record the resource URLs, the download date and the publisher's "last updated" date in the release notes. |
| **Spatial layers** | Re-download a layer only when its publisher releases a new version: Roads and Tracks, locality boundaries, ABS postal areas (each ASGS edition), QPS regions, G-NAF (quarterly releases; refresh at least annually). Update `sources.json` with feature counts and dates. |
| **Checks on arrival** | The notebook's Phase 1–2 assertions run first: file presence, unique crash references, cross-file tallies, recording and severity-mix checks. A failed check stops the release (`Implementation_Design.md` §18–19). |
| **Storage** | Raw files at the project root and in `Public spatial data/`, versioned in Git LFS. Superseded releases to `Archive/`. |
| **Provenance** | The release manifest stores the SHA-256 of every input, so any result can be traced to the exact files used. |
| **Partial years** | The latest year is usually partial. It is scored separately and excluded wherever complete years are needed. |

---

## 7. Data still to collect

| Data | Source | Purpose | Collection plan | Constraint |
|---|---|---|---|---|
| **Rainfall amounts** | SILO (Queensland Government, gridded daily rainfall for any point, from 1889) — preferred. Or BoM Climate Data Online daily/monthly station rainfall, using the station list already held. | Wetter-than-usual months; rainfall on the candidate days of each crash | Script `traffic_weather.py` (`Implementation_Design.md` §16). Query SILO for each unique crash location (rounded to its 0.05° grid cell) for 2001–2025, cache locally, and join by month or candidate days. Fallback: nearest station ≥90% complete within an agreed distance. | SILO needs a free registration (an email address passed as an API parameter), supplied by the user at run time and never committed |
| **Population** | ABS Estimated Resident Population by SA2 and LGA, annual | Crashes and casualties per 100,000 people | Download ABS ERP tables. Join on SA2 and LGA names/codes already in the crash file, harmonising boundary editions. | SA2 boundaries change between ASGS editions |
| **Traffic volumes** | Department of Transport and Main Roads traffic census (AADT) for state-controlled roads, open data | Per-vehicle risk; a safety performance function for site screening | Download AADT segments and join to road links by road name and location | Covers state-controlled roads only |
| **Full crash dates** (optional) | Department of Transport and Main Roads, by data request | Exact daily weather join; holiday analysis | Formal request explaining purpose and handling | May be refused or restricted for privacy |

---

## 8. Data quality summary

| Dimension | Finding |
|---|---|
| Completeness | Coordinates missing for 598 crashes (0.14%), 127 recovered. Intersecting street and state-road name blank where not applicable. Approach direction missing 8,021. |
| Validity | Placeholders such as `Unknown` (600 remoteness, 380 lighting, 319 surface, 219 weather) and `Not coded` authority (331) are kept as their own levels |
| Consistency | All crash and casualty tallies agree across files. Restraint-file scope explains its gap exactly. |
| Uniqueness | `Crash_Ref_Number` unique. Each grouped file has unique `_id` rows but no crash key. |
| Accuracy (location) | Observed coordinates are all inside Queensland bounds. 9,485 crashes sit on stacked points shared by 10 or more records, mostly intersection geocoding. |
| Timeliness | Latest year partial; publisher release dates should be recorded on download |
| Stability over time | Four recording changes, including the severity-grading drift (`Data_Engineering.md` §5) |

---

## 9. Computing, software and people resources

| Resource | Detail |
|---|---|
| Compute | One Linux workstation (32 cores, 61 GB RAM). A full warm run takes about 1 minute; the cold cache rebuild adds about 40 s. A 16 GB laptop should suffice (estimate; memory not profiled). |
| Storage | About 425 MB sources plus about 500 MB outputs per release (mostly the cleaned crash table and `crashes.csv`). Git LFS for large files. |
| Software | Python 3.14 stack (`Implementation_Design.md` §12, §17); Tableau for dashboards; a web browser for maps. All open-source except Tableau. |
| People (roles) | Data analyst (refresh, reporting), data scientist (methods, models, experiments), data engineer (environment, spatial layers, packaging), road-safety lead (objectives, sign-off). One person can cover several roles. |
| Reference material | `ML Model Cheat Sheet.xlsx`; Highway Safety Manual network screening; references in `Model_Engineering.md` §12 and `Analytics_Methods.md` §6 |

---

## 10. Licensing, privacy and attribution

- **Crash data:** Queensland Government open data under its published open licence. De-identified, with no date of crash. The project doesn't attempt re-identification.
- **G-NAF:** incorporates G-NAF © Geoscape Australia, licensed by the Commonwealth of Australia under the G-NAF End User Licence Agreement.
- **Roads, localities, QPS regions:** Queensland Government open data. **Postal areas:** © Australian Bureau of Statistics.
- **BoM data:** © Commonwealth of Australia, Bureau of Meteorology. **SILO** has its own terms of use (to accept at registration).
- Attribution is recorded in `README.md` and `Public spatial data/sources.json`.

---

## Appendix — attribute profile of every source field

Generated from the source files on 27 November 2026. "Missing" counts empty cells only. Placeholder values such as `Unknown` are counted as values. Examples show the most frequent values.

### Road crash locations.csv — 415,407 rows × 53 columns

| Column | Type | Missing | Distinct | Examples / range |
|---|---|---|---|---|
| `_id` | integer | 0 | 415,407 | 1 – 415407 |
| `Crash_Ref_Number` | integer | 0 | 415,407 | 1 – 415408 |
| `Crash_Severity` | text | 0 | 5 | Hospitalisation; Medical treatment; Property damage only; Minor injury; … |
| `Crash_Year` | integer | 0 | 25 | 2001 – 2025 |
| `Crash_Month` | text | 0 | 12 | May; March; August; July; … |
| `Crash_Day_Of_Week` | text | 0 | 7 | Friday; Thursday; Wednesday; Tuesday; … |
| `Crash_Hour` | integer | 0 | 24 | 0 – 23 |
| `Crash_Nature` | text | 0 | 15 | Angle; Rear-end; Hit object; Overturned; … |
| `Crash_Type` | text | 0 | 4 | Multi-Vehicle; Single Vehicle; Hit pedestrian; Other |
| `Crash_Longitude` | decimal | 598 | 380,161 | 137.998 – 153.55 |
| `Crash_Latitude` | decimal | 598 | 380,577 | -29.1458 – -9.38021 |
| `Crash_Street` | text | 15 | 23,456 | Bruce Hwy; Pacific Hwy; Gold Coast Hwy; Gateway Arterial Rd; … |
| `Crash_Street_Intersecting` | text | 234,997 | 14,655 | Wynnum Rd; Warrego Hwy; Gold Coast Hwy; West St; … |
| `State_Road_Name` | text | 224,003 | 628 | Pacific Highway (Pacific Mot; Bruce Highway (Brisbane - Gy; South-East Arterial Road (Pa; Gympie Arterial Road; … |
| `Loc_Suburb` | text | 0 | 3,064 | Southport; Brisbane City; Caboolture; Surfers Paradise; … |
| `Loc_Local_Government_Area` | text | 0 | 79 | Brisbane City; Gold Coast City; Moreton Bay Region; Logan City; … |
| `Loc_Post_Code` | text | 0 | 446 | 4350; 4870; 4740; 4670; … |
| `Loc_Police_Division` | text | 0 | 338 | Toowoomba; Upper Mount Gravatt; Brisbane City; Cairns; … |
| `Loc_Police_District` | text | 0 | 16 | South Brisbane; North Brisbane; Gold Coast; Logan; … |
| `Loc_Police_Region` | text | 0 | 8 | Brisbane; North Coast; South Eastern; Southern; … |
| `Loc_Queensland_Transport_Region` | text | 0 | 6 | SEQ South; SEQ North; Southern; Northern; … |
| `Loc_Main_Roads_Region` | text | 0 | 7 | Metropolitan; South Coast; North Coast; Southern Queensland; … |
| `Loc_ABS_Statistical_Area_2` | text | 0 | 529 | Brisbane City; Cairns City; Southport - North; Caboolture; … |
| `Loc_ABS_Statistical_Area_3` | text | 0 | 83 | Townsville; Toowoomba; Brisbane Inner; Rockhampton; … |
| `Loc_ABS_Statistical_Area_4` | text | 0 | 20 | Gold Coast; Brisbane - South; Brisbane Inner City; Ipswich; … |
| `Loc_ABS_Remoteness` | text | 0 | 6 | Major Cities; Inner Regional; Outer Regional; Remote; … |
| `Loc_State_Electorate` | text | 0 | 94 | Mcconnel; South Brisbane; Clayfield; Cairns; … |
| `Loc_Federal_Electorate` | text | 0 | 31 | Brisbane; Moncrieff; Moreton; Rankin; … |
| `Crash_Controlling_Authority` | text | 0 | 4 | Locally-controlled; State-controlled; Not coded; Other |
| `Crash_Roadway_Feature` | text | 0 | 16 | No Roadway Feature; Intersection - T-Junction; Intersection - Cross; Intersection - Roundabout; … |
| `Crash_Traffic_Control` | text | 0 | 17 | No traffic control; Operating traffic lights; Give way sign; Stop sign; … |
| `Crash_Speed_Limit` | text | 5 | 5 | 60 km/h; 0 - 50 km/h; 100 - 110 km/h; 80 - 90 km/h; … |
| `Crash_Road_Surface_Condition` | text | 0 | 5 | Sealed - Dry; Sealed - Wet; Unsealed - Dry; Unsealed - Wet; … |
| `Crash_Atmospheric_Condition` | text | 0 | 5 | Clear; Raining; Fog; Smoke/Dust; … |
| `Crash_Lighting_Condition` | text | 0 | 5 | Daylight; Darkness - Lighted; Darkness - Not lighted; Dawn/Dusk; … |
| `Crash_Road_Horiz_Align` | text | 1 | 4 | Straight; Curved - view open; Curved - view obscured; Unknown |
| `Crash_Road_Vert_Align` | text | 2 | 5 | Level; Grade; Crest; Dip; … |
| `Crash_DCA_Code` | code (text) | 0 | 89 | 301; 202; 101; 703; … |
| `Crash_DCA_Description` | text | 0 | 89 | Vehs Same Direction: Rear En; Vehs Opposite Approach: Thru; Vehs Adjacent Approach: Thru; Off Path-Straight: Left Off ; … |
| `Crash_DCA_Group_Description` | text | 0 | 22 | 04: Rear-end; 01: Intersection: Adjacent A; 16: Off Carriageway on Strai; 03: Opposing Vehicles Turnin; … |
| `DCA_Key_Approach_Dir` | text | 8,021 | 6 | N; S; E; W; … |
| `Count_Casualty_Fatality` | integer | 0 | 6 | 0; 1; 2; 3; … |
| `Count_Casualty_Hospitalised` | integer | 0 | 18 | 0 – 22 |
| `Count_Casualty_MedicallyTreated` | integer | 0 | 21 | 0 – 29 |
| `Count_Casualty_MinorInjury` | integer | 0 | 16 | 0 – 17 |
| `Count_Casualty_Total` | integer | 0 | 27 | 0 – 32 |
| `Count_Unit_Car` | integer | 0 | 14 | 0 – 15 |
| `Count_Unit_Motorcycle_Moped` | integer | 0 | 6 | 0; 1; 2; 3; … |
| `Count_Unit_Truck` | integer | 0 | 6 | 0; 1; 2; 3; … |
| `Count_Unit_Bus` | integer | 0 | 4 | 0; 1; 2; 3 |
| `Count_Unit_Bicycle` | integer | 0 | 9 | 0; 1; 2; 3; … |
| `Count_Unit_Pedestrian` | integer | 0 | 9 | 0; 1; 2; 3; … |
| `Count_Unit_Other` | integer | 0 | 5 | 0; 1; 2; 3; … |

### Factors in road crashes.csv — 5,523 rows × 14 columns

| Column | Type | Missing | Distinct | Examples / range |
|---|---|---|---|---|
| `_id` | integer | 0 | 5,523 | 1 – 5523 |
| `Crash_Year` | integer | 0 | 25 | 2001 – 2025 |
| `Crash_Police_Region` | text | 0 | 8 | North Coast; Southern; Central; South Eastern; … |
| `Crash_Severity` | text | 0 | 5 | Hospitalisation; Medical treatment; Minor injury; Fatal; … |
| `Involving_Drink_Driving` | text | 0 | 2 | No; Yes |
| `Involving_Driver_Speed` | text | 0 | 2 | No; Yes |
| `Involving_Fatigued_Driver` | text | 0 | 2 | No; Yes |
| `Involving_Defective_Vehicle` | text | 0 | 2 | No; Yes |
| `Count_Crashes` | integer | 0 | 548 | 1 – 2190 |
| `Count_Fatality` | integer | 0 | 49 | 0 – 59 |
| `Count_Hospitalised` | integer | 0 | 283 | 0 – 1687 |
| `Count_Medically_Treated` | integer | 0 | 284 | 0 – 2289 |
| `Count_Minor_Injury` | integer | 0 | 259 | 0 – 1547 |
| `Count_All_Casualties` | integer | 0 | 535 | 0 – 2458 |

### Vehicle types.csv — 3,764 rows × 13 columns

| Column | Type | Missing | Distinct | Examples / range |
|---|---|---|---|---|
| `_id` | integer | 0 | 3,764 | 1 – 3764 |
| `Crash_Year` | integer | 0 | 25 | 2001 – 2025 |
| `Crash_Police_Region` | text | 0 | 8 | Brisbane; South Eastern; North Coast; Southern; … |
| `Crash_Severity` | text | 0 | 5 | Hospitalisation; Medical treatment; Minor injury; Fatal; … |
| `Involving_Motorcycle_Moped` | text | 0 | 2 | No; Yes |
| `Involving_Truck` | text | 0 | 2 | No; Yes |
| `Involving_Bus` | text | 0 | 2 | No; Yes |
| `Count_Crashes` | integer | 0 | 578 | 1 – 2276 |
| `Count_Casualty_Fatality` | integer | 0 | 52 | 0 – 60 |
| `Count_Casualty_Hospitalised` | integer | 0 | 336 | 0 – 1471 |
| `Count_Casualty_MedicallyTreated` | integer | 0 | 311 | 0 – 2070 |
| `Count_Casualty_MinorInjury` | integer | 0 | 259 | 0 – 1393 |
| `Count_Casualty_All` | integer | 0 | 576 | 0 – 2192 |

### Driver demographics.csv — 22,699 rows × 17 columns

| Column | Type | Missing | Distinct | Examples / range |
|---|---|---|---|---|
| `_id` | integer | 0 | 22,699 | 1 – 22699 |
| `Crash_Year` | integer | 0 | 25 | 2001 – 2025 |
| `Crash_Police_Region` | text | 0 | 8 | Brisbane; North Coast; South Eastern; Southern; … |
| `Crash_Severity` | text | 0 | 5 | Hospitalisation; Medical treatment; Minor injury; Property damage only; … |
| `Involving_Male_Driver` | text | 0 | 2 | Yes; No |
| `Involving_Female_Driver` | text | 0 | 2 | Yes; No |
| `Involving_Young_Driver_16-24` | text | 0 | 2 | No; Yes |
| `Involving_Senior_Driver_60plus` | text | 0 | 2 | No; Yes |
| `Involving_Provisional_Driver` | text | 0 | 2 | No; Yes |
| `Involving_Overseas_Licensed_Driver` | text | 0 | 2 | No; Yes |
| `Involving_Unlicensed_Driver` | text | 0 | 2 | No; Yes |
| `Count_Crashes` | integer | 0 | 316 | 1 – 456 |
| `Count_Casualty_Fatality` | integer | 0 | 28 | 0 – 27 |
| `Count_Casualty_Hospitalised` | integer | 0 | 254 | 0 – 437 |
| `Count_Casualty_MedicallyTreated` | integer | 0 | 268 | 0 – 463 |
| `Count_Casualty_MinorInjury` | integer | 0 | 158 | 0 – 306 |
| `Count_Casualty_All` | integer | 0 | 331 | 0 – 482 |

### Road casualties.csv — 38,893 rows × 8 columns

| Column | Type | Missing | Distinct | Examples / range |
|---|---|---|---|---|
| `_id` | integer | 0 | 38,893 | 1 – 38893 |
| `Crash_Year` | integer | 0 | 25 | 2001 – 2025 |
| `Crash_Police_Region` | text | 0 | 8 | Brisbane; North Coast; South Eastern; Southern; … |
| `Casualty_Severity` | text | 0 | 4 | Hospitalised; Medically treated; Minor injury; Fatality |
| `Casualty_AgeGroup` | text | 0 | 9 | 17 to 24; 30 to 39; 40 to 49; 50 to 59; … |
| `Casualty_Gender` | text | 0 | 3 | Male; Female; Unknown |
| `Casualty_RoadUserType` | text | 0 | 6 | Driver; Passenger; Motorcyclist; Pedestrian; … |
| `Casualty_Count` | integer | 0 | 207 | 1 – 257 |

### Seatbelt restraints and helmet use.csv — 42,787 rows × 9 columns

| Column | Type | Missing | Distinct | Examples / range |
|---|---|---|---|---|
| `_id` | integer | 0 | 42,787 | 1 – 42787 |
| `Crash_Year` | integer | 0 | 25 | 2001 – 2025 |
| `Crash_PoliceRegion` | text | 0 | 8 | Brisbane; North Coast; South Eastern; Southern; … |
| `Casualty_Severity` | text | 0 | 4 | Hospitalised; Medically treated; Minor injury; Fatality |
| `Casualty_AgeGroup` | text | 0 | 9 | 17 to 24; 30 to 39; 40 to 49; 25 to 29; … |
| `Casualty_Gender` | text | 0 | 3 | Male; Female; Unknown |
| `Casualty_Road_User_Type` | text | 0 | 3 | Vehicle Occupant; Motorcyclist; Bicyclist |
| `Casualty_Restraint_Helmet_Use` | text | 0 | 7 | Helmet Worn; Restrained; Restraint Use Not determined; Unrestrained; … |
| `Casualty_Count` | integer | 0 | 203 | 1 – 309 |

---

<!-- project-docs-nav -->
**Project documentation:** [Index](Documentation_Index.md) · [Goals and tasks](Analytical_Goals_and_Tasks.md) · **Data and resources** · [Data engineering](Data_Engineering.md) · [Analytics methods](Analytics_Methods.md) · [Model engineering](Model_Engineering.md) · [Implementation design](Implementation_Design.md) · [System architecture](Analytical_System_Architecture.md) · [Timeline and milestones](Timeline_and_Milestones.md) · [Risk management](Risk_Management.md)
