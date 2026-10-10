# Production readiness: status of the review items

Status as of 9 October 2026. Each row is one item from the production-readiness review, what was
done, with real data where the item asked for it, and what remains. Metrics quoted here come from
`ml_models/model_registry.json`, `app/data/calibration.json` and `app/data/station_bias.json`.

## Must fix before production

| Item | Status | What exists now | Still open |
|---|---|---|---|
| No ground truth anywhere | **Done, with a measured answer** | TNDMA gauge file (629 stations, 38 TN districts, 1990-2023) downloaded; `python -m app.station_bias` reports ERA5 bias per district (`docs/ERA5_STATION_BIAS.md`); `python -m app.calibrate_ifi` joins 141 India Flood Inventory events to 395,630 gauge district-days (`docs/IFI_CALIBRATION.md`): rainfall score AUC 0.84, flood rate 0.8% in `safe`, 17% in `mod`, 27% in `high`. The UI banner reads CALIBRATED with the event count and AUC; the response carries `validation_status` and `reanalysis_bias`. | Only the rainfall term is calibrated; elevation, drainage and the modifiers are still expert-set because the inventory is by district and day. The gauge network covers 7 of 48 RIIS districts. |
| Defaults silently standing in for missing data | **Done** | `features.build_training_frame` leaves NaN; `build_live_features(with_quality=True)` returns the imputed list; every `/api/ml/*` and `/api/hyperlocal/impact` response carries `data_quality` and caps the class at `mod` with `cap_reason` when key inputs are imputed. The daily table's constant-zero `precipitation_hours` and `humidity_avg` were replaced from the hourly archive (60,990 rows) and set to NULL where no hourly backing exists (366 rows). Tabular models retrained on the NaN-aware frame. | |
| Uneven training coverage | **Done** | Backfilled 2022-2023 daily rows for all 48 districts (61,356 rows, was 38k) and 2022-2023 hourly rows for 48 districts (1.46 M rows, was 868k). Inverse-coverage sample weights multiplied into the class weights; every registry entry carries `data_pins` with rows per district and the imbalance ratio. | Districts seeded after 2022 still have fewer years; the weights compensate, the registry says so. |
| Spatial training set eight months long | **Done** | Grid extended to 1 June 2023 to 31 January 2025: 11,760 frames, two north-east monsoons plus Cyclone Fengal (was 5,880). ConvLSTM and ConvGRU retrained; the test block stays November 2024. | A third season (2022) is another ~2,200 budget units; not pulled today. |
| Seeded reservoirs beside live ones | **Done** | Every reservoir row carries `observed_at`, `fetched_at`, `age_h`, `stale`, `live`, `source`; `RIIS_RESERVOIR_MAX_AGE_H` (48 h). Seeded rows are always `stale`. The engine drops stale rows from the upstream modifier and records it in `data_quality`. | Mettur and Bhavanisagar have no live page; they stay seeded and stale. |
| Open-Meteo single point of failure | **Partly done** | MET Norway Locationforecast wired as the live fallback (`forecast_providers.fetch_with_fallback`, used by the district poll and the hyperlocal engine); provenance names the provider; `docs/FORECAST_PROVIDERS.md` spells out the commercial-plan requirement and the ECMWF Open Data and Copernicus CDS paths. District poll interval raised from 5 to 30 minutes (5 min was ~20k units a day). | Training archive is still Open-Meteo only; CDS needs an account key the project does not have. A public deployment still needs the Open-Meteo commercial plan or the CDS archive. |

## Should fix in the same release

| Item | Status | What exists now | Still open |
|---|---|---|---|
| Caching in-process and per-machine | **Done** | `site_cache` and `site_cache_locks` tables in riis.db (WAL), legacy JSON imported on first read; Overpass chain takes a lock so two workers never fetch the same site. | SQLite is still one file; a multi-host deployment needs Postgres behind the same module. |
| Scrapers with no contract | **Done** | `validate_row` schema check, last-good fallback with its own `observed_at`, failure counter, alert after 3 consecutive failures (`monitoring.alert`). | |
| Nominatim name matching | **Done** | `app/data/district_lookup.json` (935 districts, 711 with LGD codes) built by `python -m app.build_district_lookup`; alias matching; every miss logged as `district_miss`; `location.district_code` in the response. | |
| Population from a district number | **Done with real data** | JRC GHS-POP 2020 (3 arc-second) tiles downloaded for Tamil Nadu; `services/population.py` gives people per km² within 2.5 km; T Nagar 34,540 /km², Potheri 3,117 /km². | WorldPop stays unusable (API timeout, raster without range reads). Tiles outside R8-R9 / C26-C27 download on first use. |
| Impervious cover default outside cities | **Done with real data** | ESA WorldCover 2021 read as a window from S3 (`services/landcover.py`, 1-4 s, cached 180 d); built-up share drives impervious cover, OSM polygons only fill gaps. | |
| Overpass for every new site | **Partly done** | Fetch is idempotent across workers, cached in the DB, mirrors rotated, empties counted. | No Geofabrik pre-fetch: the Southern India extract is 558 MB and needs an osmium/pyrosm pipeline. |
| Budget enforcement in code | **Done** | `services/budget.py` token bucket with Open-Meteo's per-location-per-two-weeks accounting, 600/min, 5,000/h, 10,000/day hard, `RIIS_OPENMETEO_DAILY_CAP` soft (8,000); every call site wrapped; bulk scripts refuse to start without budget unless `RIIS_BUDGET_OVERRIDE=1`; `/api/health/budget`. | |

## Operational and compliance

| Item | Status | What exists now | Still open |
|---|---|---|---|
| Provenance on every number | **Done** | `provenance` list on every impact response: source, url, fetched_at, cache_age_s, ttl_s, licence, status per layer, plus per-reservoir observations. | |
| Attribution | **Done** | Footer on every screen and the FastAPI description: Open-Meteo CC BY 4.0, OpenStreetMap ODbL, SoilGrids CC BY 4.0, India Flood Inventory CC BY 4.0, SRTM, MET Norway CC BY 4.0, ESA WorldCover CC BY 4.0, JRC GHSL CC BY 4.0. | |
| Reproducible training | **Done** | `services/train_meta.py`: date range, district ids, seed, row count and SHA-256 of the training table in every registry entry (`data_pins`) and a `.pins.json` sidecar per model. | |
| Monitoring | **Done** | `services/monitoring.py`: counters and SystemLog rows for Open-Meteo 429s and budget refusals, Overpass empties, scraper parse failures, provider fallback, model drift (total-variation distance against the registry's test distribution), stale site cache; `RIIS_ALERT_WEBHOOK`; `/api/health/monitoring`. | Alert delivery beyond webhook (email, pager) is not configured. |
| Data retention and privacy | **Done** | `services/retention.py`, scheduled 03:30 daily: coordinates coarsened to 2 decimals after 30 days, route logs deleted and report free text stripped after 365 days; `docs/DATA_RETENTION.md`. | Uploaded media is not deleted when a report is stripped. |
| Tests on data | **Done** | `tests/test_schema_tables.py` (schema, ranges, uniqueness on the real DB), `tests/test_nwp_smoke.py` (three NWP models, live when `RIIS_LIVE_TESTS=1`), nightly canary at 02:15 comparing the Potheri score to a stored baseline; `tests/test_hyperlocal_quality.py`, `tests/test_hardening.py`. 69 passed, 1 skipped. | Canary baseline is created on its first scheduled run. |

## Model metrics before and after (same held-out months, 1 July 2025 onward for tabular)

| Model | Train rows before -> after | Accuracy | Macro F1 | Heavy-rain AUC |
|---|---|---|---|---|
| XGBoost | 31,372 -> 54,720 | 0.714 -> 0.722 | 0.433 -> 0.463 | 0.870 -> 0.876 |
| Random Forest | 31,372 -> 54,720 | 0.731 -> 0.730 | 0.426 -> 0.435 | 0.868 -> 0.873 |
| Gradient Boost | 31,372 -> 54,720 | 0.712 -> 0.727 | 0.423 -> 0.457 | 0.854 -> 0.873 |
| Ensemble Vote | 31,372 -> 54,720 | 0.717 -> 0.726 | 0.428 -> 0.466 | 0.868 -> 0.877 |

Spatial models, same held-out block (1 November to 5 December 2024), training frames 5,880 -> 11,760:

| Model | RMSE mm/6h | CSI 5 mm | CSI 20 mm | Pixel class accuracy |
|---|---|---|---|---|
| ConvLSTM | 5.686 -> 5.727 | 0.438 -> 0.426 | 0.256 -> 0.197 | 0.858 -> 0.877 |
| ConvGRU | 5.875 -> 5.820 | 0.429 -> 0.422 | 0.052 -> 0.197 | 0.871 -> 0.848 |
| Persistence baseline | 6.753 | 0.351 | 0.318 | 0.844 |

Doubling the grid to two seasons did not move the November 2024 skill much either way: both models still beat
persistence on RMSE and CSI at 5 mm, and both stay below it at 20 mm. Both runs hit the 25-minute per-model time
cap (`RIIS_SPATIAL_MINUTES`), so a longer run is the next lever, not more frames.

Sequence models, same held-out window (1 July 2025 onward), hourly rows 868k -> 1.46 M:

| Model | Accuracy | Macro F1 | Heavy-rain AUC | Rain AUC |
|---|---|---|---|---|
| LSTM-Impact | 0.901 -> 0.910 | 0.371 -> 0.377 | 0.877 -> 0.884 | - -> 0.895 |
| Transformer | 0.900 -> 0.905 | 0.370 -> 0.427 | 0.880 -> 0.918 | - -> 0.898 |

The Transformer gained the most from the evened-out archive: heavy-rain AUC 0.880 to 0.918 on the same six test months.

## Budget spent today (Open-Meteo units, approximate)

| Pull | Units |
|---|---|
| Daily 2022-2023, 48 districts (two runs, the first rate-limited) | ~2,450 |
| Hourly 2022-2023, 24 district-years | ~1,360 |
| Grid June 2023 to January 2024 | ~2,160 |
| Station-bias ERA5 window, 7 districts x 3 years | ~550 |
| Total | ~6,500 of the 8,000 soft cap |

## How to rerun the evidence

```bash
cd backend
python -m app.station_bias        # ERA5 vs gauges (uses cached ERA5; ~550 units if the cache is cold)
python -m app.calibrate_ifi       # flood-inventory calibration, no network
python -m app.train_tabular && python -m app.build_feature_medians
python -m app.train_sequence
python -m app.train_spatial
python -m app.report_models
RIIS_MONITORING_PERSIST=0 python -m pytest tests -q
```
