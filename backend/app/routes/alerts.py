"""Alert routes — create, list, broadcast alerts."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Alert, User
from app.services.auth import require_admin

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertCreate(BaseModel):
    severity: str
    title: str
    body: str = ""
    area: str = "General"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: float = 50.0
    channels: list[str] = ["web"]


class AlertOut(BaseModel):
    id: int
    severity: str
    title: str
    body: str
    area: str
    latitude: Optional[float]
    longitude: Optional[float]
    radius_km: float
    channels: list[str]
    is_broadcast: bool
    is_active: bool
    created_at: Optional[str]
    expires_at: Optional[str]

    class Config:
        from_attributes = True


@router.post("/", response_model=AlertOut, status_code=201)
async def create_alert(
    body: AlertCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    alert = Alert(
        severity=body.severity,
        title=body.title,
        body=body.body,
        area=body.area,
        latitude=body.latitude,
        longitude=body.longitude,
        radius_km=body.radius_km,
        channels=body.channels,
        is_broadcast=True,
        is_active=True,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    return _alert_out(alert)


@router.get("/", response_model=list[AlertOut])
async def list_alerts(
    active_only: bool = Query(True),
    severity: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(Alert)
    if active_only:
        q = q.where(Alert.is_active == True)
    if severity:
        q = q.where(Alert.severity == severity)
    q = q.order_by(desc(Alert.created_at)).limit(limit)
    result = await db.execute(q)
    return [_alert_out(a) for a in result.scalars().all()]


@router.put("/{alert_id}/deactivate")
async def deactivate_alert(
    alert_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_active = False
    return {"ok": True}


class BroadcastRequest(BaseModel):
    channels: list[str] = ["web"]


@router.post("/{alert_id}/broadcast")
async def broadcast_alert(
    alert_id: int,
    body: BroadcastRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Broadcast an alert via SMS/WhatsApp/Push channels."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    from app.services.alerting import broadcast_alert as do_broadcast
    broadcast_result = await do_broadcast(
        severity=alert.severity,
        title=alert.title,
        body=alert.body,
        area=alert.area,
        channels=body.channels,
    )

    alert.is_broadcast = True
    alert.channels = body.channels
    await db.commit()

    return {"ok": True, "alert_id": alert_id, "broadcast": broadcast_result}


def _alert_out(a: Alert) -> dict:
    return {
        "id": a.id,
        "severity": a.severity,
        "title": a.title,
        "body": a.body,
        "area": a.area,
        "latitude": a.latitude,
        "longitude": a.longitude,
        "radius_km": a.radius_km,
        "channels": a.channels or ["web"],
        "is_broadcast": a.is_broadcast,
        "is_active": a.is_active,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
    }
