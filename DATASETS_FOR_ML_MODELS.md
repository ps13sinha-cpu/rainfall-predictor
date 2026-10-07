# Datasets for RIIS ML Models

Research notes, 7 October 2026. Which free datasets feed each model type you want to add
(XGBoost / Random Forest / Gradient Boost / Ensemble, LSTM / Transformer, ConvLSTM / ConvGRU),
how to get them, and what to realistically use when.

---

## Quick answer

| Model family | What it needs | Best free source | Effort |
|---|---|---|---|
| XGBoost, Random Forest, Gradient Boost, Ensemble Vote | Tabular daily or hourly rows per district | **Open-Meteo archive** (already in your repo) | Already have it |
| LSTM-Impact, Transformer | Hourly sequences per district | **Open-Meteo archive, `hourly=` params** | One extra ingestion script |
| ConvLSTM, ConvGRU | Gridded precipitation frames over Tamil Nadu | **ERA5-Land via Open-Meteo on a lat/lon grid**, or **GPM IMERG / CHIRPS via Google Earth Engine** | New data pipeline |
| Flood labels for validation | Historical flood events by district | **India Flood Inventory (IFI-Impacts) on Zenodo** | Download one file |
| Long-run ground truth | Station rainfall 1991 to 2023 | **TNDMA daily rainfall CSV on OpenCity** | Download one file |

---

## 1. Tabular models: XGBoost, Random Forest, Gradient Boost, Ensemble

### Open-Meteo Historical Weather API (you already use this)

- **URL pattern:** `https://archive-api.open-meteo.com/v1/archive?latitude=..&longitude=..&start_date=..&end_date=..&daily=..`
- **Coverage:** 1940 to present, roughly 5 day lag. Models behind it: ERA5 at 0.25 deg, ERA5-Land at 0.1 deg, ECMWF IFS at 9 km from 2017.
- **Daily variables you are not yet pulling:** `rain_sum`, `precipitation_probability_max` is forecast-only but archive has `precipitation_hours`, `wind_gusts_10m_max`, `shortwave_radiation_sum`, `et0_fao_evapotranspiration`, `relative_humidity_2m_mean` is available only via hourly, so pull hourly and aggregate.
- **License:** free for non-commercial use, no key, fair use around 10,000 calls per day.
- **Why it is enough:** 36 districts times 2 years is small. Adding 2022 and 2023 by changing `START_DATE` in `train_ml.py` doubles your rows for free.

**Fix to make before training anything:** label must be *next day's* rainfall class, and current-day rain must leave the feature list. Otherwise all four tree models learn the threshold and report 99 percent.

### Supplementary station data

- **TNDMA Tamil Nadu daily rainfall 1991 to 2023** (CSV, 34 MB). Station-level daily rain, far longer history than Open-Meteo gives you per call. Good for return-period estimates and for checking ERA5 bias in your districts.
  https://data.opencity.in/dataset/chennai-rainfall-data/resource/tamil-nadu-daily-rainfall-from-1991-to-2023
- **Chennai daily rainfall 1991 to 2023** (CSV, 873 KB), same source, Chennai only.
  https://data.opencity.in/dataset/chennai-rainfall-data/resource/chennai-daily-rainfall-data-from-1991-2023
- **IMD sub-division monthly rainfall 1901 to 2015** on Kaggle. Monthly only, too coarse to train on, fine for a context slide.
  https://baselight.app/u/kaggle/dataset/rajanand_rainfall_in_india

---

## 2. Sequence models: LSTM-Impact, Transformer

Same Open-Meteo archive endpoint, add `hourly=` instead of `daily=`.

- **Hourly variables available:** `temperature_2m`, `relative_humidity_2m`, `dew_point_2m`, `precipitation`, `rain`, `pressure_msl`, `surface_pressure`, `cloud_cover`, `cloud_cover_low/mid/high`, `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, `soil_moisture_0_to_7cm`, `soil_temperature_0_to_7cm`, `vapour_pressure_deficit`, `et0_fao_evapotranspiration`, `weather_code`.
- **Size:** 36 districts times 2 years times 8,760 hours is about 630,000 rows. A few hundred MB in SQLite. One request per district per year is 72 calls, well inside fair use.
- **Window design:** input is the last 48 hours of features, target is rainfall class for the next 6 hours. This matches the "6h" story your UI already tells.
- **Soil moisture matters.** `soil_moisture_0_to_7cm` is the antecedent-saturation signal your hyperlocal engine currently estimates. Pulling it as a feature is the single best upgrade for all models.

No new data source needed. One ingestion script and a new `historical_hourly` table.

---

## 3. Spatial models: ConvLSTM, ConvGRU

These need a stack of 2D rain maps over time, not points. Four options, ranked by how fast you can get going.

### Option A: ERA5-Land through Open-Meteo on a synthetic grid (fastest)

Request Open-Meteo hourly `precipitation` for a regular grid of lat/lon points over Tamil Nadu, for example 0.25 deg spacing from 8 to 13.6 N and 76.2 to 80.4 E, which is about 23 by 17 points. Stack the responses into an array of shape `(time, 23, 17)`.

- **Pros:** no account, no new library, same API you know, hourly, 0.1 deg resolution underneath.
- **Cons:** 391 point requests per year, so run it once and cache. It is interpolated reanalysis, not radar, so the fields are smooth.
- **Verdict:** this is what to do first. It lets you train a real ConvLSTM in a day.

### Option B: GPM IMERG via Google Earth Engine (best satellite product)

- **Dataset:** `NASA/GPM_L3/IMERG_V07`, 30 minute, 0.1 deg (about 11 km), June 2000 onward.
  https://developers.google.com/earth-engine/datasets/catalog/NASA_GPM_L3_IMERG_V07
- **Access:** free Earth Engine account, Python `ee` library, filter by date and the Tamil Nadu bounding box, export to Drive as GeoTIFF or NumPy via `geemap`.
- **Alternative access:** NASA GES DISC with an Earthdata login, HDF5 files, Early run has 4 hour latency, Final run has 3.5 month latency. Also mirrored on AWS Open Data.
  https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGHH_07/summary
  https://registry.opendata.aws/nasa-gpm3imerghh
- **Verdict:** best for the roadmap slide. Real satellite precipitation, half-hourly, the standard input for nowcasting papers. Setup takes an evening because of the account and the export step.

### Option C: CHIRPS daily via Google Earth Engine (highest resolution, daily only)

- **Dataset:** `UCSB-CHG/CHIRPS/DAILY`, 0.05 deg (about 5.5 km), 1981 to 2024, satellite blended with stations.
  https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHG_CHIRPS_DAILY
- **Verdict:** daily is too coarse for a 6 hour nowcast but good for a next-day spatial model and for long-history training. Public domain.

### Option D: IMD gridded rainfall (official Indian source, daily)

- **Dataset:** IMD 0.25 deg daily gridded rainfall, 1901 to present, binary `.grd` files.
- **Access:** Python package `imdlib` downloads and converts to xarray. `pip install imdlib`, then `imd.get_data('rain', 2022, 2024)`.
  https://imdlib.readthedocs.io/en/latest/Usage.html
- **Caveat:** IMD moved downloads behind the Data Supply Portal at `https://dsp.imdpune.gov.in/` with a one-time registration using an ID card. Check whether `imdlib` still downloads without login before relying on it the night before a demo.
- **Verdict:** use it when you want to say "trained on official IMD data". Daily only.

### Option E: ERA5 directly from Copernicus (if you outgrow Open-Meteo)

- **Dataset:** `reanalysis-era5-single-levels`, variable `total_precipitation`, hourly, 0.25 deg, 1940 onward.
- **Access:** free CDS account, `pip install cdsapi`, API key in `~/.cdsapirc`. Request a bounding box and a year at a time. Queue times vary from minutes to hours.
- **Verdict:** same underlying data as Open-Meteo's ERA5 model, but you get NetCDF grids directly instead of point queries. Worth it only when you want many years of full grids.

### Benchmark datasets for comparison in a paper or slide

- **SEVIR**, radar VIL over the US, 384 km tiles, 5 minute steps, 4 hour events. The standard ConvLSTM benchmark.
- **HKO-7**, Hong Kong radar, the dataset from the original ConvLSTM paper (Shi et al. 2015).
- **MeteoNet**, French radar.
- A unified preprocessed pack of all three is on IEEE DataPort.
  https://ieee-dataport.org/documents/unified-preprocessed-weather-radar-nowcasting-datasets-sevir-vil-meteonet
  https://arxiv.org/pdf/1506.04214
- **Use:** cite these as the method's provenance, do not train on them. They are not India.

---

## 4. Flood ground truth for validation

Your models predict rainfall class. To prove it maps to impact, you need flood events.

- **India Flood Inventory with Impacts (IFI-Impacts), v4, August 2025.** IIT Delhi. Flood events 1967 to 2023 with dates, districts, deaths, damage, and a District Flood Severity Index. Sourced mainly from IMD Disastrous Weather Events plus EM-DAT and Dartmouth Flood Observatory. Free on Zenodo.
  https://zenodo.org/doi/10.5281/zenodo.4742142
- **How to use it:** join on district and date. Check how many "extreme" predictions coincide with a logged flood event in that district within 48 hours. That one number is more convincing to a judge than any accuracy figure.

---

## 5. What to say tomorrow

- **Current data:** "Two years of ERA5-based daily weather for 36 Tamil Nadu districts via Open-Meteo, 26,000 training rows, plus live forecasts, SRTM terrain, OpenStreetMap drainage, and SoilGrids."
- **Tree models:** trained on this, honest metrics after the leakage fix.
- **Roadmap slide:** "Hourly ERA5-Land ingestion for LSTM and Transformer, then GPM IMERG half-hourly satellite grids via Earth Engine for ConvLSTM spatial nowcasting, validated against the India Flood Inventory."

Naming IMERG, ERA5-Land, and IFI by name with their resolutions shows you know what the models need. That is the point of the slide.

---

## Sources

- Open-Meteo Historical Weather API docs: https://open-meteo.com/en/docs/historical-weather-api
- Open-Meteo historical data overview: https://openmeteo.substack.com/p/historical-weather-data-from-1940
- imdlib usage: https://imdlib.readthedocs.io/en/latest/Usage.html
- imdlib on PyPI: https://pypi.org/project/imdlib
- IMD Climate Data Service Portal announcement: https://iasexamportal.com/the-gist/pib-climate-data-service-portal
- IMD data procedure (registration): https://mausam.imd.gov.in/shimla/docs/data-procedure.pdf
- ERA5 cdsapi example script: https://portal.nersc.gov/cfs/e3sm/inputdata/atm/datm7/ERA.0.25d.v5/download_ERA5_tp.py
- ERA5 download notes: https://coldcast.readthedocs.io/en/latest/_sources/sources/era5.rst.txt
- GPM IMERG at GES DISC: https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGHH_07/summary
- GPM IMERG on AWS Open Data: https://registry.opendata.aws/nasa-gpm3imerghh
- GPM IMERG V07 in Earth Engine: https://developers.google.com/earth-engine/datasets/catalog/NASA_GPM_L3_IMERG_V07
- CHIRPS Daily in Earth Engine: https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHG_CHIRPS_DAILY
- TNDMA Tamil Nadu daily rainfall 1991 to 2023: https://data.opencity.in/dataset/chennai-rainfall-data/resource/tamil-nadu-daily-rainfall-from-1991-to-2023
- Chennai daily rainfall 1991 to 2023: https://data.opencity.in/dataset/chennai-rainfall-data/resource/chennai-daily-rainfall-data-from-1991-2023
- Chennai monthly rainfall 1901 to 2021: https://data.opencity.in/dataset/chennai-rainfall-data/resource/chennai-monthly-rainfall-data-1901-2021
- Kaggle Rainfall in India 1901 to 2015: https://baselight.app/u/kaggle/dataset/rajanand_rainfall_in_india
- India Flood Inventory on Zenodo: https://zenodo.org/doi/10.5281/zenodo.4742142
- IFI background: https://india.mongabay.com/2021/11/freely-available-geospatial-dataset-to-make-flood-research-easier/
- ConvLSTM original paper: https://arxiv.org/pdf/1506.04214
- Unified SEVIR / HKO-7 / MeteoNet pack: https://ieee-dataport.org/documents/unified-preprocessed-weather-radar-nowcasting-datasets-sevir-vil-meteonet
- Precipitation nowcasting benchmark (NeurIPS 2017): https://neurips.cc/virtual/2017/poster/9336
