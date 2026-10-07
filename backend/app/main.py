"""RIIS Backend — FastAPI entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, async_session
from app.services.scheduler import start_scheduler, stop_scheduler
from app.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables, seed data, start scheduler."""
    await init_db()
    # Add the live-telemetry columns to an existing reservoirs table before anything selects from it.
    from app.services.reservoir_live import ensure_schema
    async with async_session() as db:
        await ensure_schema(db)
    await seed()
    start_scheduler()
    # Pull today's reservoir reports right away (the scheduler also repeats this every 6 h).
    import asyncio
    from app.services.scheduler import scheduled_reservoir_sync
    asyncio.create_task(scheduled_reservoir_sync())
    print(f"[RIIS] Server running on {settings.host}:{settings.port}")
    yield
    stop_scheduler()
    print("[RIIS] Server shutting down")


app = FastAPI(
    title="RIIS — Real-time Indian Infrastructure Intelligence System",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS (allow frontend dev server) ──────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──────────────────────────────────────────────────────────
from app.routes.auth import router as auth_router
from app.routes.districts import router as districts_router
from app.routes.reservoirs import router as reservoirs_router
from app.routes.reports import router as reports_router
from app.routes.alerts import router as alerts_router
from app.routes.historical import router as historical_router
from app.routes.weather import router as weather_router
from app.routes.ml import router as ml_router
from app.routes.safe_routes import router as safe_routes_router
from app.routes.farmer import router as farmer_router
from app.routes.uploads import router as uploads_router
from app.routes.subscriptions import router as subscriptions_router
from app.routes.hyperlocal import router as hyperlocal_router
from app.routes.inundation import router as inundation_router

app.include_router(auth_router)
app.include_router(districts_router)
app.include_router(reservoirs_router)
app.include_router(reports_router)
app.include_router(alerts_router)
app.include_router(historical_router)
app.include_router(weather_router)
app.include_router(ml_router)
app.include_router(safe_routes_router)
app.include_router(farmer_router)
app.include_router(uploads_router)
app.include_router(subscriptions_router)
app.include_router(hyperlocal_router)
app.include_router(inundation_router)

# Serve uploaded files
from fastapi.staticfiles import StaticFiles
import os
upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
if os.path.exists(upload_dir):
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/stats")
async def stats():
    """System-wide statistics for admin dashboard."""
    async with async_session() as db:
        from sqlalchemy import func, select
        from app.models import District, Reservoir, CommunityReport, Alert, User

        district_count = (await db.execute(select(func.count(District.id)))).scalar() or 0
        reservoir_count = (await db.execute(select(func.count(Reservoir.id)))).scalar() or 0
        report_count = (await db.execute(select(func.count(CommunityReport.id)))).scalar() or 0
        pending_reports = (await db.execute(
            select(func.count(CommunityReport.id)).where(CommunityReport.status == "pending")
        )).scalar() or 0
        alert_count = (await db.execute(
            select(func.count(Alert.id)).where(Alert.is_active == True)
        )).scalar() or 0
        user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0

        # Risk distribution
        risk_dist = {}
        for cls in ["extreme", "high", "mod", "safe"]:
            cnt = (await db.execute(
                select(func.count(District.id)).where(District.risk_class == cls)
            )).scalar() or 0
            risk_dist[cls] = cnt

    return {
        "districts": district_count,
        "reservoirs": reservoir_count,
        "community_reports": report_count,
        "pending_reports": pending_reports,
        "active_alerts": alert_count,
        "users": user_count,
        "risk_distribution": risk_dist,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
