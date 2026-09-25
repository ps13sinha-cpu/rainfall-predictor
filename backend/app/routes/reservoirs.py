"""Reservoir routes — live telemetry + admin updates."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.database import get_db
from app.models import Reservoir
from app.services.auth import require_admin

router = APIRouter(prefix="/api/reservoirs", tags=["reservoirs"])


class ReservoirOut(BaseModel):
    id: int
    code: str
    name: str
    lat: float
    lon: float
    capacity_mcft: float
    current_mcft: float
    inflow_cms: float
    outflow_cms: float
    overflow_prob: float
    risk_class: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReservoirUpdate(BaseModel):
    current_mcft: Optional[float] = None
    inflow_cms: Optional[float] = None
    outflow_cms: Optional[float] = None
    overflow_prob: Optional[float] = None


@router.get("/", response_model=list[ReservoirOut])
async def list_reservoirs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reservoir).order_by(Reservoir.id))
    reservoirs = result.scalars().all()
    return [
        ReservoirOut(
            id=r.id, code=r.code, name=r.name, lat=r.lat, lon=r.lon,
            capacity_mcft=r.capacity_mcft, current_mcft=r.current_mcft,
            inflow_cms=r.inflow_cms, outflow_cms=r.outflow_cms,
            overflow_prob=r.overflow_prob, risk_class=r.risk_class,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in reservoirs
    ]


@router.get("/{reservoir_code}")
async def get_reservoir(reservoir_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reservoir).where(Reservoir.code == reservoir_code))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Reservoir not found")
    return {
        "id": r.id, "code": r.code, "name": r.name, "lat": r.lat, "lon": r.lon,
        "capacity_mcft": r.capacity_mcft, "current_mcft": r.current_mcft,
        "inflow_cms": r.inflow_cms, "outflow_cms": r.outflow_cms,
        "overflow_prob": r.overflow_prob, "risk_class": r.risk_class,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.put("/{reservoir_code}")
async def update_reservoir(
    reservoir_code: str,
    body: ReservoirUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=None,  # Would use Depends(require_admin) with real auth
):
    """Admin-only: manually update reservoir telemetry."""
    result = await db.execute(select(Reservoir).where(Reservoir.code == reservoir_code))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Reservoir not found")

    if body.current_mcft is not None:
        r.current_mcft = body.current_mcft
    if body.inflow_cms is not None:
        r.inflow_cms = body.inflow_cms
    if body.outflow_cms is not None:
        r.outflow_cms = body.outflow_cms
    if body.overflow_prob is not None:
        r.overflow_prob = body.overflow_prob

    # Recalculate risk class
    pct = (r.current_mcft / r.capacity_mcft * 100) if r.capacity_mcft > 0 else 0
    if pct > 95 or r.overflow_prob > 80:
        r.risk_class = "extreme"
    elif pct > 85 or r.overflow_prob > 50:
        r.risk_class = "high"
    elif pct > 70 or r.overflow_prob > 20:
        r.risk_class = "mod"
    else:
        r.risk_class = "safe"

    r.updated_at = datetime.utcnow()
    return {"ok": True, "code": r.code, "risk_class": r.risk_class}
