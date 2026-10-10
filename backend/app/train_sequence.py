"""
RIIS — Train the sequence models: LSTM-Impact and Transformer.

Input:  the last 48 hours of hourly weather for a district (historical_hourly).
Target: rainfall class of the NEXT 6 hours (same thresholds the app uses for
        next_6h_rain: safe <5mm, mod 5-20, high 20-50, extreme >50).

Chronological split: windows whose target starts before HOLDOUT_FROM train,
the rest test.

Usage:
    cd backend
    python -m app.train_sequence                 # both models
    python -m app.train_sequence lstm            # one model
    python -m app.train_sequence transformer
"""
import os
import sys
import json
import time
import math
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models")
REGISTRY = os.path.join(MODEL_DIR, "model_registry.json")

HOLDOUT_FROM = "2025-07-01"
DATA_PINS = {}
WINDOW = 48          # hours of input
HORIZON = 6          # hours ahead to accumulate
STRIDE = 2           # training windows every 2 hours
CLASS_NAMES = ["safe", "mod", "high", "extreme"]

RAW_VARS = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
            "pressure_msl", "cloud_cover", "wind_speed_10m", "wind_direction_10m",
            "wind_gusts_10m", "soil_moisture_0_to_7cm", "vapour_pressure_deficit"]
SEQ_FEATURES = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
                "pressure_msl", "cloud_cover", "wind_speed_10m", "wind_gusts_10m",
                "soil_moisture_0_to_7cm", "vapour_pressure_deficit",
                "wdir_sin", "wdir_cos", "hour_sin", "hour_cos", "doy_sin", "doy_cos",
                "lat", "lon", "rain_sum_6", "rain_sum_24"]

# time budget per model so the whole run fits an evening
MAX_EPOCHS = int(os.environ.get("RIIS_SEQ_EPOCHS", "12"))
MAX_MINUTES = float(os.environ.get("RIIS_SEQ_MINUTES", "20"))


def rain_class(mm):
    return np.where(mm > 50, 3, np.where(mm > 20, 2, np.where(mm > 5, 1, 0)))


def load_series():
    """Return (X_all (N,F) float32, y6 (N,) next-6h rain, valid window end indices, is_test, norm)."""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    df = pd.read_sql_query(
        f"SELECT h.district_id, h.time, {','.join('h.'+v for v in RAW_VARS)}, d.lat, d.lon "
        "FROM historical_hourly h JOIN districts d ON d.id = h.district_id "
        "ORDER BY h.district_id, h.time", conn)
    conn.close()
    print(f"hourly rows: {len(df)}  districts: {df.district_id.nunique()}")
    global DATA_PINS
    from app.services.train_meta import pins, SEED
    DATA_PINS = pins(df, ["district_id", "time"], seed=SEED, holdout_from=HOLDOUT_FROM,
                     label_source="Open-Meteo archive hourly (ERA5-Land reanalysis), not station gauges")
    print(f"coverage imbalance {DATA_PINS['coverage_imbalance']}x; table sha256 {DATA_PINS['sha256'][:12]}")

    blocks, targets, ends, is_test, tstamps = [], [], [], [], []
    offset = 0
    for did, g in df.groupby("district_id", sort=True):
        g = g.copy()
        g["time"] = pd.to_datetime(g["time"])
        g = g.set_index("time").sort_index()
        # make the series strictly hourly and contiguous per calendar year block
        full = pd.date_range(g.index.min(), g.index.max(), freq="h")
        g = g.reindex(full)
        g[RAW_VARS] = g[RAW_VARS].interpolate(limit=6).ffill().bfill()
        g["precipitation"] = g["precipitation"].fillna(0.0)
        g["lat"] = g["lat"].ffill().bfill()
        g["lon"] = g["lon"].ffill().bfill()
        gap = g["temperature_2m"].isna().values  # remaining holes mark invalid windows

        wd = np.deg2rad(g["wind_direction_10m"].fillna(0).values)
        hr = g.index.hour.values
        doy = g.index.dayofyear.values
        rain = g["precipitation"].values
        feat = np.column_stack([
            g[["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
               "pressure_msl", "cloud_cover", "wind_speed_10m", "wind_gusts_10m",
               "soil_moisture_0_to_7cm", "vapour_pressure_deficit"]].values,
            np.sin(wd), np.cos(wd),
            np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24),
            np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25),
            g["lat"].values, g["lon"].values,
            pd.Series(rain).rolling(6, min_periods=1).sum().values,
            pd.Series(rain).rolling(24, min_periods=1).sum().values,
        ]).astype(np.float32)
        feat = np.nan_to_num(feat, nan=0.0)

        # next-6h rain for a window ending at index t (inclusive): sum rain[t+1 .. t+6]
        T = len(feat)
        y6 = np.zeros(T, dtype=np.float32)
        cs = np.concatenate([[0.0], np.cumsum(rain)])
        for t in range(T - HORIZON):
            y6[t] = cs[t + 1 + HORIZON] - cs[t + 1]

        hol = pd.Timestamp(HOLDOUT_FROM)
        for t in range(WINDOW - 1, T - HORIZON, STRIDE):
            if gap[t - WINDOW + 1:t + HORIZON + 1].any():
                continue
            ends.append(offset + t)
            is_test.append(g.index[t] >= hol)
            tstamps.append(g.index[t])
        blocks.append(feat)
        targets.append(y6)
        offset += T

    X = np.concatenate(blocks, axis=0)
    y = np.concatenate(targets, axis=0)
    ends = np.array(ends, dtype=np.int64)
    is_test = np.array(is_test, dtype=bool)
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-6
    # keep lat/lon and the sin/cos columns unscaled-ish by using their own std (fine)
    Xn = (X - mean) / std
    return Xn.astype(np.float32), y, ends, is_test, {"mean": mean.tolist(), "std": std.tolist()}


# ── models ────────────────────────────────────────────────────────────────────
def build_models():
    import torch
    import torch.nn as nn

    class LSTMImpact(nn.Module):
        def __init__(self, n_feat, hidden=96, layers=2, n_cls=4, p=0.2):
            super().__init__()
            self.lstm = nn.LSTM(n_feat, hidden, num_layers=layers, batch_first=True, dropout=p)
            self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Dropout(p), nn.Linear(hidden, 64),
                                      nn.GELU(), nn.Linear(64, n_cls))

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1])

    class TransformerImpact(nn.Module):
        def __init__(self, n_feat, d_model=64, heads=4, layers=2, n_cls=4, p=0.15, seq=WINDOW):
            super().__init__()
            self.inp = nn.Linear(n_feat, d_model)
            self.pos = nn.Parameter(torch.randn(1, seq, d_model) * 0.02)
            enc = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=128, dropout=p,
                                             batch_first=True, norm_first=True)
            self.enc = nn.TransformerEncoder(enc, num_layers=layers)
            self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, 64), nn.GELU(),
                                      nn.Dropout(p), nn.Linear(64, n_cls))

        def forward(self, x):
            h = self.enc(self.inp(x) + self.pos)
            return self.head(torch.cat([h[:, -1:], h.mean(dim=1, keepdim=True)], dim=1).mean(dim=1))

    return {"lstm_impact": LSTMImpact, "transformer": TransformerImpact}


def batches(X, ends, idx, bs, device, shuffle, rng):
    import torch
    if shuffle:
        idx = rng.permutation(idx)
    ar = np.arange(-WINDOW + 1, 1)
    for i in range(0, len(idx), bs):
        e = ends[idx[i:i + bs]]
        win = X[e[:, None] + ar[None, :]]  # (B, WINDOW, F)
        yield torch.from_numpy(win).to(device), idx[i:i + bs]


def evaluate(model, X, y_cls, y_mm, ends, idx, device):
    import torch
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, precision_recall_fscore_support, confusion_matrix
    model.eval()
    probs = []
    with torch.no_grad():
        for xb, _ in batches(X, ends, idx, 2048, device, False, None):
            probs.append(torch.softmax(model(xb), dim=1).cpu().numpy())
    probs = np.concatenate(probs)
    pred = probs.argmax(1)
    yt = y_cls[ends[idx]]
    p, r, f, _ = precision_recall_fscore_support(yt, pred, labels=[0, 1, 2, 3], zero_division=0)
    heavy = (yt >= 2).astype(int)
    try:
        auc = round(float(roc_auc_score(heavy, probs[:, 2:].sum(1))), 4)
        rain_auc = round(float(roc_auc_score((yt >= 1).astype(int), 1 - probs[:, 0])), 4)
    except ValueError:
        auc, rain_auc = None, None
    return {
        "accuracy": round(float(accuracy_score(yt, pred)), 4),
        "macro_f1": round(float(f1_score(yt, pred, average="macro")), 4),
        "weighted_f1": round(float(f1_score(yt, pred, average="weighted")), 4),
        "heavy_rain_auc": auc,
        "rain_auc": rain_auc,
        "per_class": {CLASS_NAMES[i]: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3),
                                       "f1": round(float(f[i]), 3)} for i in range(4)},
        "confusion_matrix": confusion_matrix(yt, pred, labels=[0, 1, 2, 3]).tolist(),
        "n": int(len(idx)),
    }


def train_one(name, cls, X, y_cls, y_mm, ends, is_test, norm, device):
    import torch
    import torch.nn as nn
    rng = np.random.default_rng(42)
    torch.manual_seed(42)

    tr_idx = np.where(~is_test)[0]
    te_idx = np.where(is_test)[0]
    # small validation slice from the tail of the training period for model selection
    cut = int(len(tr_idx) * 0.9)
    va_idx, tr_idx = tr_idx[cut:], tr_idx[:cut]

    counts = np.bincount(y_cls[ends[tr_idx]], minlength=4).astype(np.float64)
    # mild re-weighting (fourth root of inverse frequency); sqrt was enough to make the
    # extreme-class probability a flat 0.3 everywhere and destroy the heavy-rain ranking
    w = (counts.sum() / (4 * np.maximum(counts, 1))) ** 0.25
    weight = torch.tensor(w / w.mean(), dtype=torch.float32, device=device)
    print(f"  class counts (train): {counts.astype(int).tolist()}  loss weights: {np.round(w / w.mean(), 2).tolist()}")

    model = cls(X.shape[1]).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    steps_per_epoch = math.ceil(len(tr_idx) / 512)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, total_steps=MAX_EPOCHS * steps_per_epoch,
                                                pct_start=0.15)
    loss_fn = nn.CrossEntropyLoss(weight=weight, label_smoothing=0.02)
    y_t = torch.from_numpy(y_cls).to(device)

    best, best_state, t0, history = -1.0, None, time.time(), []
    for epoch in range(MAX_EPOCHS):
        model.train()
        tot, nb = 0.0, 0
        for xb, bi in batches(X, ends, tr_idx, 512, device, True, rng):
            yb = y_t[torch.from_numpy(ends[bi]).to(device)]
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item()
            nb += 1
        va = evaluate(model, X, y_cls, y_mm, ends, va_idx, device)
        history.append({"epoch": epoch + 1, "loss": round(tot / nb, 4), "val_macro_f1": va["macro_f1"],
                        "val_acc": va["accuracy"]})
        print(f"  epoch {epoch+1:2d} loss {tot/nb:.4f}  val acc {va['accuracy']:.3f}  "
              f"val macroF1 {va['macro_f1']:.3f}  ({time.time()-t0:.0f}s)")
        if va["macro_f1"] > best:
            best = va["macro_f1"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if (time.time() - t0) / 60 > MAX_MINUTES:
            print("  time budget reached")
            break

    model.load_state_dict(best_state)
    test = evaluate(model, X, y_cls, y_mm, ends, te_idx, device)
    secs = time.time() - t0
    torch.save({"state_dict": best_state, "features": SEQ_FEATURES, "norm": norm, "window": WINDOW,
                "horizon": HORIZON, "model": name, "class_names": CLASS_NAMES},
               os.path.join(MODEL_DIR, f"{name}.pt"))
    entry = {
        "family": "sequence", "task": "next_6h_rain_class", "input": f"last {WINDOW}h x {len(SEQ_FEATURES)} features",
        "params": int(n_params), "device": str(device), "epochs_run": len(history),
        "train_windows": int(len(tr_idx)), "val_windows": int(len(va_idx)), "test_windows": int(len(te_idx)),
        "holdout_from": HOLDOUT_FROM, "data_pins": DATA_PINS, "train_seconds": round(secs, 1),
        "trained_at": datetime.utcnow().isoformat(), "history": history, "metrics": test,
    }
    print(f"  {name}: TEST acc {test['accuracy']:.3f} macroF1 {test['macro_f1']:.3f} "
          f"heavyAUC {test['heavy_rain_auc']}  ({secs:.0f}s, {n_params} params)")
    return entry


def main():
    import torch
    which = sys.argv[1:] or ["lstm", "transformer"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}  torch {torch.__version__}")
    if device.type == "cpu":
        torch.set_num_threads(max(1, os.cpu_count() - 2))

    X, y_mm, ends, is_test, norm = load_series()
    y_cls = rain_class(y_mm).astype(np.int64)
    print(f"windows: {len(ends)} (train {int((~is_test).sum())}, test {int(is_test.sum())})  "
          f"features {X.shape[1]}  class dist {np.bincount(y_cls[ends], minlength=4).tolist()}")

    from app.services.features import update_registry
    models = build_models()
    for key in which:
        name = "lstm_impact" if key.startswith("lstm") else "transformer"
        print(f"\n== {name} ==")
        entry = train_one(name, models[name], X, y_cls, y_mm, ends, is_test, norm, device)
        update_registry(REGISTRY, {name: entry})
    print(f"\nSEQUENCE TRAINING COMPLETE -> {REGISTRY}")


if __name__ == "__main__":
    main()
