"""Road flood-risk surrogate model.

Scores a road segment's flood risk in well under a millisecond from static
features plus the scenario, so the roads layer can render before the DEM
simulation finishes, and so the model can learn from field reports over time.

HONEST CAVEAT: the initial training labels come from the physics simulation in
services/roads.score_segments (a surrogate of a surrogate), not from observed
floods. `label_source` on every RoadRiskSample records whether a row came from
the simulation ("sim") or a community RoadReport ("report"); report rows are
weighted 5x in training. The metrics file records both counts.
"""
import os
import json
import pickle
from datetime import datetime

import numpy as np

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ml_models")
MODEL_PATH = os.path.join(MODEL_DIR, "road_risk.pkl")
METRICS_PATH = os.path.join(MODEL_DIR, "road_risk_metrics.json")

FEATURES = ["rainfall_mm", "duration_h", "intensity_mm_h", "elev_m", "hand_m", "pit_depth_m", "slope_pct", "dist_water_m",
            "impervious_pct", "culvert_near", "tunnel", "bridge", "layer", "highway_class", "length_m",
            "site_saturation_pct", "site_infiltration_mm_h", "site_drain_count"]
LABELS = {"open": 0, "caution": 1, "closed_cars": 2, "closed_all": 2}
_model = None


def segment_features(seg: dict, scenario: dict, site_ctx: dict) -> dict:
    from app.services.roads import HIGHWAY_CLASS
    return {
        "rainfall_mm": scenario["rainfall_mm"], "duration_h": scenario["duration_h"],
        "intensity_mm_h": scenario.get("intensity_mm_h") or round(scenario["rainfall_mm"] / max(scenario["duration_h"], 0.5), 1),
        "elev_m": seg.get("elev_m"), "hand_m": seg.get("hand_m"), "pit_depth_m": seg.get("pit_depth_m"), "slope_pct": seg.get("slope_pct"),
        "dist_water_m": seg.get("dist_water_m"), "impervious_pct": seg.get("impervious_pct"),
        "culvert_near": int(bool(seg.get("culvert_near"))), "tunnel": int(bool(seg.get("tunnel"))),
        "bridge": int(bool(seg.get("bridge"))), "layer": seg.get("layer") or 0,
        "highway_class": HIGHWAY_CLASS.get(seg.get("highway"), 5), "length_m": seg.get("length_m"),
        "site_saturation_pct": site_ctx.get("saturation_pct"), "site_infiltration_mm_h": site_ctx.get("infiltration_mm_h"),
        "site_drain_count": site_ctx.get("drain_count"),
    }


def site_context(bundle: dict) -> dict:
    geo, ant = bundle["geo"], bundle["ant"]
    water = geo.get("water") or {}
    return {"saturation_pct": ant.get("saturation_pct", 45),
            "infiltration_mm_h": (geo.get("soil") or {}).get("infiltration_mm_h", 5.0),
            "drain_count": (water.get("counts") or {}).get("drain", 0) + (water.get("counts") or {}).get("waterway", 0)}


def _matrix(rows: list) -> np.ndarray:
    return np.array([[np.nan if r.get(f) is None else float(r.get(f)) for f in FEATURES] for r in rows], dtype=np.float32)


def train(samples: list, held_out_site: int | None) -> dict:
    """samples: [{features, label, label_source, site_id}]. Split BY SITE: one whole site is the test set."""
    import xgboost as xgb
    from sklearn.metrics import f1_score, recall_score, confusion_matrix, accuracy_score
    sites = sorted({s["site_id"] for s in samples})
    if held_out_site is None and len(sites) > 1:
        held_out_site = sites[-1]
    tr = [s for s in samples if s["site_id"] != held_out_site]
    te = [s for s in samples if s["site_id"] == held_out_site]
    if not tr:
        tr, te = samples, []
    X, y = _matrix([s["features"] for s in tr]), np.array([s["label"] for s in tr])
    counts = np.bincount(y, minlength=3).astype(float)
    cw = counts.sum() / (3 * np.maximum(counts, 1))
    w = cw[y] * np.array([5.0 if s["label_source"] == "report" else 1.0 for s in tr])
    model = xgb.XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05, objective="multi:softprob",
                              num_class=3, tree_method="hist", n_jobs=4, random_state=42, verbosity=0)
    model.fit(X, y, sample_weight=w)
    metrics = {"trained_at": datetime.utcnow().isoformat(), "features": FEATURES, "n_train": int(len(tr)), "n_test": int(len(te)),
               "sites": sites, "held_out_site": held_out_site,
               "label_sources": {"sim": sum(1 for s in samples if s["label_source"] == "sim"),
                                 "report": sum(1 for s in samples if s["label_source"] == "report")},
               "train_label_counts": counts.astype(int).tolist(),
               "caveat": "Labels come from the DEM ponding simulation (surrogate), not observed floods, except rows with label_source=report."}
    if te:
        Xt, yt = _matrix([s["features"] for s in te]), np.array([s["label"] for s in te])
        pred = model.predict(Xt)
        metrics.update({"accuracy": round(float(accuracy_score(yt, pred)), 4),
                        "macro_f1": round(float(f1_score(yt, pred, average="macro")), 4),
                        "per_class_recall": dict(zip(["open", "caution", "closed"],
                                                     [round(float(v), 3) for v in recall_score(yt, pred, labels=[0, 1, 2], average=None, zero_division=0)])),
                        "confusion_matrix": confusion_matrix(yt, pred, labels=[0, 1, 2]).tolist(),
                        "test_label_counts": np.bincount(yt, minlength=3).astype(int).tolist()})
    imp = model.feature_importances_
    metrics["feature_importance"] = {f: round(float(v), 4) for f, v in sorted(zip(FEATURES, imp), key=lambda x: -x[1])}
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)
    global _model
    _model = model
    return metrics


def load_model():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, "rb") as f:
            _model = pickle.load(f)
    return _model


def load_metrics() -> dict:
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH) as f:
            return json.load(f)
    return {"status": "not_trained", "message": "run `python -m app.train_roads all` or POST /api/routes/train"}


def predict_segments(bundle: dict, scenario: dict | None = None) -> dict:
    """{segment_id: risk} with risk = P(closed) + 0.5 P(caution). Uses the site's live scenario defaults."""
    model = load_model()
    if model is None:
        return {}
    scenario = scenario or {"rainfall_mm": 60.0, "duration_h": 3.0}
    ctx = site_context(bundle)
    ids = list(bundle["segments"].keys())
    X = _matrix([segment_features(bundle["segments"][i], scenario, ctx) for i in ids])
    probs = model.predict_proba(X)
    return {sid: round(float(p[2] + 0.5 * p[1]), 3) for sid, p in zip(ids, probs)}
