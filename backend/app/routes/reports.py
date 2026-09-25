"""Community report routes — submit, list, moderate."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CommunityReport, User
from app.services.auth import require_user, require_reporter, require_admin, get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportCreate(BaseModel):
    report_type: str
    title: str
    description: str = ""
    severity: str = "mod"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: str = ""


class ReportOut(BaseModel):
    id: int
    author_id: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]
    location_name: str
    report_type: str
    title: str
    description: str
    severity: str
    media_url: str
    is_verified: bool
    ai_class: str
    upvotes: int
    status: str
    created_at: Optional[str]

    class Config:
        from_attributes = True


@router.post("/", response_model=ReportOut, status_code=201)
async def create_report(
    body: ReportCreate,
    user: User = Depends(require_reporter),
    db: AsyncSession = Depends(get_db),
):
    report = CommunityReport(
        author_id=user.id,
        latitude=body.latitude,
        longitude=body.longitude,
        location_name=body.location_name,
        report_type=body.report_type,
        title=body.title,
        description=body.description,
        severity=body.severity,
        status="pending",
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)
    return _report_to_out(report)


@router.get("/", response_model=list[ReportOut])
async def list_reports(
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = None,
    limit: int = Query(50, le=200),
    user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(CommunityReport)
    if status_filter:
        q = q.where(CommunityReport.status == status_filter)
    elif not user or user.role == "public":
        q = q.where(CommunityReport.status == "approved")
    if severity:
        q = q.where(CommunityReport.severity == severity)
    q = q.order_by(desc(CommunityReport.created_at)).limit(limit)
    result = await db.execute(q)
    return [_report_to_out(r) for r in result.scalars().all()]


@router.get("/{report_id}")
async def get_report(report_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CommunityReport).where(CommunityReport.id == report_id))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_to_out(r)


@router.post("/{report_id}/upvote")
async def upvote_report(report_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CommunityReport).where(CommunityReport.id == report_id))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    r.upvotes += 1
    return {"upvotes": r.upvotes}


@router.put("/{report_id}/moderate")
async def moderate_report(
    report_id: int,
    action: str = Query(...),  # approve | reject
    note: str = Query(""),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CommunityReport).where(CommunityReport.id == report_id))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    r.status = "approved" if action == "approve" else "rejected"
    r.verified_by = user.id
    r.verification_note = note
    return {"ok": True, "status": r.status}


def _report_to_out(r: CommunityReport) -> dict:
    return {
        "id": r.id,
        "author_id": r.author_id,
        "latitude": r.latitude,
        "longitude": r.longitude,
        "location_name": r.location_name,
        "report_type": r.report_type,
        "title": r.title,
        "description": r.description,
        "severity": r.severity,
        "media_url": r.media_url or "",
        "is_verified": r.is_verified,
        "ai_class": r.ai_class or "",
        "upvotes": r.upvotes,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
