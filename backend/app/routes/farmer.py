"""Farmer advisory routes — live, location-specific crop advice."""
from fastapi import APIRouter, HTTPException, Query

from app.services.farmer import advisory, CROPS, STAGES
from app.services import roads as R

router = APIRouter(prefix="/api/farmer", tags=["farmer"])


@router.get("/crops")
async def crops():
    return {"crops": [{"key": k, "name": v["name"]} for k, v in CROPS.items()], "stages": STAGES}


@router.get("/advisory")
async def farmer_advisory(lat: float = Query(...), lon: float = Query(...),
                          crop: str = Query("paddy"), stage: str = Query("Vegetative")):
    """Everything a grower needs for this point: live weather, soil moisture, water balance,
    waterlogging, stress, disease pressure, spray / sowing / harvest windows, and ranked advisories."""
    if crop not in CROPS:
        raise HTTPException(status_code=400, detail=f"crop must be one of {list(CROPS)}")
    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"stage must be one of {STAGES}")
    try:
        return await advisory(lat, lon, crop, stage)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/geocode")
async def farmer_geocode(q: str = Query(..., min_length=2)):
    """India-wide place search for the advisory location box (Nominatim proxy, 1 req/s)."""
    try:
        data = await R.nominatim("search", {"format": "json", "q": q, "limit": 6, "countrycodes": "in", "addressdetails": 1})
        return {"results": [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"]), "type": x.get("type"),
                             "district": (x.get("address") or {}).get("state_district"), "state": (x.get("address") or {}).get("state")}
                            for x in data]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"geocoding unavailable: {e}")
