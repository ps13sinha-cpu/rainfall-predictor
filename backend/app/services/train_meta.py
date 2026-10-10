"""Reproducibility and coverage helpers shared by the training scripts.

Every registry entry should pin what it was trained on: the archive date range, the district ids,
the random seed, the row count and a SHA-256 of the training table. A retrain on another day pulls
a different corpus; with these pins two entries are comparable or visibly not.

Coverage weights: districts that have more years of archive would otherwise dominate the fit.
`coverage_weights` returns per-row weights proportional to 1 / (rows of that district), normalised
to mean 1, and the per-district row counts for the registry.
"""
import hashlib
import json
import os

import numpy as np
import pandas as pd

SEED = int(os.environ.get("RIIS_SEED", "42"))


def dataset_fingerprint(df: pd.DataFrame, key_cols: list, value_cols: list | None = None) -> dict:
    """Date range, district list, row count and a content hash of the (sorted) training table."""
    cols = key_cols + (value_cols or [c for c in df.columns if c not in key_cols])
    sub = df[cols].sort_values(key_cols).reset_index(drop=True)
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(sub, index=False).values.tobytes())
    out = {"rows": int(len(sub)), "sha256": h.hexdigest(), "columns": cols, "seed": SEED}
    if "date" in df.columns:
        out["start_date"], out["end_date"] = str(df["date"].min())[:10], str(df["date"].max())[:10]
    if "time" in df.columns:
        out["start_time"], out["end_time"] = str(df["time"].min())[:16], str(df["time"].max())[:16]
    if "district_id" in df.columns:
        out["district_ids"] = sorted(int(x) for x in df["district_id"].unique())
    return out


def coverage_weights(df: pd.DataFrame, group_col: str = "district_id") -> tuple[np.ndarray, dict]:
    """Inverse-coverage sample weights (mean 1) and the per-group row counts behind them."""
    counts = df[group_col].value_counts()
    w = np.array(1.0 / df[group_col].map(counts).to_numpy(dtype=np.float64), dtype=np.float64)
    w *= len(w) / w.sum()
    cov = {int(k): int(v) for k, v in counts.sort_index().items()}
    return w, cov


def pins(df: pd.DataFrame, key_cols: list, group_col: str = "district_id", **extra) -> dict:
    """One dict to drop into a registry entry under 'data_pins'."""
    fp = dataset_fingerprint(df, key_cols)
    cov = {int(k): int(v) for k, v in df[group_col].value_counts().sort_index().items()} if group_col in df else {}
    fp["coverage_rows_per_group"] = cov
    if cov:
        vals = np.array(list(cov.values()), dtype=float)
        fp["coverage_imbalance"] = round(float(vals.max() / max(vals.min(), 1)), 2)
    fp.update(extra)
    return fp


def write_pins_sidecar(model_dir: str, name: str, p: dict) -> None:
    with open(os.path.join(model_dir, f"{name}.pins.json"), "w") as f:
        json.dump(p, f, indent=2)
