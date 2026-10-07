"""
RIIS — Hourly weather ingestion for sequence models (LSTM / Transformer)
and richer daily aggregates for the tree models.

Pulls hourly ERA5 / ERA5-Land reanalysis from the Open-Meteo archive for
every district, one request per district per year, into `historical_hourly`.

Usage:
    cd backend
    python -m app.ingest_hourly              # 2022-01-01 .. 2025-12-31
    python -m app.ingest_hourly 2024 2025    # explicit year range
"""
import os
import sys
import time
import sqlite3

import httpx

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
    "pressure_msl", "cloud_cover", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "soil_moisture_0_to_7cm", "vapour_pressure_deficit",
    "weather_code",
]

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS historical_hourly (
    district_id INTEGER NOT NULL,
    time TEXT NOT NULL,
    temperature_2m REAL, relative_humidity_2m REAL, dew_point_2m REAL,
    precipitation REAL, pressure_msl REAL, cloud_cover REAL,
    wind_speed_10m REAL, wind_direction_10m REAL, wind_gusts_10m REAL,
    soil_moisture_0_to_7cm REAL, vapour_pressure_deficit REAL, weather_code INTEGER,
    PRIMARY KEY (district_id, time)
)
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fetch_year(client, lat, lon, year):
    url = (
        f"{ARCHIVE}?latitude={lat}&longitude={lon}"
        f"&start_date={year}-01-01&end_date={year}-12-31"
        f"&hourly={','.join(HOURLY_VARS)}&timezone=Asia%2FKolkata"
    )
    for attempt in range(6):
        try:
            r = client.get(url, timeout=120)
            if r.status_code == 200:
                return r.json().get("hourly", {})
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"\n    rate limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"\n    HTTP {r.status_code}: {r.text[:120]}", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"\n    error {e}, retrying", flush=True)
            time.sleep(10)
    return {}


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2025

    conn = connect()
    conn.execute(CREATE_SQL)
    conn.commit()
    districts = conn.execute("SELECT id, code, name, lat, lon FROM districts ORDER BY code").fetchall()

    # skip (district, year) pairs already fully present
    done = set()
    for did, yr, n in conn.execute(
        "SELECT district_id, substr(time,1,4), COUNT(*) FROM historical_hourly GROUP BY 1,2"
    ):
        if n >= 8700:
            done.add((did, int(yr)))

    total = 0
    t0 = time.time()
    with httpx.Client() as client:
        for i, (did, code, name, lat, lon) in enumerate(districts):
            for year in range(y0, y1 + 1):
                if (did, year) in done:
                    continue
                print(f"[{i+1}/{len(districts)}] {name} {year} ...", end=" ", flush=True)
                h = fetch_year(client, lat, lon, year)
                times = h.get("time", [])
                if not times:
                    print("no data")
                    continue
                cols = [h.get(v, []) for v in HOURLY_VARS]
                rows = []
                for k, t in enumerate(times):
                    rows.append((did, t) + tuple(
                        (c[k] if k < len(c) else None) for c in cols
                    ))
                conn.executemany(
                    f"INSERT OR IGNORE INTO historical_hourly (district_id, time, {','.join(HOURLY_VARS)}) "
                    f"VALUES ({','.join(['?'] * (2 + len(HOURLY_VARS)))})",
                    rows,
                )
                conn.commit()
                total += len(rows)
                print(f"{len(rows)} rows  ({time.time()-t0:.0f}s)")
                time.sleep(0.6)

    n = conn.execute("SELECT COUNT(*) FROM historical_hourly").fetchone()[0]
    print(f"\nHOURLY INGESTION COMPLETE: {total} new rows, {n} total, {time.time()-t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
