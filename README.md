# Queensland Traffic Data — V5

This project analyses Queensland road-crash records, enriches crash locations with public spatial data, and presents the results in a Tableau workbook and interactive maps. It also includes an experimental crash-severity classifier; its results are exploratory, not an operational prediction service.

## Project files

- [`Traffic_Incidents_V5.ipynb`](Traffic_Incidents_V5.ipynb) — main analysis notebook. Run it from the project directory.
- The six source CSVs at the project root — crash locations, factors, casualties, vehicle types, driver demographics, and restraints/helmet use.
- [`Public spatial data/`](Public%20spatial%20data/) — spatial reference layers used by the analysis. See [`sources.json`](<Public spatial data/sources.json>) for providers, source links, and attribution.
- [`Traffic release manifest V5.json`](Traffic%20release%20manifest%20V5.json) — input and output checksums, software versions, and analysis metadata.
- [`Tableau data V5/`](<Tableau data V5/>) — analysis exports and Tableau extracts.
- [`Queensland Traffic V5.twbx`](Queensland%20Traffic%20V5.twbx) — packaged Tableau workbook; [`Queensland Traffic V5 - Esri Maps.html`](Queensland%20Traffic%20V5%20-%20Esri%20Maps.html) — interactive maps.
- [`traffic_spatial_lookup.py`](traffic_spatial_lookup.py) — local spatial matching utility.
- [`Archive/`](Archive/) — earlier analysis and review snapshots.

## Reproduce the analysis

1. Clone the repository with Git LFS enabled; the large CSV and spatial files are stored using LFS:

   ```bash
   git lfs install
   git clone https://github.com/AuraMetrics-AU/Traffic_Data.git
   cd Traffic_Data
   ```

2. Use Python 3.14.4 and the package versions listed in `Traffic release manifest V5.json`.
3. Open `Traffic_Incidents_V5.ipynb` in Jupyter and run the cells from top to bottom. Keep the six source CSVs in the project directory and the reference layers in `Public spatial data/`.
4. To rebuild the packaged Tableau workbook from the notebook exports, install `tableauhyperapi` and run:

   ```bash
   python build_tableau_workbook.py
   ```

## Interpretation notes

- 2025 is partial wherever complete years are required.
- Property-damage-only crashes are recorded through 2010 only; analyses spanning that change use injury crashes where appropriate.
- The overseas-licensed driver flag ends in 2016 and is not analysed.
- The G-NAF data incorporates G-NAF © Geoscape Australia, licensed by the Commonwealth of Australia under the G-NAF End User Licence Agreement. Additional spatial-data attribution is recorded in [`sources.json`](<Public spatial data/sources.json>).
