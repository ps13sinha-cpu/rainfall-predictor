"""Hyperlocal impact routes — geofactors + full rainfall impact assessment."""
from fastapi import APIRouter, HTTPException, Query

from app.services.hyperlocal import get_geofactors, get_antecedent, compute_impact

router = APIRouter(prefix="/api/hyperlocal", tags=["hyperlocal"])


async def _nearest_district_population(lat: float, lon: float) -> int:
    """Population of the nearest seeded district to the requested point."""
    try:
        from app.database import async_session
        from app.models import District
        from sqlalchemy import select

        async with async_session() as db:
            rows = (await db.execute(select(District))).scalars().all()
        best, bd = None, 1e18
        for d in rows:
            if d.lat is None or d.lon is None:
                continue
            dx, dy = d.lat - lat, d.lon - lon
            dist = dx * dx + dy * dy
            if dist < bd:
                bd, best = dist, d
        if best is None:
            return 0
        return int(getattr(best, "pop", 0) or 0)
    except Exception:
        return 0


@router.get("/geofactors")
async def geofactors(lat: float = Query(...), lon: float = Query(...),
                     force: bool = Query(False)):
    """Static geospatial factors: elevation, slope, water distance, soil, landuse."""
    try:
        geo = await get_geofactors(lat, lon, force=force)
        ant = await get_antecedent(lat, lon)
        return {"lat": lat, "lon": lon, "geo": geo, "antecedent": {k: v for k, v in ant.items() if k != "series"}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/impact")
async def impact(lat: float = Query(...), lon: float = Query(...),
                 rainfall_mm: float = Query(50.0, ge=0, le=500),
                 duration_h: float = Query(6.0, ge=0.5, le=72),
                 intensity_mm_h: float = Query(None, ge=0, le=300),
                 ml_score: float = Query(None)):
    """Full 8-category rainfall impact assessment for a hyperlocal point."""
    try:
        geo = await get_geofactors(lat, lon)
        ant = await get_antecedent(lat, lon)

        # Live weather for the point
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,cloud_cover",
                    "hourly": "precipitation,precipitation_probability",
                    "forecast_days": 2,
                    "timezone": "auto",
                },
            )
            wx = r.json()

        cur = wx.get("current", {})
        hourly = wx.get("hourly", {})
        next_6h = sum((hourly.get("precipitation") or [0])[:6])
        probs = [p for p in (hourly.get("precipitation_probability") or [])[:6] if p is not None]
        weather = {
            "current_rain": cur.get("precipitation", 0) or 0,
            "temperature": cur.get("temperature_2m", 28),
            "humidity": cur.get("relative_humidity_2m", 70),
            "wind_speed": cur.get("wind_speed_10m", 0),
            "probability": round(sum(probs) / len(probs)) if probs else 40,
            "next_6h_rain": round(next_6h, 1),
            "peak_intensity": max(hourly.get("precipitation") or [0][:12]),
        }

        scenario = {
            "rainfall_mm": rainfall_mm,
            "duration_h": duration_h,
            "intensity_mm_h": intensity_mm_h,
            "lat": lat,
            "lon": lon,
        }

        population = await _nearest_district_population(lat, lon)
        result = compute_impact(geo, ant, weather, scenario, population, ml_score=ml_score)
        result["weather"] = weather
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
