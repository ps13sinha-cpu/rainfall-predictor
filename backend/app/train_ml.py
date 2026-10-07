"""
RIIS — Historical Data Ingestion + ML Training Script (Synchronous SQLite version)

Pulls 2 years of daily weather from Open-Meteo archive API for all 36 districts,
stores in the HistoricalWeather table, then trains the XGBoost model.

Usage:
    cd backend
    python -m app.train_ml
"""
import asyncio
import sqlite3
import sys
import os
import json

import httpx

# ── Configuration ──────────────────────────────────────────────────────────────
START_DATE = os.environ.get("RIIS_START_DATE", "2022-01-01")
END_DATE = os.environ.get("RIIS_END_DATE", "2025-12-31")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")
OPENMETEO_ARCHIVE = "https://archive-api.open-meteo.com/v1"


def get_districts():
    """Get all districts from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, code, name, lat, lon FROM districts ORDER BY code")
    rows = c.fetchall()
    conn.close()
    return rows


def ingest_district_data(district_id, dates, daily):
    """Insert historical weather rows using INSERT OR IGNORE for idempotency."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    rain_vals = daily.get("precipitation_sum", [])
    tmax_vals = daily.get("temperature_2m_max", [])
    tmin_vals = daily.get("temperature_2m_min", [])
    wind_vals = daily.get("wind_speed_10m_max", [])

    rows = []
    for i, date in enumerate(dates):
        rain = (rain_vals[i] if i < len(rain_vals) else 0) or 0
        tmax = (tmax_vals[i] if i < len(tmax_vals) else 0) or 0
        tmin = (tmin_vals[i] if i < len(tmin_vals) else 0) or 0
        wind = (wind_vals[i] if i < len(wind_vals) else 0) or 0
        rows.append((district_id, date, rain, tmax, tmin, 0, wind, 0))

    c.executemany(
        """INSERT OR IGNORE INTO historical_weather
           (district_id, date, rainfall_mm, temp_max, temp_min, humidity_avg, wind_speed_max, precipitation_hours)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows
    )
    inserted = c.rowcount
    conn.commit()
    conn.close()
    return inserted


def run_ingestion():
    """Ingest historical weather for all districts."""
    districts = get_districts()

    print()
    print("=" * 60)
    print("RIIS Historical Data Ingestion")
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Districts: {len(districts)}")
    print("=" * 60)
    print()

    total_ingested = 0

    with httpx.Client() as client:
        for i, (did, code, name, lat, lon) in enumerate(districts):
            print(f"[{i+1}/{len(districts)}] {name} ({code})...", end=" ", flush=True)

            try:
                url = (
                    f"{OPENMETEO_ARCHIVE}/archive?"
                    f"latitude={lat}&longitude={lon}"
                    f"&start_date={START_DATE}&end_date={END_DATE}"
                    f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                    f"precipitation_sum,precipitation_hours,wind_speed_10m_max"
                    f"&timezone=auto"
                )
                resp = client.get(url, timeout=30)
                if resp.status_code != 200:
                    print(f"HTTP {resp.status_code}")
                    continue

                data = resp.json()
                daily = data.get("daily", {})
                dates = daily.get("time", [])
                if not dates:
                    print("no data")
                    continue

                n = ingest_district_data(did, dates, daily)
                total_ingested += n
                print(f"{len(dates)} days - {n} new rows")

            except Exception as e:
                print(f"ERROR: {e}")

    print()
    print("=" * 60)
    print(f"INGESTION COMPLETE: {total_ingested} new rows ingested")
    print("=" * 60)
    return total_ingested


def run_training():
    """Train the XGBoost model on all historical data."""
    print()
    print("Loading historical data for training...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM historical_weather")
    count = c.fetchone()[0]
    print(f"Total historical rows: {count}")
    conn.close()

    if count < 30:
        print("ERROR: Not enough data to train. Need at least 30 rows.")
        return

    # Import ML service (needs sys.path)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # Use a simple data class to hold rows
    class Row:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT date, rainfall_mm, temp_max, temp_min, humidity_avg,
               wind_speed_max, precipitation_hours
        FROM historical_weather
        ORDER BY date
    """)
    rows = [Row(
        date=r[0], rainfall_mm=r[1], temp_max=r[2], temp_min=r[3],
        humidity_avg=r[4], wind_speed_max=r[5], precipitation_hours=r[6]
    ) for r in c.fetchall()]
    conn.close()

    print(f"\nTraining XGBoost model on {len(rows)} samples...")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

    # Directly import and call train_model
    from app.services.ml import train_model
    metrics = train_model(rows)

    print()
    print("=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print("=" * 60)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode in ("ingest", "all"):
        run_ingestion()

    if mode in ("train", "all"):
        run_training()

    if mode not in ("ingest", "train", "all"):
        print("Usage: python -m app.train_ml [ingest|train|all]")


if __name__ == "__main__":
    main()
