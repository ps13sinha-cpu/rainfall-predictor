"""Safe Routes endpoints — road network, flood status per segment, flood-avoiding routing,
geocoding proxies, road condition reports, and the road flood-risk model."""
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RoadReport, RouteLog, User
from app.services.auth import get_current_user
from app.services import roads as R

router = APIRouter(prefix="/api/routes", tags=["safe-routes"])

MODES = ("car", "bike", "walk")


class ReportIn(BaseModel):
    lat: float
    lon: float
    status: str = Field(..., pattern="^(open|caution|closed)$")
    depth_cm: Optional[float] = Field(None, ge=0, le=500)
    note: str = Field("", max_length=300)
    rainfall_mm: Optional[float] = None
    duration_h: Optional[float] = None


def _scn(rainfall_mm, duration_h, intensity_mm_h):
    return {"rainfall_mm": rainfall_mm, "duration_h": duration_h,
            "intensity_mm_h": intensity_mm_h or round(rainfall_mm / max(duration_h, 0.5), 1),
            "key": R.scenario_key(rainfall_mm, duration_h, intensity_mm_h)}


def _risk_ml(bundle):
    """P(closed) + 0.5 P(caution) per segment from the surrogate model, or {} when untrained."""
    try:
        from app.services.roads_ml import predict_segments
        return predict_segments(bundle)
    except Exception:
        return {}


@router.get("/site")
async def site(lat: float = Query(...), lon: float = Query(...), force: bool = Query(False), db: AsyncSession = Depends(get_db)):
    """Ensure the road site around a point exists (fetches OSM + DEM on first call) and return its metadata."""
    try:
        b = await R.ensure_site(db, lat, lon, force=force)
        return dict(b["site"], cached_in_memory=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"site build failed: {e}")


@router.get("/roads")
async def roads(lat: float = Query(...), lon: float = Query(...),
                rainfall_mm: float = Query(60.0, ge=0, le=600), duration_h: float = Query(3.0, ge=0.5, le=72),
                intensity_mm_h: Optional[float] = Query(None, ge=0, le=300), mode: str = Query("car"),
                db: AsyncSession = Depends(get_db)):
    """GeoJSON of every road segment with its flood status for the scenario, plus the most affected named roads."""
    t0 = time.time()
    scn = _scn(rainfall_mm, duration_h, intensity_mm_h)
    try:
        b = await R.ensure_site(db, lat, lon)
        status = await R.score_segments(db, b, rainfall_mm, duration_h, intensity_mm_h)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    risk = _risk_ml(b)
    feats = []
    for sid, seg in b["segments"].items():
        st = status.get(sid, {})
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": seg["geom_json"]},
                      "properties": {"segment_id": sid, "name": seg["name"], "highway": seg["highway"],
                                     "status": st.get("status", "open"), "max_depth_m": st.get("max_depth_m", 0.0),
                                     "wet_fraction": st.get("wet_fraction", 0.0), "tunnel": seg["tunnel"], "bridge": seg["bridge"],
                                     "oneway": seg["oneway"], "length_m": seg["length_m"], "hand_m": seg["hand_m"],
                                     "culvert_near": seg["culvert_near"], "source": st.get("source", "sim"),
                                     "risk_ml": risk.get(sid)}})
    # most affected: worst depth per named road
    by_name = {}
    for f in feats:
        p = f["properties"]
        if not p["name"] or p["status"] == "open":
            continue
        cur = by_name.get(p["name"])
        if cur is None or p["max_depth_m"] > cur["max_depth_m"]:
            by_name[p["name"]] = {"name": p["name"], "highway": p["highway"], "status": p["status"],
                                  "max_depth_m": p["max_depth_m"], "segment_id": p["segment_id"],
                                  "lat": b["segments"][p["segment_id"]]["mid_lat"], "lon": b["segments"][p["segment_id"]]["mid_lon"]}
    most = sorted(by_name.values(), key=lambda x: (-R.STATUS_ORDER[x["status"]], -x["max_depth_m"]))[:15]
    counts = {}
    for f in feats:
        counts[f["properties"]["status"]] = counts.get(f["properties"]["status"], 0) + 1
    return {"type": "FeatureCollection", "features": feats, "site": b["site"], "scenario": scn, "mode": mode,
            "status_counts": counts, "most_affected": most, "risk_ml_coverage": round(len(risk) / max(len(feats), 1), 2),
            "computed_in_s": round(time.time() - t0, 2)}


@router.get("/route")
async def route(from_lat: float = Query(...), from_lon: float = Query(...), to_lat: float = Query(...), to_lon: float = Query(...),
                rainfall_mm: float = Query(60.0, ge=0, le=600), duration_h: float = Query(3.0, ge=0.5, le=72),
                intensity_mm_h: Optional[float] = Query(None, ge=0, le=300), mode: str = Query("car"),
                db: AsyncSession = Depends(get_db)):
    """Flood-avoiding route next to the normal shortest route."""
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {MODES}")
    scn = _scn(rainfall_mm, duration_h, intensity_mm_h)
    try:
        b = await R.ensure_site(db, from_lat, from_lon)
        status = await R.score_segments(db, b, rainfall_mm, duration_h, intensity_mm_h)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    bbox = b["site"]["bbox"]
    if not (bbox["south"] <= to_lat <= bbox["north"] and bbox["west"] <= to_lon <= bbox["east"]):
        return {"site_id": b["site"]["id"], "scenario": scn, "snapped": False, "reachable": False,
                "error": "destination is outside this site's road grid (about 3.6 km); pick a closer point",
                "bbox": bbox}
    res = R.find_routes(b, status, (from_lat, from_lon), (to_lat, to_lon), mode, scn)
    try:
        db.add(RouteLog(site_id=b["site"]["id"], from_lat=from_lat, from_lon=from_lon, to_lat=to_lat, to_lon=to_lon,
                        scenario_key=scn["key"], safe_len_m=(res.get("safe_route") or {}).get("length_m"),
                        normal_len_m=(res.get("normal_route") or {}).get("length_m"), closed_avoided=len(res.get("closed_avoided", []))))
        await db.commit()
    except Exception:
        pass
    return res


@router.get("/geocode")
async def geocode(q: str = Query(..., min_length=2), lat: float = Query(...), lon: float = Query(...)):
    """Nominatim search bounded to 15 km around the point (proxied, 1 request/s, cached)."""
    try:
        return {"results": await R.geocode(q, lat, lon)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"geocoding unavailable: {e}")


@router.get("/reverse")
async def reverse(lat: float = Query(...), lon: float = Query(...)):
    try:
        return await R.reverse(lat, lon)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"reverse geocoding unavailable: {e}")


@router.post("/report", status_code=201)
async def report(body: ReportIn, user: Optional[User] = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Road condition report from the field. Overrides the simulation within 25 m for 6 hours."""
    # nearest segment, if a site covers the point
    seg_id = None
    for b in R._sites.values():
        bb = b["site"]["bbox"]
        if bb["south"] <= body.lat <= bb["north"] and bb["west"] <= body.lon <= bb["east"]:
            best = None
            for sid, s in b["segments"].items():
                d = (s["mid_lat"] - body.lat) ** 2 + (s["mid_lon"] - body.lon) ** 2
                if best is None or d < best[0]:
                    best = (d, sid)
            if best:
                seg_id = best[1]
            R.invalidate_status(b["site"]["id"])
    key = R.scenario_key(body.rainfall_mm, body.duration_h) if body.rainfall_mm is not None and body.duration_h else None
    rep = RoadReport(segment_id=seg_id, lat=body.lat, lon=body.lon, status=body.status, depth_cm=body.depth_cm,
                     source="admin" if (user and getattr(user, "role", "") == "admin") else "user", note=body.note,
                     scenario_key=key, expires_at=datetime.utcnow() + timedelta(hours=6))
    db.add(rep)
    await db.commit()
    return {"id": rep.id, "segment_id": seg_id, "status": rep.status, "expires_at": rep.expires_at.isoformat()}


@router.get("/reports")
async def reports(lat: float = Query(...), lon: float = Query(...), db: AsyncSession = Depends(get_db)):
    """Active (unexpired) road reports within ~3 km of the point."""
    d = 3 / 111.0
    now = datetime.utcnow()
    rows = (await db.execute(select(RoadReport).where(RoadReport.lat.between(lat - d, lat + d),
                                                       RoadReport.lon.between(lon - d, lon + d)))).scalars().all()
    return {"reports": [{"id": r.id, "segment_id": r.segment_id, "lat": r.lat, "lon": r.lon, "status": r.status,
                         "depth_cm": r.depth_cm, "source": r.source, "note": r.note, "created_at": r.created_at.isoformat(),
                         "expires_at": r.expires_at.isoformat() if r.expires_at else None}
                        for r in rows if r.expires_at is None or r.expires_at > now]}


@router.get("/model")
async def model():
    """Metrics of the road flood-risk surrogate model (trained on simulated scenarios + community labels)."""
    from app.services.roads_ml import load_metrics
    return load_metrics()


@router.post("/train")
async def train(user: Optional[User] = Depends(get_current_user)):
    """Admin: regenerate training samples from every site and retrain the road risk model."""
    if user is not None and getattr(user, "role", "") not in ("admin",):
        raise HTTPException(status_code=403, detail="admin only")
    from app.train_roads import run_all
    try:
        return await run_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
