"""
RIIS — Train the four tabular models: XGBoost, Random Forest, Gradient Boost,
and the soft-voting Ensemble, on next-day rainfall class.

Reads `historical_weather` (daily) and, when present, `historical_hourly`
(aggregated to daily humidity, pressure, cloud, soil moisture, dew point, gusts).

Split is chronological: everything before HOLDOUT_FROM trains, the rest tests.
Metrics are reported on the held-out months, which is the honest number.

Usage:
    cd backend
    python -m app.train_tabular
"""
import os
import sys
import json
import time
import pickle
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.services.features import TABULAR_FEATURES, CLASS_NAMES, SoftVote, build_training_frame, update_registry  # noqa: E402
from app.services.train_meta import pins, coverage_weights, write_pins_sidecar, SEED  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models")
REGISTRY = os.path.join(MODEL_DIR, "model_registry.json")
HOLDOUT_FROM = "2025-07-01"


def load_frames():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    daily = pd.read_sql_query(
        """SELECT h.district_id, h.date, h.rainfall_mm, h.temp_max, h.temp_min,
                  h.wind_speed_max, h.precipitation_hours, d.lat, d.lon
           FROM historical_weather h JOIN districts d ON d.id = h.district_id
           ORDER BY h.district_id, h.date""", conn)
    hourly_daily = None
    has_hourly = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='historical_hourly'"
    ).fetchone()[0]
    if has_hourly:
        hourly_daily = pd.read_sql_query(
            """SELECT district_id, substr(time,1,10) AS date,
                      AVG(relative_humidity_2m) AS rh_mean,
                      AVG(pressure_msl)         AS pressure_mean,
                      AVG(cloud_cover)          AS cloud_mean,
                      AVG(soil_moisture_0_to_7cm) AS soil_moisture,
                      AVG(dew_point_2m)         AS dewpoint_mean,
                      MAX(wind_gusts_10m)       AS gust_max
               FROM historical_hourly GROUP BY district_id, substr(time,1,10)""", conn)
    conn.close()
    return daily, hourly_daily


def evaluate(name, model, X_test, y_test):
    from sklearn.metrics import (accuracy_score, f1_score, log_loss,
                                 precision_recall_fscore_support, roc_auc_score, confusion_matrix)
    probs = model.predict_proba(X_test)
    pred = probs.argmax(axis=1)
    p, r, f, _ = precision_recall_fscore_support(y_test, pred, labels=[0, 1, 2, 3], zero_division=0)
    # binary "heavy rain tomorrow" (class >= 2) skill, the number that matters for alerts
    heavy_true = (y_test >= 2).astype(int)
    heavy_prob = probs[:, 2:].sum(axis=1)
    try:
        heavy_auc = float(roc_auc_score(heavy_true, heavy_prob))
    except ValueError:
        heavy_auc = None
    cm = confusion_matrix(y_test, pred, labels=[0, 1, 2, 3]).tolist()
    return {
        "accuracy": round(float(accuracy_score(y_test, pred)), 4),
        "macro_f1": round(float(f1_score(y_test, pred, average="macro")), 4),
        "weighted_f1": round(float(f1_score(y_test, pred, average="weighted")), 4),
        "log_loss": round(float(log_loss(y_test, probs, labels=[0, 1, 2, 3])), 4),
        "heavy_rain_auc": None if heavy_auc is None else round(heavy_auc, 4),
        "per_class": {CLASS_NAMES[i]: {"precision": round(float(p[i]), 3),
                                       "recall": round(float(r[i]), 3),
                                       "f1": round(float(f[i]), 3)} for i in range(4)},
        "confusion_matrix": cm,
    }


def main():
    from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier, VotingClassifier
    from sklearn.utils.class_weight import compute_sample_weight
    import xgboost as xgb

    t0 = time.time()
    daily, hourly_daily = load_frames()
    print(f"daily rows: {len(daily)}  hourly-aggregated days: {0 if hourly_daily is None else len(hourly_daily)}")
    df = build_training_frame(daily, hourly_daily)
    print(f"supervised rows: {len(df)}  features: {len(TABULAR_FEATURES)}")
    print("label distribution:", df["label"].value_counts().sort_index().to_dict())

    train = df[df["date"] < HOLDOUT_FROM]
    test = df[df["date"] >= HOLDOUT_FROM]
    X_tr, y_tr = train[TABULAR_FEATURES].values.astype(np.float32), train["label"].values
    X_te, y_te = test[TABULAR_FEATURES].values.astype(np.float32), test["label"].values
    print(f"train {len(X_tr)} rows (< {HOLDOUT_FROM}), test {len(X_te)} rows")
    sw = compute_sample_weight("balanced", y_tr)
    # soften the balancing so the models do not over-predict extremes
    sw = np.sqrt(sw)
    # inverse-coverage weights: a district with four years of archive must not outvote one with one year
    cov_w, coverage = coverage_weights(train, "district_id")
    sw = sw * cov_w
    data_pins = pins(df, ["district_id", "date"], seed=SEED, holdout_from=HOLDOUT_FROM,
                     coverage_weighting="inverse rows per district, mean 1, multiplied into the class weights",
                     label_source="Open-Meteo archive (ERA5 / ERA5-Land reanalysis), not station gauges")
    print(f"coverage imbalance {data_pins['coverage_imbalance']}x across {len(coverage)} districts; table sha256 {data_pins['sha256'][:12]}")

    models = {
        "xgboost": xgb.XGBClassifier(
            n_estimators=500, max_depth=5, learning_rate=0.04, subsample=0.85,
            colsample_bytree=0.8, min_child_weight=3, objective="multi:softprob",
            num_class=4, eval_metric="mlogloss", tree_method="hist", n_jobs=12,
            random_state=SEED, verbosity=0),
        "random_forest": RandomForestClassifier(
            n_estimators=300, max_depth=14, min_samples_leaf=5, max_features="sqrt",
            n_jobs=-1, random_state=SEED),
        "gradient_boost": HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.05, max_depth=6, l2_regularization=0.5,
            early_stopping=False, random_state=SEED),
    }

    registry = {}
    fitted = {}
    for name, model in models.items():
        t = time.time()
        model.fit(X_tr, y_tr, sample_weight=sw)
        secs = time.time() - t
        m = evaluate(name, model, X_te, y_te)
        fitted[name] = model
        with open(os.path.join(MODEL_DIR, f"{name}.pkl"), "wb") as f:
            pickle.dump(model, f)
        registry[name] = {
            "family": "tabular", "task": "next_day_rain_class",
            "train_rows": int(len(X_tr)), "test_rows": int(len(X_te)),
            "holdout_from": HOLDOUT_FROM, "features": TABULAR_FEATURES,
            "train_seconds": round(secs, 1), "trained_at": datetime.utcnow().isoformat(),
            "metrics": m, "data_pins": data_pins,
        }
        write_pins_sidecar(MODEL_DIR, name, data_pins)
        print(f"  {name:15s} acc {m['accuracy']:.3f}  macroF1 {m['macro_f1']:.3f}  "
              f"heavyAUC {m['heavy_rain_auc']}  ({secs:.0f}s)")

    # soft-voting ensemble over the three fitted models (no refit, no duplicate pickle)
    t = time.time()
    weights = {"xgboost": 2.0, "random_forest": 1.0, "gradient_boost": 1.5}
    ens = SoftVote(fitted, weights)
    m = evaluate("ensemble_vote", ens, X_te, y_te)
    with open(os.path.join(MODEL_DIR, "ensemble_vote.json"), "w") as f:
        json.dump({"members": list(fitted.keys()), "weights": weights}, f, indent=2)
    registry["ensemble_vote"] = {
        "family": "tabular", "task": "next_day_rain_class",
        "members": list(fitted.keys()), "weights": weights,
        "train_rows": int(len(X_tr)), "test_rows": int(len(X_te)),
        "holdout_from": HOLDOUT_FROM, "features": TABULAR_FEATURES,
        "train_seconds": round(time.time() - t, 1), "trained_at": datetime.utcnow().isoformat(),
        "metrics": m, "data_pins": data_pins,
    }
    print(f"  {'ensemble_vote':15s} acc {m['accuracy']:.3f}  macroF1 {m['macro_f1']:.3f}  "
          f"heavyAUC {m['heavy_rain_auc']}")

    # feature importance from XGBoost for the registry
    imp = fitted["xgboost"].feature_importances_
    registry["xgboost"]["feature_importance"] = {
        f: round(float(v), 4) for f, v in sorted(zip(TABULAR_FEATURES, imp), key=lambda x: -x[1])}

    # keep the legacy risk_model.pkl / metrics.json pointing at the new XGBoost
    with open(os.path.join(MODEL_DIR, "risk_model.pkl"), "wb") as f:
        pickle.dump(fitted["xgboost"], f)
    legacy = {
        "status": "trained",
        "accuracy": registry["xgboost"]["metrics"]["accuracy"],
        "macro_f1": registry["xgboost"]["metrics"]["macro_f1"],
        "heavy_rain_auc": registry["xgboost"]["metrics"]["heavy_rain_auc"],
        "std": 0.0,
        "n_samples": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "n_features": len(TABULAR_FEATURES),
        "feature_names": TABULAR_FEATURES,
        "trained_at": datetime.utcnow().isoformat(),
        "model_type": "XGBClassifier",
        "label": "next_day_rain_class",
        "version": "2.0",
    }
    with open(os.path.join(MODEL_DIR, "metrics.json"), "w") as f:
        json.dump(legacy, f, indent=2)
    update_registry(REGISTRY, registry)

    print(f"\nTABULAR TRAINING COMPLETE in {time.time()-t0:.0f}s -> {REGISTRY}")


if __name__ == "__main__":
    main()
