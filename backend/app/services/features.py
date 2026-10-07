"""Shared feature engineering for the RIIS tabular models.

Used by both training (app/train_tabular.py) and live prediction
(app/services/ml.py) so the two can never drift apart.

Label: rainfall class of the NEXT day (0 safe <5mm, 1 mod 5-20, 2 high 20-50,
3 extreme >50). Every feature is known at the end of the current day.
"""
import math
from datetime import date as _date

import numpy as np

CLASS_NAMES = ["safe", "mod", "high", "extreme"]

TABULAR_FEATURES = [
    "rain_today", "precip_hours", "temp_max", "temp_min", "temp_range",
    "wind_max", "rh_mean", "pressure_mean", "cloud_mean", "soil_moisture",
    "dewpoint_mean", "gust_max",
    "rain_lag1", "rain_lag2", "rain_lag3",
    "rain_sum_3", "rain_sum_7", "rain_sum_14", "rain_sum_30",
    "wet_days_7", "doy_sin", "doy_cos", "lat", "lon",
]

# Defaults used when the live weather cache lacks a value
DEFAULTS = {
    "rh_mean": 72.0, "pressure_mean": 1009.0, "cloud_mean": 45.0,
    "soil_moisture": 0.25, "dewpoint_mean": 22.0, "gust_max": 25.0,
    "precip_hours": 0.0, "wind_max": 12.0,
}


def update_registry(path, entries: dict):
    """Read-modify-write the model registry so concurrent trainers never clobber each other."""
    import json, os
    reg = {}
    if os.path.exists(path):
        with open(path) as f:
            try:
                reg = json.load(f)
            except json.JSONDecodeError:
                reg = {}
    reg.update(entries)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(reg, f, indent=2)
    os.replace(tmp, path)
    return reg


class SoftVote:
    """Weighted soft-voting over already-fitted classifiers (no refit, no duplicate pickles)."""

    def __init__(self, members: dict, weights: dict):
        self.members = members
        self.weights = weights
        self.classes_ = np.array([0, 1, 2, 3])

    def predict_proba(self, X):
        tot = sum(self.weights[k] for k in self.members)
        return sum(self.weights[k] * m.predict_proba(X) for k, m in self.members.items()) / tot

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)


def rain_class(mm):
    if mm > 50:
        return 3
    if mm > 20:
        return 2
    if mm > 5:
        return 1
    return 0


def doy_features(d):
    """Seasonality from the day of year."""
    if isinstance(d, str):
        d = _date.fromisoformat(d[:10])
    doy = d.timetuple().tm_yday
    ang = 2 * math.pi * doy / 365.25
    return math.sin(ang), math.cos(ang)


def build_live_features(weather: dict, history_rain: list, lat: float, lon: float, today=None):
    """Build one feature row for live prediction.

    weather: dict from WeatherCache (temperature, humidity, pressure, wind_speed,
             cloud_cover, next_6h_rain, peak_intensity) plus optional daily keys.
    history_rain: list of daily rainfall_mm for the previous days, oldest first
                  (up to 30 values; yesterday is the last element).
    """
    rain_today = float(weather.get("rainfall_mm") or weather.get("next_6h_rain") or 0.0)
    temp = float(weather.get("temperature") or 28.0)
    tmax = float(weather.get("temp_max") or temp + 3.0)
    tmin = float(weather.get("temp_min") or temp - 5.0)
    hist = [float(x or 0.0) for x in history_rain][-30:]
    pad = [0.0] * (30 - len(hist)) + hist  # oldest .. yesterday

    def lag(k):
        return pad[-k]

    def rsum(k):
        return float(sum(pad[-k:]))

    s, c = doy_features(today or _date.today())
    row = {
        "rain_today": rain_today,
        "precip_hours": float(weather.get("precipitation_hours") or (6.0 if rain_today > 1 else 0.0)),
        "temp_max": tmax,
        "temp_min": tmin,
        "temp_range": tmax - tmin,
        "wind_max": float(weather.get("wind_speed_max") or weather.get("wind_speed") or DEFAULTS["wind_max"]),
        "rh_mean": float(weather.get("humidity_avg") or weather.get("humidity") or DEFAULTS["rh_mean"]),
        "pressure_mean": float(weather.get("pressure") or DEFAULTS["pressure_mean"]),
        "cloud_mean": float(weather.get("cloud_cover") or DEFAULTS["cloud_mean"]),
        "soil_moisture": float(weather.get("soil_moisture") or DEFAULTS["soil_moisture"]),
        "dewpoint_mean": float(weather.get("dew_point") or DEFAULTS["dewpoint_mean"]),
        "gust_max": float(weather.get("wind_gusts") or DEFAULTS["gust_max"]),
        "rain_lag1": lag(1), "rain_lag2": lag(2), "rain_lag3": lag(3),
        "rain_sum_3": rsum(3), "rain_sum_7": rsum(7), "rain_sum_14": rsum(14), "rain_sum_30": rsum(30),
        "wet_days_7": float(sum(1 for x in pad[-7:] if x > 1.0)),
        "doy_sin": s, "doy_cos": c, "lat": float(lat), "lon": float(lon),
    }
    return np.array([[row[f] for f in TABULAR_FEATURES]], dtype=np.float32), row


def build_training_frame(daily_df, hourly_daily_df=None):
    """Build the supervised table from the daily history.

    daily_df columns: district_id, date, rainfall_mm, temp_max, temp_min,
                      wind_speed_max, precipitation_hours, lat, lon
    hourly_daily_df (optional): district_id, date, rh_mean, pressure_mean,
                      cloud_mean, soil_moisture, dewpoint_mean, gust_max
    Returns a DataFrame with TABULAR_FEATURES + 'label' + 'date' + 'district_id'.
    """
    import pandas as pd

    df = daily_df.sort_values(["district_id", "date"]).copy()
    df["rainfall_mm"] = df["rainfall_mm"].fillna(0.0)
    if hourly_daily_df is not None and len(hourly_daily_df):
        df = df.merge(hourly_daily_df, on=["district_id", "date"], how="left")
    for col in ["rh_mean", "pressure_mean", "cloud_mean", "soil_moisture", "dewpoint_mean", "gust_max"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = df.groupby("district_id")[col].transform(lambda s: s.fillna(s.median()))
        df[col] = df[col].fillna(DEFAULTS[col])

    g = df.groupby("district_id")["rainfall_mm"]
    df["rain_today"] = df["rainfall_mm"]
    df["precip_hours"] = df["precipitation_hours"].fillna(0.0)
    df["wind_max"] = df["wind_speed_max"].fillna(DEFAULTS["wind_max"])
    df["temp_range"] = df["temp_max"] - df["temp_min"]
    for k in (1, 2, 3):
        df[f"rain_lag{k}"] = g.shift(k).fillna(0.0)
    for k in (3, 7, 14, 30):
        df[f"rain_sum_{k}"] = g.transform(lambda s: s.rolling(k, min_periods=1).sum())
    df["wet_days_7"] = g.transform(lambda s: (s > 1.0).astype(float).rolling(7, min_periods=1).sum())
    dts = pd.to_datetime(df["date"])
    ang = 2 * np.pi * dts.dt.dayofyear / 365.25
    df["doy_sin"] = np.sin(ang)
    df["doy_cos"] = np.cos(ang)

    # label = next day's class, within the same district
    df["rain_next"] = g.shift(-1)
    df = df.dropna(subset=["rain_next"])
    df["label"] = df["rain_next"].apply(rain_class).astype(int)
    return df[["district_id", "date"] + TABULAR_FEATURES + ["label", "rain_next"]].reset_index(drop=True)
