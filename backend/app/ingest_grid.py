"""
RIIS — Gridded hourly precipitation over northern Tamil Nadu for ConvLSTM / ConvGRU.

Requests Open-Meteo archive hourly precipitation for a regular 0.25 deg
lat/lon grid (11.0..13.5 N, 78.0..80.5 E -> 11 x 11 points, Chennai-centred)
one calendar month at a time for all points, and stacks the responses into an
array of shape (time, 11, 11) saved as a compressed .npz.

Open-Meteo counts one call unit per location per two weeks of data, so one
month for 121 points costs roughly 270 units. A full year is about 3,200 units
against the free tier's 10,000 per day.

Usage:
    cd backend
    python -m app.ingest_grid                      # 2024-01 .. 2024-12
    python -m app.ingest_grid 2024-01 2025-06      # explicit month range
"""
import os
import sys
import time
import json
import calendar

import httpx
import numpy as np

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models")
OUT_PATH = os.path.join(OUT_DIR, "grid_precip.npz")
CACHE_DIR = os.path.join(OUT_DIR, "grid_cache")

LATS = np.round(np.arange(11.0, 13.5 + 1e-6, 0.25), 2)   # 11
LONS = np.round(np.arange(78.0, 80.5 + 1e-6, 0.25), 2)   # 11
SLEEP_BETWEEN = 15  # seconds, keeps us under the 5,000 units / hour limit


def month_range(start, end):
    y, m = map(int, start.split("-"))
    y1, m1 = map(int, end.split("-"))
    while (y, m) <= (y1, m1):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch_month(client, pts, year, month):
    last = calendar.monthrange(year, month)[1]
    lat_s = ",".join(str(p[0]) for p in pts)
    lon_s = ",".join(str(p[1]) for p in pts)
    url = (
        f"{ARCHIVE}?latitude={lat_s}&longitude={lon_s}"
        f"&start_date={year}-{month:02d}-01&end_date={year}-{month:02d}-{last}"
        f"&hourly=precipitation&timezone=Asia%2FKolkata"
    )
    for attempt in range(8):
        try:
            r = client.get(url, timeout=180)
            if r.status_code == 200:
                data = r.json()
                return [data] if isinstance(data, dict) else data
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"\n    rate limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"\n    HTTP {r.status_code}: {r.text[:160]}", flush=True)
            time.sleep(10)
        except Exception as e:
            print(f"\n    error {e}, retrying", flush=True)
            time.sleep(15)
    return None


def assemble(pts):
    """Stack every cached month (in order) into (T, nlat, nlon)."""
    files = sorted(f for f in os.listdir(CACHE_DIR) if f.endswith(".json"))
    times, arrs = [], []
    for fn in files:
        with open(os.path.join(CACHE_DIR, fn)) as f:
            data = json.load(f)
        if len(data) != len(pts):
            print(f"  {fn}: expected {len(pts)} locations, got {len(data)}; skipping")
            continue
        t = data[0]["hourly"]["time"]
        T = len(t)
        arr = np.zeros((T, len(LATS), len(LONS)), dtype=np.float32)
        for (la, lo), d in zip(pts, data):
            i = int(round((la - LATS[0]) / 0.25))
            j = int(round((lo - LONS[0]) / 0.25))
            v = np.array(d["hourly"]["precipitation"], dtype=np.float32)
            if len(v) == T:
                arr[:, i, j] = np.nan_to_num(v, nan=0.0)
        times.extend(t)
        arrs.append(arr)
    if not arrs:
        print("nothing cached, no grid written")
        return
    all_arr = np.concatenate(arrs, axis=0)
    np.savez_compressed(OUT_PATH, precip=all_arr, times=np.array(times), lats=LATS, lons=LONS)
    print(f"\nGRID COMPLETE: {all_arr.shape} frames ({times[0]} .. {times[-1]}) saved to {OUT_PATH}")
    print(f"mean {all_arr.mean():.3f} mm/h, max {all_arr.max():.1f}, wet-hour fraction {(all_arr>0.1).mean():.3f}")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2024-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2024-12"
    os.makedirs(CACHE_DIR, exist_ok=True)

    pts = [(float(la), float(lo)) for la in LATS for lo in LONS]
    months = list(month_range(start, end))
    print(f"Grid {len(LATS)}x{len(LONS)} = {len(pts)} points, {len(months)} months {start}..{end}")

    t0 = time.time()
    with httpx.Client() as client:
        for y, m in months:
            cache = os.path.join(CACHE_DIR, f"{y}-{m:02d}.json")
            if os.path.exists(cache):
                continue
            print(f"{y}-{m:02d} ...", end=" ", flush=True)
            data = fetch_month(client, pts, y, m)
            if data is None:
                print("FAILED")
                continue
            with open(cache, "w") as f:
                json.dump(data, f)
            print(f"ok ({time.time()-t0:.0f}s)")
            time.sleep(SLEEP_BETWEEN)

    assemble(pts)


if __name__ == "__main__":
    main()
