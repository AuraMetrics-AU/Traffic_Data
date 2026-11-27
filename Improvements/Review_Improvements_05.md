# Review of `Traffic_Incidents_V5.ipynb` — improvement opportunities

*Reviewed 27 November 2026. Scope: all 164 cells of the V5 notebook, the exported Tableau tables, the 47 Tableau worksheets, and spot checks on the raw crash file. Items marked **[on your list]** already appear in V5's "Missing process elements" table (cell 162); for those, this review only suggests a concrete method.*

The notebook is careful about provenance, denominators and caveats. Most of the gains are in what it doesn't analyse yet and in a few method choices.

---

## 1. Most important: the severity measure itself changes over time

Nearly every analysis uses the **fatal-or-hospitalisation share** of injury crashes as its outcome, and that share drifts a lot across the series:

| Year | Fatal | Hospitalisation | Medical treatment | Minor injury |
|---|---|---|---|---|
| 2001 | 2.1% | 30.5% | 42.7% | 24.6% |
| 2015 | 1.8% | 41.6% | 47.5% | 9.1% |
| 2024 | 1.9% | 49.1% | 30.7% | 18.3% |

The fatal share is steady, but the hospitalisation share rose from about 30% to 49%. Cell 76 suggests casualty classification may have changed, but the notebook never applies that to the crash-level measure. This affects:

- **The model (cells 133 and 147):** it trains on 2001–2022 and tests on 2023–25, where the class mix is different. That partly explains the low accuracy.
- **Pooled results:** the association rules (cell 142) and the "statewide 1.19×" figure in the hotspot persistence check (cell 137) mix periods with different severity coding.

**Recommendation:** add severity mix by year to the recording-change check (cell 53). Use the fatal share for long-run trends. Limit serious-share comparisons and model training to a stable window (2020 onwards looks consistent), or include year in the model.

---

## 2. Data cleansing

1. **Rebalance the effort.** About 28% of the notebook's code (cells 16–41, ~55k characters) recovers coordinates for 598 crashes (0.14% of records) and produced 127 coordinate pairs. `traffic_spatial_lookup.py` already holds identical copies of most of these functions, but the notebook doesn't import it. Moving the logic into the module and loading cached results would shorten the notebook a lot.
2. **Stacked coordinates matter more than missing ones.** 9,485 crashes sit on exact coordinates shared by 10 or more crashes (up to 58 at one point). Hotspot #10 (Gateway Arterial ramp / Wynnum Rd) is centred on a point shared by 38 crashes, which may point to geocoder snapping rather than a real cluster *(see the correction in §7: at junctions this is intersection geocoding and expected)*. Flag stacked points and make the hotspot step either exclude them or report how many distinct points each hotspot has.
3. **Cross-check recorded and polygon labels.** You already compute police region and locality from polygons. Tabulating where they disagree with the recorded `Loc_Police_Region` / `Loc_Suburb` would be a cheap quality check.
4. **Placeholder values are minor** (for example, 600 `Unknown` remoteness, 331 `Not coded` controlling authority, 380 `Unknown` lighting). Document them.

---

## 3. Data modelling: fields that are never analysed

`Count_Unit_*`, `Crash_Month`, SA2/SA4, police district, electorates, `Crash_DCA_Code`/description and the per-crash casualty counts are exported to Tableau (cell 156) but not used in any analysis.

- **Pedestrian and cyclist crashes** (17,936 and 19,204 injury crashes) get no crash-level analysis.
- **Vehicle effects use grouped data unnecessarily.** Cells 67 and 128 use the grouped Vehicles file and region-year matching. The same motorcycle, truck and bus flags exist on each crash, so a crash-level regression can adjust for speed zone, remoteness and so on all at once. The grouped files are only needed for drink-driving, speed, fatigue and driver demographics.
- **Per-capita rates** **[on your list]**. SA2 and LGA codes join directly to ABS population estimates, giving rates per 100k people instead of only shares.

---

## 4. Analysis models and methods

1. **Classifier (cells 133 and 147).**
   - It trains on 60k of roughly 260k available rows. `HistGradientBoostingClassifier` (already in scikit-learn) handles categories natively and runs fast on all of them.
   - SMOTENC lowered fatal average precision (0.081 vs 0.088). Drop it, and use class weights or a threshold instead **[on your list]**.
   - Treating severity as four unordered classes ignores its ordering, while the rest of the notebook uses serious vs not. A binary serious or fatal target would be consistent and easier to evaluate.
   - Add the crash-level unit counts as features, and report partial-year 2025 separately rather than mixing it into the test set.
2. **Interpretable companion model.** A logistic regression of serious outcome with main effects and a few interactions would give adjusted odds ratios with confidence intervals. That replaces the region-year-only matching in cell 128 and checks the Apriori rules in one model.
3. **Hotspots (cell 137).** The persistence test shows top sites fall back the next period (0.61×). The standard road-safety answer is **Empirical Bayes** ranking, or, without traffic volumes, the Highway Safety Manual's **excess proportion of serious crashes** screening. That ranks sites by observed serious crashes minus what their total injury crashes predict, so busy sites aren't favoured just for volume. Two further changes:
   - Assign crashes to road segments from `roads.geojson`, which the notebook already loads, rather than using DBSCAN. That avoids clusters chaining along a single road (V5 hotspot #6 is a 222 m stretch of the Story Bridge).
   - Run a DBSCAN sensitivity grid **[on your list]**.
4. **Association rules (cell 142).** Eight of the top 12 rules are "head-on + something". Keep a two-item rule only if its lift beats both one-item rules it contains, and refit on a later period to check the rules recur **[on your list]**.
5. **Trends.** Monthly seasonality is never analysed. Breakpoint or interrupted time-series analysis (2020 shows a jump) and region-by-year small multiples with confidence intervals would help.

---

## 5. Charts, maps and insights

Tableau already covers a lot (47 sheets, including an every-crash point map, month, suburb and LGA views). So the notebook's interactive work should support the analysis rather than repeat Tableau.

- **The cell 62 map samples heavily:** 5,000 heat points and 180 markers per severity out of 415k crashes. Replace it with a locality or LGA choropleth from the polygons on disk, showing count, serious share and confidence interval, with a year slider. Folium's `TimeSliderChoropleth` / `HeatMapWithTime` plugins need no new dependency.
- **Funnel plots** of serious share against crash count for LGAs, suburbs or segments, with 95% and 99.8% control limits. They show which areas are genuinely unusual for any criterion (pedestrians, night, motorcycles), and small areas can't top the list by chance.
- **Hotspot map popups** should show severity mix, distinct-coordinate count and a by-year count line, and the map should go beyond the top 150.
- **Hand-drawn Sankeys and treemaps** (cells 108 and 116, ~11k characters of matplotlib) would be shorter and interactive in plotly. Plotly isn't installed and versions are pinned in the release manifest, so this means adding a dependency.
- **Uncovered criteria:**
  - pedestrians aged 75+ by locality
  - cyclists by speed zone
  - single- vs multi-vehicle crashes
  - state- vs council-controlled roads by remoteness
  - DCA codes (run-off-road on curves)
  - results by electorate, for stakeholder reporting

---

## 6. Suggested priority

1. Fix the outcome-drift issue.
2. Analyse the unused crash-level fields.
3. Switch hotspots to severity-excess ranking on road segments.
4. Replace the classifier with gradient boosting plus a logistic regression on a recent window.
5. Move the spatial recovery code into the module.

---

## 7. Implementation status (V6)

Items 1–5 of the priority list are implemented in [`Traffic_Incidents_V6.ipynb`](Traffic_Incidents_V6.ipynb). The V5 notebook and its exports are unchanged.

| # | Item | What V6 does | Main result |
|---|---|---|---|
| 1 | Outcome drift | New Phase 2 check derives a stable severity window: complete years within 3 points of the latest year on both hospitalisation and serious share. Serious-share heatmaps, rules and models use it. Site screening uses year-specific expected shares. | Window is **2020–2024** (66,624 injury crashes). Weekend-night serious share is 64.6% against 47.1% for weekday days (V5 pooled: 57.0% against 39.9%). |
| 2 | Unused crash-level fields | New sections on unit counts, month, council area, police district and state electorate (funnel plots against road mix) and DCA codes. | Unit counts match the grouped vehicle table exactly. Pedestrian crashes: 4.1% fatal. Single-vehicle crashes: 25% of injury crashes, 44% of fatal. Head-on: 19% of fatal crashes. Five councils above the 99.8% funnel limit (Moreton Bay, Ipswich, Mackay, Gladstone, Burdekin). |
| 3 | Severity-excess road sites | `traffic_road_sites.py` builds 513k links and 251k junctions. Crashes are snapped to sites (99.3% assigned) and ranked by empirical-Bayes excess serious crashes (k = 21.4). A two-period test checks persistence and calibration. | Count-ranked top 100 kept **no** excess next period (−3). Excess-ranked top 100 kept 45–50 serious crashes above expected. Shrinkage did not improve the *ranking* but makes the estimates far better calibrated: slope ≈ 1, with a 3–4 point offset because busy sites sit below their stratum's expected share. Next step: add site crash frequency to the strata. The top links are largely recreational motorcycle routes: 33% motorcycle crashes against 12% statewide. |
| 4 | Classifier | Gradient boosting and logistic regression for binary fatal-or-hospitalisation and fatal outcomes. Train 2020–22, set the threshold on 2023, test on 2024, score 2025 separately. No SMOTENC. Calibration and permutation importance reported. Crash-level logistic regression gives adjusted odds. | Fatal average precision on V5's test years: **0.13 against 0.091** in V5. Fatal precision 9–10% at 45–50% recall (V5: 5–6.5%). Serious ROC AUC 0.72 and well calibrated. Logistic regression matches boosting. Adjusted odds: bus 1.01 (V5 matched 0.84), truck 1.31 (V5 1.10). |
| 5 | Spatial recovery into a module | `traffic_location_recovery.py` holds V5 cells 16–41 and imports the 15 identical helpers from `traffic_spatial_lookup.py`. The slow public-layer pass is cached in `.cache/`. | Cleaned crash CSV and reconciliation CSV are **byte-identical** to V5. The recovery step takes 3 s with the cache and 32 s without. |

**Correction to §2.2.** The V6 site screening shows that stacked coordinates occur almost entirely at junctions: 26% of crashes at junction sites against 0.5% on links. Every stacked crash in the top 100 sites is at a junction. This matches intersection crashes being geocoded to the intersection point, so stacked points at junctions are expected and not an error. The V5 hotspot at the Gateway Arterial ramp is therefore not shown to be an artefact. V6 reports distinct crash points and stacked crashes per site so the distinction stays visible.

**Not yet done from this review:** per-capita rates (needs ABS population data), the polygon-label cross-check (§2.3), the rule-redundancy filter and later-period rule check (§4.4), breakpoint and interrupted time-series analysis (§4.5), the map and chart upgrades in §5 other than the funnel plots and the new site map, and a V6 Tableau workbook (`build_tableau_workbook.py` still targets the V5 tables).
