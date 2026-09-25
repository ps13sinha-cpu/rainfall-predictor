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


def start_scheduler():
    """Start the background scheduler. Call once on app startup."""
    interval_sec = settings.district_poll_interval
    scheduler.add_job(
        scheduled_weather_poll,
        "interval",
        seconds=interval_sec,
        id="weather_poll",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[RIIS-Scheduler] Started — polling every {interval_sec}s")


def stop_scheduler():
    """Stop the scheduler. Call on app shutdown."""
    scheduler.shutdown(wait=False)
    print("[RIIS-Scheduler] Stopped")
