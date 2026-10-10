# RIIS model training

Eight models, three families, all trained on free Open-Meteo reanalysis for the
36 RIIS districts. Everything below runs from `backend/`.

| Family | Models | Input | Target | Script |
|---|---|---|---|---|
| Tabular | XGBoost, Random Forest, Gradient Boost, Ensemble Vote | Today's daily weather + 30 days of rain history (24 features) | Rain class **tomorrow** (safe <5 mm, mod 5-20, high 20-50, extreme >50) | `app/train_tabular.py` |
| Sequence | LSTM-Impact, Transformer | Last 48 hours x 20 hourly features per district | Rain class for the **next 6 hours** (same thresholds) | `app/train_sequence.py` |
| Spatial | ConvLSTM, ConvGRU | Last 12 hourly rain frames on an 11x11 grid (0.25 deg, 11.0-13.5 N / 78.0-80.5 E, Chennai-centred) | Rain accumulation map for the **next 6 hours** | `app/train_spatial.py` |

## 1. Get the data

```bash
# daily rows for all districts (idempotent, INSERT OR IGNORE)
RIIS_START_DATE=2022-01-01 RIIS_END_DATE=2025-12-31 python -m app.train_ml ingest

# hourly rows, one request per district per year -> historical_hourly table
python -m app.ingest_hourly 2024 2025

# gridded hourly precipitation, one request per month -> ml_models/grid_precip.npz
python -m app.ingest_grid 2024-06 2025-01
```

Open-Meteo's free tier counts **one call unit per location per two weeks of
data** (limits: 600/min, 5,000/hour, 10,000/day). One district-year of hourly
data is about 31 units; one month of the 121-point grid is about 270 units.
Both ingest scripts cache what they have fetched (per district-year, per month)
and skip it on rerun, so when you get HTTP 429 just run the same command again
later. See `DATASETS_FOR_ML_MODELS.md` at the repo root for other sources.

Current coverage (9 Oct 2026):

- `historical_weather`: 61k daily rows, 2022-2025 for all 48 districts. `precipitation_hours` and `humidity_avg`
  are aggregated from the hourly table (NULL for the 366 rows without hourly backing; no constants).
- `historical_hourly`: 1.46 M rows, 2022-2025 for all 48 districts.
- `grid_precip.npz`: 11,760 hourly frames, 1 Jun 2023 to 31 Jan 2025 (two north-east monsoons and Cyclone Fengal).

Every training run records `data_pins` in the registry (date range, district ids, seed, row count, SHA-256 of the
training table, rows per district and the coverage imbalance) via `app/services/train_meta.py`; the tabular
models multiply inverse-coverage weights into the class weights so a district with four years does not outvote
one with two. Missing hourly aggregates stay NaN in the training frame (all three tabular estimators handle NaN);
`app/ml_models/feature_medians.json` (from `python -m app.build_feature_medians`) is only a safety net for a
NaN-intolerant estimator at serving time, and every prediction reports what was imputed.

## 2. Train

```bash
python -m app.train_tabular        # ~2 min CPU, writes xgboost.pkl, random_forest.pkl, gradient_boost.pkl, ensemble_vote.json
python -m app.train_sequence       # ~20 min on an RTX 2050, writes lstm_impact.pt, transformer.pt
python -m app.train_spatial        # ~10 min on an RTX 2050, writes convlstm.pt, convgru.pt
python -m app.report_models        # markdown summary of ml_models/model_registry.json
```

Knobs via environment variables: `RIIS_SEQ_EPOCHS` / `RIIS_SEQ_MINUTES` (default 12 / 20 per model),
`RIIS_SPATIAL_EPOCHS` / `RIIS_SPATIAL_MINUTES` (40 / 25), `RIIS_SPATIAL_TEST` and
`RIIS_SPATIAL_VAL` (held-out time blocks, default November 2024 and 10-31 October 2024).
The deep models use CUDA when `torch.cuda.is_available()`; the CPU build works, just slower.

Every run appends its entry (metrics, history, timing, feature list) to
`ml_models/model_registry.json`, which `GET /api/ml/models` serves verbatim.
`risk_model.pkl` and `metrics.json` are kept as aliases of the XGBoost model so
older clients keep working.

## 3. Evaluation design

- **No leakage.** The previous model used the same day's rainfall as both a feature and the
  label, which is why it reported 99.95 percent. Labels are now strictly in the future
  (next day for tabular, next 6 hours for sequence and spatial) and every feature is known
  at the end of the input window.
- **Chronological splits.** Tabular and sequence models test on everything from 1 July 2025
  onward (the last six months). Spatial models test on a held-out event block, 1 November
  to 5 December 2024, which is the wettest stretch in the grid (NE monsoon plus Fengal,
  186 mm per 6 h peak); a late-December tail would have been nearly dry and uninformative.
- **Class imbalance.** Extreme days are about 1 percent of rows. The trees use square-root
  balanced sample weights; the sequence models use fourth-root inverse-frequency loss
  weights (square-root weights made the extreme-class probability a flat 0.3 everywhere
  and destroyed the heavy-rain ranking).
- **Metrics that matter for alerts.** Besides accuracy and macro F1, every classifier
  reports `heavy_rain_auc` (ranking of class high-or-extreme by P(high)+P(extreme)) and the
  sequence models also `rain_auc` (any rain >= 5 mm by 1-P(safe)). Spatial models report
  RMSE / MAE in mm per 6 h and Critical Success Index at 1, 5 and 20 mm against a
  persistence baseline (the last 6 hours repeat).

## 4. Results

Held-out metrics after the 9 Oct 2026 retrain on the evened-out corpus (every entry in
`ml_models/model_registry.json` carries its `data_pins`). The 7 Oct numbers are kept in the registry history.

### Classification models (next-day for tabular, next-6h for sequence)

| Model | Family | Train rows | Test rows | Accuracy | Macro F1 | Heavy-rain AUC | Train time |
|---|---|---|---|---|---|---|---|
| XGBoost | tabular | 54720 | 6588 | 0.722 | 0.463 | 0.876 | 22s |
| Random Forest | tabular | 54720 | 6588 | 0.730 | 0.435 | 0.873 | 12s |
| Gradient Boost | tabular | 54720 | 6588 | 0.727 | 0.457 | 0.873 | 35s |
| Ensemble Vote | tabular | 54720 | 6588 | 0.726 | 0.466 | 0.877 | 1s |
| LSTM-Impact | sequence | 1.46 M hourly rows | from 2025-07-01 | 0.910 | 0.377 | 0.884 | ~10 min |
| Transformer | sequence | 1.46 M hourly rows | from 2025-07-01 | 0.905 | 0.427 | 0.918 | ~10 min |

### Spatial nowcasting models (next-6h rain map, 11x11 grid at 0.25 deg, 11,760 training frames)

| Model | RMSE mm/6h | CSI 5mm | CSI 20mm | Pixel class acc | Train time |
|---|---|---|---|---|---|
| ConvLSTM | 5.727 | 0.426 | 0.197 | 0.877 | 1100s (time-capped) |
| ConvGRU | 5.820 | 0.422 | 0.197 | 0.848 | 1270s (time-capped) |
| Persistence baseline | 6.753 | 0.351 | 0.318 | 0.844 | - |

Before-and-after on the same test sets is in `docs/PRODUCTION_READINESS.md`.

### Per-class F1 (classification models)

| Model | safe | mod | high | extreme |
|---|---|---|---|---|
| XGBoost | 0.843 | 0.536 | 0.281 | 0.073 |
| Random Forest | 0.853 | 0.542 | 0.285 | 0.025 |
| Gradient Boost | 0.842 | 0.517 | 0.272 | 0.062 |
| Ensemble Vote | 0.845 | 0.529 | 0.274 | 0.065 |
| LSTM-Impact | 0.949 | 0.414 | 0.122 | 0.000 |
| Transformer | 0.948 | 0.418 | 0.116 | 0.000 |

Top XGBoost features: rain_today (0.344), rain_sum_3 (0.120), rain_sum_7 (0.041), cloud_mean (0.033), rain_sum_14 (0.031), lat (0.029), dewpoint_mean (0.027), temp_range (0.026)

Reading the numbers:

- Tabular accuracy of about 71 to 73 percent and heavy-rain AUC of about 0.87 is the honest
  next-day skill; the previous 99.95 percent came from label leakage.
- The sequence models reach about 90 percent accuracy because 93 percent of 6-hour windows
  are dry; their value is the heavy-rain AUC of about 0.88 on the last six months of 2025.
- Extreme (>50 mm) recall is low everywhere because the test set holds only 34 to 60 such
  events; use the `high`+`extreme` ranking (heavy-rain AUC) for alerting, not the argmax.
- ConvLSTM and ConvGRU both beat persistence on RMSE and on CSI at 5 mm during the November
  2024 block, which includes Cyclone Fengal. Pixel class accuracy is high because most
  pixel-hours are dry even in that block.

## 5. Serving

`app/services/ml.py` loads the tabular models lazily and builds the 24-feature row with
`app/services/features.py` (shared with training, so the two cannot drift). The route
fetches the district's last 30 daily rows for the lag and rolling-sum features.
The sequence and spatial checkpoints are saved with their normalisation and config and
are not yet wired to a live endpoint; `app/eval_sequence.py` shows how to load one.

## 6. Road flood-risk surrogate

`app/services/roads_ml.py` trains an XGBoost classifier on (segment, scenario) samples labelled by the
DEM ponding simulation (`python -m app.train_roads`). Since 9 Oct 2026 it carries monotone constraints
so it agrees with the hyperlocal engine's primaries in direction: rainfall and intensity +1, pit depth
+1, site saturation +1; elevation, HAND, distance to water and infiltration -1. Held-out site 6 after the
change: accuracy 0.797 (was 0.794), macro F1 0.416 (was 0.421), closed-road recall 0.995 (was 0.935),
caution recall 0.19 (was 0.28). Feature importance after retraining: tunnel 0.245, intensity 0.227,
duration 0.134, pit depth 0.098; HAND (0.018) and distance to water (0.011) rank low because the
simulation labels come from local pit filling, not from river proximity. The tabular rain models have
no terrain features, so constraints on elevation or water distance do not apply to them.
