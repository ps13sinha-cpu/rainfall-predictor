"""Weather Service — fetches from Open-Meteo, caches in DB, computes risk."""
import httpx
import asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models import District, WeatherCache

# ── Open-Meteo query params ───────────────────────────────────────────────────
CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,"
    "precipitation,rain,showers,weather_code,cloud_cover,"
    "pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,visibility,uv_index"
)
HOURLY_FIELDS = (
    "temperature_2m,relative_humidity_2m,precipitation_probability,"
    "precipitation,rain,weather_code,pressure_msl,visibility,"
    "wind_speed_10m,wind_direction_10m,dew_point_2m"
)
DAILY_FIELDS = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_sum,precipitation_probability_max,uv_index_max"
)

# ── Helpers ───────────────────────────────────────────────────────────────────
WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

WIND_DIRS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def wind_dir_label(deg):
    return WIND_DIRS[int((deg + 11.25) / 22.5) % 16]


# ── Fetch weather for one coordinate ─────────────────────────────────────────
async def fetch_weather(lat: float, lon: float) -> dict:
    """Fetch current + hourly + daily + air quality from Open-Meteo.

    Both requests go through the call budget (1 unit each). Raises BudgetExhausted
    (nothing sent), OpenMeteoRateLimited (429) or httpx errors for the forecast call so
    callers can fall back to another provider; air quality stays best-effort.
    """
    from app.services.budget import budgeted_get, BudgetExhausted
    w_url = (
        f"{settings.openmeteo_base_url}/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current={CURRENT_FIELDS}"
        f"&hourly={HOURLY_FIELDS}"
        f"&daily={DAILY_FIELDS}"
        f"&timezone=auto"
    )
    a_url = (
        f"{settings.air_quality_url}/air-quality?"
        f"latitude={lat}&longitude={lon}"
        f"&current=us_aqi,pm2_5,pm10&timezone=auto"
    )

    async with httpx.AsyncClient(timeout=15) as client:
        w_resp, a_resp = await asyncio.gather(
            budgeted_get(client, w_url, 1, "weather_forecast"),
            budgeted_get(client, a_url, 1, "air_quality"),
            return_exceptions=True,
        )

    if isinstance(w_resp, BaseException):
        raise w_resp
    if w_resp.status_code != 200:
        raise httpx.HTTPStatusError(f"Open-Meteo forecast HTTP {w_resp.status_code}",
                                    request=w_resp.request, response=w_resp)
    w_data = w_resp.json()
    a_data = {}
    if not isinstance(a_resp, BaseException) and a_resp.status_code == 200:
        try:
            a_data = a_resp.json()
        except Exception:
            a_data = {}

    return {"weather": w_data, "air_quality": a_data}


# ── Parse weather into our schema ─────────────────────────────────────────────
def parse_weather(w_data: dict, a_data: dict) -> dict:
    """Convert raw Open-Meteo response into a flat dict for WeatherCache."""
    c = w_data.get("current", {})
    h = w_data.get("hourly", {})
    h_time = h.get("time", [])

    current_str = (c.get("time", "") or "")[:13]
    idx = 0
    for i, t in enumerate(h_time):
        if t and t.startswith(current_str):
            idx = i
            break

    temp = float(c.get("temperature_2m") or 28.0)
    humidity = int(c.get("relative_humidity_2m") or 75)
    pressure = float(c.get("pressure_msl") or 1010.0)
    wind_speed = float(c.get("wind_speed_10m") or 10.0)
    wind_gusts = float(c.get("wind_gusts_10m") or wind_speed * 1.5)
    wind_dir = int(c.get("wind_direction_10m") or 0)
    cloud_cover = int(c.get("cloud_cover") or 40)
    weather_code = int(c.get("weather_code") or 0)

    h_precip = h.get("precipitation", [])
    h_prob = h.get("precipitation_probability", [])

    future_6h = h_precip[idx:idx + 6]
    next_6h_rain = round(sum(v or 0 for v in future_6h), 1)

    future_12h = h_precip[idx:idx + 12]
    peak = round(max((v or 0) for v in future_12h), 1) if future_12h else 0.0

    prob_6h = h_prob[idx:idx + 6]
    max_prob = max((v or 0) for v in prob_6h) if prob_6h else 0

    # Air quality
    aq = a_data.get("current", {})
    aqi_val = int(aq.get("us_aqi") or 55)
    aqi_label = "Good" if aqi_val <= 50 else "Moderate" if aqi_val <= 100 else "Unhealthy" if aqi_val <= 200 else "Hazardous"

    # Build hourly dict for timeline
    hourly = {}
    for key in ["time", "temperature_2m", "relative_humidity_2m", "precipitation",
                "precipitation_probability", "pressure_msl", "wind_speed_10m",
                "wind_direction_10m", "dew_point_2m", "weather_code", "visibility"]:
        hourly[key] = h.get(key, [])

    return {
        "temperature": temp,
        "humidity": humidity,
        "pressure": pressure,
        "wind_speed": wind_speed,
        "wind_gusts": wind_gusts,
        "wind_direction": wind_dir,
        "cloud_cover": cloud_cover,
        "weather_code": weather_code,
        "weather_description": WMO_DESCRIPTIONS.get(weather_code, f"Code {weather_code}"),
        "aqi": aqi_val,
        "aqi_label": aqi_label,
        "pm2_5": float(aq.get("pm2_5") or 0),
        "pm10": float(aq.get("pm10") or 0),
        "uv_index": float(c.get("uv_index") or 0),
        "next_6h_rain": next_6h_rain,
        "peak_intensity": peak,
        "max_probability": int(max_prob),
        "hourly_data": hourly,
    }


# ── Risk calculation ──────────────────────────────────────────────────────────
def calculate_risk(next_6h_rain: float, peak_intensity: float,
                   humidity: int, wind_speed: float, cloud_cover: int) -> dict:
    """Server-side risk index computation (matches client-side formula)."""
    rain_score = min(60, (next_6h_rain / 50) * 60)
    prob_score = min(15, (min(100, next_6h_rain * 5) / 100) * 15)
    hum_score = max(0, (humidity - 65) * 0.25)
    wind_score = min(15, (wind_speed / 50) * 15)
    risk = max(5, min(100, round(rain_score + prob_score + hum_score + wind_score)))

    cls = "safe"
    if next_6h_rain > 50 or peak_intensity > 35:
        cls = "extreme"
    elif next_6h_rain > 20 or peak_intensity > 15:
        cls = "high"
    elif next_6h_rain > 5 or peak_intensity > 4:
        cls = "mod"

    if cls == "extreme" and risk < 75:
        risk = 78
    elif cls == "high" and risk < 50:
        risk = 58
    elif cls == "mod" and risk < 25:
        risk = 38
    elif cls == "safe" and risk > 30:
        risk = 22

    return {"risk": risk, "risk_class": cls}


# ── Update one district in DB ─────────────────────────────────────────────────
_CACHE_COLUMNS = {c.name for c in WeatherCache.__table__.columns}


async def update_district_weather(db: AsyncSession, district: District):
    """Fetch live weather for a district (Open-Meteo, else MET Norway) and persist to DB."""
    try:
        from app.services.forecast_providers import fetch_with_fallback
        parsed = await fetch_with_fallback(district.lat, district.lon)

        # Upsert weather_cache
        result = await db.execute(
            select(WeatherCache).where(WeatherCache.district_id == district.id)
        )
        cache = result.scalar_one_or_none()
        if cache is None:
            cache = WeatherCache(district_id=district.id)
            db.add(cache)

        for k, v in parsed.items():
            if k in _CACHE_COLUMNS:
                setattr(cache, k, v)
        if "provider" in _CACHE_COLUMNS:
            cache.provider = parsed.get("source", "open_meteo")
            cache.provider_fallback = bool(parsed.get("provider_fallback", False))
        cache.fetched_at = datetime.utcnow()

        # Update district risk (the fallback provider may leave fields None)
        next_6h = parsed.get("next_6h_rain") or 0.0
        peak = parsed.get("peak_intensity") or 0.0
        risk_info = calculate_risk(
            next_6h, peak,
            int(parsed.get("humidity") or 0), float(parsed.get("wind_speed") or 0.0),
            int(parsed.get("cloud_cover") or 0),
        )
        district.rain = next_6h if next_6h > 0.1 else parsed.get("current_rain", 0)
        district.risk = risk_info["risk"]
        district.risk_class = risk_info["risk_class"]
        district.updated_at = datetime.utcnow()

    except Exception as e:
        print(f"[RIIS] Weather fetch failed for {district.name}: {e}")


# ── Batch update all districts ────────────────────────────────────────────────
async def update_all_districts(db: AsyncSession):
    """Fetch weather for every district, in batches of 5 with small delays."""
    result = await db.execute(select(District))
    districts = result.scalars().all()
    batch_size = 5

    for i in range(0, len(districts), batch_size):
        batch = districts[i:i + batch_size]
        tasks = [update_district_weather(db, d) for d in batch]
        await asyncio.gather(*tasks)
        if i + batch_size < len(districts):
            await asyncio.sleep(0.2)  # respect rate limits

    await db.commit()
    print(f"[RIIS] Updated {len(districts)} districts")
