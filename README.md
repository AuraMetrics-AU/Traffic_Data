# Queensland Traffic Data — V6

This project analyses Queensland road-crash records. It enriches crash locations with public spatial data, screens road sites for excess serious crashes, and presents the results in Tableau tables and interactive maps. It also includes experimental crash-severity models; their results are exploratory, not an operational prediction service.

**Start with the [documentation index](Write_Ups/Documentation_Index.md).** It links the project documents: goals and tasks, data and resources, data engineering, analytics methods, model engineering, implementation design, system architecture, timeline and milestones, and risk management.

## Project files

- [`Traffic_Incidents_V6.ipynb`](Traffic_Incidents_V6.ipynb) — main analysis notebook, in CRISP-ML(Q) order. Run it from the project directory.
- Helper modules, kept beside the notebook:
  - [`traffic_location_recovery.py`](traffic_location_recovery.py) — location recovery (cached).
  - [`traffic_road_sites.py`](traffic_road_sites.py) — junction and link network for site screening.
  - [`traffic_spatial_lookup.py`](traffic_spatial_lookup.py) — public-layer helpers and a standalone spatial matching utility.
- The six source CSVs at the project root — crash locations, factors, casualties, vehicle types, driver demographics, and restraints/helmet use.
- [`Public spatial data/`](Public%20spatial%20data/) — spatial reference layers. See [`sources.json`](<Public spatial data/sources.json>) for providers, source links and attribution.
- [`Traffic release manifest V6.json`](Traffic%20release%20manifest%20V6.json) — input, code and output checksums, software versions, and run constants.
- [`Tableau data V6/`](<Tableau data V6/>) — 35 analysis tables for Tableau, including model, screening and reliability results.
- [`Queensland Traffic V6 - Esri Maps.html`](Queensland%20Traffic%20V6%20-%20Esri%20Maps.html) — interactive maps, including the road-site screening map.
- [`Write_Ups/`](Write_Ups/) — project write-ups (start at the documentation index) and [`Write_Ups/figures/`](Write_Ups/figures/) draw.io diagrams (editable `.drawio` and exported `.png`).
- [`Queensland Traffic V6.twbx`](Queensland%20Traffic%20V6.twbx) — packaged Tableau workbook (data included; 12 dashboards). [`Queensland Traffic V6.twb`](Queensland%20Traffic%20V6.twb) is the same workbook linked to the files in `Tableau data V6/`, which must stay beside it. `Queensland Traffic V6 (direct extract).twbx` is a fallback that connects straight to the extracts.
- [`build_tableau_workbook.py`](build_tableau_workbook.py) — rebuilds the three workbook files from `Tableau data V6/` (needs `tableauhyperapi`).
- [`Archive/`](Archive/) — earlier analysis versions and the V5 snapshot.

## Reproduce the analysis

1. Clone the repository with Git LFS enabled; the large CSV and spatial files are stored using LFS:

   ```bash
   git lfs install
   git clone https://github.com/AuraMetrics-AU/Traffic_Data.git
   cd Traffic_Data
   ```

2. Use Python 3.14.4 and the package versions listed in `Traffic release manifest V6.json`.
3. Open `Traffic_Incidents_V6.ipynb` in Jupyter or VS Code and run the cells from top to bottom. Keep these in the project directory:
   - the six source CSVs;
   - the three helper modules;
   - the reference layers in `Public spatial data/`.

   Slow steps are cached in `.cache/` (git-ignored; safe to delete). A warm run takes about a minute.
4. To rebuild the Tableau workbook from the notebook exports, install `tableauhyperapi` and run `python build_tableau_workbook.py`. If `/tmp` is full or not writable, set `HYPER_DOMAIN_SOCKET_DIR` to another folder first.
5. To regenerate the diagrams:

   ```bash
   python Write_Ups/figures/make_drawio_diagrams.py --png
   ```

   The `--png` export needs the draw.io desktop app.

See [`Implementation_Design.md`](Write_Ups/Implementation_Design.md) §11 for headless runs, Google Colab and the release procedure.

## Interpretation notes

- 2025 is partial wherever complete years are required.
- Property-damage-only crashes are recorded through 2010 only; analyses spanning that change use injury crashes.
- **The hospitalisation share of injury crashes rises from 30.5% (2001) to 49.1% (2024) while the fatal share stays level.** Serious-share comparisons, rules and models therefore use the stable window 2020–2024, and long-run trends use the fatal share.
- The overseas-licensed driver flag ends in 2016 and is not analysed.
- The source data has no crash date (only year, month, weekday and hour), and none is reconstructed.
- There is no exposure data (traffic, population), so results are shares and counts among recorded crashes, not risk per trip or person.
- The G-NAF data incorporates G-NAF © Geoscape Australia, licensed by the Commonwealth of Australia under the G-NAF End User Licence Agreement. Additional spatial-data attribution is recorded in [`sources.json`](<Public spatial data/sources.json>).
