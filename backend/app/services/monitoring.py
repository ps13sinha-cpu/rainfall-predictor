"""Monitoring — in-process counters, a persisted rolling event log (SystemLog), alerts
with an optional webhook, and model-drift checks.

    from app.services import monitoring
    monitoring.incr("overpass_empty", detail={"lat": .., "lon": ..})
    monitoring.alert("scraper_parse_failure", {"scraper": "kseb", "consecutive": 3})
    monitoring.record_prediction("high")            # ML route calls this per served class
    monitoring.check_drift()                         # TVD against the registry's test distribution

Counter kinds (free-form kinds are accepted too, these are the documented ones):
  open_meteo_429, open_meteo_budget_refused, overpass_empty, scraper_parse_failure
  (per scraper: detail={"scraper": ...} is counted under "scraper_parse_failure:<name>"),
  forecast_provider_fallback, model_drift, stale_site_cache, canary_failure, canary_drift.

Persistence: ``alert()`` always writes a ``system_logs`` row with level='alert',
source='monitoring'. ``incr()`` writes one level='warn' row per kind per minute carrying
the count accumulated since the previous row, so the table holds a rolling log without
one row per event. Everything here is best-effort and never raises into callers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

log = logging.getLogger("riis.monitoring")

KINDS = (
    "open_meteo_429", "open_meteo_budget_refused", "overpass_empty", "scraper_parse_failure",
    "forecast_provider_fallback", "model_drift", "stale_site_cache", "canary_failure", "canary_drift",
)
CLASS_NAMES = ["safe", "mod", "high", "extreme"]
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ml_models", "model_registry.json")
PERSIST_INTERVAL_S = 60.0
# RIIS_MONITORING_PERSIST=0 keeps everything in memory (unit tests, offline scripts).
PERSIST_ENABLED = os.environ.get("RIIS_MONITORING_PERSIST", "1").strip() not in ("0", "false", "no")

_started_at = time.time()
_lock = threading.Lock()
_counters: dict[str, int] = {}
_last: dict[str, dict] = {}                 # kind -> {"at": iso, "detail": {...}}
_pending: dict[str, int] = {}               # events not yet written to SystemLog
_last_persisted: dict[str, float] = {}
_alerts: deque = deque(maxlen=200)          # in-memory copy of recent alerts
_predictions: deque = deque(maxlen=50000)   # (epoch, cls)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Counters ──────────────────────────────────────────────────────────────────
def _counter_key(kind: str, detail: dict | None) -> str:
    if kind == "scraper_parse_failure" and detail and detail.get("scraper"):
        return f"{kind}:{detail['scraper']}"
    return kind


def incr(kind: str, n: int = 1, detail: dict | None = None) -> int:
    """Bump a counter; persist a rolling 'warn' row at most once per minute per kind."""
    key = _counter_key(kind, detail)
    with _lock:
        _counters[key] = _counters.get(key, 0) + n
        _pending[key] = _pending.get(key, 0) + n
        _last[key] = {"at": _now_iso(), "detail": detail or {}}
        total = _counters[key]
        due = time.time() - _last_persisted.get(key, 0.0) >= PERSIST_INTERVAL_S
        if due:
            _last_persisted[key] = time.time()
            count = _pending.pop(key, 0)
    if due:
        _fire(_persist("warn", key, {"count": count, "total_since_start": total, **(detail or {})}))
    return total


def counters() -> dict:
    with _lock:
        return {k: {"count": v, "last": _last.get(k)} for k, v in sorted(_counters.items())}


def snapshot() -> dict:
    return {
        "started_at": datetime.fromtimestamp(_started_at, tz=timezone.utc).isoformat(),
        "uptime_s": round(time.time() - _started_at),
        "counters": counters(),
        "recent_alerts_in_memory": list(_alerts)[-50:],
        "predictions_24h": served_class_counts(),
    }


# ── Persistence (SystemLog) ───────────────────────────────────────────────────
async def _persist(level: str, kind: str, detail: dict) -> None:
    if not PERSIST_ENABLED:
        return
    try:
        from app.database import async_session
        from app.models import SystemLog
        async with async_session() as db:
            db.add(SystemLog(level=level, source="monitoring", message=kind, details=_jsonable(detail)))
            await db.commit()
    except Exception as e:
        log.debug("monitoring persist skipped: %s", e)


def _jsonable(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"repr": repr(obj)[:500]}


def _fire(coro) -> None:
    """Run a coroutine without blocking the caller: schedule it on the running loop, or, from
    synchronous code (ingest scripts), run it in a daemon thread. A SQLite write can wait up
    to 30 s for a lock held by another process, so it must never run inline."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        try:
            loop.create_task(coro)
            return
        except Exception:
            pass

    def _runner():
        try:
            asyncio.run(coro)
        except Exception as e:
            log.debug("monitoring background task failed: %s", e)

    try:
        threading.Thread(target=_runner, name="riis-monitoring", daemon=True).start()
    except Exception as e:
        log.debug("monitoring thread failed: %s", e)
        try:
            coro.close()
        except Exception:
            pass


# ── Alerts ────────────────────────────────────────────────────────────────────
async def alert_async(kind: str, detail: dict | None = None) -> dict:
    """Write an 'alert' row and POST it to RIIS_ALERT_WEBHOOK if set. Never raises."""
    detail = detail or {}
    entry = {"kind": kind, "detail": _jsonable(detail), "at": _now_iso()}
    with _lock:
        _alerts.append(entry)
        _counters[f"alert:{kind}"] = _counters.get(f"alert:{kind}", 0) + 1
    log.warning("ALERT %s %s", kind, json.dumps(entry["detail"], default=str)[:400])
    await _persist("alert", kind, detail)
    await _webhook(entry)
    return entry


def alert(kind: str, detail: dict | None = None) -> None:
    """Fire-and-forget alert usable from sync or async code."""
    _fire(alert_async(kind, detail))


async def _webhook(entry: dict) -> None:
    url = os.environ.get("RIIS_ALERT_WEBHOOK", "").strip()
    if not url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json={"service": "riis", **entry})
    except Exception as e:
        log.debug("alert webhook failed: %s", e)


async def recent_alerts(limit: int = 50) -> list[dict]:
    """Last ``limit`` alert rows from system_logs (newest first); falls back to memory."""
    try:
        from sqlalchemy import select
        from app.database import async_session
        from app.models import SystemLog
        async with async_session() as db:
            rows = (await db.execute(
                select(SystemLog).where(SystemLog.level == "alert").order_by(SystemLog.id.desc()).limit(limit)
            )).scalars().all()
        return [{"id": r.id, "kind": r.message, "detail": r.details, "source": r.source,
                 "at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    except Exception as e:
        log.debug("recent_alerts fell back to memory: %s", e)
        return list(_alerts)[-limit:][::-1]


async def recent_events(limit: int = 100) -> list[dict]:
    """Rolling warn-level monitoring rows (counter persistence), newest first."""
    try:
        from sqlalchemy import select
        from app.database import async_session
        from app.models import SystemLog
        async with async_session() as db:
            rows = (await db.execute(
                select(SystemLog).where(SystemLog.source == "monitoring", SystemLog.level != "alert")
                .order_by(SystemLog.id.desc()).limit(limit)
            )).scalars().all()
        return [{"id": r.id, "kind": r.message, "level": r.level, "detail": r.details,
                 "at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    except Exception:
        return []


# ── Model drift ───────────────────────────────────────────────────────────────
def record_prediction(cls: str) -> None:
    """Remember a served risk class (safe | mod | high | extreme) for the 24 h drift window."""
    if cls not in CLASS_NAMES:
        return
    with _lock:
        _predictions.append((time.time(), cls))


def served_class_counts(hours: float = 24.0) -> dict:
    cutoff = time.time() - hours * 3600
    counts = {c: 0 for c in CLASS_NAMES}
    with _lock:
        while _predictions and _predictions[0][0] < cutoff:
            _predictions.popleft()
        for _, c in _predictions:
            counts[c] += 1
    return counts


def baseline_class_distribution(model: str = "ensemble_vote") -> dict | None:
    """Test-set class shares from ml_models/model_registry.json.

    The registry stores ``metrics.per_class`` (keys in class order) and
    ``metrics.confusion_matrix`` (rows = true class, same order); the row sums are the
    held-out class counts. Returns {"counts": {...}, "shares": {...}, "model": name,
    "test_rows": n} or None if unavailable.
    """
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            reg = json.load(f)
    except Exception:
        return None
    entry = reg.get(model) or reg.get("xgboost") or next(
        (v for v in reg.values() if isinstance(v, dict) and v.get("metrics", {}).get("confusion_matrix")), None)
    if not entry:
        return None
    metrics = entry.get("metrics", {})
    cm = metrics.get("confusion_matrix")
    names = list(metrics.get("per_class", {}).keys()) or CLASS_NAMES
    if not cm or len(cm) != len(names):
        return None
    counts = {name: int(sum(row)) for name, row in zip(names, cm)}
    total = sum(counts.values()) or 1
    return {"model": model if model in reg else next(k for k, v in reg.items() if v is entry),
            "counts": counts, "shares": {k: v / total for k, v in counts.items()},
            "test_rows": entry.get("test_rows", total), "holdout_from": entry.get("holdout_from")}


def total_variation_distance(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def check_drift(predicted_class_counts: dict | None = None, threshold: float | None = None,
                min_samples: int | None = None, do_alert: bool = True) -> dict:
    """Compare served class distribution (last 24 h by default) with the test-set distribution.

    Uses total-variation distance; ``RIIS_DRIFT_TVD`` (default 0.25) is the alert threshold
    and ``RIIS_DRIFT_MIN_SAMPLES`` (default 30) the minimum served count before judging.
    """
    threshold = float(os.environ.get("RIIS_DRIFT_TVD", "0.25")) if threshold is None else threshold
    min_samples = int(os.environ.get("RIIS_DRIFT_MIN_SAMPLES", "30")) if min_samples is None else min_samples
    observed = dict(predicted_class_counts) if predicted_class_counts is not None else served_class_counts()
    n = sum(int(v) for v in observed.values())
    base = baseline_class_distribution()
    out = {"observed_counts": observed, "n": n, "threshold_tvd": threshold, "min_samples": min_samples,
           "baseline": base, "tvd": None, "drifted": False, "status": "ok", "checked_at": _now_iso()}
    if base is None:
        out["status"] = "no_baseline"
        return out
    if n < min_samples:
        out["status"] = "insufficient_samples"
        return out
    shares = {k: observed.get(k, 0) / n for k in base["shares"]}
    tvd = total_variation_distance(shares, base["shares"])
    out["observed_shares"] = shares
    out["tvd"] = round(tvd, 4)
    if tvd > threshold:
        out["drifted"] = True
        out["status"] = "drift"
        incr("model_drift", detail={"tvd": round(tvd, 4)})
        if do_alert:
            alert("model_drift", {"tvd": round(tvd, 4), "threshold": threshold, "n": n,
                                  "observed": shares, "baseline": base["shares"], "model": base["model"]})
    return out


def reset_for_tests() -> None:
    with _lock:
        _counters.clear(); _last.clear(); _pending.clear(); _last_persisted.clear()
        _alerts.clear(); _predictions.clear()
