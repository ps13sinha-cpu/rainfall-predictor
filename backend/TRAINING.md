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

Current coverage (7 Oct 2026):

- `historical_weather`: 38k daily rows, 2024-2025 for all 36 districts, 2022-2023 for 16.
- `historical_hourly`: 868k rows, 2025 for all 36 districts, 2024 for 35, 2022-2023 for 14.
- `grid_precip.npz`: 5,880 hourly frames, 1 Jun 2024 to 31 Jan 2025 (both monsoons and Cyclone Fengal).

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

Held-out metrics from `python -m app.report_models` (7 Oct 2026).

### Classification models (next-day for tabular, next-6h for sequence)

| Model | Family | Train rows | Test rows | Accuracy | Macro F1 | Heavy-rain AUC | Extreme recall | Train time |
|---|---|---|---|---|---|---|---|---|
| XGBoost | tabular | 31372 | 6588 | 0.714 | 0.433 | 0.870 | 0.056 | 19s |
| Random Forest | tabular | 31372 | 6588 | 0.731 | 0.426 | 0.868 | 0.014 | 7s |
| Gradient Boost | tabular | 31372 | 6588 | 0.712 | 0.423 | 0.854 | 0.042 | 25s |
| Ensemble Vote | tabular | 31372 | 6588 | 0.717 | 0.428 | 0.868 | 0.042 | 2s |
| LSTM-Impact | sequence | 318351 | 79380 | 0.901 | 0.371 | 0.877 | 0.000 | 368s |
| Transformer | sequence | 318351 | 79380 | 0.900 | 0.370 | 0.880 | 0.000 | 426s |

### Spatial nowcasting models (next-6h rain map, 11x11 grid at 0.25 deg)

| Model | RMSE mm/6h | MAE mm/6h | CSI 1mm | CSI 5mm | CSI 20mm | POD 5mm | Pixel class acc | Train time |
|---|---|---|---|---|---|---|---|---|
| ConvLSTM | 5.686 | 2.260 | 0.537 | 0.438 | 0.256 | 0.668 | 0.858 | 209s |
| ConvLSTM persistence baseline | 6.753 | 2.466 | 0.490 | 0.350 | 0.318 | 0.519 | 0.844 | - |
| ConvGRU | 5.875 | 2.104 | 0.550 | 0.429 | 0.052 | 0.577 | 0.871 | 226s |
| ConvGRU persistence baseline | 6.753 | 2.466 | 0.490 | 0.350 | 0.318 | 0.519 | 0.844 | - |

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
