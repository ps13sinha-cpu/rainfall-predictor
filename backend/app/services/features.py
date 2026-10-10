"""Shared feature engineering for the RIIS tabular models.

Used by both training (app/train_tabular.py) and live prediction
(app/services/ml.py) so the two can never drift apart.

Label: rainfall class of the NEXT day (0 safe <5mm, 1 mod 5-20, 2 high 20-50,
3 extreme >50). Every feature is known at the end of the current day.

Missing inputs are NaN, never a silent constant. `build_live_features(..., with_quality=True)`
also returns the names of the features it could not fill, so the prediction can say so.
XGBoost, HistGradientBoosting and RandomForest (sklearn >= 1.4) all route NaN natively;
`ml.predict` median-imputes only when a model refuses NaN, and records that it did.
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

# Inputs whose absence makes a next-day prediction unreliable; a prediction made with any of
# these imputed is capped at class 'mod' (see ml.predict).
KEY_INPUTS = ("rain_today", "rain_sum_3", "rain_sum_7", "soil_moisture", "rh_mean")

# DEPRECATED (kept importable for older callers and scripts): these constants were silently
# substituted for missing live inputs until 9 Oct 2026. Nothing in features.py uses them any
# more; a missing input is NaN and is reported in the prediction's data_quality block.
DEFAULTS = {
    "rh_mean": 72.0, "pressure_mean": 1009.0, "cloud_mean": 45.0,
    "soil_moisture": 0.25, "dewpoint_mean": 22.0, "gust_max": 25.0,
    "precip_hours": 0.0, "wind_max": 12.0,
}

NAN = float("nan")


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


def _num(weather: dict, *keys):
    """First of `keys` present with a non-None numeric value, as float; None when all are missing.
    Zero is a value, not a gap (0 mm of rain is a real observation)."""
    for k in keys:
        v = weather.get(k)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(f):
            return f
    return None


def build_live_features(weather: dict, history_rain: list, lat: float, lon: float, today=None,
                        with_quality: bool = False):
    """Build one feature row for live prediction.

    weather: dict from WeatherCache (temperature, humidity, pressure, wind_speed,
             cloud_cover, next_6h_rain, peak_intensity) plus optional daily keys.
    history_rain: list of daily rainfall_mm for the previous days, oldest first
                  (up to 30 values; yesterday is the last element).

    Returns (X, row) by default; with_quality=True returns (X, row, imputed) where
    `imputed` lists the feature names that had no live input and are NaN (or, for the
    rolling rain sums, were computed over fewer days than their window).
    """
    imputed = []

    def pick(name, *keys):
        v = _num(weather, *keys)
        if v is None:
            imputed.append(name)
            return NAN
        return v

    rain_today = pick("rain_today", "rainfall_mm", "next_6h_rain")
    temp = _num(weather, "temperature")
    tmax = _num(weather, "temp_max")
    tmin = _num(weather, "temp_min")
    if tmax is None:
        imputed.append("temp_max")
        tmax = NAN
    if tmin is None:
        imputed.append("temp_min")
        tmin = NAN
    # the daily range needs both ends; the current temperature alone does not give it
    if math.isnan(tmax) or math.isnan(tmin):
        imputed.append("temp_range")
        trange = NAN
    else:
        trange = tmax - tmin
    del temp

    hist = [float(x) if x is not None else 0.0 for x in (history_rain or [])][-30:]
    n_hist = len(hist)
    pad = [0.0] * (30 - n_hist) + hist  # oldest .. yesterday

    def lag(k):
        if n_hist < k:
            imputed.append(f"rain_lag{k}")
            return NAN
        return pad[-k]

    def rsum(k):
        if n_hist == 0:
            imputed.append(f"rain_sum_{k}")
            return NAN
        if n_hist < k:
            imputed.append(f"rain_sum_{k}")   # partial window: zero-padded days are an imputation
        return float(sum(pad[-k:]))

    if n_hist < 7:
        imputed.append("wet_days_7")
    wet7 = NAN if n_hist == 0 else float(sum(1 for x in pad[-7:] if x > 1.0))

    s, c = doy_features(today or _date.today())
    row = {
        "rain_today": rain_today,
        "precip_hours": pick("precip_hours", "precipitation_hours"),
        "temp_max": tmax,
        "temp_min": tmin,
        "temp_range": trange,
        "wind_max": pick("wind_max", "wind_speed_max", "wind_speed"),
        "rh_mean": pick("rh_mean", "humidity_avg", "humidity"),
        "pressure_mean": pick("pressure_mean", "pressure"),
        "cloud_mean": pick("cloud_mean", "cloud_cover"),
        "soil_moisture": pick("soil_moisture", "soil_moisture", "soil_moisture_0_7"),
        "dewpoint_mean": pick("dewpoint_mean", "dew_point", "dewpoint"),
        "gust_max": pick("gust_max", "wind_gusts", "wind_gusts_max"),
        "rain_lag1": lag(1), "rain_lag2": lag(2), "rain_lag3": lag(3),
        "rain_sum_3": rsum(3), "rain_sum_7": rsum(7), "rain_sum_14": rsum(14), "rain_sum_30": rsum(30),
        "wet_days_7": wet7,
        "doy_sin": s, "doy_cos": c, "lat": float(lat), "lon": float(lon),
    }
    X = np.array([[row[f] for f in TABULAR_FEATURES]], dtype=np.float32)
    imputed = [f for f in TABULAR_FEATURES if f in set(imputed)]   # feature order, no duplicates
    if with_quality:
        return X, row, imputed
    return X, row


def build_training_frame(daily_df, hourly_daily_df=None):
    """Build the supervised table from the daily history.

    daily_df columns: district_id, date, rainfall_mm, temp_max, temp_min,
                      wind_speed_max, precipitation_hours, lat, lon
    hourly_daily_df (optional): district_id, date, rh_mean, pressure_mean,
                      cloud_mean, soil_moisture, dewpoint_mean, gust_max
    Returns a DataFrame with TABULAR_FEATURES + 'label' + 'date' + 'district_id'.

    Missing hourly-derived columns, wind and precipitation hours stay NaN so the trees learn
    a missing-value branch that matches what live prediction feeds them. Only rainfall_mm is
    filled with 0 (it is the label source and the base of every lag and rolling sum).
    """
    import pandas as pd

    df = daily_df.sort_values(["district_id", "date"]).copy()
    df["rainfall_mm"] = df["rainfall_mm"].fillna(0.0)
    if hourly_daily_df is not None and len(hourly_daily_df):
        df = df.merge(hourly_daily_df, on=["district_id", "date"], how="left")
    for col in ["rh_mean", "pressure_mean", "cloud_mean", "soil_moisture", "dewpoint_mean", "gust_max"]:
        if col not in df.columns:
            df[col] = np.nan

    g = df.groupby("district_id")["rainfall_mm"]
    df["rain_today"] = df["rainfall_mm"]
    df["precip_hours"] = df["precipitation_hours"]
    df["wind_max"] = df["wind_speed_max"]
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


def compute_feature_medians(db_path: str) -> dict:
    """Per-feature medians of the training frame built from riis.db (same SQL as
    app/train_tabular.load_frames). Used by ml.predict only when a model refuses NaN."""
    import sqlite3
    import pandas as pd

    conn = sqlite3.connect(db_path, timeout=60)
    daily = pd.read_sql_query(
        """SELECT h.district_id, h.date, h.rainfall_mm, h.temp_max, h.temp_min,
                  h.wind_speed_max, h.precipitation_hours, d.lat, d.lon
           FROM historical_weather h JOIN districts d ON d.id = h.district_id
           ORDER BY h.district_id, h.date""", conn)
    hourly_daily = None
    has_hourly = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='historical_hourly'").fetchone()[0]
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
    df = build_training_frame(daily, hourly_daily)
    medians, coverage = {}, {}
    for f in TABULAR_FEATURES:
        col = pd.to_numeric(df[f], errors="coerce")
        med = col.median(skipna=True)
        medians[f] = None if pd.isna(med) else float(med)
        coverage[f] = round(float(col.notna().mean()), 4) if len(col) else 0.0
    return {"medians": medians, "non_null_share": coverage, "rows": int(len(df))}
