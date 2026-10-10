"""Hyperlocal impact routes — factors + full rainfall impact assessment (engine 3.0).

Every /impact response carries `data_quality` (which inputs are fallbacks or defaults and
whether the class was capped), `provenance` (source, age, TTL and licence per layer),
`validation_status` (untested_hypothesis until app/data/calibration.json exists) and
`cap_reason`; `location.district_code` is the LGD code resolved through district_lookup.json.
"""
import asyncio

from app.services.station_bias_lookup import station_bias_for
from fastapi import APIRouter, HTTPException, Query

from app.services.hyperlocal import (get_geofactors, get_antecedent, get_live_conditions, get_tide,
                                     get_upstream_reservoirs, compute_impact)

router = APIRouter(prefix="/api/hyperlocal", tags=["hyperlocal"])

PATTERNS = ("steady", "front", "back", "burst")


async def _district_context(lat: float, lon: float) -> dict:
    """Nearest seeded district: population, code, and its last 30 days of daily rain."""
    try:
        from app.database import async_session
        from app.models import District, HistoricalWeather
        from sqlalchemy import select

        async with async_session() as db:
            rows = (await db.execute(select(District))).scalars().all()
            best, bd = None, 1e18
            for d in rows:
                if d.lat is None or d.lon is None:
                    continue
                dist = (d.lat - lat) ** 2 + (d.lon - lon) ** 2
                if dist < bd:
                    bd, best = dist, d
            if best is None:
                return {"population": 0, "code": None, "name": None, "history": []}
            h = await db.execute(
                select(HistoricalWeather.rainfall_mm)
                .where(HistoricalWeather.district_id == best.id)
                .order_by(HistoricalWeather.date.desc()).limit(30))
            history = [r[0] or 0.0 for r in h.all()][::-1]
        return {"population": int(getattr(best, "pop", 0) or 0), "code": best.code, "name": best.name,
                "history": history}
    except Exception:
        return {"population": 0, "code": None, "name": None, "history": []}


def _auto_ml(weather: dict, history: list, lat: float, lon: float):
    """Heavy-rain probability (0-100) from the tabular ensemble, if trained."""
    try:
        from app.services.ml import predict
        p = predict(weather, history, lat, lon, model_name="ensemble_vote")
        if p.get("method") == "formula_fallback":
            return None, None
        return round(100 * p["heavy_rain_probability"]), p
    except Exception:
        return None, None


async def _gather_all(lat: float, lon: float):
    geo, ant, live, ctx = await asyncio.gather(
        get_geofactors(lat, lon), get_antecedent(lat, lon), get_live_conditions(lat, lon),
        _district_context(lat, lon))
    coastal = bool((geo.get("coast") or {}).get("coastal"))
    terr = geo.get("terrain") or {}
    point_elev = terr.get("elevation_m", (geo.get("elevation") or {}).get("elevation_m", 20.0))
    tide, upstream = await asyncio.gather(get_tide(lat, lon, coastal), get_upstream_reservoirs(lat, lon, point_elev))
    return geo, ant, live, ctx, tide, upstream


@router.get("/geofactors")
async def geofactors(lat: float = Query(...), lon: float = Query(...), force: bool = Query(False)):
    """Static geospatial factors: terrain hydrology, water, soil, landuse, infrastructure, coast, flood history."""
    try:
        geo = await get_geofactors(lat, lon, force=force)
        ant = await get_antecedent(lat, lon)
        return {"lat": lat, "lon": lon, "geo": geo, "antecedent": {k: v for k, v in ant.items() if k != "series"}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/factors")
async def factors(lat: float = Query(...), lon: float = Query(...)):
    """Every input the impact engine uses, static and live, without scoring."""
    try:
        geo, ant, live, ctx, tide, upstream = await _gather_all(lat, lon)
        return {"lat": lat, "lon": lon, "geo": geo, "antecedent": {k: v for k, v in ant.items() if k != "series"},
                "live": live, "tide": tide, "upstream_reservoirs": upstream,
                "district_context": {k: v for k, v in ctx.items() if k != "history"}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/impact")
async def impact(lat: float = Query(...), lon: float = Query(...),
                 rainfall_mm: float = Query(50.0, ge=0, le=500),
                 duration_h: float = Query(6.0, ge=0.5, le=72),
                 intensity_mm_h: float = Query(None, ge=0, le=300),
                 pattern: str = Query("steady", description="steady | front | back | burst"),
                 ml_score: float = Query(None, description="override the model score (0-100)")):
    """Full ten-category rainfall impact assessment for a hyperlocal point."""
    if pattern not in PATTERNS:
        raise HTTPException(status_code=400, detail=f"pattern must be one of {PATTERNS}")
    try:
        geo, ant, live, ctx, tide, upstream = await _gather_all(lat, lon)
        weather = dict(live)
        weather.setdefault("humidity_avg", weather.get("humidity"))
        weather.setdefault("rainfall_mm", weather.get("next_6h_rain"))
        auto_score, ml_detail = (None, None) if ml_score is not None else _auto_ml(weather, ctx["history"], lat, lon)
        scenario = {"rainfall_mm": rainfall_mm, "duration_h": duration_h, "intensity_mm_h": intensity_mm_h,
                    "pattern": pattern, "lat": lat, "lon": lon}
        result = compute_impact(geo, ant, weather, scenario, ctx["population"],
                                ml_score=ml_score if ml_score is not None else auto_score,
                                upstream=upstream, tide=tide, ml_detail=ml_detail)
        result["weather"] = live
        result["still_loading"] = geo.get("still_loading", [])
        result["data_quality"]["still_loading"] = result["still_loading"]
        result["district_context"] = {"nearest_seeded_district": ctx["name"], "code": ctx["code"]}
        result["reanalysis_bias"] = station_bias_for(ctx["name"], (result.get("location") or {}).get("district"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
