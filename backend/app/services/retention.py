"""Data retention for location-bearing tables (community_reports, road_reports, route_logs).

Policy (docs/DATA_RETENTION.md):
  * after RIIS_RETENTION_COARSEN_DAYS (default 30): lat/lon on those rows are rounded to
    2 decimals (about 1.1 km) so a row no longer pins a house or a daily commute;
  * after RIIS_RETENTION_DELETE_DAYS (default 365): route_logs rows are deleted outright
    (they are movement data) and reports keep only their structured fields — free text
    (description, verification note, location name, road-report note) and the user
    linkage (author_id, verified_by) are stripped.

``run_retention(dry_run=True)`` only counts; ``run_retention()`` applies and logs the counts
both to the process log and to system_logs (source='retention'). Scheduled daily by
services/scheduler.py.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select, func, update, delete, or_

log = logging.getLogger("riis.retention")


def coarsen_days() -> int:
    return int(os.environ.get("RIIS_RETENTION_COARSEN_DAYS", "30"))


def delete_days() -> int:
    return int(os.environ.get("RIIS_RETENTION_DELETE_DAYS", "365"))


COARSEN_DECIMALS = 2


def _needs_coarsening(lat_col, lon_col):
    return or_(lat_col != func.round(lat_col, COARSEN_DECIMALS), lon_col != func.round(lon_col, COARSEN_DECIMALS))


async def run_retention(dry_run: bool = False, now: datetime | None = None, db=None) -> dict:
    """Apply (or, with dry_run, only count) the retention policy. Returns the counts."""
    from app.models import CommunityReport, RoadReport, RouteLog, SystemLog
    from app.database import async_session

    now = now or datetime.utcnow()
    coarsen_before = now - timedelta(days=coarsen_days())
    delete_before = now - timedelta(days=delete_days())
    counts = {"dry_run": dry_run, "coarsen_before": coarsen_before.isoformat(), "delete_before": delete_before.isoformat(),
              "coarsen_days": coarsen_days(), "delete_days": delete_days()}

    async def _run(session):
        # ── Coarsen coordinates ──
        jobs = [
            ("community_reports_coarsened", CommunityReport, CommunityReport.latitude, CommunityReport.longitude, CommunityReport.created_at),
            ("road_reports_coarsened", RoadReport, RoadReport.lat, RoadReport.lon, RoadReport.created_at),
            ("route_logs_from_coarsened", RouteLog, RouteLog.from_lat, RouteLog.from_lon, RouteLog.created_at),
            ("route_logs_to_coarsened", RouteLog, RouteLog.to_lat, RouteLog.to_lon, RouteLog.created_at),
        ]
        for key, model, lat_col, lon_col, ts_col in jobs:
            cond = (ts_col < coarsen_before) & lat_col.isnot(None) & lon_col.isnot(None) & _needs_coarsening(lat_col, lon_col)
            n = (await session.execute(select(func.count()).select_from(model).where(cond))).scalar() or 0
            counts[key] = n
            if n and not dry_run:
                await session.execute(update(model).where(cond).values({
                    lat_col.key: func.round(lat_col, COARSEN_DECIMALS), lon_col.key: func.round(lon_col, COARSEN_DECIMALS)}))

        # ── Delete route logs (movement data) ──
        cond = RouteLog.created_at < delete_before
        n = (await session.execute(select(func.count()).select_from(RouteLog).where(cond))).scalar() or 0
        counts["route_logs_deleted"] = n
        if n and not dry_run:
            await session.execute(delete(RouteLog).where(cond))

        # ── Strip free text + user linkage from old reports ──
        cond = (CommunityReport.created_at < delete_before) & or_(
            CommunityReport.author_id.isnot(None), CommunityReport.verified_by.isnot(None),
            CommunityReport.description != "", CommunityReport.verification_note != "", CommunityReport.location_name != "")
        n = (await session.execute(select(func.count()).select_from(CommunityReport).where(cond))).scalar() or 0
        counts["community_reports_stripped"] = n
        if n and not dry_run:
            await session.execute(update(CommunityReport).where(cond).values(
                author_id=None, verified_by=None, description="", verification_note="", location_name=""))

        cond = (RoadReport.created_at < delete_before) & (RoadReport.note != "")
        n = (await session.execute(select(func.count()).select_from(RoadReport).where(cond))).scalar() or 0
        counts["road_reports_stripped"] = n
        if n and not dry_run:
            await session.execute(update(RoadReport).where(cond).values(note=""))

        if not dry_run:
            session.add(SystemLog(level="info", source="retention", message="retention_run", details=dict(counts)))
            await session.commit()

    if db is not None:
        await _run(db)
    else:
        async with async_session() as session:
            await _run(session)

    log.info("retention %s: %s", "dry-run" if dry_run else "applied", {k: v for k, v in counts.items() if isinstance(v, int)})
    print(f"[RIIS-Retention] {'dry-run' if dry_run else 'applied'}: "
          + ", ".join(f"{k}={v}" for k, v in counts.items() if isinstance(v, int) and not isinstance(v, bool)))
    return counts


async def dry_run() -> dict:
    """Counts only; nothing is changed."""
    return await run_retention(dry_run=True)
