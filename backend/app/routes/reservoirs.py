"""Reservoir routes — live telemetry (CMWSSB + KSEB daily reports), history, admin updates."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Reservoir
from app.services.reservoir_live import sync_reservoirs, load_state, cmwssb_history, CMWSSB_MAP, KSEB_MAP, freshness, max_age_h

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
    # live provenance
    source: Optional[str] = "seed"
    observed_at: Optional[str] = None
    level_ft: Optional[float] = None
    full_level_ft: Optional[float] = None
    storage_pct: Optional[float] = None
    rainfall_mm: Optional[float] = None
    last_year_mcft: Optional[float] = None
    alert_level: Optional[str] = None
    remarks: Optional[str] = None
    source_url: Optional[str] = None
    # freshness contract (computed at read time; see services/reservoir_live.freshness)
    fetched_at: Optional[str] = None
    age_h: Optional[float] = None        # hours since observed_at (None when no observation date)
    freshness: Optional[float] = None    # same as age_h
    stale: bool = True                   # older than RIIS_RESERVOIR_MAX_AGE_H, or seeded
    live: bool = False                   # not stale and from a live source

    class Config:
        from_attributes = True


class ReservoirUpdate(BaseModel):
    current_mcft: Optional[float] = None
    inflow_cms: Optional[float] = None
    outflow_cms: Optional[float] = None
    overflow_prob: Optional[float] = None


def _out(r: Reservoir) -> ReservoirOut:
    pct = getattr(r, "storage_pct", None)
    if pct is None and r.capacity_mcft:
        pct = round(100 * r.current_mcft / r.capacity_mcft, 1)
    fr = freshness(getattr(r, "observed_at", None), getattr(r, "source", None) or "seed")
    fetched = getattr(r, "fetched_at", None)
    return ReservoirOut(
        id=r.id, code=r.code, name=r.name, lat=r.lat, lon=r.lon,
        capacity_mcft=r.capacity_mcft, current_mcft=r.current_mcft,
        inflow_cms=r.inflow_cms, outflow_cms=r.outflow_cms,
        overflow_prob=r.overflow_prob, risk_class=r.risk_class,
        updated_at=r.updated_at.isoformat() if r.updated_at else None,
        source=getattr(r, "source", None) or "seed", observed_at=getattr(r, "observed_at", None),
        level_ft=getattr(r, "level_ft", None), full_level_ft=getattr(r, "full_level_ft", None),
        storage_pct=pct, rainfall_mm=getattr(r, "rainfall_mm", None), last_year_mcft=getattr(r, "last_year_mcft", None),
        alert_level=getattr(r, "alert_level", None), remarks=getattr(r, "remarks", None),
        source_url=getattr(r, "source_url", None),
        fetched_at=fetched.isoformat() if fetched else None,
        age_h=fr["age_h"], freshness=fr["age_h"], stale=fr["stale"], live=fr["live"],
    )


@router.get("/", response_model=list[ReservoirOut])
async def list_reservoirs(db: AsyncSession = Depends(get_db)):
    """All reservoirs. Live rows (source cmwssb / kseb) first, seeded rows last."""
    result = await db.execute(select(Reservoir).order_by(Reservoir.id))
    rows = [_out(r) for r in result.scalars().all()]
    rows.sort(key=lambda x: (x.source == "seed", x.id))
    return rows


@router.get("/live/status")
async def live_status():
    """When the daily reports were last fetched, per-source outcome, and which codes are live."""
    st = load_state()
    return {
        "fetched_at": st.get("fetched_at"),
        "sources": st.get("sources", {}),
        "live_codes": sorted(st.get("rows", {}).keys()),
        "feeds": {
            "cmwssb": {"url": "https://cmwssb.tn.gov.in/lake-level", "cadence": "daily", "reservoirs": [v[1] for v in CMWSSB_MAP.values()]},
            "kseb": {"url": "https://dams.kseb.in/?page_id=45", "cadence": "daily", "reservoirs": [v[1] for v in KSEB_MAP.values()]},
        },
        "schedule": "every 6 hours, and 5 s after backend start",
        "failures": st.get("failures", {}),
        "last_good": {k: {"as_on": v.get("as_on"), "fetched_at": v.get("fetched_at"), "codes": sorted((v.get("rows") or {}).keys())}
                      for k, v in (st.get("last_good") or {}).items()},
        "max_age_h": max_age_h(),
    }


@router.post("/sync")
async def sync_now(db: AsyncSession = Depends(get_db)):
    """Fetch both daily reports now and update the table."""
    try:
        return await sync_reservoirs(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sync failed: {e}")


@router.get("/{reservoir_code}/history")
async def reservoir_history(reservoir_code: str, days: int = Query(14, ge=1, le=60)):
    """Daily storage history (CMWSSB reservoirs only; one request per day, cached on disk)."""
    if reservoir_code not in {v[0] for v in CMWSSB_MAP.values()}:
        return {"code": reservoir_code, "days": days, "history": [], "note": "history is available for Chennai Metro Water reservoirs only"}
    hist = await cmwssb_history(reservoir_code, days)
    return {"code": reservoir_code, "days": days, "history": hist, "source": "cmwssb"}


@router.get("/{reservoir_code}")
async def get_reservoir(reservoir_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reservoir).where(Reservoir.code == reservoir_code))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Reservoir not found")
    return _out(r).model_dump()


@router.put("/{reservoir_code}")
async def update_reservoir(
    reservoir_code: str,
    body: ReservoirUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=None,  # Would use Depends(require_admin) with real auth
):
    """Admin-only: manually update reservoir telemetry (marks the row as manual)."""
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

    pct = (r.current_mcft / r.capacity_mcft * 100) if r.capacity_mcft > 0 else 0
    r.storage_pct = round(pct, 1)
    if pct > 95 or r.overflow_prob > 80:
        r.risk_class = "extreme"
    elif pct > 85 or r.overflow_prob > 50:
        r.risk_class = "high"
    elif pct > 70 or r.overflow_prob > 20:
        r.risk_class = "mod"
    else:
        r.risk_class = "safe"
    r.source = "manual"
    r.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "code": r.code, "risk_class": r.risk_class}
