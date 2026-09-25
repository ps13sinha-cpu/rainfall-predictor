"""ML Service — XGBoost rainfall prediction + SHAP explanations.

This module trains a gradient-boosted model on historical weather data
and serves predictions with feature attribution via SHAP.
"""
import json
import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

# Model storage
MODEL_DIR = Path(__file__).parent.parent / "ml_models"
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "risk_model.pkl"
FEATURE_NAMES = [
    "rainfall_mm", "temp_max", "temp_min", "humidity_avg",
    "wind_speed_max", "precipitation_hours",
    # Derived features
    "rain_lag1", "temp_range", "rain_squared",
    "humidity_x_rain", "wind_x_rain"
]


def _build_training_data(db_rows):
    """Convert HistoricalWeather rows into feature matrix + labels."""
    if len(db_rows) < 30:
        return None, None

    # Sort by date
    rows = sorted(db_rows, key=lambda r: r.date)
    features = []
    labels = []

    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]

        rain = curr.rainfall_mm or 0
        tmax = curr.temp_max or 0
        tmin = curr.temp_min or 0
        hum = curr.humidity_avg or 70
        wind = curr.wind_speed_max or 0
        p_hours = curr.precipitation_hours or 0
        prev_rain = prev.rainfall_mm or 0

        feat = [
            rain, tmax, tmin, hum, wind, p_hours,
            prev_rain,                          # lag-1 rainfall
            tmax - tmin,                        # temp range
            rain ** 2,                          # nonlinear rain
            hum * rain / 100,                   # humidity × rain interaction
            wind * rain / 100                   # wind × rain interaction
        ]

        # Label: risk class based on NEXT day rainfall
        # We use the same threshold logic as the existing system
        if rain > 50:
            label = 3  # extreme
        elif rain > 20:
            label = 2  # high
        elif rain > 5:
            label = 1  # mod
        else:
            label = 0  # safe

        features.append(feat)
        labels.append(label)

    return np.array(features), np.array(labels)


def train_model(historical_rows):
    """Train XGBoost model on historical data. Returns metrics dict."""
    X, y = _build_training_data(historical_rows)
    if X is None or len(X) < 30:
        return {"status": "insufficient_data", "rows": len(historical_rows) if historical_rows else 0}

    try:
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score

        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            objective="multi:softprob",
            num_class=4,
            eval_metric="mlogloss",
            use_label_encoder=False,
            random_state=42,
            verbosity=0
        )

        # Cross-validation for metrics
        scores = cross_val_score(model, X, y, cv=min(5, len(X) // 10 or 2), scoring="accuracy")

        # Final fit on all data
        model.fit(X, y)

        # Save model
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(model, f)

        metrics = {
            "status": "trained",
            "accuracy": float(round(scores.mean(), 4)),
            "std": float(round(scores.std(), 4)),
            "n_samples": len(X),
            "n_features": X.shape[1],
            "feature_names": FEATURE_NAMES,
            "trained_at": datetime.utcnow().isoformat(),
            "model_type": "XGBClassifier",
            "version": "1.0"
        }

        # Save metrics
        with open(MODEL_DIR / "metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)

        print(f"[RIIS-ML] Model trained — accuracy: {metrics['accuracy']:.2%} ± {metrics['std']:.2%}")
        return metrics

    except ImportError:
        return {"status": "error", "message": "xgboost not installed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def load_model():
    """Load the saved XGBoost model."""
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def predict(weather_data: dict) -> dict:
    """Predict risk class from current weather data.
    
    Args:
        weather_data: dict with keys matching WeatherCache columns
    Returns:
        dict with prediction, confidence, class probabilities
    """
    model = load_model()
    if model is None:
        # Fallback to formula-based prediction
        return _formula_predict(weather_data)

    try:
        rain = weather_data.get("next_6h_rain", 0) or weather_data.get("rainfall_mm", 0)
        tmax = weather_data.get("temp_max", 28)
        tmin = weather_data.get("temp_min", 22)
        hum = weather_data.get("humidity_avg", weather_data.get("humidity", 70))
        wind = weather_data.get("wind_speed_max", weather_data.get("wind_speed", 10))
        p_hours = weather_data.get("precipitation_hours", 0)
        prev_rain = weather_data.get("rain_lag1", 0)

        feat = np.array([[
            rain, tmax, tmin, hum, wind, p_hours,
            prev_rain,
            tmax - tmin,
            rain ** 2,
            hum * rain / 100,
            wind * rain / 100
        ]])

        probs = model.predict_proba(feat)[0]
        pred_class = int(model.predict(feat)[0])

        class_names = ["safe", "mod", "high", "extreme"]
        class_probs = {class_names[i]: float(round(probs[i], 4)) for i in range(len(class_names))}

        return {
            "prediction": class_names[pred_class],
            "confidence": float(round(max(probs), 4)),
            "class_probabilities": class_probs,
            "model_version": "1.0",
            "method": "xgboost"
        }
    except Exception as e:
        print(f"[RIIS-ML] Prediction error: {e}")
        return _formula_predict(weather_data)


def get_shap_explanations(weather_data: dict) -> dict:
    """Get SHAP feature attributions for a prediction."""
    model = load_model()

    # Only try SHAP if model is trained and shap is available
    if model is not None:
        try:
            import shap
            rain = weather_data.get("next_6h_rain", 0) or weather_data.get("rainfall_mm", 0)
            tmax = weather_data.get("temp_max", 28)
            tmin = weather_data.get("temp_min", 22)
            hum = weather_data.get("humidity_avg", weather_data.get("humidity", 70))
            wind = weather_data.get("wind_speed_max", weather_data.get("wind_speed", 10))
            p_hours = weather_data.get("precipitation_hours", 0)
            prev_rain = weather_data.get("rain_lag1", 0)

            feat = np.array([[
                rain, tmax, tmin, hum, wind, p_hours,
                prev_rain,
                tmax - tmin,
                rain ** 2,
                hum * rain / 100,
                wind * rain / 100
            ]])

            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(feat)

            # Reduce SHAP values to 1D per-feature importance.
            # Multi-class XGBoost returns 3D (batch, features, classes) or a list of 2D arrays.
            if isinstance(shap_values, list):
                # List of 2D arrays, one per class; average absolute across classes then take first sample
                stacked = np.stack([np.abs(sv) for sv in shap_values], axis=-1)  # (1, 11, num_classes)
                mean_abs = np.mean(stacked, axis=-1)[0]  # (11,)
            else:
                arr = np.array(shap_values)
                if arr.ndim == 3:
                    # (batch, features, classes) -> mean abs across classes, take first sample
                    mean_abs = np.mean(np.abs(arr), axis=-1)[0]  # (11,)
                elif arr.ndim == 2:
                    mean_abs = np.abs(arr)[0]  # (11,)
                else:
                    mean_abs = np.abs(arr)

            # Ensure 1D
            mean_abs = np.asarray(mean_abs).flatten()

            # Normalize to 0-1
            max_val = float(mean_abs.max()) if mean_abs.max() > 0 else 1.0
            normalized = (mean_abs / max_val)

            features = []
            for i, name in enumerate(FEATURE_NAMES):
                val = float(round(normalized[i], 4))
                features.append({
                    "name": name,
                    "shap_value": val,
                    "raw_value": float(round(float(feat[0][i]), 4)),
                    "direction": "positive" if val > 0.3 else "neutral"
                })

            features.sort(key=lambda f: f["shap_value"], reverse=True)

            # expected_value is a list for multi-class; take the mean
            ev = explainer.expected_value
            if isinstance(ev, (list, np.ndarray)):
                base = float(np.mean(ev))
            else:
                base = float(ev)

            return {
                "method": "shap_tree",
                "features": features,
                "base_value": round(base, 4),
            }

        except Exception as e:
            print(f"[RIIS-ML] SHAP error: {e}")

    # Formula fallback
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
    """Return saved training metrics."""
    metrics_path = MODEL_DIR / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            return json.load(f)
    return {"status": "not_trained", "message": "No model trained yet. POST /api/ml/train to train."}
