"""Weather refresh endpoint — manual trigger for polling."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.weather import update_all_districts, update_district_weather
from app.services.auth import require_admin

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.post("/refresh")
async def refresh_all(db: AsyncSession = Depends(get_db)):
    """Refresh weather for all districts. Public endpoint (rate-limited)."""
    await update_all_districts(db)
    return {"ok": True, "message": "All districts refreshed"}


@router.post("/refresh/{district_code}")
async def refresh_one(district_code: str, db: AsyncSession = Depends(get_db)):
    """Refresh weather for one district."""
    from sqlalchemy import select
    from app.models import District

    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="District not found")

    await update_district_weather(db, district)
    await db.commit()
    return {"ok": True, "district": district_code, "risk": district.risk, "risk_class": district.risk_class}
