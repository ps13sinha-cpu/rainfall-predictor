"""Open-Meteo call budget — a persistent token bucket shared by the API server and the
bulk ingest scripts.

Open-Meteo's free tier is accounted in *call units*, not HTTP requests:

  * 1 unit per location per two-week window of requested data, so a forecast call
    (<= 16 days) is 1 unit, an archive call is ceil(days / 14) units per location
    and a multi-location call multiplies by the number of locations;
  * every 10 requested variables (hourly or daily fields) counts as another block;
  * hard limits 600 units / minute, 5,000 / hour, 10,000 / day (the day resets at
    00:00 UTC, about 05:30 IST — see memory/open-meteo-call-budget.md).

On top of the hard limits a *soft* daily cap (``RIIS_OPENMETEO_DAILY_CAP``, default
8,000) leaves head-room for the live pollers when a bulk pull is running.

State lives in ``backend/cache/openmeteo_budget.json`` (minute buckets, written
atomically under a lock file) so several processes share one bucket.

    from app.services.budget import reserve, estimate_units, BudgetExhausted, budgeted_get

    units = estimate_units("2024-01-01", "2024-12-31", n_locations=36)
    reserve(units, "train_ml")                 # raises BudgetExhausted
    resp = await budgeted_get(client, url, 1, "weather_poll")   # reserve + 429 bookkeeping
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import logging
from datetime import date, datetime, timezone

log = logging.getLogger("riis.budget")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache")
STATE_PATH = os.path.abspath(os.path.join(CACHE_DIR, "openmeteo_budget.json"))
LOCK_PATH = STATE_PATH + ".lock"

HARD_LIMITS = {"minute": 600, "hour": 5000, "day": 10000}
UNITS_PER_WINDOW_DAYS = 14
VARS_PER_UNIT = 10


def soft_daily_cap() -> int:
    try:
        return int(os.environ.get("RIIS_OPENMETEO_DAILY_CAP", "8000"))
    except ValueError:
        return 8000


class BudgetExhausted(RuntimeError):
    """Raised by reserve() when the requested units would exceed a window's limit."""

    def __init__(self, window: str, requested: int, used: int, limit: int):
        self.window, self.requested, self.used, self.limit = window, requested, used, limit
        super().__init__(
            f"Open-Meteo budget: {requested} unit(s) requested but {window} window has "
            f"{max(limit - used, 0)} of {limit} left (used {used})"
        )


class OpenMeteoRateLimited(RuntimeError):
    """Raised by budgeted_get() when Open-Meteo answers 429."""


# ── Unit accounting ───────────────────────────────────────────────────────────
def _to_date(d) -> date | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def estimate_units(start=None, end=None, n_locations: int = 1, n_vars: int = 0) -> int:
    """Units Open-Meteo will charge for one request.

    ``start``/``end`` are the requested data range (ISO strings or dates); None on both
    means a plain forecast call (1 unit per location). ``n_vars`` is optional; when given
    every started block of 10 variables multiplies the cost.
    """
    s, e = _to_date(start), _to_date(end)
    if s is None or e is None:
        days = 1
    else:
        days = max((e - s).days + 1, 1)
    windows = max(1, math.ceil(days / UNITS_PER_WINDOW_DAYS))
    var_blocks = max(1, math.ceil(max(n_vars, 0) / VARS_PER_UNIT)) if n_vars else 1
    return int(windows * var_blocks * max(int(n_locations), 1))


# ── Persistent state ──────────────────────────────────────────────────────────
_EMPTY = {"buckets": {}, "n_429": {}, "last_429": None, "labels": {}, "refused": {}}


def _load() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict):
            raise ValueError("not a dict")
        for k, v in _EMPTY.items():
            st.setdefault(k, json.loads(json.dumps(v)))
        return st
    except FileNotFoundError:
        return json.loads(json.dumps(_EMPTY))
    except Exception as e:  # corrupt file: start over rather than block every caller
        log.warning("budget state unreadable (%s); starting fresh", e)
        return json.loads(json.dumps(_EMPTY))


def _save(st: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = f"{STATE_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=0, sort_keys=True)
    os.replace(tmp, STATE_PATH)


class _FileLock:
    """Tiny cross-process lock (O_EXCL lock file, stale after 10 s). Best effort."""

    def __init__(self, path: str, timeout: float = 5.0):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > 10:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    log.warning("budget lock busy; proceeding without it")
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.close(self.fd)
                os.remove(self.path)
            except OSError:
                pass


def _minute(ts: float | None = None) -> int:
    return int((ts or time.time()) // 60)


def _utc_day(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).strftime("%Y-%m-%d")


def _prune(st: dict, now: float) -> None:
    cutoff = _minute(now) - 24 * 60 - 1
    st["buckets"] = {k: v for k, v in st["buckets"].items() if int(k) >= cutoff}
    today = _utc_day(now)
    for key in ("labels", "n_429", "refused"):
        st[key] = {d: v for d, v in st[key].items() if d == today}


def _used(st: dict, now: float) -> dict:
    m = _minute(now)
    day_start = _minute(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    used = {"minute": 0, "hour": 0, "day": 0}
    for k, v in st["buckets"].items():
        mk = int(k)
        if mk == m:
            used["minute"] += v
        if mk > m - 60:
            used["hour"] += v
        if mk >= day_start:
            used["day"] += v
    return used


# ── Public API ────────────────────────────────────────────────────────────────
def reserve(units: int, label: str = "unlabelled") -> dict:
    """Charge ``units`` against every window, or raise BudgetExhausted without charging.

    Returns the post-reservation usage ({"minute": n, "hour": n, "day": n}).
    """
    units = max(int(units), 0)
    now = time.time()
    with _FileLock(LOCK_PATH):
        st = _load()
        _prune(st, now)
        used = _used(st, now)
        limits = dict(HARD_LIMITS)
        limits["day"] = min(limits["day"], soft_daily_cap())
        for window in ("minute", "hour", "day"):
            if used[window] + units > limits[window]:
                today = _utc_day(now)
                st["refused"][today] = st["refused"].get(today, 0) + 1
                _save(st)
                exc = BudgetExhausted(window, units, used[window], limits[window])
                _notify("open_meteo_budget_refused", {"label": label, "window": window, "requested": units,
                                                      "used": used[window], "limit": limits[window]})
                raise exc
        if units:
            key = str(_minute(now))
            st["buckets"][key] = st["buckets"].get(key, 0) + units
            today = _utc_day(now)
            st["labels"].setdefault(today, {})
            st["labels"][today][label] = st["labels"][today].get(label, 0) + units
            _save(st)
        used = _used(st, now)
    return used


def record_429(label: str = "unlabelled") -> None:
    """Note a 429 from Open-Meteo (they are counted per UTC day) and raise a monitoring event."""
    now = time.time()
    with _FileLock(LOCK_PATH):
        st = _load()
        _prune(st, now)
        today = _utc_day(now)
        st["n_429"][today] = st["n_429"].get(today, 0) + 1
        st["last_429"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        _save(st)
    _notify("open_meteo_429", {"label": label})


def status() -> dict:
    """Used / remaining per window plus today's 429 and refusal counts."""
    now = time.time()
    st = _load()
    _prune(st, now)
    used = _used(st, now)
    limits = dict(HARD_LIMITS)
    cap = soft_daily_cap()
    today = _utc_day(now)
    return {
        "used": used,
        "limits": limits,
        "soft_daily_cap": cap,
        "remaining": {
            "minute": max(limits["minute"] - used["minute"], 0),
            "hour": max(limits["hour"] - used["hour"], 0),
            "day": max(min(limits["day"], cap) - used["day"], 0),
        },
        "day_resets_at_utc": "00:00",
        "n_429_today": st["n_429"].get(today, 0),
        "refused_today": st["refused"].get(today, 0),
        "last_429": st.get("last_429"),
        "by_label_today": st["labels"].get(today, {}),
        "state_file": STATE_PATH,
    }


def remaining_today() -> int:
    return status()["remaining"]["day"]


def override_enabled() -> bool:
    return os.environ.get("RIIS_BUDGET_OVERRIDE", "").strip() in ("1", "true", "yes")


def require_bulk(units: int, label: str) -> bool:
    """Gate for bulk scripts: True when ``units`` fit in today's remaining budget.

    Prints a clear message and returns False otherwise (unless RIIS_BUDGET_OVERRIDE=1,
    which prints a warning and returns True). Nothing is charged here; each request is
    charged as it is made.
    """
    rem = remaining_today()
    st = status()
    print(f"[budget] {label}: estimated {units} Open-Meteo unit(s); "
          f"{rem} left today (used {st['used']['day']} of soft cap {st['soft_daily_cap']}, hard 10,000).")
    if units <= rem:
        return True
    if override_enabled():
        print("[budget] RIIS_BUDGET_OVERRIDE=1 set; starting anyway. Expect 429s past the hard limit.")
        return True
    print(f"[budget] REFUSED: {label} needs {units} unit(s) but only {rem} remain today. "
          f"Shrink the range / location list, wait for the 00:00 UTC (05:30 IST) reset, "
          f"or set RIIS_BUDGET_OVERRIDE=1 to force it.", file=sys.stderr)
    return False


def _notify(kind: str, detail: dict) -> None:
    """Forward to the monitoring counters; never raise (budget is imported by scripts too)."""
    try:
        from app.services import monitoring
        monitoring.incr(kind, detail=detail)
    except Exception:
        pass


def _handle_response(resp, label: str):
    if getattr(resp, "status_code", 200) == 429:
        record_429(label)
        raise OpenMeteoRateLimited(f"Open-Meteo 429 for {label}")
    return resp


async def budgeted_get(client, url: str, units: int, label: str, **kwargs):
    """``await client.get(url, **kwargs)`` with the budget charged first.

    Raises BudgetExhausted (nothing sent) or OpenMeteoRateLimited (429 recorded). Any
    other status is returned as-is for the caller to handle. Intended for every
    Open-Meteo call site, including app/services/hyperlocal.py.
    """
    reserve(units, label)
    resp = await client.get(url, **kwargs)
    return _handle_response(resp, label)


def budgeted_get_sync(client, url: str, units: int, label: str, **kwargs):
    """Synchronous twin of budgeted_get() for httpx.Client users (the ingest scripts)."""
    reserve(units, label)
    resp = client.get(url, **kwargs)
    return _handle_response(resp, label)
