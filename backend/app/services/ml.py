"""ML Service — tabular rainfall-risk models + SHAP explanations.

Models are trained by `python -m app.train_tabular` (XGBoost, Random Forest,
Gradient Boost, soft-voting Ensemble), `python -m app.train_sequence`
(LSTM-Impact, Transformer) and `python -m app.train_spatial` (ConvLSTM, ConvGRU).
Every trained model is described in ml_models/model_registry.json.

Live prediction here uses the tabular models: the label is the rainfall class
of the NEXT day, built from today's weather plus the last 30 days of history.
"""
import json
import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

from app.services.features import (TABULAR_FEATURES, CLASS_NAMES, DEFAULTS, SoftVote,
                                   build_live_features)

# Model storage
MODEL_DIR = Path(__file__).parent.parent / "ml_models"
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "risk_model.pkl"          # legacy alias of xgboost.pkl
REGISTRY_PATH = MODEL_DIR / "model_registry.json"
FEATURE_NAMES = TABULAR_FEATURES

TABULAR_MODELS = ["xgboost", "random_forest", "gradient_boost", "ensemble_vote"]
DISPLAY_NAMES = {
    "xgboost": "XGBoost", "random_forest": "Random Forest", "gradient_boost": "Gradient Boost",
    "ensemble_vote": "Ensemble Vote", "lstm_impact": "LSTM-Impact", "transformer": "Transformer",
    "convlstm": "ConvLSTM", "convgru": "ConvGRU",
}

_cache = {}


def _load_pickle(name):
    if name in _cache:
        return _cache[name]
    path = MODEL_DIR / f"{name}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        _cache[name] = pickle.load(f)
    return _cache[name]


def load_model(name="xgboost"):
    """Load a trained tabular model (defaults to XGBoost)."""
    if name == "ensemble_vote":
        if name in _cache:
            return _cache[name]
        spec = MODEL_DIR / "ensemble_vote.json"
        if not spec.exists():
            return None
        with open(spec) as f:
            spec = json.load(f)
        members = {k: _load_pickle(k) for k in spec["members"]}
        members = {k: v for k, v in members.items() if v is not None}
        if not members:
            return None
        _cache[name] = SoftVote(members, spec["weights"])
        return _cache[name]
    m = _load_pickle(name)
    if m is None and name == "xgboost" and MODEL_PATH.exists():
        with open(MODEL_PATH, "rb") as f:
            _cache["xgboost"] = pickle.load(f)
        return _cache["xgboost"]
    return m


def get_registry():
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    return {}


def train_model(historical_rows=None):
    """Retrain the tabular models (kept for the POST /api/ml/train route)."""
    try:
        from app import train_tabular
        train_tabular.main()
        _cache.clear()
        return get_model_metrics()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _features(weather_data, history_rain=None, lat=None, lon=None):
    return build_live_features(
        weather_data, history_rain or [],
        lat if lat is not None else 13.08, lon if lon is not None else 80.27)


def predict(weather_data: dict, history_rain=None, lat=None, lon=None, model_name="ensemble_vote") -> dict:
    """Predict next-day risk class from current weather plus recent rain history."""
    model = load_model(model_name) or load_model("xgboost")
    if model is None:
        return _formula_predict(weather_data)
    try:
        feat, row = _features(weather_data, history_rain, lat, lon)
        probs = model.predict_proba(feat)[0]
        pred_class = int(np.argmax(probs))
        class_probs = {CLASS_NAMES[i]: float(round(probs[i], 4)) for i in range(len(CLASS_NAMES))}
        reg = get_registry().get(model_name, {})
        return {
            "prediction": CLASS_NAMES[pred_class],
            "confidence": float(round(max(probs), 4)),
            "class_probabilities": class_probs,
            "heavy_rain_probability": float(round(probs[2] + probs[3], 4)),
            "model": model_name,
            "model_name": DISPLAY_NAMES.get(model_name, model_name),
            "model_version": "2.0",
            "method": model_name,
            "horizon": "next_day",
            "test_accuracy": reg.get("metrics", {}).get("accuracy"),
            "test_macro_f1": reg.get("metrics", {}).get("macro_f1"),
            "features_used": {k: round(float(v), 3) for k, v in row.items()},
        }
    except Exception as e:
        print(f"[RIIS-ML] Prediction error: {e}")
        return _formula_predict(weather_data)


def predict_all(weather_data: dict, history_rain=None, lat=None, lon=None) -> dict:
    """Run every trained tabular model on the same inputs."""
    out = {}
    for name in TABULAR_MODELS:
        if load_model(name) is not None:
            out[name] = predict(weather_data, history_rain, lat, lon, model_name=name)
    return out


def get_shap_explanations(weather_data: dict, history_rain=None, lat=None, lon=None) -> dict:
    """SHAP feature attributions from the XGBoost model."""
    model = load_model("xgboost")
    if model is not None:
        try:
            import shap
            feat, row = _features(weather_data, history_rain, lat, lon)
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(feat)
            probs = model.predict_proba(feat)[0]
            k = int(np.argmax(probs))

            arr = np.array(shap_values)
            if isinstance(shap_values, list):
                per_class = np.stack([np.asarray(sv)[0] for sv in shap_values], axis=-1)  # (F, C)
            elif arr.ndim == 3:
                per_class = arr[0]  # (F, C)
            else:
                per_class = np.asarray(arr)[0][:, None]
            signed = per_class[:, min(k, per_class.shape[1] - 1)]  # contribution to the predicted class
            mean_abs = np.abs(per_class).mean(axis=1)
            max_val = float(mean_abs.max()) if mean_abs.max() > 0 else 1.0

            features = []
            for i, name in enumerate(FEATURE_NAMES):
                features.append({
                    "name": name,
                    "shap_value": float(round(mean_abs[i] / max_val, 4)),
                    "signed_shap": float(round(signed[i], 4)),
                    "raw_value": float(round(float(feat[0][i]), 4)),
                    "direction": "positive" if signed[i] > 0.02 else ("negative" if signed[i] < -0.02 else "neutral"),
                })
            features.sort(key=lambda f: f["shap_value"], reverse=True)

            ev = explainer.expected_value
            base = float(np.mean(ev)) if isinstance(ev, (list, np.ndarray)) else float(ev)
            return {
                "method": "shap_tree",
                "explained_class": CLASS_NAMES[k],
                "features": features,
                "base_value": round(base, 4),
            }
        except Exception as e:
            print(f"[RIIS-ML] SHAP error: {e}")

    return _formula_shap(weather_data)


def _formula_predict(weather_data):
    """Fallback formula-based prediction when ML model isn't available."""
    rain = weather_data.get("next_6h_rain", 0) or weather_data.get("rainfall_mm", 0)
    peak = weather_data.get("peak_intensity", 0)
    hum = weather_data.get("humidity", 70)
    wind = weather_data.get("wind_speed", 10)

    rain_score = min(60, (rain / 50) * 60)
    prob_score = min(15, (min(100, rain * 5) / 100) * 15)
    hum_score = max(0, (hum - 65) * 0.25)
    wind_score = min(15, (wind / 50) * 15)
    risk = max(5, min(100, round(rain_score + prob_score + hum_score + wind_score)))

    cls = "safe"
    if rain > 50 or peak > 35:
        cls = "extreme"
    elif rain > 20 or peak > 15:
        cls = "high"
    elif rain > 5 or peak > 4:
        cls = "mod"

    if cls == "extreme" and risk < 75: risk = 78
    elif cls == "high" and risk < 50: risk = 58
    elif cls == "mod" and risk < 25: risk = 38
    elif cls == "safe" and risk > 30: risk = 22

    return {
        "prediction": cls,
        "confidence": 0.75,
        "class_probabilities": {cls: 0.75},
        "risk_score": risk,
        "method": "formula_fallback",
        "model_version": "none"
    }


def _formula_shap(weather_data):
    """Formula-based feature importance when SHAP isn't available."""
    rain = weather_data.get("next_6h_rain", 0) or weather_data.get("rainfall_mm", 0)
    hum = weather_data.get("humidity", 70)
    pressure = weather_data.get("pressure", 1010)
    cloud = weather_data.get("cloud_cover", 40)
    wind = weather_data.get("wind_speed", 10)
    temp = weather_data.get("temperature", 28)

    features = [
        {"name": "Precipitation (6h)", "shap_value": round(min(1, rain / 30), 3), "raw_value": rain, "direction": "positive"},
        {"name": "Relative Humidity", "shap_value": round(hum / 100 * 0.9, 3), "raw_value": hum, "direction": "positive"},
        {"name": "Barometric Pressure", "shap_value": round(max(0, (1020 - pressure) / 25) * 0.8, 3), "raw_value": pressure, "direction": "positive"},
        {"name": "Cloud Cover", "shap_value": round(cloud / 100 * 0.7, 3), "raw_value": cloud, "direction": "positive"},
        {"name": "Wind Speed", "shap_value": round(min(0.8, wind / 40), 3), "raw_value": wind, "direction": "positive"},
        {"name": "Temperature", "shap_value": round(min(0.5, abs(temp - 26) / 15), 3), "raw_value": temp, "direction": "positive"},
    ]
    features.sort(key=lambda f: f["shap_value"], reverse=True)

    return {
        "method": "formula",
        "features": features,
        "base_value": 0.15,
        "model_version": "none"
    }


def get_model_metrics():
    """Return saved training metrics (legacy shape) plus the full registry."""
    metrics_path = MODEL_DIR / "metrics.json"
    out = {"status": "not_trained", "message": "No model trained yet. POST /api/ml/train to train."}
    if metrics_path.exists():
        with open(metrics_path) as f:
            out = json.load(f)
    reg = get_registry()
    out["models"] = {
        name: {
            "name": DISPLAY_NAMES.get(name, name),
            "family": entry.get("family"),
            "task": entry.get("task"),
            "trained_at": entry.get("trained_at"),
            "train_seconds": entry.get("train_seconds"),
            "metrics": entry.get("metrics"),
            "persistence_baseline": entry.get("persistence_baseline"),
        }
        for name, entry in reg.items()
    }
    return out
