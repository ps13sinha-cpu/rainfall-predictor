"""DEM-driven inundation endpoint — real flood extent polygons for the simulator."""
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.inundation import get_dem, simulate
from app.services.hyperlocal import get_geofactors, get_antecedent

router = APIRouter(prefix="/api/hyperlocal", tags=["hyperlocal"])


@router.get("/inundation")
async def inundation(
    lat: float = Query(...),
    lon: float = Query(...),
    rainfall_mm: float = Query(60.0, ge=0, le=600),
    duration_h: float = Query(3.0, ge=0.5, le=72),
    intensity_mm_h: float = Query(None, ge=0, le=300),
):
    """Real DEM-based flood extent for a what-if rainfall scenario.

    Runoff and drainage capacity come from the hyperlocal geofactors
    (soil infiltration, impervious surface, mapped drains, antecedent
    saturation); the water is then placed on a real 4.6 m elevation grid
    with depression filling, and wet cells are stitched to GeoJSON.
    """
    try:
        # Warm independent lookups in parallel — this path used to serialize
        # geofactors (Overpass) + archive + DEM and took ~40s cold.
        geo_t = asyncio.create_task(get_geofactors(lat, lon))
        ant_t = asyncio.create_task(get_antecedent(lat, lon))
        dem_t = asyncio.create_task(get_dem(lat, lon))
        geo, ant, grid = await asyncio.gather(geo_t, ant_t, dem_t)

        soil = geo["soil"]
        land = geo["landuse"]
        water = geo["water"]

        impervious = land.get("impervious_pct", 40.0)
        sat = ant.get("saturation_pct", 45)
        drains = (water.get("counts") or {}).get("drain", 0)
        waterways = (water.get("counts") or {}).get("waterway", 0)

        # Same runoff model as the impact engine (kept consistent on purpose)
        runoff_c = max(0.05, min(0.95,
            0.18 + 0.55 * (impervious / 100.0)
            + 0.22 * (sat / 100.0) + soil.get("runoff_adj", 0)))
        drainage_cap = max(8.0, min(45.0,
            30.0 + 3.0 * drains - 0.06 * impervious * 30 / 100 * 10))

        runoff_mm = rainfall_mm * runoff_c
        drainage_mm = drainage_cap * duration_h
        net_mm = max(0.0, runoff_mm - drainage_mm)

        result = simulate(grid, net_mm)
        result["forcing"] = {
            "rainfall_mm": rainfall_mm,
            "duration_h": duration_h,
            "intensity_mm_h": intensity_mm_h or round(rainfall_mm / max(duration_h, 0.5), 1),
            "runoff_coefficient": round(runoff_c, 2),
            "runoff_mm": round(runoff_mm, 1),
            "drainage_capacity_mm_h": round(drainage_cap, 1),
            "drainage_removed_mm": round(min(runoff_mm, drainage_mm), 1),
            "net_ponding_mm": round(net_mm, 1),
            "saturation_pct": sat,
        }
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
