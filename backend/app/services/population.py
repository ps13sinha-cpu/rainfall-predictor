"""Population density from the GHSL population grid (GHS-POP R2023A, epoch 2020, 3 arc-second, ~90 m).

Replaces the district-total-over-a-nominal-cell proxy. Tiles are static 10 x 10 degree GeoTIFFs
published by the JRC (https://ghsl.jrc.ec.europa.eu/download.php?ds=pop), about 20 MB each,
downloaded once into backend/cache/rasters/ and read with rasterio. Licence: CC BY 4.0,
cite "Schiavina M., Freire S., Carioli A., MacManus K. (2023) GHS-POP R2023A, JRC, doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE".

Public API (sync; call through asyncio.to_thread from async code):
    population_density(lat, lon, radius_m=2500) -> dict
"""
import os
import io
import math
import json
import time
import zipfile
import logging
import threading

import numpy as np

log = logging.getLogger("riis.population")

RASTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache", "rasters")
BASE_URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
            "GHS_POP_E2020_GLOBE_R2023A_4326_3ss/V1-0/tiles/")
PRODUCT = "GHS_POP_E2020_GLOBE_R2023A_4326_3ss_V1_0"
LICENCE = "CC BY 4.0 (JRC GHSL)"
SOURCE = "GHS-POP R2023A epoch 2020, 3 arc-second"
CELL_DEG = 3.0 / 3600.0
_locks: dict = {}
_lock_guard = threading.Lock()


def tile_name(lat: float, lon: float) -> str:
    row = int(math.floor((90.0 - lat) / 10.0)) + 1
    col = int(math.floor((lon + 180.0) / 10.0)) + 1
    return f"{PRODUCT}_R{row}_C{col}"


def tile_path(lat: float, lon: float) -> str:
    return os.path.join(RASTER_DIR, tile_name(lat, lon) + ".tif")


def ensure_tile(lat: float, lon: float, download: bool = True) -> str | None:
    """Return the local tile path, downloading the 20 MB zip once if allowed."""
    path = tile_path(lat, lon)
    if os.path.exists(path):
        return path
    if not download:
        return None
    name = tile_name(lat, lon)
    with _lock_guard:
        lock = _locks.setdefault(name, threading.Lock())
    with lock:
        if os.path.exists(path):
            return path
        import httpx
        os.makedirs(RASTER_DIR, exist_ok=True)
        url = BASE_URL + name + ".zip"
        log.info("downloading GHSL tile %s", url)
        try:
            with httpx.Client(timeout=300, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                tifs = [n for n in z.namelist() if n.lower().endswith(".tif")]
                if not tifs:
                    return None
                tmp = path + ".tmp"
                with z.open(tifs[0]) as src, open(tmp, "wb") as dst:
                    dst.write(src.read())
                os.replace(tmp, path)
            return path
        except Exception as e:
            log.warning("GHSL tile download failed for %s: %s", name, e)
            return None


def population_density(lat: float, lon: float, radius_m: float = 2500.0, download: bool = True) -> dict:
    """People per km2 within radius_m of the point, from GHS-POP cell counts.

    Returns {"density_km2", "people_in_radius", "radius_m", "cells", "source", "licence", "tile",
             "fetched_at"} or {"source": "unavailable", "error": ...}.
    """
    path = ensure_tile(lat, lon, download=download)
    if path is None:
        return {"source": "unavailable", "error": "GHSL tile not available locally"}
    try:
        import rasterio
        from rasterio.windows import Window
        with rasterio.open(path) as ds:
            r, c = ds.index(lon, lat)
            half_deg = radius_m / 111_320.0
            half = int(math.ceil(half_deg / CELL_DEG))
            r0, c0 = max(r - half, 0), max(c - half, 0)
            r1, c1 = min(r + half + 1, ds.height), min(c + half + 1, ds.width)
            arr = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float64)
            nodata = ds.nodata
        if nodata is not None:
            arr[arr == nodata] = 0.0
        arr[arr < 0] = 0.0
        # circular mask in cell units (latitude correction on the x axis)
        rows = np.arange(r0, r1)[:, None] - r
        cols = (np.arange(c0, c1)[None, :] - c) * math.cos(math.radians(lat))
        mask = (rows ** 2 + cols ** 2) <= (half ** 2)
        people = float(arr[mask].sum())
        cell_km2 = (CELL_DEG * 111.32) * (CELL_DEG * 111.32 * math.cos(math.radians(lat)))
        area_km2 = float(mask.sum()) * cell_km2
        return {
            "density_km2": round(people / area_km2) if area_km2 > 0 else None,
            "people_in_radius": round(people), "radius_m": radius_m, "cells": int(mask.sum()),
            "source": SOURCE, "licence": LICENCE, "tile": os.path.basename(path),
            "fetched_at": time.time(),
        }
    except Exception as e:
        log.warning("GHSL read failed at %.3f,%.3f: %s", lat, lon, e)
        return {"source": "unavailable", "error": str(e)[:160]}


if __name__ == "__main__":
    import sys
    la, lo = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (13.04, 80.234)
    print(json.dumps(population_density(la, lo), indent=2))
