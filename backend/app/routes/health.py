"""Health / monitoring routes — /api/health/monitoring and helpers.

The plain GET /api/health liveness check stays in app/main.py; this router adds the
operational view: in-process counters, the last 50 alerts, Open-Meteo budget status, the
three-model NWP smoke result, the canary outcome and the model-drift check.
"""
from fastapi import APIRouter, Query

from app.services import monitoring
from app.services import budget
from app.services.forecast_providers import last_nwp_smoke, nwp_smoke
from app.services import canary as canary_svc
from app.services import retention

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/monitoring")
async def monitoring_status(alerts: int = Query(50, ge=1, le=200)):
    snap = monitoring.snapshot()
    try:
        budget_status = budget.status()
    except Exception as e:  # never let a budget-file problem take the health route down
        budget_status = {"error": str(e)}
    return {
        "status": "ok",
        "started_at": snap["started_at"],
        "uptime_s": snap["uptime_s"],
        "counters": snap["counters"],
        "alerts": await monitoring.recent_alerts(alerts),
        "budget": budget_status,
        "nwp_smoke": last_nwp_smoke(),
        "canary": {"last": canary_svc.last_result(), "baseline": canary_svc.baseline(), "tolerance": canary_svc.tolerance()},
        "drift": monitoring.check_drift(do_alert=False),
        "predictions_24h": snap["predictions_24h"],
    }


@router.get("/budget")
async def budget_status():
    return budget.status()


@router.get("/events")
async def monitoring_events(limit: int = Query(100, ge=1, le=500)):
    """Rolling warn-level counter rows persisted in system_logs (newest first)."""
    return await monitoring.recent_events(limit)


@router.post("/nwp-smoke")
async def run_nwp_smoke():
    """Run the three-model Open-Meteo smoke check now (costs 3 budget units)."""
    return await nwp_smoke()


@router.post("/canary")
async def run_canary_now():
    return await canary_svc.run_canary()


@router.get("/retention/dry-run")
async def retention_dry_run():
    """Counts of rows the daily retention job would coarsen / strip / delete right now."""
    return await retention.run_retention(dry_run=True)
