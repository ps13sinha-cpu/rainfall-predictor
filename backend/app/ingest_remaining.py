"""
RIIS — Ingest remaining districts that hit rate limits.

Run after the main ingestion to pick up districts that returned 429.
"""
import sqlite3
import os
import time

import httpx
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.services.budget import estimate_units, require_bulk, budgeted_get_sync, BudgetExhausted, OpenMeteoRateLimited  # noqa: E402

START_DATE = "2024-01-01"
END_DATE = "2025-12-31"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")
OPENMETEO_ARCHIVE = "https://archive-api.open-meteo.com/v1"

# Districts that returned 429 on previous run
RATE_LIMITED = [
    "IN-MZ-AI", "IN-NL-KO", "IN-OR-BU", "IN-PB-LO", "IN-RJ-JP",
    "IN-SK-GA", "IN-TG-HY", "IN-TN-CH", "IN-TN-CO", "IN-TN-KA",
    "IN-TN-MU", "IN-TN-TN", "IN-TR-AG", "IN-UP-LK", "IN-WB-KO", "IN-WB-SI",
]


def get_districts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(RATE_LIMITED))
    c.execute(f"SELECT id, code, name, lat, lon FROM districts WHERE code IN ({placeholders})", RATE_LIMITED)
    rows = c.fetchall()
    conn.close()
    return rows


def ingest_district_data(district_id, dates, daily):
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


def run():
    districts = get_districts()
    print(f"\nIngesting {len(districts)} rate-limited districts (with retry + delay)...\n")

    per_call = estimate_units(START_DATE, END_DATE, n_locations=1, n_vars=6)
    if not require_bulk(per_call * len(districts), "ingest_remaining"):
        return 0

    total = 0
    with httpx.Client() as client:
        for i, (did, code, name, lat, lon) in enumerate(districts):
            print(f"[{i+1}/{len(districts)}] {name} ({code})...", end=" ", flush=True)

            for attempt in range(3):
                try:
                    url = (
                        f"{OPENMETEO_ARCHIVE}/archive?"
                        f"latitude={lat}&longitude={lon}"
                        f"&start_date={START_DATE}&end_date={END_DATE}"
                        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                        f"precipitation_sum,precipitation_hours,wind_speed_10m_max"
                        f"&timezone=auto"
                    )
                    try:
                        resp = budgeted_get_sync(client, url, per_call, "ingest_remaining", timeout=30)
                    except BudgetExhausted as e:
                        print(f"STOP: {e}")
                        return total
                    except OpenMeteoRateLimited:
                        wait = 5 * (attempt + 1)
                        print(f"rate limited, waiting {wait}s...", end=" ", flush=True)
                        time.sleep(wait)
                        continue
                    if resp.status_code != 200:
                        print(f"HTTP {resp.status_code}")
                        break

                    data = resp.json()
                    daily = data.get("daily", {})
                    dates = daily.get("time", [])
                    if not dates:
                        print("no data")
                        break

                    n = ingest_district_data(did, dates, daily)
                    total += n
                    print(f"{len(dates)} days - {n} new rows")
                    break
                except Exception as e:
                    print(f"ERROR: {e}")
                    break

            # 3-second delay between districts to avoid rate limiting
            if i < len(districts) - 1:
                time.sleep(3)

    print(f"\nDONE: {total} new rows ingested")
    return total


if __name__ == "__main__":
    run()
