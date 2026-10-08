"""Districts & Weather routes — live weather data + risk indices."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import District, WeatherCache

router = APIRouter(prefix="/api/districts", tags=["districts"])


class DistrictOut(BaseModel):
    id: int
    code: str
    name: str
    state: str
    lat: float
    lon: float
    pop: int
    risk: int
    rain: float
    risk_class: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class WeatherOut(BaseModel):
    temperature: float
    humidity: int
    pressure: float
    wind_speed: float
    wind_gusts: float
    wind_direction: int
    cloud_cover: int
    weather_code: int
    weather_description: str
    aqi: int
    aqi_label: str
    pm2_5: float
    pm10: float
    uv_index: float
    next_6h_rain: float
    peak_intensity: float
    max_probability: int
    fetched_at: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[DistrictOut])
async def list_districts(
    state: Optional[str] = None,
    risk_class: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all districts with current risk indices."""
    q = select(District)
    if state:
        q = q.where(District.state == state)
    if risk_class:
        q = q.where(District.risk_class == risk_class)
    q = q.order_by(desc(District.risk)).limit(limit)
    result = await db.execute(q)
    districts = result.scalars().all()
    return [
        DistrictOut(
            id=d.id, code=d.code, name=d.name, state=d.state,
            lat=d.lat, lon=d.lon, pop=d.pop, risk=d.risk,
            rain=d.rain, risk_class=d.risk_class,
            updated_at=d.updated_at.isoformat() if d.updated_at else None,
        )
        for d in districts
    ]


@router.get("/states")
async def state_risk(db: AsyncSession = Depends(get_db)):
    """Risk index per state, aggregated from the live district risks.

    index = 0.6 x worst district + 0.4 x mean of the state's districts, so one flooding city lifts
    its state but a single dry city does not hide a wet one. Class follows the same thresholds."""
    result = await db.execute(select(District))
    rows = [d for d in result.scalars().all() if d.state]
    by_state = {}
    for d in rows:
        by_state.setdefault(d.state, []).append(d)
    order = {"safe": 0, "mod": 1, "high": 2, "extreme": 3}
    out = []
    for state, ds in by_state.items():
        risks = [int(d.risk or 0) for d in ds]
        worst = max(ds, key=lambda d: int(d.risk or 0))
        idx = round(0.6 * max(risks) + 0.4 * sum(risks) / len(risks))
        cls = "extreme" if idx >= 75 else "high" if idx >= 50 else "mod" if idx >= 25 else "safe"
        worst_cls = max((d.risk_class or "safe" for d in ds), key=lambda c: order.get(c, 0))
        out.append({
            "state": state, "code": worst.code.split("-")[1] if worst.code.count("-") >= 2 else worst.code[:2],
            "risk_index": idx, "risk_class": cls, "worst_district_class": worst_cls,
            "max_risk": max(risks), "mean_risk": round(sum(risks) / len(risks), 1),
            "worst_district": {"code": worst.code, "name": worst.name, "risk": int(worst.risk or 0), "rain": worst.rain},
            "rain_max_mm": round(max(float(d.rain or 0) for d in ds), 1),
            "population": sum(int(d.pop or 0) for d in ds), "districts": len(ds),
            "district_list": [{"code": d.code, "name": d.name, "risk": int(d.risk or 0), "risk_class": d.risk_class, "rain": d.rain} for d in sorted(ds, key=lambda x: -int(x.risk or 0))],
            "updated_at": max((d.updated_at for d in ds if d.updated_at), default=None).isoformat() if any(d.updated_at for d in ds) else None,
        })
    out.sort(key=lambda s: -s["risk_index"])
    for i, s_ in enumerate(out):
        s_["rank"] = i + 1
    return {"states": out, "count": len(out), "districts_covered": len(rows)}


@router.get("/{district_code}")
async def get_district(district_code: str, db: AsyncSession = Depends(get_db)):
    """Get a single district with its full weather data."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    # Get weather cache
    w_result = await db.execute(
        select(WeatherCache).where(WeatherCache.district_id == district.id)
    )
    weather = w_result.scalar_one_or_none()

    return {
        "district": {
            "id": district.id,
            "code": district.code,
            "name": district.name,
            "state": district.state,
            "lat": district.lat,
            "lon": district.lon,
            "pop": district.pop,
            "risk": district.risk,
            "rain": district.rain,
            "risk_class": district.risk_class,
        },
        "weather": {
            "temperature": weather.temperature if weather else 0,
            "humidity": weather.humidity if weather else 0,
            "pressure": weather.pressure if weather else 1010,
            "wind_speed": weather.wind_speed if weather else 0,
            "wind_gusts": weather.wind_gusts if weather else 0,
            "wind_direction": weather.wind_direction if weather else 0,
            "cloud_cover": weather.cloud_cover if weather else 0,
            "weather_code": weather.weather_code if weather else 0,
            "weather_description": weather.weather_description if weather else "",
            "aqi": weather.aqi if weather else 0,
            "aqi_label": weather.aqi_label if weather else "Good",
            "pm2_5": weather.pm2_5 if weather else 0,
            "pm10": weather.pm10 if weather else 0,
            "uv_index": weather.uv_index if weather else 0,
            "next_6h_rain": weather.next_6h_rain if weather else 0,
            "peak_intensity": weather.peak_intensity if weather else 0,
            "max_probability": weather.max_probability if weather else 0,
            "fetched_at": weather.fetched_at.isoformat() if weather and weather.fetched_at else None,
        } if weather else None,
    }


@router.get("/{district_code}/hourly")
async def get_district_hourly(district_code: str, db: AsyncSession = Depends(get_db)):
    """Get hourly forecast data for timeline/charts."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    w_result = await db.execute(
        select(WeatherCache).where(WeatherCache.district_id == district.id)
    )
    weather = w_result.scalar_one_or_none()
    if weather is None:
        raise HTTPException(status_code=404, detail="No weather data yet — wait for next poll")

    hourly = weather.hourly_data or {}
    return {
        "district_code": district.code,
        "fetched_at": weather.fetched_at.isoformat() if weather.fetched_at else None,
        "hourly": hourly,
    }
