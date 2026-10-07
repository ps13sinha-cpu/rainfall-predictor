"""DEM-driven inundation endpoint — real flood extent polygons for the simulator."""
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.inundation import get_dem, simulate, net_ponding_mm
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

        # Shared runoff / drainage derivation (services/inundation.net_ponding_mm),
        # also used by the Safe Routes scorer so the two cannot drift.
        f = net_ponding_mm(geo, ant, rainfall_mm, duration_h)
        result = simulate(grid, f["net_mm"])
        result["forcing"] = {
            "rainfall_mm": rainfall_mm,
            "duration_h": duration_h,
            "intensity_mm_h": intensity_mm_h or round(rainfall_mm / max(duration_h, 0.5), 1),
            "runoff_coefficient": f["runoff_coefficient"],
            "runoff_mm": f["runoff_mm"],
            "drainage_capacity_mm_h": f["drainage_capacity_mm_h"],
            "drainage_removed_mm": f["drainage_removed_mm"],
            "net_ponding_mm": f["net_ponding_mm"],
            "saturation_pct": f["saturation_pct"],
        }
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
