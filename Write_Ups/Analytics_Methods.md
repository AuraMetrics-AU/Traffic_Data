# Analytics methods — Queensland road crash analysis

*Covers the descriptive and comparative analyses in `Traffic_Incidents_V6.ipynb` (27 November 2026), the statistical techniques behind them, and a log of every experiment and diagnostic run while building V5 and V6, including the negative results. It sits beside [`Data_Engineering.md`](Data_Engineering.md), which covers how the data was prepared, and [`Model_Engineering.md`](Model_Engineering.md), which covers the predictive and ranking models and their evaluation. Each analysis names its CRISP-ML(Q) phase and notebook section.*

---

## Contents

1. [Shared conventions](#1-shared-conventions)
2. [Catalogue of analyses](#2-catalogue-of-analyses)
   - [2.1 Recording and data quality](#21-recording-and-data-quality)
   - [2.2 Severity and crash types](#22-severity-and-crash-types)
   - [2.3 Time](#23-time)
   - [2.4 Place](#24-place)
   - [2.5 Road setting and movement](#25-road-setting-and-movement)
   - [2.6 Road users and vehicles](#26-road-users-and-vehicles)
   - [2.7 Casualties, protection and weather](#27-casualties-protection-and-weather)
   - [2.8 Comparing like with like](#28-comparing-like-with-like)
3. [Statistical techniques reference](#3-statistical-techniques-reference)
4. [Experiment and diagnostic log](#4-experiment-and-diagnostic-log)
5. [Open analytical questions](#5-open-analytical-questions)
6. [References](#6-references)

> **Coverage of the methodology brief.** Method details and formulas: §2 (each analysis) and §3. Selection criteria for the analytical techniques: §3.1. Experimental design and the reliability programme: §4 (design principles, E1–E31). Evaluation of the analytical methods: the "how to read" and caveats in §2, plus the validation experiments in §4. Supporting material: notebook figures and the `Tableau data V6/result_*` tables named in each entry, and §6. The models (classifiers, adjusted odds, site screening, rules), their algorithms, metrics and selection matrix are in [`Model_Engineering.md`](Model_Engineering.md).

---

## 1. Shared conventions

These rules apply to every analysis unless the analysis says otherwise.

| Convention | Rule | Why |
|---|---|---|
| Population | **Injury crashes** (fatal, hospitalisation, medical treatment, minor injury) | Property-damage-only crashes are recorded only to 2010 |
| Severity measure | **Serious share** = fatal or hospitalisation ÷ injury crashes. **Fatal share** = fatal ÷ injury crashes. | Outcome among recorded crashes, not risk of crashing |
| Casualty measure | **Fatalities per 100 casualties**, or the share of fatalities in a group | A rate answers "how often did this group die"; a share answers "who died" |
| Windows | **Stable severity window 2020–2024** for serious shares. **Latest ten complete years 2015–2024** for casualty rates and site screening. **Complete years** (all 12 months) wherever a year is a unit. | The grading drift (E7). Small groups need more years. 2025 is partial. |
| Pooling | Sum numerators and denominators across years and areas **before** dividing | Averaging percentages weights small groups wrongly |
| Weighting | Grouped files are summed by their count column (`Count_Crashes`, `Casualty_Count`) | One row is a group, not a crash |
| Uncertainty | Wilson 95% interval on shares. Exact Poisson interval on low-count rates. Funnel limits for area comparisons. | Small groups otherwise look extreme |
| Minimum cells | Blank where n < 100 (remoteness × speed heatmap) or n < 50 (day × hour heatmap). ≥10 crashes per stratum in direct standardisation. ≥5 crashes for a ranked road site. | Avoids reading noise |
| Exposure | None. No traffic volumes, travel or population. | Every comparison is among recorded crashes or casualties, not per trip or per person |
| Coordinates | Maps and site screening use **observed** coordinates only. Estimated points are a separate optional map layer. | Estimates carry location error |
| Unknown categories | Kept visible as their own level (for example, restraint "not determined") rather than dropped | Leaving them out can bias the known-status shares (E-series notes) |

---

## 2. Catalogue of analyses

Each entry gives the question, the data and window, the method, the output, how to read it and its caveats. Headline results are from the 27 November 2026 run.

### 2.1 Recording and data quality

#### Recording changes over time

- **Phase and section:** Phase 2, "Check for recording changes over time".
- **Question:** Which series changed because of how data was recorded rather than road safety?
- **Data:** Crash file by year; overseas-licensed flag from demographics; minor-injury casualties for complete years.
- **Method:** Stacked bars of injury vs property-damage-only records, flagged crashes by severity, and a line of minor-injury casualties. The last property-damage-only year is derived from the data.
- **Output:** Three-panel chart and audit table.
- **How to read:**
  - Property-damage-only crashes are 35.6–40.8% of records each year to 2010, then absent.
  - The overseas flag covers all severities to 2013 and fatal crashes only to 2016.
  - Minor-injury casualties fall from 6,089 (2007) to 2,029 (2015), then recover to 4,253 (2024).
- **Caveats:** The minor-injury dip is unexplained by the sources.

#### Severity mix drift (V6)

- **Phase and section:** Phase 2, "Check whether the severity mix drifts".
- **Question:** Does the grading of injury severity change over time?
- **Data:** Injury crashes by year, 2001–2025.
- **Method:** Severity shares by year. A **stable window** is derived by walking back from the latest complete year while the hospitalisation and serious shares stay within 3 points of it. The fatal share is plotted with Wilson intervals.
- **Output:** Two-panel chart; `result_severity_mix_by_year`; `stable_years`.
- **How to read:** Hospitalisation rises from 30.5% to 49.1% and serious from 32.6% to 51.0%, with the fatal share flat at 1.5–2.3%. The window is 2020–2024.
- **Caveats:** The cause is unconfirmed. The pattern points to grading practice rather than more severe crashes.

#### Source tallies

- **Phase and section:** Phase 2, "Check that source counts tally".
- **Question:** Do the six files describe the same crashes and casualties?
- **Method:** Statewide and year × region totals compared with the locations file. Restraint and casualty files aligned by road user.
- **How to read:**
  - Crash counts agree everywhere (415,407).
  - Casualty counts agree (437,355).
  - The restraint shortfall (20,207) is exactly pedestrians plus "Other".

  Details are in `Data_Engineering.md` §4.

#### Location recovery

- **Phase and section:** Phase 2, "Run the location recovery" and the summary chart.
- **Question:** How many crashes lacking coordinates were recovered?
- **How to read:** 598 lacked coordinates. 127 coordinate pairs and 28 suburb-only estimates were recovered, and 443 still lack both. Method details are in `Data_Engineering.md` §6.

### 2.2 Severity and crash types

#### Severity distribution and most frequent crash types

- **Phase and section:** Phase 2, "Explore severity, crash types, time of day, and road setting".
- **Question:** How are injury crashes distributed by severity and by crash nature?
- **Data:** All 327,975 injury crashes, 2001–2025 (counts only).
- **Method:** Horizontal bars of counts and shares. Top 12 crash natures.
- **How to read:** 40.6% hospitalisation and 1.9% fatal across the whole series.
- **Caveats:** All years pooled. Use the stable window for any share comparison.

### 2.3 Time

#### Day × hour severity heatmap

- **Question:** When are injury crashes most severe?
- **Data:** Stable window 2020–2024. Peak-hour counts use all years.
- **Method:** Serious share for each day × hour cell. Cells with fewer than 50 crashes are blank.
- **How to read:** Late-night weekend cells are the most severe. The most injury crashes occur at 15:00.
- **Caveats:** Severity, not volume, so pair it with counts.

#### Weekend night vs weekday contrast

- **Question:** How much more severe are weekend nights?
- **Data:** Stable window.
- **Method:** Two fixed groups: weekend 22:00–04:59 against weekday 05:00–21:59.
- **How to read:** Serious 64.6% against 47.1%; fatal 3.76% against 1.57%. V5 pooled all years and got 57.0% against 39.9%: a similar gap at a lower level.
- **Caveats:** Weekday nights and weekend days are excluded from both groups.

#### Seasonality (V6)

- **Question:** Which months have more crashes, and are they more severe?
- **Data:** Complete years 2001–2024 for volume; stable window for severity.
- **Method:**
  - **Volume:** monthly injury crashes ÷ days in that month and year, indexed to the year's mean (100). Shown as a year × month heatmap.
  - **Severity:** serious and fatal shares by month with Wilson intervals.
- **Output:** Heatmap, two share panels; `result_month_seasonality`, `result_month_severity`.
- **How to read:**
  - **Volume:** January (86) and December (94) are lowest, August highest (104). April 2020 (65) shows the COVID-19 restrictions.
  - **Severity:** flat (serious 47–52%, fatal 1.7–2.2%, all intervals overlapping).
- **Caveats:** No crash date is available, so holiday periods cannot be isolated (E22).

### 2.4 Place

#### Crash map

- **Phase and section:** Phase 2, "Map the crashes".
- **Question:** Where do crashes concentrate?
- **Method:** Folium on an Esri basemap: a heat layer of a 5,000-point sample of observed crashes, 180 sampled markers per severity, and estimated coordinates in their own layer.
- **Caveats:** Sampled for speed, so it shows broad concentration only. Tableau's "Crash points" sheet shows every crash.

#### Regional profiles

- **Phase and section:** Phase 2, "Compare regional burden, severity and reported contributing factors".
- **Question:** How do police regions differ in volume, severity and reported factors?
- **Data:** 2020–2024, named regions.
- **Method:** Each measure is built from its own source's numerator and denominator (`grouped_rate`), then pooled across the window. Measures include serious crashes, severe casualties, speed, fatigue, drink driving, truck, motorcycle, young driver, and unrestrained or helmet not worn (known status only). Shown as a volume × severity scatter, a speed × severity bubble per region-year, and a heatmap.
- **How to read:** Brisbane has the most injury crashes (18,395) and Central the highest serious share (66.5%).
- **Caveats:** Associations between regional summaries don't show that the same crashes shared those characteristics.

#### Region road mix (indirect standardisation)

- **Phase and section:** Phase 2, "Allow for each region's road mix".
- **Question:** Is a region's severity explained by where its crashes happen?
- **Data:** 2020–2024 injury crashes, named regions.
- **Method:** Each crash's expected serious probability is the statewide share for its remoteness × speed-zone cell. A region's ratio is recorded ÷ expected, with an interval from the Wilson interval of the recorded share divided by the expected share.
- **Output:** Dumbbell chart; `result_region_road_mix`.
- **How to read:** Recorded shares span 26.4 points (40.1% Brisbane to 66.5% Central). After road mix, ratios span only 0.94–1.05. Central (1.03–1.07), North Coast (1.02–1.06) and Brisbane (0.93–0.96) exclude 1.
- **Caveats:** Adjusts for two factors only. A region that dominates a cell pulls its own ratio towards 1.

#### Area funnel plots (V6)

- **Phase and section:** Phase 2, "Local areas compared with their road mix".
- **Question:** Which council areas, police districts and state electorates record more serious crashes than their road mix predicts?
- **Data:** Stable window.
- **Method:** The same indirect standardisation as the region road mix. Areas are plotted as recorded ÷ expected against expected count (log scale), with 95% and 99.8% limits 1 ± z·√(E(1 − p̄))/E. Council names are normalised.
- **Output:** Three funnels; `result_area_funnel`.
- **How to read:**
  - Above 99.8%: Moreton Bay City, Ipswich City, Mackay Region, Gladstone Region and Burdekin Shire; the Moreton, Ipswich and Mackay districts; Ipswich, Redcliffe, Morayfield, Nanango and other electorates.
  - Below 99.8%: Brisbane City and Toowoomba Region, among others.
- **Caveats:** These are areas to investigate, not rankings. Local differences in grading can produce them.

#### Region maps

- **Phase and section:** Phase 2, "Map restraint and weather patterns by region".
- **Question:** How do restraint non-use and rain fatalities vary by region?
- **Method:** Police-region polygons are merged and simplified.
  - **Bubble map:** bubble area = female occupant casualties with known status; colour = unrestrained share.
  - **Shaded map:** share of all fatalities recorded in rain.
- **Caveats:** Seven named regions only, with pooled counts.

#### Road-site screening

Excess serious crashes at junctions and links. Covered as a model in `Model_Engineering.md` §5. Its diagnostics are E15–E18 below.

### 2.5 Road setting and movement

#### Remoteness × speed zone heatmap

- **Question:** How does severity vary with remoteness and speed limit together?
- **Data:** Stable window.
- **Method:** Serious share per cell, blank where n < 100. A companion table gives fatal shares by remoteness and by speed zone.
- **How to read:** Fatal share 1.01% in major cities against 6.48% remote; 0.96% at 60 km/h against 5.32% at 100–110 km/h.
- **Caveats:** If minor crashes are less completely reported remotely, remote shares are overstated.

#### Lighting × wet/dry surface (direct standardisation)

- **Phase and section:** Phase 2, "Lighting and wet-road comparisons".
- **Question:** Is a wet sealed road more severe than a dry one under the same lighting?
- **Data:** 2020–2024, sealed roads, three lighting conditions.
- **Method:** Serious shares for the six lighting × surface combinations, each reweighted to one common region × speed-zone mix. Only strata with ≥10 crashes in all six combinations are used.
- **Output:** Heatmap and wet − dry bars; `result_wet_dry_standardised`.
- **How to read:** In unlit darkness both are about 64%. The wet − dry gaps are small.
- **Caveats:** Wet-road crashes may differ in exposure (fewer, slower trips).

#### Movement codes (V6)

- **Phase and section:** Phase 2, "Detailed movement codes".
- **Question:** Which crash movements produce fatal crashes?
- **Data:** Stable window, 89 DCA descriptions.
- **Method:** Injury, serious and fatal counts by code; fatal share with Wilson interval; share of all fatal crashes. Top 15 by fatal count.
- **Output:** Bars and interval plot; `result_dca_codes`.
- **How to read:**
  - **Head-on:** 3.6% of injury crashes but 19.0% of fatal (10.2% fatal share).
  - **Run-off-road:** three run-off-road codes on curves and straights add 24%.
  - **Rear-end:** the most common crash, with the lowest fatal share of the 15 codes shown (0.34%).

### 2.6 Road users and vehicles

#### Flag shares by severity (grouped files)

- **Phase and section:** Phase 2, "Explore vehicle involvement, driver characteristics, and safety".
- **Question:** How common is each reported flag within each severity level?
- **Method:** For each factor, vehicle and driver flag, flagged crashes ÷ crashes of that severity, from the flag's own source. The overseas flag is excluded.
- **How to read:** Drink driving is in 21.5% of fatal crashes against 4.5% of minor-injury crashes, and speed in 22.8% against 3.0%.

#### Vehicle involvement (grouped vehicle table)

- **Phase and section:** Phase 2, "Vehicle involvement and crash severity".
- **Question:** How severe are crashes involving a motorcycle, truck or bus?
- **Data:** 2020–2024 for the contrast; complete years for the trend; ten years for the per-year spread.
- **Method:** Weighted severity shares with and without each flag; annual involvement share; box plot of annual serious shares.
- **How to read:** Fatal share: motorcycle 4.38% vs 1.63%; truck 4.84% vs 1.75%; bus 2.03% vs 1.96%.
- **Caveats:** **The source has no car flag.** Cars are covered below.

#### Crash-level road users and vehicles (V6)

- **Phase and section:** Phase 2, "Road users and vehicles in each crash".
- **Question:** The same comparison at crash level, adding pedestrians, cyclists, cars and single-vehicle crashes.
- **Data:** Stable window; flags from `Count_Unit_*` > 0.
- **Method:** Serious and fatal shares, involved against not involved, with Wilson intervals. Crash-level motorcycle, truck and bus counts are first checked against the grouped table (exact match).
- **Output:** Dot-and-interval chart; `result_unit_involvement`.
- **How to read:**
  - **Pedestrian:** 4.08% fatal.
  - **Motorcycle:** 72.4% serious.
  - **Truck:** 4.84% fatal.
  - **Single vehicle:** 25% of injury crashes but 44% of fatal crashes.
- **Caveats:** The car flag compares car crashes with the 9% that have no car, so it looks "protective" (E9).

#### Crash type composition, including cars (V6)

- **Question:** Where do cars feature, and how severe is each combination of road users?
- **Data:** Stable window.
- **Method:** One mutually exclusive type per crash, first match in a fixed order: pedestrian struck; single car; two or more cars only; car + motorcycle / bicycle / truck / bus / other; motorcycle without car; bicycle without car; truck or bus without car; other. For each type: share of injury and of fatal crashes, and serious and fatal shares with intervals.
- **Output:** Paired bars and interval plot; `result_crash_composition`.
- **How to read:**

  | Type | Share of injury crashes | Share of fatal crashes | Fatal share |
  |---|---|---|---|
  | Car-on-car only | 49% | 14.7% | 0.59% |
  | Single car | 18.6% | **29.6%** | 3.1% |
  | Car + motorcycle | — | — | 3.8% |
  | Car + truck | — | — | 3.8% |
  | Motorcycle without a car | — | — | 5.2% (highest) |

- **Caveats:** The order decides which type multi-type crashes get. Car + motorcycle + truck counts as car + motorcycle.

#### Treemaps

- **Phase and section:** Phase 2, "Treemaps of crash counts and severity".
- **Question:** What does the volume and severity mix look like by region and by vehicle group?
- **Method:** Recursive binary split (each rectangle is divided along its longer side at the count-weighted midpoint). Areas are proportional to injury crash counts, with severity tiles nested inside each group, and an assertion checks every area.
- **Caveats:** For proportions at a glance, not precise comparison.

#### Sankey diagrams

- **Phase and section:** Phase 2, "Two- and three-level Sankey diagrams" and "Sankey of recorded gender, seatbelt status and injury severity".
- **Question:** How do counts flow from one category to the next?
- **Method:** Custom count-weighted Sankey with Bézier bands. Totals are reconciled at every stage by assertion.
  - Vehicle flag group → crash severity.
  - Road user → equipment status → injury severity (known status).
  - Gender → seatbelt status → injury severity, with gender totals checked against the flat file.
- **Caveats:** Known status only. "Not determined" is shown in the rate analysis instead.

### 2.7 Casualties, protection and weather

#### Annual casualties and index

- **Question:** How have casualty counts changed?
- **Method:** Casualties by severity for complete years, as counts and as an index (first year = 100). The minor-injury dip is shaded.
- **How to read:** From 2001 to 2024, hospitalised casualties rose 62.8% (5,309 → 8,641), fatalities fell 6.8% (324 → 302) and medically treated fell 28.0%.
- **Caveats:** Grading drift (E7). Counts are not population-adjusted.

#### Fatalities per 100 casualties by protection, age and road user

- **Phase and section:** Phase 2, "Fatalities per 100 casualties by protective equipment, age and road user".
- **Question:** How often does a casualty in each group die?
- **Data:** Ten complete years, 2015–2024. "Not applicable" equipment excluded.
- **Method:** Fatalities ÷ casualties × 100 with a Wilson interval, by road user × equipment status and by age group × road user. The "not determined" groups are kept.
- **Output:** `result_equipment_fatality_rates`.
- **How to read:**
  - Unrestrained occupants: 9.15 per 100 against 0.85 restrained (10.8×). "Not determined": 1.52.
  - Motorcyclists: 7.58 without a helmet against 3.65 with one.
  - Pedestrians: 12.1 per 100 aged 75+ against 4.2 aged 17–74.
- **Caveats:** Uninjured occupants are not in the data. Restraint status is established more thoroughly after a fatal crash, which overstates the protective effect.

#### Seatbelt non-use by gender (flat file)

- **Phase and section:** Phase 2, "Examples the flat file can answer".
- **Question:** What share of occupant casualties, and of fatalities, were unrestrained, by recorded gender?
- **Data:** 2020–2024, known status.
- **How to read:** 778 of 31,696 female occupant casualties with known status were unrestrained.

#### Weather fatality rates

- **Phase and section:** Phase 2, "Charts and Esri maps for the flat file".
- **Question:** Are crashes in some atmospheric conditions deadlier?
- **Data:** 2020–2024, all people.
- **Method:** Fatalities per 100 recorded crashes by condition, as a bubble chart (crash volume against rate) with an exact Poisson interval.
- **How to read:**
  - **Fog:** 17 fatalities, 2.6–7.3 per 100, just above clear (2.0–2.2) and rain (1.9–2.6).
  - **Smoke/dust:** 3 fatalities (0.6–8.4), which supports no conclusion.
- **Caveats:** Recorded condition at the crash. External rainfall data is pending (§5).

### 2.8 Comparing like with like

#### Pooled vs within-region-and-year correlation

- **Phase and section:** Phase 2, "Associations that change when we compare like with like".
- **Question:** Is the region-year link between reported speed involvement and serious share real or compositional?
- **Data:** 2020–2024 region-years.
- **Method:** Least-squares fit of each rate on region and year indicators. The residuals are the deviations from typical region and year levels. Pooled and residual correlations are compared.
- **Output:** Paired scatter plots; `result_speed_severity_region_year`.
- **How to read:** The correlation falls from 0.81 pooled to 0.12 within region and year. Most of the apparent link reflects which regions and years have both.

#### Matched odds (grouped flags)

- **Phase and section:** Phase 2, "Matched odds of serious crash outcomes".
- **Question:** Do flag associations with a serious outcome hold within year × region?
- **Method:** Mantel–Haenszel odds ratio across year × region 2×2 tables, with Robins–Breslow–Greenland 95% intervals, compared with the pooled odds ratio.
- **Output:** `result_matched_odds`.
- **How to read:** Motorcycle 3.06, speed 2.79, drink driving 2.57, truck 1.10, young driver 0.86, bus 0.84.
- **Caveats:** Cannot adjust for anything else. Crash-level adjusted odds (`Model_Engineering.md` §4) supersede the vehicle flags.

#### Association rules

Apriori on the stable window. Covered in `Model_Engineering.md` §6.

---

## 3. Statistical techniques reference

| Technique | Formula / procedure | Used in |
|---|---|---|
| **Wilson score interval** | Centre (p + z²/2n)/(1 + z²/n), half-width z√(p(1−p)/n + z²/4n²)/(1 + z²/n), z = 1.96 | Every share and rate per 100 |
| **Exact Poisson interval** | Lower χ²(0.025; 2k)/2, upper χ²(0.975; 2(k+1))/2, divided by the denominator | Weather fatality rates |
| **Indirect standardisation** | E = Σ p₍stratum₎ over the area's crashes; ratio = O/E | Region road mix, area funnels, site screening |
| **Funnel limits** | 1 ± z·√(E(1 − p̄))/E, z = 1.96 and 3.09 | Area funnel plots |
| **Direct standardisation** | Σ w₍stratum₎ × share₍stratum, condition₎, with weights from the pooled stratum distribution | Wet against dry by lighting |
| **Mantel–Haenszel odds ratio** | Σ(aᵢdᵢ/nᵢ) / Σ(bᵢcᵢ/nᵢ) with the Robins–Breslow–Greenland variance of the log odds ratio | Matched odds |
| **Fixed-effects residual correlation** | Residuals of each rate after least squares on region and year indicators; Pearson correlation of residuals | Speed against severity |
| **Seasonal index** | (count ÷ days in month) ÷ the year's mean daily rate × 100 | Seasonality |
| **Beta-binomial empirical Bayes** | ρ by method of moments; k = (1 − ρ)/ρ; shrunk excess = (O − E)·n/(n + k) | Road-site screening |
| **Logistic regression with Wald intervals** | exp(β ± 1.96·SE), SE from (X′WX)⁻¹ | Adjusted odds |

---

### 3.1 Why these techniques

The analytical techniques were chosen against the criteria used for the models (`Model_Engineering.md` §2.1). The most relevant criteria here are fit to grouped and crash-level count data, honest uncertainty for small groups, interpretability, and no extra dependencies.

| Technique | Chosen over | Why it is feasible and effective here |
|---|---|---|
| Wilson interval | Normal (Wald) interval | Stays inside 0–1 and keeps close to nominal coverage for small *n* and shares near 0, which matters for fatal shares of 1–5% |
| Exact Poisson interval | Normal approximation | Weather categories with 3–17 fatalities need exact limits |
| Indirect standardisation | Raw shares; regression | Needs only stratum shares; works for any area with few crashes; gives an intuitive recorded ÷ expected ratio |
| Funnel plot | Ranked league table | Shows chance variation, so small areas cannot top a list through noise (Spiegelhalter 2005) |
| Direct standardisation | Stratified tables only | One number per lighting × surface cell under a common mix, so the cells can be compared directly |
| Mantel–Haenszel odds ratio | Pooled odds ratio | The only stratified adjustment possible on year × region tables. Superseded at crash level by logistic regression. |
| Fixed-effects residual correlation | Pooled correlation | Removes region and year composition with plain least squares |
| Seasonal index per day | Raw monthly counts | Removes month-length and year-level effects, leaving only the seasonal shape |
| Mutually exclusive crash types | Overlapping flags | Shares add to 100%, and the "car protects" illusion of an overlapping flag is avoided (E9) |
| Custom Sankey and treemap code | Plotly or other packages | No new dependency, and totals are asserted in code. The trade-off is static images. |

## 4. Experiment and diagnostic log

Every test run while building V5 and V6, in the order they matter, with its question, method, result and decision. Negative results are kept on purpose.

**Design principles.** Each experiment states the question it tests and compares against a baseline or control: a withheld truth (E3–E5), the unadjusted figure (E10–E12), the previous method (E13–E15, E19–E20) or the baseline setting (R-series). It varies one choice at a time, uses the time order of the data where relevant (E14–E15, R7), and records the decision taken. E1–E24 are development experiments that chose the methods. E25–E31 are the reliability programme run on the chosen methods (notebook Phase 4 "Reliability and sensitivity experiments"; details in `Model_Engineering.md` §11).

| # | Question | Method | Result | Decision |
|---|---|---|---|---|
| **E1** | Can the six files be joined crash by crash? | Key audit of `_id`, `Crash_Ref_Number` and shared columns | `_id` is a per-file row number (matching IDs disagree on year); only the locations file has the crash reference | Join only at year × police region |
| **E2** | Do the files describe the same crashes and casualties? | Statewide and 186-group tallies; restraint vs casualty alignment by road user | All crash and casualty totals agree. The restraint gap of 20,207 = pedestrians + "Other". 23,375 detailed groups agree. | Files treated as consistent; tallies kept as assertions |
| **E3** | Which donor rule best estimates missing coordinates? | 10,000 withheld observed locations; three rule sets | Median error: V2 suburb/LGA 0.87 km, V3 hierarchy 0.23 km, street fallback 0.011 km (37% coverage) | Use the V3 hierarchy plus the compact/coarse street fallback |
| **E4** | Are the second-pass junction and corridor estimates accurate? | 5,441 withheld crashes on comparable streets, each excluded from its own evidence | Four-arm junctions 9.3 m median (7 estimates); corridors 41.7 m (2) | Keep the strict rules; unsupported candidates are review-only |
| **E5** | Is suburb-only recovery reliable? | Holdout on 4,446 eligible records | 294 of 295 estimates correct | Apply; record in `Reconciled_Suburb` |
| **E6** | Which series changed for recording reasons? | Yearly series of property-damage-only records, overseas flag and minor injuries | Property-damage-only ends 2010; overseas flag ends 2013/2016; unexplained minor-injury dip | Injury crashes only; drop the overseas flag; caution on minor-injury trends |
| **E7** | Does severity grading drift? (V6) | Severity mix by year; ±3-point stable-window rule | Hospitalisation 30.5% → 49.1%, fatal flat; window 2020–2024 | Serious shares, rules and models use the window; trends use the fatal share; screening uses year strata |
| **E8** | Do crash-level unit counts reproduce the grouped vehicle table? (V6) | Count crashes with each unit type > 0 against the grouped flag totals | Exact match for motorcycle, truck and bus | Crash-level analysis replaces grouped analysis where possible |
| **E9** | Is a car-involvement flag informative? (V6) | Car flag against crash-type composition | Cars in 91% of injury crashes. The flag "protects" (1.7% vs 4.8% fatal) only because the no-car group is motorcycle-, bicycle- and truck-only. | Report cars through mutually exclusive crash types |
| **E10** | How much of the regional severity gap is road setting? | Indirect standardisation by remoteness × speed | Spread 26.4 points raw; ratios 0.94–1.05 after | Regional rankings are mostly setting |
| **E11** | Is the speed–severity regional link real? | Pooled vs fixed-effects residual correlation | 0.81 → 0.12 | Treat statewide region-year rankings with caution |
| **E12** | Are the grouped matched odds confounded? (V6) | Crash-level logistic regression against Mantel–Haenszel | Bus 0.84 → 1.01 (no association); truck 1.10 → 1.31; motorcycle 3.06 → 3.35 | Use crash-level adjusted odds for vehicle effects |
| **E13** | Can K-Means find hotspots? (V3–V4) | K-Means on longitude, latitude, hour and year | Clusters separated the early and late recording periods | Rejected |
| **E14** | Do DBSCAN count hotspots persist? (V5) | 529 DBSCAN hotspots; 200 m grid two-period test | The top 100 cells fell to 0.61× next period while all cells rose 1.19×; 22 stayed in the top 100 | Counts regress to the mean; replaced in V6 |
| **E15** | Does excess ranking persist better than count ranking? (V6) | Rank sites in 2015–19 by count, raw excess and shrunk excess; measure in 2020–24 | Count top 100: −3 excess later. Raw and shrunk top 100: +50 and +45. Shrinkage did not improve the ranking order. | Use excess ranking; shrinkage for magnitudes |
| **E16** | Why do shrunk estimates overshoot? (V6) | Decile calibration, crash-weighted on both sides; excess share by site-size band | Slope ≈ 1 with a 3–4 point offset; excess share falls from +3.2 points (1 crash) to −7.4 (20+) | The reference is off, not k. Next: add site frequency to the strata. |
| **E17** | Are stacked coordinates geocoding artefacts? (V6) | Stacked-point share by site type | 26% of junction-site crashes against 0.5% on links; none at top links | Intersection geocoding; review claim corrected; report per site |
| **E18** | What drives excess at the top rural links? (V6) | Motorcycle share at top sites | 33% at the top-20 links against 12% statewide (Mt Mee Rd 75%, Northbrook Pkwy 86%) | Flag as motorcycle routes; a road-user-adjusted variant is open |
| **E19** | Did SMOTENC help the V5 classifier? | Random Forest with and without SMOTENC, average precision | Fatal average precision 0.088 → 0.081; recall up, precision 0.05 | Drop resampling |
| **E20** | Do binary models on the stable window beat V5? (V6) | Gradient boosting and logistic regression, time split; scored on V5's test years | Fatal average precision 0.13 vs 0.091; precision 9–10% vs 5–6.5% at about 50% recall; logistic regression = boosting | Logistic regression recommended; not operational |
| **E21** | Do association rules change on the stable window? (V6) | Apriori 2020–2024 against V5's 2001–2025 | Baseline 49.9% vs 42.6%; 136 rules vs 40; head-on in 100–110 km/h still leads (lift 1.70) | Use the window; a redundancy filter is pending |
| **E22** | Can the crash date be reconstructed? (V6) | Test whether the reference number is in date order (overall correlation; implied days within months) | Correlation 0.35; about 3 implied days per record (random order); 0 of 294 months consistent | Not possible; not pursued; ask Transport and Main Roads if needed |
| **E23** | Do any areas stand out after road mix? (V6) | Funnel plots by council, district and electorate | 5 councils, 3 districts and 7 electorates above the 99.8% limit | Investigate locally; check grading practice first |
| **E24** | Is the BoM rainfall file usable for a join? (V6) | Parse and profile | A station list (IDCJMC0014, 4,028 stations; 848 open 2001–2025), no amounts | Need SILO or BoM station data; month × location or candidate days |
| **E25 (R1)** | Are the test metrics precise enough to compare models? | 500 paired bootstrap resamples of 2024 | Serious ROC AUC 0.71–0.72; fatal average precision 0.09–0.15; boosting − logistic includes 0 for fatal | Report intervals; treat the models as equivalent |
| **E26 (R2)** | Do the results depend on the random seed? | Five gradient-boosting seeds | Fatal average precision 0.121–0.135; serious ROC AUC 0.716–0.717 | Stable |
| **E27 (R3)** | Which inputs carry the signal? Can severe crashes be predicted from inputs known before a crash? | Feature-group ablation | Fatal average precision 0.118 → 0.089 (no unit counts), 0.082 (no crash description), 0.051 (road, time and environment only) | Only weak prediction before a crash; the models describe crashes that occurred |
| **E28 (R4)** | Is the alert trade-off sensitive to the recall target? | Targets 0.3–0.7 | Smooth: 14–16% precision at 30% recall down to about 6% at 70% | 50% kept as a middle point; no setting suits operational use |
| **E29 (R5)** | Is the stable window an artefact of the tolerance? | Tolerances 2–5 points | 3–5 points → 2020–2024; 2 points → 2023–2024 | Window robust |
| **E30 (R6)** | Is the site list robust to analyst choices? | Snapping, minimum crashes, strata varied | Top-100 overlap 95–100; without remoteness 61 | Robust; keep remoteness in the reference |
| **E31 (R7)** | Do the association rules recur over time? | Apriori 2020–22 against 2023–24 | 125 rules shared; 11 of the top 12 recur; lift r = 0.88 | Rules stable within the window |

---

## 5. Open analytical questions

1. **Rainfall:** Do crash counts or serious shares rise in wetter-than-usual months at a location? This needs rainfall amounts (SILO or BoM) joined by month × location or the 4–5 candidate days per crash.
2. **Exposure:** Are areas and sites risky per trip or per person, not just severe? This needs ABS population by SA2/LGA and traffic volumes.
3. **Severity drift:** What drove the steady rise in the hospitalisation share across the series, and the step of about 3 points in 2020? Confirm with the data custodian.
4. **Site screening:** Re-test calibration once site crash frequency is added to the strata, and build a road-user-adjusted variant.
5. **Rules:** A redundancy filter, and a later-period check on the stable window.
6. **Trends:** Breakpoint or interrupted time-series analysis of the fatal share, including 2020.
7. **Labels:** Cross-check recorded against polygon police region and suburb for all observed points.

---

## 6. References

- Agresti, A. & Coull, B. A. (1998). Approximate is better than "exact" for interval estimation of binomial proportions. *The American Statistician*, 52(2), 119–126.
- Garwood, F. (1936). Fiducial limits for the Poisson distribution. *Biometrika*, 28(3/4), 437–442.
- Mantel, N. & Haenszel, W. (1959). Statistical aspects of the analysis of data from retrospective studies of disease. *Journal of the National Cancer Institute*, 22(4), 719–748.
- Robins, J., Breslow, N. & Greenland, S. (1986). Estimators of the Mantel–Haenszel variance consistent in both sparse data and large-strata limiting models. *Biometrics*, 42(2), 311–323.
- Spiegelhalter, D. J. (2005). Funnel plots for comparing institutional performance. *Statistics in Medicine*, 24(8), 1185–1202.
- Wilson, E. B. (1927). Probable inference, the law of succession, and statistical inference. *Journal of the American Statistical Association*, 22(158), 209–212.
- Model and screening references (Highway Safety Manual, Hauer, Friedman, Agrawal and Srikant, Saito and Rehmsmeier, Studer et al.) are listed in `Model_Engineering.md` §12.

---

<!-- project-docs-nav -->
**Project documentation:** [Index](Documentation_Index.md) · [Goals and tasks](Analytical_Goals_and_Tasks.md) · [Data and resources](Data_and_Resources.md) · [Data engineering](Data_Engineering.md) · **Analytics methods** · [Model engineering](Model_Engineering.md) · [Implementation design](Implementation_Design.md) · [System architecture](Analytical_System_Architecture.md) · [Timeline and milestones](Timeline_and_Milestones.md) · [Risk management](Risk_Management.md)
