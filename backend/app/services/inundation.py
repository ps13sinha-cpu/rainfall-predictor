"""DEM-driven inundation model.

Fetches a real elevation grid from AWS Terrain Tiles (terrarium encoding,
SRTM-derived, ~9 m at z14 / ~4.6 m at z15), depression-fills it with
priority-flood (Barnes et al.), matches ponded water volume against the
runoff produced by the hyperlocal impact engine, and stitches the wet mask
into GeoJSON polygons for the flood-simulation map.

Volume model
------------
    runoff_mm   = event_rain_mm * runoff_coefficient      (from geofactors)
    drainage_mm = drainage_capacity_mm_h * duration_h     (from geofactors)
    net_mm      = max(0, runoff_mm - drainage_mm)         -> what ponds
    V           = net_mm/1000 * grid_area_m2

Water surface level W is found by binary search on the depression-filled
surface F so that sum(min(W, F) - dem)+ == V (pit storage first, then
uniform sheet excess over the domain when pits are full).
"""
import asyncio
import heapq
import io
import math
import time
from datetime import datetime

import httpx
import numpy as np
from PIL import Image
from scipy import ndimage

TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_UA = {"User-Agent": "RIIS-Inundation/1.0 (rainfall impact research)"}

_DEM_TTL = 60 * 60 * 24          # terrain is static — cache 24 h
_dem_cache = {}                   # key -> (ts, payload)
_MAX_CACHE = 8                    # keep memory bounded (~3.5 MB/site)


def _px_to_lon(x_px: float, z: int) -> float:
    return x_px / (256 * 2 ** z) * 360.0 - 180.0


def _py_to_lat(y_px: float, z: int) -> float:
    n = math.pi * (1.0 - 2.0 * y_px / (256 * 2 ** z))
    return math.degrees(math.atan(math.sinh(n)))


def _lat_to_py(lat: float, z: int) -> float:
    return (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (256 * 2 ** z)


def _lon_to_px(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (256 * 2 ** z)


async def get_dem(lat: float, lon: float, z: int = 15, n: int = 384) -> dict:
    """n x n elevation grid centred on (lat, lon) at zoom z (cached 24 h).

    Returns dict with dem (n,n) float32 metres, geoaxes, and cell size in m.
    """
    key = (round(lat, 3), round(lon, 3), z, n)
    now = time.time()
    hit = _dem_cache.get(key)
    if hit and now - hit[0] < _DEM_TTL:
        return hit[1]

    cx, cy = _lon_to_px(lon, z), _lat_to_py(lat, z)
    ix0, iy0 = int(cx - n / 2), int(cy - n / 2)
    ix1, iy1 = ix0 + n - 1, iy0 + n - 1
    txs = range(ix0 // 256, ix1 // 256 + 1)
    tys = range(iy0 // 256, iy1 // 256 + 1)

    async def _tile(tx, ty):
        url = TERRAIN_URL.format(z=z, x=tx, y=ty)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=TILE_UA)
            r.raise_for_status()
            return tx, ty, np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.uint8)

    tiles = await asyncio.gather(*(_tile(tx, ty) for tx in txs for ty in tys))

    tx0, ty0 = min(t for t, _, _ in tiles), min(t for _, t, _ in tiles)
    tx1 = max(t for t, _, _ in tiles)
    ty1 = max(t for _, t, _ in tiles)
    canvas = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), dtype=np.uint8)
    for tx, ty, arr in tiles:
        canvas[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = arr

    sub = canvas[iy0 - ty0 * 256: iy0 - ty0 * 256 + n, ix0 - tx0 * 256: ix0 - tx0 * 256 + n]
    dem = (sub[:, :, 0].astype(np.float64) * 256.0
           + sub[:, :, 1].astype(np.float64)
           + sub[:, :, 2].astype(np.float64) / 256.0) - 32768.0

    lons = np.array([_px_to_lon(ix0 + i + 0.5, z) for i in range(n)])
    lats = np.array([_py_to_lat(iy0 + j + 0.5, z) for j in range(n)])
    mid_lat = float(lats[n // 2])
    cell_w = (float(lons[1]) - float(lons[0])) * 111_320.0 * math.cos(math.radians(mid_lat))
    cell_h = abs(float(lats[1]) - float(lats[0])) * 110_540.0

    payload = {
        "dem": dem.astype(np.float32),
        "lats": lats, "lons": lons,
        "cell_w_m": cell_w, "cell_h_m": cell_h,
        "z": z, "n": n, "res_m": round((cell_w + cell_h) / 2, 1),
        "span_km": round(n * (cell_w + cell_h) / 2000, 2),
        "source": "AWS Terrain Tiles (terrarium, SRTM-derived)",
    }
    if len(_dem_cache) >= _MAX_CACHE:
        _dem_cache.pop(next(iter(_dem_cache)))
    _dem_cache[key] = (now, payload)
    return payload


def priority_flood(dem: np.ndarray) -> np.ndarray:
    """Depression-filled surface F (spill elevation per cell), Barnes priority-flood.

    F - dem == depression storage depth at that cell (0 outside pits).
    """
    h, w = dem.shape
    filled = np.full((h, w), -1e9, dtype=np.float64)
    visited = np.zeros((h, w), dtype=bool)
    heap = []

    # Seed with the grid boundary (assumed outlet).
    for x in range(w):
        for y in (0, h - 1):
            if not visited[y, x]:
                visited[y, x] = True
                filled[y, x] = dem[y, x]
                heapq.heappush(heap, (float(dem[y, x]), y, x))
    for y in range(1, h - 1):
        for x in (0, w - 1):
            if not visited[y, x]:
                visited[y, x] = True
                filled[y, x] = dem[y, x]
                heapq.heappush(heap, (float(dem[y, x]), y, x))

    while heap:
        v, y, x = heapq.heappop(heap)
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                visited[ny, nx] = True
                fv = max(float(dem[ny, nx]), v)
                filled[ny, nx] = fv
                heapq.heappush(heap, (fv, ny, nx))
    # Anything unreachable (shouldn't happen with boundary seed) keeps its own elev.
    filled[filled < -1e8] = dem[filled < -1e8]
    return filled


def _wet_rings(wet: np.ndarray):
    """Stitch binary wet mask into closed rings (corner coordinates, col/row)."""
    h, w = wet.shape
    pad = np.zeros((h + 2, w + 2), dtype=bool)
    pad[1:-1, 1:-1] = wet
    edges = {}
    ys, xs = np.nonzero(pad)
    for p, q in zip(ys, xs):
        y, x = int(p), int(q)
        if not pad[y - 1, x]:
            edges[(x, y)] = (x + 1, y)
        if not pad[y, x + 1]:
            edges[(x + 1, y)] = (x + 1, y + 1)
        if not pad[y + 1, x]:
            edges[(x + 1, y + 1)] = (x, y + 1)
        if not pad[y, x - 1]:
            edges[(x, y + 1)] = (x, y)

    rings = []
    while edges:
        start = next(iter(edges))
        ring = [start]
        cur = start
        while True:
            nxt = edges.pop(cur, None)
            if nxt is None:
                break
            ring.append(nxt)
            cur = nxt
            if cur == start:
                break
        if len(ring) >= 5:
            # drop collinear points (axis-aligned staircase -> shorter)
            simp = [ring[0]]
            for i in range(1, len(ring) - 1):
                ax, ay = simp[-1]
                bx, by = ring[i]
                cx, cy = ring[i + 1]
                if (bx - ax) * (cy - by) != (by - ay) * (cx - bx):
                    simp.append(ring[i])
            simp.append(ring[-1])
            rings.append(simp)
    return rings


def simulate(dem_grid: dict, net_mm: float) -> dict:
    """Match net ponding depth against DEM storage and build GeoJSON."""
    dem = dem_grid["dem"].astype(np.float64)
    cell_a = dem_grid["cell_w_m"] * dem_grid["cell_h_m"]
    n_cells = dem.size

    # Depression filling is pure terrain — compute once, reuse from the DEM cache.
    filled = dem_grid.get("filled")
    if filled is None:
        filled = priority_flood(dem)
        dem_grid["filled"] = filled
    pit_storage = float(np.sum(filled - dem) * cell_a)          # m^3 held in depressions
    volume = max(0.0, net_mm / 1000.0) * n_cells * cell_a       # m^3 to place

    mode = "contained"
    if volume <= 0:
        depth = np.zeros_like(dem)
        level = None
        spilled = 0.0
    elif volume <= pit_storage:
        lo, hi = float(dem.min()), float(filled.max())
        for _ in range(50):
            mid = (lo + hi) / 2
            v = float(np.clip(np.minimum(mid, filled) - dem, 0, None).sum() * cell_a)
            if v < volume:
                lo = mid
            else:
                hi = mid
        level = round(hi, 2)
        depth = np.clip(np.minimum(hi, filled) - dem, 0, None)
        spilled = 0.0
    else:
        level = round(float(filled.max()), 2)
        depth = filled - dem
        excess = volume - pit_storage
        sheet = excess / (n_cells * cell_a)
        depth = depth + sheet
        spilled = round(excess, 1)
        mode = "spilling"

    depth = np.where(dem <= 0, 0, depth)          # guard: never flood sea-level voids
    wet = depth >= 0.05                           # ponding threshold 5 cm
    wet_area = float(wet.sum() * cell_a / 1e6)    # km²

    features = []
    if wet.any():
        labels, nlab = ndimage.label(wet, structure=np.ones((3, 3), dtype=int))
        # corner rings use padded coordinates: shift by +1
        for lab in range(1, nlab + 1):
            mask = labels == lab
            cells = int(mask.sum())
            if cells < 3:
                continue
            dmax = float(depth[mask].max())
            if dmax < 0.05:
                continue
            rings = _wet_rings(mask)
            if not rings:
                continue
            coords = []
            for ring in rings:
                ring_geo = []
                for (cx, cy) in ring:
                    gi, gj = cx - 1, cy - 1          # un-pad
                    gi = min(max(gi, 0), dem_grid["n"])   # corner may sit on far edge
                    gj = min(max(gj, 0), dem_grid["n"])
                    lon_c = _corner_val(dem_grid["lons"], gi)
                    lat_c = _corner_val(dem_grid["lats"], gj, lat_axis=True)
                    ring_geo.append([round(float(lon_c), 6), round(float(lat_c), 6)])
                if ring_geo and ring_geo[0] != ring_geo[-1]:
                    ring_geo.append(ring_geo[0])
                coords.append([ring_geo])
            features.append({
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": coords},
                "properties": {
                    "max_depth_m": round(dmax, 2),
                    "mean_depth_m": round(float(depth[mask].mean()), 2),
                    "area_km2": round(cells * cell_a / 1e6, 3),
                    "cells": cells,
                },
            })

    # deepest point
    if depth.max() > 0:
        j, i = np.unravel_index(int(depth.argmax()), depth.shape)
        deepest = {"lat": round(float(dem_grid["lats"][j]), 5),
                   "lon": round(float(dem_grid["lons"][i]), 5),
                   "depth_m": round(float(depth.max()), 2)}
    else:
        deepest = None

    return {
        "grid": {"z": dem_grid["z"], "res_m": dem_grid["res_m"],
                 "span_km": dem_grid["span_km"], "n": dem_grid["n"],
                 "center": [round(float(dem_grid["lats"][dem_grid["n"] // 2]), 5),
                            round(float(dem_grid["lons"][dem_grid["n"] // 2]), 5)]},
        "water": {
            "mode": mode,
            "level_m": level,
            "net_runoff_mm": round(net_mm, 1),
            "volume_m3": round(volume, 0),
            "pit_storage_m3": round(pit_storage, 0),
            "spilled_m3": spilled,
        },
        "stats": {
            "wet_area_km2": round(wet_area, 3),
            "max_depth_m": round(float(depth.max()), 2),
            "mean_depth_m": round(float(depth[wet].mean()), 2) if wet.any() else 0.0,
            "deepest": deepest,
            "ponded_volume_m3": round(float(depth.sum() * cell_a), 0),
        },
        "geojson": {"type": "FeatureCollection", "features": features},
        "source": dem_grid["source"],
        "computed_at": datetime.utcnow().isoformat(),
    }


def _corner_val(axis: np.ndarray, i: int, lat_axis: bool = False) -> float:
    """Value at cell *corner* i (n cells -> n+1 corners; clamp at edges)."""
    n = len(axis)
    if i <= 0:
        step = axis[1] - axis[0]
        return axis[0] - step / 2
    if i >= n:
        step = axis[-1] - axis[-2]
        return axis[-1] + step / 2
    return (axis[i - 1] + axis[i]) / 2
