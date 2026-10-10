"""Background scheduler — polls weather APIs on interval."""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings
from app.database import async_session
from app.services.weather import update_all_districts


scheduler = AsyncIOScheduler()


async def scheduled_weather_poll():
    """Periodic weather update for all districts."""
    try:
        async with async_session() as db:
            await update_all_districts(db)
    except Exception as e:
        print(f"[RIIS-Scheduler] Weather poll failed: {e}")


async def scheduled_retention():
    """Daily privacy job: coarsen old coordinates, delete old route logs, strip old free text."""
    try:
        from app.services.retention import run_retention
        await run_retention(dry_run=False)
    except Exception as e:
        print(f"[RIIS-Scheduler] Retention job failed: {e}")


async def scheduled_canary():
    """Nightly engine canary: fixed site, fixed scenario, compare with the stored baseline."""
    try:
        from app.services.canary import run_canary
        out = await run_canary()
        print(f"[RIIS-Scheduler] Canary: ok={out['ok']} score={out['score']} baseline={out['baseline']} delta={out['delta']} err={out['error']}")
    except Exception as e:
        print(f"[RIIS-Scheduler] Canary job failed: {e}")


async def scheduled_reservoir_sync():
    """Pull the daily CMWSSB and KSEB reservoir reports into the reservoirs table."""
    try:
        from app.services.reservoir_live import sync_reservoirs
        async with async_session() as db:
            await sync_reservoirs(db)
    except Exception as e:
        print(f"[RIIS-Scheduler] Reservoir sync failed: {e}")


def start_scheduler():
    """Start the background scheduler. Call once on app startup."""
    from datetime import datetime, timedelta
    interval_sec = settings.district_poll_interval
    scheduler.add_job(
        scheduled_weather_poll,
        "interval",
        seconds=interval_sec,
        id="weather_poll",
        replace_existing=True,
    )
    # Reports are daily; poll every 6 h and once shortly after startup.
    scheduler.add_job(
        scheduled_reservoir_sync,
        "interval",
        hours=6,
        id="reservoir_sync",
        replace_existing=True,
        next_run_time=datetime.now() + timedelta(seconds=5),
        misfire_grace_time=600,   # startup can be slow; never skip the first sync
    )
    # Daily data-retention pass (docs/DATA_RETENTION.md) at 03:30 local time.
    scheduler.add_job(
        scheduled_retention,
        "cron",
        hour=3, minute=30,
        id="data_retention",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Nightly engine canary (services/canary.py) at 02:15 local time.
    scheduler.add_job(
        scheduled_canary,
        "cron",
        hour=2, minute=15,
        id="engine_canary",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    print(f"[RIIS-Scheduler] Started — weather every {interval_sec}s, reservoirs every 6h, retention daily 03:30, canary nightly 02:15")


def stop_scheduler():
    """Stop the scheduler. Call on app shutdown."""
    scheduler.shutdown(wait=False)
    print("[RIIS-Scheduler] Stopped")
