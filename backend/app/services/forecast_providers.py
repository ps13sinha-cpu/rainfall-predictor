"""Second live-forecast provider and provider fallback.

* ``fetch_metno(lat, lon)`` — MET Norway Locationforecast 2.0 *compact*
  (https://api.met.no/weatherapi/locationforecast/2.0/compact). Their terms of use require an
  identifying User-Agent, at most 4 decimals on coordinates, honouring ``Expires`` and
  sending ``If-Modified-Since`` on re-requests; all three are done here with a small
  on-disk cache in ``backend/cache/metno/``. Returns the same flat dict that
  ``app.services.weather.parse_weather`` produces. Fields MET does not provide (air
  quality, UV, gusts, WMO code, precipitation probability, dew point, visibility) are
  ``None``, never defaults.
* ``fetch_with_fallback(lat, lon)`` — Open-Meteo first (``weather.fetch_weather``), MET
  Norway when Open-Meteo raises, answers 429 or the call budget is exhausted. Adds
  ``source`` ('open_meteo' | 'met_norway') and ``provider_fallback`` (bool).
* ``nwp_smoke(lat, lon)`` — one Open-Meteo forecast request for three NWP models
  (ecmwf_ifs025, gfs_seamless, icon_seamless); used by tests/test_nwp_smoke.py and the
  /api/health/monitoring route. Result cached in ``backend/cache/nwp_smoke.json``.

Units: MET reports wind in m/s; Open-Meteo in km/h, so wind is converted to km/h here.
See docs/FORECAST_PROVIDERS.md for licensing and the self-hosted (ECMWF / ERA5) paths.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, format_datetime

import httpx

from app.services import budget as _budget
from app.services import monitoring

log = logging.getLogger("riis.forecast_providers")

METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
METNO_UA = "RIIS/1.0 sinhapiyush987@gmail.com"
CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache"))
METNO_CACHE_DIR = os.path.join(CACHE_DIR, "metno")
NWP_SMOKE_PATH = os.path.join(CACHE_DIR, "nwp_smoke.json")
NWP_MODELS = ("ecmwf_ifs025", "gfs_seamless", "icon_seamless")
CHENNAI = (13.0827, 80.2707)

# Weather-cache fields in the order parse_weather emits them (kept for contract clarity)
PARSE_WEATHER_KEYS = (
    "temperature", "humidity", "pressure", "wind_speed", "wind_gusts", "wind_direction", "cloud_cover",
    "weather_code", "weather_description", "aqi", "aqi_label", "pm2_5", "pm10", "uv_index",
    "next_6h_rain", "peak_intensity", "max_probability", "hourly_data",
)
HOURLY_KEYS = ("time", "temperature_2m", "relative_humidity_2m", "precipitation", "precipitation_probability",
               "pressure_msl", "wind_speed_10m", "wind_direction_10m", "dew_point_2m", "weather_code", "visibility")


# ── MET Norway ────────────────────────────────────────────────────────────────
def _metno_cache_path(lat: float, lon: float) -> str:
    return os.path.join(METNO_CACHE_DIR, f"{lat:.4f}_{lon:.4f}.json")


def _read_cache(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(path: str, entry: dict) -> None:
    try:
        os.makedirs(METNO_CACHE_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        os.replace(tmp, path)
    except Exception as e:
        log.debug("metno cache write failed: %s", e)


def _http_date_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except Exception:
        return None


async def fetch_metno_raw(lat: float, lon: float, client: httpx.AsyncClient | None = None) -> dict:
    """Raw Locationforecast JSON, served from the disk cache while ``Expires`` holds."""
    lat, lon = round(float(lat), 4), round(float(lon), 4)
    path = _metno_cache_path(lat, lon)
    cached = _read_cache(path)
    now = datetime.now(timezone.utc).timestamp()
    if cached and cached.get("expires") and now < float(cached["expires"]) and cached.get("data"):
        return cached["data"]

    headers = {"User-Agent": METNO_UA, "Accept": "application/json"}
    if cached and cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]

    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(METNO_URL, params={"lat": lat, "lon": lon}, headers=headers)
    finally:
        if own:
            await client.aclose()

    expires = _http_date_to_epoch(r.headers.get("Expires")) or (now + 1800)
    if r.status_code == 304 and cached and cached.get("data"):
        cached["expires"] = expires
        _write_cache(path, cached)
        return cached["data"]
    if r.status_code == 203:
        log.warning("MET Norway answered 203: this product version is deprecated; update METNO_URL")
    if r.status_code not in (200, 203):
        if cached and cached.get("data"):
            log.warning("MET Norway HTTP %s; serving cached forecast", r.status_code)
            return cached["data"]
        r.raise_for_status()
    data = r.json()
    _write_cache(path, {
        "expires": expires,
        "last_modified": r.headers.get("Last-Modified") or format_datetime(datetime.now(timezone.utc), usegmt=True),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    })
    return data


def _f(v):
    return None if v is None else float(v)


def parse_metno(data: dict) -> dict:
    """Map a Locationforecast 2.0 compact document onto parse_weather()'s dict shape."""
    series = (data.get("properties") or {}).get("timeseries") or []
    if not series:
        raise ValueError("MET Norway response has no timeseries")

    def inst(entry):
        return ((entry.get("data") or {}).get("instant") or {}).get("details") or {}

    def precip(entry, horizon):
        blk = (entry.get("data") or {}).get(horizon) or {}
        return _f((blk.get("details") or {}).get("precipitation_amount"))

    def symbol(entry):
        for horizon in ("next_1_hours", "next_6_hours", "next_12_hours"):
            blk = (entry.get("data") or {}).get(horizon) or {}
            code = (blk.get("summary") or {}).get("symbol_code")
            if code:
                return code
        return None

    first = series[0]
    d0 = inst(first)
    wind_ms = _f(d0.get("wind_speed"))

    hourly = {k: [] for k in HOURLY_KEYS}
    hourly_precip = []
    for entry in series:
        if "next_1_hours" not in (entry.get("data") or {}):
            continue   # beyond ~48 h MET switches to 6-hourly steps; those are not hourly samples
        d = inst(entry)
        p1 = precip(entry, "next_1_hours")
        hourly["time"].append(entry.get("time"))
        hourly["temperature_2m"].append(_f(d.get("air_temperature")))
        hourly["relative_humidity_2m"].append(_f(d.get("relative_humidity")))
        hourly["precipitation"].append(p1)
        hourly["precipitation_probability"].append(None)
        hourly["pressure_msl"].append(_f(d.get("air_pressure_at_sea_level")))
        ws = _f(d.get("wind_speed"))
        hourly["wind_speed_10m"].append(None if ws is None else round(ws * 3.6, 1))
        hourly["wind_direction_10m"].append(_f(d.get("wind_from_direction")))
        hourly["dew_point_2m"].append(None)
        hourly["weather_code"].append(None)
        hourly["visibility"].append(None)
        hourly_precip.append(p1)

    next_6h = [v for v in hourly_precip[:6] if v is not None]
    if len(next_6h) >= 6:
        next_6h_rain = round(sum(next_6h), 1)
    else:
        p6 = precip(first, "next_6_hours")
        next_6h_rain = p6 if p6 is not None else (round(sum(next_6h), 1) if next_6h else None)
    next_12h = [v for v in hourly_precip[:12] if v is not None]
    peak = round(max(next_12h), 1) if next_12h else None

    sym = symbol(first)
    humidity = _f(d0.get("relative_humidity"))
    cloud = _f(d0.get("cloud_area_fraction"))
    wind_dir = _f(d0.get("wind_from_direction"))
    return {
        "temperature": _f(d0.get("air_temperature")),
        "humidity": None if humidity is None else int(round(humidity)),
        "pressure": _f(d0.get("air_pressure_at_sea_level")),
        "wind_speed": None if wind_ms is None else round(wind_ms * 3.6, 1),
        "wind_gusts": None,
        "wind_direction": None if wind_dir is None else int(round(wind_dir)),
        "cloud_cover": None if cloud is None else int(round(cloud)),
        "weather_code": None,
        "weather_description": sym.replace("_", " ") if sym else None,
        "aqi": None,
        "aqi_label": None,
        "pm2_5": None,
        "pm10": None,
        "uv_index": None,
        "next_6h_rain": next_6h_rain,
        "peak_intensity": peak,
        "max_probability": None,
        "hourly_data": hourly,
        "metno_symbol_code": sym,
        "observed_time": first.get("time"),
    }


async def fetch_metno(lat: float, lon: float) -> dict:
    """MET Norway forecast in parse_weather() shape (plus source='met_norway')."""
    data = await fetch_metno_raw(lat, lon)
    out = parse_metno(data)
    out["source"] = "met_norway"
    return out


# ── Fallback chain ────────────────────────────────────────────────────────────
async def fetch_with_fallback(lat: float, lon: float) -> dict:
    """Open-Meteo, else MET Norway. Returns parse_weather()-shaped dict with ``source`` and
    ``provider_fallback``; raises only when both providers fail."""
    from app.services.weather import fetch_weather, parse_weather
    try:
        raw = await fetch_weather(lat, lon)
        parsed = parse_weather(raw["weather"], raw["air_quality"])
        parsed["source"] = "open_meteo"
        parsed["provider_fallback"] = False
        return parsed
    except Exception as primary_exc:
        reason = type(primary_exc).__name__
        monitoring.incr("forecast_provider_fallback", detail={"reason": reason, "lat": lat, "lon": lon})
        log.warning("Open-Meteo unavailable (%s: %s); falling back to MET Norway", reason, primary_exc)
        try:
            parsed = await fetch_metno(lat, lon)
        except Exception as fallback_exc:
            log.error("MET Norway fallback failed too: %s", fallback_exc)
            raise primary_exc
        parsed["provider_fallback"] = True
        parsed["fallback_reason"] = reason
        return parsed


# ── Three-model smoke check ───────────────────────────────────────────────────
async def nwp_smoke(lat: float = CHENNAI[0], lon: float = CHENNAI[1], persist: bool = True) -> dict:
    """Ask Open-Meteo for hourly precipitation from three NWP models in one request and report
    which returned an array. One budget unit per model (three locations-equivalents)."""
    from app.config import settings
    url = (f"{settings.openmeteo_base_url}/forecast?latitude={lat}&longitude={lon}"
           f"&hourly=precipitation&models={','.join(NWP_MODELS)}&forecast_days=2&timezone=UTC")
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "lat": lat, "lon": lon,
              "models": {m: {"ok": False, "n_hours": 0} for m in NWP_MODELS}, "ok": False, "error": None}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await _budget.budgeted_get(client, url, len(NWP_MODELS), "nwp_smoke")
        if r.status_code != 200:
            result["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
        else:
            hourly = r.json().get("hourly", {})
            for m in NWP_MODELS:
                arr = hourly.get(f"precipitation_{m}")
                if arr is None and len(NWP_MODELS) == 1:
                    arr = hourly.get("precipitation")
                vals = [v for v in (arr or []) if v is not None]
                result["models"][m] = {"ok": bool(vals), "n_hours": len(arr or []),
                                       "sum_mm": round(sum(vals), 2) if vals else None}
            result["ok"] = all(v["ok"] for v in result["models"].values())
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    if persist:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = f"{NWP_SMOKE_PATH}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=1)
            os.replace(tmp, NWP_SMOKE_PATH)
        except Exception as e:
            log.debug("nwp smoke persist failed: %s", e)
    return result


def last_nwp_smoke() -> dict:
    try:
        with open(NWP_SMOKE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ok": None, "status": "not_run",
                "hint": "run `RIIS_LIVE_TESTS=1 python -m pytest tests/test_nwp_smoke.py` or POST /api/health/nwp-smoke"}
