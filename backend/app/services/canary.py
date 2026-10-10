"""Nightly canary — recompute the hyperlocal impact for one fixed, well-cached site and
compare the score with a stored baseline.

Site: 12.803 N, 80.037 E (the most-cached hyperlocal site), scenario 50 mm over 6 h,
steady pattern. Baseline lives in backend/cache/canary_baseline.json (created on the
first successful run); a move of more than RIIS_CANARY_TOLERANCE points (default 10)
raises a 'canary_drift' alert through services/monitoring. The engine call needs the
network and the hyperlocal engine; any failure is recorded as 'canary_failure' and
never propagates to the scheduler. The last outcome is kept in cache/canary_last.json
for /api/health/monitoring.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from app.services import monitoring

log = logging.getLogger("riis.canary")

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache"))
BASELINE_PATH = os.path.join(CACHE_DIR, "canary_baseline.json")
LAST_PATH = os.path.join(CACHE_DIR, "canary_last.json")

SITE = {"lat": 12.803, "lon": 80.037}
SCENARIO = {"rainfall_mm": 50.0, "duration_h": 6.0, "pattern": "steady"}


def tolerance() -> float:
    try:
        return float(os.environ.get("RIIS_CANARY_TOLERANCE", "10"))
    except ValueError:
        return 10.0


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write(path, obj):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, default=str)
        os.replace(tmp, path)
    except Exception as e:
        log.debug("canary write failed: %s", e)


async def compute_canary_score() -> dict:
    """Call the hyperlocal impact route function directly (no HTTP). Contract with the
    hyperlocal agent: ``app.routes.hyperlocal.impact(lat, lon, rainfall_mm, duration_h,
    intensity_mm_h, pattern, ml_score)`` returns a dict with ``impact.score``."""
    from app.routes.hyperlocal import impact
    result = await impact(lat=SITE["lat"], lon=SITE["lon"], rainfall_mm=SCENARIO["rainfall_mm"],
                          duration_h=SCENARIO["duration_h"], intensity_mm_h=None,
                          pattern=SCENARIO["pattern"], ml_score=None)
    imp = result.get("impact") if isinstance(result, dict) else None
    score = imp.get("score") if isinstance(imp, dict) else result.get("score") if isinstance(result, dict) else None
    if score is None:
        raise ValueError("impact.score missing from engine result")
    return {"score": float(score), "class": (imp or {}).get("class"), "confidence_pct": (imp or {}).get("confidence_pct"),
            "still_loading": result.get("still_loading", []), "computed_at": result.get("computed_at")}


async def run_canary() -> dict:
    """Run the canary once; tolerant of every failure. Returns the outcome dict."""
    out = {"site": SITE, "scenario": SCENARIO, "ran_at": datetime.now(timezone.utc).isoformat(),
           "ok": False, "score": None, "baseline": None, "delta": None, "drifted": False, "error": None}
    try:
        res = await compute_canary_score()
        out.update({"ok": True, "score": res["score"], "class": res.get("class"),
                    "still_loading": res.get("still_loading", [])})
        base = _read(BASELINE_PATH)
        if not base or base.get("score") is None:
            base = {"score": res["score"], "class": res.get("class"), "recorded_at": out["ran_at"],
                    "site": SITE, "scenario": SCENARIO}
            _write(BASELINE_PATH, base)
            out["baseline"] = base["score"]
            out["baseline_created"] = True
            out["delta"] = 0.0
        else:
            out["baseline"] = base["score"]
            out["baseline_recorded_at"] = base.get("recorded_at")
            out["delta"] = round(res["score"] - float(base["score"]), 1)
            if abs(out["delta"]) > tolerance():
                out["drifted"] = True
                monitoring.incr("canary_drift", detail={"delta": out["delta"]})
                monitoring.alert("canary_drift", {"site": SITE, "scenario": SCENARIO, "score": res["score"],
                                                  "baseline": base["score"], "delta": out["delta"],
                                                  "tolerance": tolerance(), "still_loading": res.get("still_loading", [])})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        monitoring.incr("canary_failure", detail={"error": out["error"]})
        log.warning("canary failed: %s", out["error"])
    _write(LAST_PATH, out)
    return out


def last_result() -> dict | None:
    return _read(LAST_PATH)


def baseline() -> dict | None:
    return _read(BASELINE_PATH)
