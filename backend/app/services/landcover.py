"""Land-cover shares from ESA WorldCover 2021 (v200, 10 m), read as a window straight from the
public cloud-optimised GeoTIFFs on S3 (no download: one HTTP range read of about 1 to 4 s per site).

Replaces the OSM-landuse-polygon proxy for impervious cover, which fell back to a default outside
cities. Licence: CC BY 4.0, cite "Zanaga, D. et al. (2022) ESA WorldCover 10 m 2021 v200,
doi:10.5281/zenodo.7254221".

Classes: 10 tree, 20 shrub, 30 grassland, 40 cropland, 50 built-up, 60 bare, 70 snow, 80 water,
90 herbaceous wetland, 95 mangroves, 100 moss. Built-up is the impervious proxy.

Public API (sync; call through asyncio.to_thread from async code):
    landcover_shares(lat, lon, radius_m=1500) -> dict
"""
import os
import math
import json
import time
import logging

import numpy as np

log = logging.getLogger("riis.landcover")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache", "landcover")
S3 = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
SOURCE = "ESA WorldCover 10 m 2021 v200"
LICENCE = "CC BY 4.0 (ESA WorldCover)"
TTL_S = 180 * 24 * 3600          # the product is static; refresh twice a year in case of reissue
CELL_DEG = 1.0 / 12000.0          # 10 m tiles are 1/12000 degree


def tile_name(lat: float, lon: float) -> str:
    lat3 = int(math.floor(lat / 3.0)) * 3
    lon3 = int(math.floor(lon / 3.0)) * 3
    ns = "N" if lat3 >= 0 else "S"
    ew = "E" if lon3 >= 0 else "W"
    return f"ESA_WorldCover_10m_2021_v200_{ns}{abs(lat3):02d}{ew}{abs(lon3):03d}_Map.tif"


def _cache_path(lat: float, lon: float, radius_m: float) -> str:
    return os.path.join(CACHE_DIR, f"{lat:.3f}_{lon:.3f}_{int(radius_m)}.json")


def landcover_shares(lat: float, lon: float, radius_m: float = 1500.0, use_cache: bool = True) -> dict:
    """Percent of the circle around the point in each WorldCover class, plus the engine's derived shares.

    Returns {"impervious_pct", "green_pct", "wetland_pct", "farmland_pct", "water_pct", "bare_pct",
             "classes": {code: pct}, "pixels", "radius_m", "source", "licence", "tile", "fetched_at"}
    or {"source": "unavailable", "error": ...}.
    """
    cp = _cache_path(lat, lon, radius_m)
    if use_cache and os.path.exists(cp):
        try:
            with open(cp) as f:
                hit = json.load(f)
            if time.time() - hit.get("fetched_at", 0) < TTL_S:
                return hit
        except Exception:
            pass
    try:
        import rasterio
        from rasterio.windows import Window
        env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                           GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_MAX_RETRY="2", GDAL_HTTP_RETRY_DELAY="1")
        url = "/vsicurl/" + S3 + tile_name(lat, lon)
        with env, rasterio.open(url) as ds:
            r, c = ds.index(lon, lat)
            half = int(math.ceil(radius_m / 111_320.0 / CELL_DEG))
            r0, c0 = max(r - half, 0), max(c - half, 0)
            r1, c1 = min(r + half + 1, ds.height), min(c + half + 1, ds.width)
            arr = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
        rows = np.arange(r0, r1)[:, None] - r
        cols = (np.arange(c0, c1)[None, :] - c) * math.cos(math.radians(lat))
        mask = (rows ** 2 + cols ** 2) <= (half ** 2)
        vals = arr[mask]
        vals = vals[vals > 0]
        n = int(vals.size)
        if n == 0:
            return {"source": "unavailable", "error": "no valid WorldCover pixels (tile edge?)"}
        counts = {int(k): int(v) for k, v in zip(*np.unique(vals, return_counts=True))}
        pct = {k: round(100.0 * v / n, 1) for k, v in counts.items()}
        g = lambda *ks: round(sum(pct.get(k, 0.0) for k in ks), 1)
        out = {
            "impervious_pct": g(50), "green_pct": g(10, 20, 30, 90), "wetland_pct": g(90, 95),
            "farmland_pct": g(40), "water_pct": g(80), "bare_pct": g(60),
            "classes": pct, "pixels": n, "radius_m": radius_m,
            "source": SOURCE, "licence": LICENCE, "tile": tile_name(lat, lon), "fetched_at": time.time(),
        }
        if use_cache:
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                tmp = cp + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(out, f)
                os.replace(tmp, cp)
            except Exception:
                pass
        return out
    except Exception as e:
        log.warning("WorldCover read failed at %.3f,%.3f: %s", lat, lon, e)
        return {"source": "unavailable", "error": str(e)[:160]}


if __name__ == "__main__":
    import sys
    la, lo = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (13.04, 80.234)
    print(json.dumps(landcover_shares(la, lo), indent=2))
