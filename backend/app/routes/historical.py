"""Historical weather routes + ingestion."""
from datetime import datetime, timedelta
import httpx
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import District, HistoricalWeather
from app.services.auth import require_admin

router = APIRouter(prefix="/api/historical", tags=["historical"])


@router.get("/{district_code}")
async def get_historical(
    district_code: str,
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    """Get historical weather for a district (daily aggregated)."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    q = (
        select(HistoricalWeather)
        .where(HistoricalWeather.district_id == district.id)
        .where(HistoricalWeather.date >= start_date)
        .where(HistoricalWeather.date <= end_date)
        .order_by(HistoricalWeather.date)
    )
    result = await db.execute(q)
    rows = result.scalars().all()

    return {
        "district_code": district_code,
        "start_date": start_date,
        "end_date": end_date,
        "data": [
            {
                "date": h.date,
                "rainfall_mm": h.rainfall_mm,
                "temp_max": h.temp_max,
                "temp_min": h.temp_min,
                "humidity_avg": h.humidity_avg,
                "wind_speed_max": h.wind_speed_max,
                "precipitation_hours": h.precipitation_hours,
            }
            for h in rows
        ],
    }


@router.post("/ingest/{district_code}")
async def ingest_historical(
    district_code: str,
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    user=None,  # require_admin
    db: AsyncSession = Depends(get_db),
):
    """Pull historical data from Open-Meteo archive API and store it."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    url = (
        f"{settings.openmeteo_archive_url}/archive?"
        f"latitude={district.lat}&longitude={district.lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        f"precipitation_sum,precipitation_hours,wind_speed_10m_max,"
        f"relative_humidity_2m_mean"
        f"&timezone=auto"
    )

    from app.services.budget import budgeted_get, estimate_units, BudgetExhausted, OpenMeteoRateLimited
    units = estimate_units(start_date, end_date, n_locations=1, n_vars=7)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await budgeted_get(client, url, units, "historical_ingest")
            data = resp.json()
    except BudgetExhausted as e:
        raise HTTPException(status_code=429, detail=str(e))
    except OpenMeteoRateLimited as e:
        raise HTTPException(status_code=429, detail=str(e))

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    ingested = 0

    for i, date in enumerate(dates):
        q = select(HistoricalWeather).where(
            HistoricalWeather.district_id == district.id,
            HistoricalWeather.date == date,
        )
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            continue

        hw = HistoricalWeather(
            district_id=district.id,
            date=date,
            rainfall_mm=daily.get("precipitation_sum", [0] * len(dates))[i] or 0,
            temp_max=daily.get("temperature_2m_max", [0] * len(dates))[i] or 0,
            temp_min=daily.get("temperature_2m_min", [0] * len(dates))[i] or 0,
            humidity_avg=daily.get("relative_humidity_2m_mean", [0] * len(dates))[i] or 0,
            wind_speed_max=daily.get("wind_speed_10m_max", [0] * len(dates))[i] or 0,
            precipitation_hours=daily.get("precipitation_hours", [0] * len(dates))[i] or 0,
        )
        db.add(hw)
        ingested += 1

    await db.commit()
    return {"ok": True, "district": district_code, "rows_ingested": ingested, "total_dates": len(dates)}
