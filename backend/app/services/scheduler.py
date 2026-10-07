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
    scheduler.start()
    print(f"[RIIS-Scheduler] Started — weather every {interval_sec}s, reservoirs every 6h")


def stop_scheduler():
    """Stop the scheduler. Call on app shutdown."""
    scheduler.shutdown(wait=False)
    print("[RIIS-Scheduler] Stopped")
