"""Hyperlocal Rainfall Impact Engine v2.

Predicts what a rainfall event does at a point (a street, a campus, a ward)
from ten factor groups, each fed by a real dataset where one exists:

  1. Meteorological     intensity, total, duration, temporal pattern, multi-model
                        agreement (ECMWF / GFS / ICON), CAPE, wind
  2. Hydrological       live soil moisture (ERA5-Land), antecedent rain, SoilGrids
                        texture, effective infiltration, runoff coefficient
  3. Topographical      HAND, slope, upstream area, closed depressions (SRTM D8)
  4. Drainage           design capacity by context, seasonal blockage, outfall
                        state (tide / river), culverts, embankments, pumps (OSM)
  5. Upstream, coastal  reservoir storage and overflow risk upstream, tide stage
                        (Open-Meteo Marine), river backwater, wetland buffer
  6. Land cover         impervious / green / wetland / farmland mix (OSM)
  7. Exposure           population, building density, critical facilities,
                        underpasses and rail (OSM)
  8. Historical         return period from the 3-year archive, India Flood
                        Inventory district severity and frequency
  9. Real-time          current rain, 15-minute nowcast, humidity, pressure trend
 10. Model              tabular ensemble heavy-rain probability + data confidence

Secondary hazards (landslide, lightning, power, traffic, disease, crops, tree
fall) are reported separately. Static layers are cached on disk per site under
backend/cache/hyperlocal/ so the endpoint stays fast after the first call.
"""
import os
import math
import json
import time
import asyncio
from datetime import datetime, timedelta

import httpx

from app.services import terrain as _terrain
from app.services.flood_history import lookup as flood_lookup
from app.services.inundation import get_dem, priority_flood

# ── Caches ────────────────────────────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache", "hyperlocal")
_geo_cache = {}           # (lat, lon) -> {component: (ts, value)}
_arc_cache = {}
_live_cache = {}
_tide_cache = {}
_elev_cache = {}
_ARC_TTL = 60 * 60 * 6
_LIVE_TTL = 60 * 10
_TIDE_TTL = 60 * 60

TTL = {  # seconds; static layers live on disk
    "terrain": 30 * 86400, "water": 7 * 86400, "soil": 30 * 86400, "landuse": 7 * 86400,
    "infra": 7 * 86400, "coast": 30 * 86400, "district": 30 * 86400, "flood_history": 30 * 86400,
    "elevation": 30 * 86400, "buildings": 7 * 86400,
}
DEGRADED_GRACE = 10 * 60

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
UA = "RIIS-Hyperlocal/2.0 (rainfall impact research)"
ELEV_URL = "https://api.open-meteo.com/v1/elevation"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
SOIL_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

DEFAULT_SOIL = {"texture": "clay_loam", "infiltration_mm_h": 4.0, "runoff_adj": 0.10,
                "porosity": 0.46, "source": "regional_default"}
POROSITY = {"clay": 0.50, "clay_loam": 0.46, "loam": 0.43, "sandy": 0.40}


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── Disk cache ────────────────────────────────────────────────────────────────
def _site_key(lat, lon):
    return f"{round(lat, 3):.3f}_{round(lon, 3):.3f}"


def _disk_load(key):
    try:
        with open(os.path.join(CACHE_DIR, f"{key}.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def _disk_save(key, store):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = os.path.join(CACHE_DIR, f"{key}.json.tmp")
        with open(tmp, "w") as f:
            json.dump({k: {"t": t, "v": v} for k, (t, v) in store.items()}, f)
        os.replace(tmp, os.path.join(CACHE_DIR, f"{key}.json"))
    except Exception as e:
        print(f"[RIIS-hyperlocal] disk cache write failed: {e}")


# ── Overpass ──────────────────────────────────────────────────────────────────
async def _overpass(client: httpx.AsyncClient, ql: str, start: int = 0) -> list:
    """POST an Overpass QL query. `start` picks the first mirror so parallel
    queries from one IP do not all queue on the same server's slots."""
    urls = OVERPASS_URLS[start:] + OVERPASS_URLS[:start]
    for url in urls:
        try:
            r = await client.post(url, data={"data": ql}, headers={"User-Agent": UA})
            if r.status_code == 200:
                return r.json().get("elements", [])
        except Exception:
            continue
    return []


# ── Static fetchers ───────────────────────────────────────────────────────────
async def _fetch_elevation(client, lat, lon) -> dict:
    """Quick centre + ring elevation (fallback when the DEM window is unavailable)."""
    d = 0.01
    pts = [(lat, lon), (lat + d, lon), (lat - d, lon), (lat, lon + d), (lat, lon - d)]
    q = "&".join(f"latitude={p[0]}&longitude={p[1]}" for p in pts)
    try:
        r = await client.get(f"{ELEV_URL}?{q}")
        elevs = r.json().get("elevation", [])
        center, ring = elevs[0], elevs[1:]
        spread = max(ring) - min(ring)
        slope = abs(center - sum(ring) / len(ring)) / 1.1
        return {"elevation_m": round(center, 1), "slope_m_km": round(max(slope, spread / 2.2), 2),
                "lowness": _clamp((max(ring) - center) / 12.0 + (0.3 if center < 60 else 0.0), 0, 1),
                "source": "open_meteo_elevation"}
    except Exception as e:
        return {"elevation_m": 20.0, "slope_m_km": 1.0, "lowness": 0.5, "source": "fallback", "error": str(e)}


async def _fetch_terrain(lat, lon) -> dict:
    """SRTM window -> slope, HAND, upstream area, sinks (see terrain.py)."""
    try:
        grid = await get_dem(lat, lon, z=13, n=256)
        filled = priority_flood(grid["dem"])
        out = _terrain.analyse(grid, filled)
        out["lowness"] = _clamp(math.exp(-out["hand_m"] / 6.0) * 0.7 + 0.3 * out["share_of_neighbours_higher"], 0, 1)
        out["slope_m_km"] = round(math.tan(math.radians(out["slope_deg"])) * 1000, 1)
        return out
    except Exception as e:
        return {"source": "unavailable", "error": str(e)}


async def _fetch_water(client, lat, lon) -> dict:
    ql = ('[out:json][timeout:15];'
          f'(way(around:3000,{lat},{lon})[natural=water];'
          f'relation(around:3000,{lat},{lon})[natural=water];'
          f'way(around:3000,{lat},{lon})[waterway~"river|stream|canal|drain|ditch"];'
          ');out center 60;')
    try:
        elements = await _overpass(client, ql)
        best = None
        counts = {"drain": 0, "waterway": 0, "water": 0, "river": 0}
        for el in elements:
            c = el.get("center") or {}
            if "lat" not in c:
                continue
            dist_m = _haversine_km(lat, lon, c["lat"], c["lon"]) * 1000
            tags = el.get("tags", {})
            if tags.get("natural") == "water":
                kind, bucket = tags.get("water") or "water", "water"
            else:
                kind = tags.get("waterway", "waterway")
                bucket = "drain" if kind in ("drain", "ditch") else "waterway"
                if kind == "river":
                    counts["river"] += 1
            counts[bucket] += 1
            cand = {"distance_m": round(dist_m), "type": kind, "osm_id": el.get("id")}
            if best is None or cand["distance_m"] < best["distance_m"]:
                best = cand
        if best is None:
            return {"distance_m": None, "type": None, "features_3km": 0, "counts": counts, "source": "osm_overpass"}
        best.update({"features_3km": len(elements), "counts": counts, "source": "osm_overpass"})
        return best
    except Exception as e:
        return {"distance_m": None, "type": None, "source": "unavailable", "error": str(e)}


async def _fetch_soil(client, lat, lon) -> dict:
    """SoilGrids texture at the point, or the nearest of a ring of offsets when the
    pixel is NoData (SoilGrids masks built-up land)."""
    for k, (dlat, dlon) in enumerate([(0, 0), (0.01, 0), (-0.01, 0), (0, 0.01), (0, -0.01), (0.02, 0.02), (-0.02, -0.02)]):
        res = await _fetch_soil_point(client, lat + dlat, lon + dlon)
        if res is not None:
            if k:
                res["source"] = "soilgrids_nearby"
                res["offset_km"] = round(_haversine_km(lat, lon, lat + dlat, lon + dlon), 1)
            return res
    return dict(DEFAULT_SOIL)


async def _fetch_soil_point(client, lat, lon):
    try:
        r = await client.get(SOIL_URL, params={"lon": lon, "lat": lat, "property": ["clay", "sand"],
                                               "depth": "0-5cm", "value": "mean"})
        props = r.json().get("properties", {})
        layers = props.get("layers") if isinstance(props, dict) else None
        if isinstance(layers, list):
            layers = {l.get("name"): l for l in layers}
        else:
            layers = props

        def _val(prop):
            try:
                return layers[prop]["depths"][0]["values"]["mean"]
            except (KeyError, IndexError, TypeError):
                return None
        clay, sand = _val("clay"), _val("sand")
        if clay is None and sand is None:
            return None
        clay, sand = (clay or 0) / 10.0, (sand or 0) / 10.0
        if clay >= 40:
            texture, inf, radj = "clay", 2.0, 0.18
        elif sand >= 65:
            texture, inf, radj = "sandy", 18.0, -0.12
        elif clay >= 27:
            texture, inf, radj = "clay_loam", 5.0, 0.10
        else:
            texture, inf, radj = "loam", 9.0, 0.0
        return {"texture": texture, "clay_pct": round(clay, 1), "sand_pct": round(sand, 1),
                "silt_pct": round(max(0.0, 100 - clay - sand), 1), "infiltration_mm_h": inf,
                "runoff_adj": radj, "porosity": POROSITY[texture], "source": "soilgrids"}
    except Exception:
        return None


async def _fetch_landuse(client, lat, lon) -> dict:
    ql = ('[out:json][timeout:15];'
          f'(way(around:2000,{lat},{lon})[landuse];way(around:2000,{lat},{lon})[natural~"wetland|wood|scrub"];'
          ');out tags 200;')
    try:
        elements = await _overpass(client, ql)
        impervious_tags = {"residential", "industrial", "commercial", "retail", "railway", "quarry", "construction"}
        green_tags = {"farmland", "forest", "meadow", "orchard", "vineyard", "greenhouse_horticulture", "grass",
                      "recreation_ground", "wood", "scrub"}
        imp = green = wet = farm = other = 0
        for el in elements:
            t = el.get("tags") or {}
            lu = t.get("landuse", "") or t.get("natural", "")
            if lu == "wetland":
                wet += 1
            elif lu in impervious_tags:
                imp += 1
            elif lu in green_tags:
                green += 1
                farm += lu == "farmland"
            else:
                other += 1
        total = imp + green + wet + other
        if total == 0:
            return {"impervious_pct": 35.0, "green_pct": 45.0, "wetland_pct": 0.0, "farmland_pct": 0.0,
                    "features": 0, "source": "osm_overpass_sparse"}
        return {"impervious_pct": round(100 * imp / total, 1), "green_pct": round(100 * green / total, 1),
                "wetland_pct": round(100 * wet / total, 1), "farmland_pct": round(100 * farm / total, 1),
                "features": total, "source": "osm_overpass"}
    except Exception as e:
        return {"impervious_pct": 40.0, "green_pct": 40.0, "wetland_pct": 0.0, "farmland_pct": 0.0,
                "source": "fallback", "error": str(e)}


async def _fetch_infra(client, lat, lon) -> dict:
    """Drainage structures, barriers, critical facilities and buildings from OSM."""
    ql = ('[out:json][timeout:25];('
          f'way(around:1500,{lat},{lon})[tunnel=culvert];'
          f'way(around:1500,{lat},{lon})[waterway=culvert];'
          f'way(around:1500,{lat},{lon})[embankment=yes];'
          f'way(around:1500,{lat},{lon})[man_made~"dyke|embankment|pumping_station|storm_drain"];'
          f'node(around:1500,{lat},{lon})[man_made~"pumping_station|storm_drain"];'
          f'way(around:1500,{lat},{lon})[highway][tunnel=yes];'
          f'way(around:1500,{lat},{lon})[railway~"rail|light_rail"];'
          f'nwr(around:1500,{lat},{lon})[amenity~"hospital|clinic|school|college|shelter|fire_station|police"];'
          f'nwr(around:1500,{lat},{lon})[power~"substation|plant"];'
          ');out tags center 400;')
    counts = {"culverts": 0, "embankments": 0, "pumping_stations": 0, "storm_drains": 0, "underpasses": 0,
              "railways": 0, "hospitals": 0, "clinics": 0, "schools": 0, "shelters": 0, "emergency_services": 0,
              "substations": 0, "power_plants": 0}
    try:
        for el in await _overpass(client, ql):
            t = el.get("tags") or {}
            if t.get("tunnel") == "culvert" or t.get("waterway") == "culvert":
                counts["culverts"] += 1
            elif t.get("embankment") == "yes" or t.get("man_made") in ("dyke", "embankment"):
                counts["embankments"] += 1
            elif t.get("man_made") == "pumping_station":
                counts["pumping_stations"] += 1
            elif t.get("man_made") == "storm_drain":
                counts["storm_drains"] += 1
            elif t.get("highway") and t.get("tunnel") == "yes":
                counts["underpasses"] += 1
            elif t.get("railway"):
                counts["railways"] += 1
            elif t.get("amenity") == "hospital":
                counts["hospitals"] += 1
            elif t.get("amenity") == "clinic":
                counts["clinics"] += 1
            elif t.get("amenity") in ("school", "college"):
                counts["schools"] += 1
            elif t.get("amenity") == "shelter":
                counts["shelters"] += 1
            elif t.get("amenity") in ("fire_station", "police"):
                counts["emergency_services"] += 1
            elif t.get("power") == "substation":
                counts["substations"] += 1
            elif t.get("power") == "plant":
                counts["power_plants"] += 1
        bq = f'[out:json][timeout:25];way(around:1000,{lat},{lon})[building];out count;'
        els = await _overpass(client, bq)
        buildings = int((els[0].get("tags", {}).get("total", 0)) if els else 0)
        counts["buildings_1km"] = buildings
        counts["buildings_per_km2"] = round(buildings / (math.pi * 1.0 ** 2))
        counts["critical_facilities"] = (counts["hospitals"] + counts["clinics"] + counts["schools"]
                                         + counts["shelters"] + counts["emergency_services"] + counts["substations"])
        counts["radius_m"] = 1500
        counts["source"] = "osm_overpass"
        return counts
    except Exception as e:
        counts.update({"buildings_1km": 0, "buildings_per_km2": 0, "critical_facilities": 0,
                       "source": "unavailable", "error": str(e)})
        return counts


async def _fetch_coast(client, lat, lon) -> dict:
    ql = f'[out:json][timeout:25];way(around:30000,{lat},{lon})[natural=coastline];out geom 40;'
    try:
        els = await _overpass(client, ql, start=1)
        best = None
        for el in els:
            for p in el.get("geometry", []) or []:
                d = _haversine_km(lat, lon, p["lat"], p["lon"])
                if best is None or d < best:
                    best = d
        return {"coast_km": round(best, 2) if best is not None else None, "coastal": best is not None and best <= 15,
                "search_km": 30, "source": "osm_overpass"}
    except Exception as e:
        return {"coast_km": None, "coastal": False, "source": "unavailable", "error": str(e)}


async def _fetch_district(client, lat, lon) -> dict:
    try:
        r = await client.get(NOMINATIM_URL, params={"lat": lat, "lon": lon, "format": "json", "zoom": 10},
                             headers={"User-Agent": UA})
        a = r.json().get("address", {})
        name = (a.get("state_district") or a.get("district") or a.get("county") or a.get("city_district")
                or a.get("city") or a.get("municipality") or a.get("town"))
        return {"district": name, "state": a.get("state"), "locality": a.get("suburb") or a.get("village") or a.get("town"),
                "source": "nominatim"}
    except Exception as e:
        return {"district": None, "state": None, "source": "unavailable", "error": str(e)}


async def _fetch_archive(client, lat, lon) -> dict:
    end = datetime.utcnow().date()
    start = end - timedelta(days=3 * 365)
    try:
        r = await client.get(ARCHIVE_URL, params={"latitude": lat, "longitude": lon, "start_date": start.isoformat(),
                                                  "end_date": end.isoformat(), "daily": "precipitation_sum",
                                                  "timezone": "auto"})
        daily = r.json().get("daily", {})
        vals = [v or 0.0 for v in daily.get("precipitation_sum", [])]
        if not vals:
            raise ValueError("empty archive")
        return {"times": daily.get("time", []), "rain": vals, "source": "open_meteo_archive"}
    except Exception as e:
        return {"times": [], "rain": [], "source": "unavailable", "error": str(e)}


def _is_degraded(name, val) -> bool:
    src = (val or {}).get("source", "")
    if name == "water":
        return val.get("distance_m") is None
    if name == "soil":
        return src == "regional_default"
    if name == "flood_history":
        return val.get("district") is None
    if name == "buildings":
        return src != "osm_overpass"
    return "fallback" in src or "unavailable" in src or "sparse" in src


async def _fetch_osm_bundle(client, lat, lon) -> dict:
    """Water, landuse and infrastructure in ONE Overpass call (Overpass serialises
    parallel queries from the same IP, so one bundled query is several times faster)."""
    ql = ('[out:json][timeout:40];('
          f'way(around:3000,{lat},{lon})[natural=water];'
          f'relation(around:3000,{lat},{lon})[natural=water];'
          f'way(around:3000,{lat},{lon})[waterway~"river|stream|canal|drain|ditch"];'
          f'way(around:2000,{lat},{lon})[landuse];'
          f'way(around:2000,{lat},{lon})[natural~"wetland|wood|scrub"];'
          f'way(around:1500,{lat},{lon})[tunnel=culvert];'
          f'way(around:1500,{lat},{lon})[waterway=culvert];'
          f'way(around:1500,{lat},{lon})[embankment=yes];'
          f'way(around:1500,{lat},{lon})[man_made~"dyke|embankment|pumping_station|storm_drain"];'
          f'node(around:1500,{lat},{lon})[man_made~"pumping_station|storm_drain"];'
          f'way(around:1500,{lat},{lon})[highway][tunnel=yes];'
          f'way(around:1500,{lat},{lon})[railway~"rail|light_rail"];'
          f'nwr(around:1500,{lat},{lon})[amenity~"hospital|clinic|school|college|shelter|fire_station|police"];'
          f'nwr(around:1500,{lat},{lon})[power~"substation|plant"];'
          ');out tags center 600;')
    elements = await _overpass(client, ql, start=0)
    if not elements:
        return {"water": {"distance_m": None, "type": None, "counts": {}, "source": "unavailable"},
                "landuse": {"impervious_pct": 40.0, "green_pct": 40.0, "wetland_pct": 0.0, "farmland_pct": 0.0,
                            "source": "fallback"},
                "infra": {"source": "unavailable"}}
    best, counts = None, {"drain": 0, "waterway": 0, "water": 0, "river": 0}
    impervious_tags = {"residential", "industrial", "commercial", "retail", "railway", "quarry", "construction"}
    green_tags = {"farmland", "forest", "meadow", "orchard", "vineyard", "greenhouse_horticulture", "grass",
                  "recreation_ground", "wood", "scrub"}
    imp = green = wet = farm = other = 0
    inf = {"culverts": 0, "embankments": 0, "pumping_stations": 0, "storm_drains": 0, "underpasses": 0,
           "railways": 0, "hospitals": 0, "clinics": 0, "schools": 0, "shelters": 0, "emergency_services": 0,
           "substations": 0, "power_plants": 0}
    n_water = 0
    for el in elements:
        t = el.get("tags") or {}
        c = el.get("center") or {}
        if t.get("natural") == "water" or t.get("waterway") in ("river", "stream", "canal", "drain", "ditch"):
            n_water += 1
            if "lat" in c:
                dist_m = _haversine_km(lat, lon, c["lat"], c["lon"]) * 1000
                if t.get("natural") == "water":
                    kind, bucket = t.get("water") or "water", "water"
                else:
                    kind = t.get("waterway")
                    bucket = "drain" if kind in ("drain", "ditch") else "waterway"
                    if kind == "river":
                        counts["river"] += 1
                counts[bucket] += 1
                cand = {"distance_m": round(dist_m), "type": kind, "osm_id": el.get("id")}
                if best is None or cand["distance_m"] < best["distance_m"]:
                    best = cand
            continue
        lu = t.get("landuse") or (t.get("natural") if t.get("natural") in ("wetland", "wood", "scrub") else None)
        if lu:
            if lu == "wetland":
                wet += 1
            elif lu in impervious_tags:
                imp += 1
            elif lu in green_tags:
                green += 1
                farm += lu == "farmland"
            else:
                other += 1
            continue
        if t.get("tunnel") == "culvert" or t.get("waterway") == "culvert":
            inf["culverts"] += 1
        elif t.get("embankment") == "yes" or t.get("man_made") in ("dyke", "embankment"):
            inf["embankments"] += 1
        elif t.get("man_made") == "pumping_station":
            inf["pumping_stations"] += 1
        elif t.get("man_made") == "storm_drain":
            inf["storm_drains"] += 1
        elif t.get("highway") and t.get("tunnel") == "yes":
            inf["underpasses"] += 1
        elif t.get("railway"):
            inf["railways"] += 1
        elif t.get("amenity") == "hospital":
            inf["hospitals"] += 1
        elif t.get("amenity") == "clinic":
            inf["clinics"] += 1
        elif t.get("amenity") in ("school", "college"):
            inf["schools"] += 1
        elif t.get("amenity") == "shelter":
            inf["shelters"] += 1
        elif t.get("amenity") in ("fire_station", "police"):
            inf["emergency_services"] += 1
        elif t.get("power") == "substation":
            inf["substations"] += 1
        elif t.get("power") == "plant":
            inf["power_plants"] += 1
    water = (dict(best, features_3km=n_water, counts=counts, source="osm_overpass") if best else
             {"distance_m": None, "type": None, "features_3km": 0, "counts": counts, "source": "osm_overpass"})
    total = imp + green + wet + other
    landuse = ({"impervious_pct": 35.0, "green_pct": 45.0, "wetland_pct": 0.0, "farmland_pct": 0.0, "features": 0,
                "source": "osm_overpass_sparse"} if total == 0 else
               {"impervious_pct": round(100 * imp / total, 1), "green_pct": round(100 * green / total, 1),
                "wetland_pct": round(100 * wet / total, 1), "farmland_pct": round(100 * farm / total, 1),
                "features": total, "source": "osm_overpass"})
    inf["critical_facilities"] = (inf["hospitals"] + inf["clinics"] + inf["schools"] + inf["shelters"]
                                  + inf["emergency_services"] + inf["substations"])
    inf["radius_m"] = 1500
    inf["source"] = "osm_overpass"
    return {"water": water, "landuse": landuse, "infra": inf}


async def _fetch_buildings(client, lat, lon) -> dict:
    try:
        els = await _overpass(client, f'[out:json][timeout:25];way(around:1000,{lat},{lon})[building];out count;', start=2)
        n = int((els[0].get("tags", {}).get("total", 0)) if els else 0)
        return {"buildings_1km": n, "buildings_per_km2": round(n / math.pi),
                "source": "osm_overpass" if els else "unavailable"}
    except Exception as e:
        return {"buildings_1km": 0, "buildings_per_km2": 0, "source": "unavailable", "error": str(e)}


_inflight = {}   # site key -> {component: asyncio.Task}


async def get_geofactors(lat: float, lon: float, force: bool = False, budget: float | None = 25.0,
                         district_hint: str | None = None) -> dict:
    """All static / slowly changing factors for a point, cached per component
    in memory and on disk.

    `budget` caps how long the caller waits for fresh components; fetchers still
    running at the deadline keep going in the background and their results land
    in the cache for the next call. `budget=None` waits for everything.
    """
    key = _site_key(lat, lon)
    now = time.time()
    store = _geo_cache.get(key)
    if store is None:
        store = {k: (v["t"], v["v"]) for k, v in _disk_load(key).items()}
        _geo_cache[key] = store
    pending = _inflight.setdefault(key, {})

    def fresh(name):
        hit = store.get(name)
        if not hit or force:
            return False
        ttl = min(TTL[name], DEGRADED_GRACE) if _is_degraded(name, hit[1]) else TTL[name]
        return now - hit[0] < ttl

    client = httpx.AsyncClient(timeout=45)
    jobs = {}
    if not fresh("terrain") and "terrain" not in pending:
        jobs["terrain"] = _fetch_terrain(lat, lon)
    if not fresh("elevation") and "elevation" not in pending:
        jobs["elevation"] = _fetch_elevation(client, lat, lon)

    # Overpass limits concurrent queries per IP, so the three OSM calls run one after another
    async def _osm_chain():
        out = {}
        if not (fresh("water") and fresh("landuse") and fresh("infra")):
            out.update(await _fetch_osm_bundle(client, lat, lon))
        if not fresh("coast"):
            out["coast"] = await _fetch_coast(client, lat, lon)
        if not fresh("buildings"):
            out["buildings"] = await _fetch_buildings(client, lat, lon)
        return out
    if "osm" not in pending and not (fresh("water") and fresh("landuse") and fresh("infra")
                                     and fresh("coast") and fresh("buildings")):
        jobs["osm"] = _osm_chain()
    for name, fn in (("soil", _fetch_soil), ("district", _fetch_district)):
        if not fresh(name) and name not in pending:
            jobs[name] = fn(client, lat, lon)

    def _absorb(name, res):
        flat = res if name == "osm" else {name: res}
        for n, v in flat.items():
            if _is_degraded(n, v) and store.get(n) and not _is_degraded(n, store[n][1]):
                continue  # keep last good value
            store[n] = (time.time(), v)
        if "infra" in store and "buildings" in store:
            inf = dict(store["infra"][1])
            inf.update({k: v for k, v in store["buildings"][1].items() if k.startswith("buildings")})
            store["infra"] = (store["infra"][0], inf)
        if "district" in store and not fresh("flood_history"):
            dname = (store["district"][1] or {}).get("district") or district_hint
            try:
                store["flood_history"] = (time.time(), flood_lookup(dname))
            except Exception as e:
                store["flood_history"] = (time.time(), {"source": "unavailable", "error": str(e)})

    for name, coro in jobs.items():
        task = asyncio.create_task(coro)
        pending[name] = task

        def _done(t, name=name):
            pending.pop(name, None)
            try:
                res = t.result()
            except asyncio.CancelledError:
                res = None
            except Exception as e:
                print(f"[RIIS-hyperlocal] {name} failed for {key}: {e}")
                res = None
            if res is not None:
                _absorb(name, res)
                _disk_save(key, store)
            if not pending:
                asyncio.ensure_future(client.aclose())
        task.add_done_callback(_done)

    if pending:
        waiting = list(pending.values())
        if budget is None:
            await asyncio.gather(*waiting, return_exceptions=True)
        else:
            await asyncio.wait(waiting, timeout=budget)
        await asyncio.sleep(0)  # let done-callbacks run
    elif jobs == {}:
        await client.aclose()

    if not fresh("flood_history"):
        dname = (store.get("district", (0, {}))[1] or {}).get("district") or district_hint
        try:
            store["flood_history"] = (now, flood_lookup(dname))
        except Exception as e:
            store["flood_history"] = (now, {"source": "unavailable", "error": str(e)})
    _disk_save(key, store)

    payload = {name: store[name][1] for name in store}
    payload.setdefault("elevation", {"elevation_m": 20.0, "slope_m_km": 1.0, "lowness": 0.5, "source": "fallback"})
    payload.setdefault("terrain", {"source": "unavailable"})
    payload.setdefault("water", {"distance_m": None, "type": None, "counts": {}, "source": "unavailable"})
    payload.setdefault("soil", dict(DEFAULT_SOIL))
    payload.setdefault("landuse", {"impervious_pct": 40.0, "green_pct": 40.0, "wetland_pct": 0.0,
                                   "farmland_pct": 0.0, "source": "fallback"})
    payload.setdefault("infra", {"source": "unavailable"})
    payload.setdefault("coast", {"coast_km": None, "coastal": False, "source": "unavailable"})
    payload.setdefault("district", {"district": None, "source": "unavailable"})
    payload.setdefault("flood_history", {"source": "unavailable"})
    payload["fetched_at"] = datetime.utcnow().isoformat()
    payload["still_loading"] = sorted(pending.keys())
    return payload


# ── Dynamic fetchers ──────────────────────────────────────────────────────────
async def get_antecedent(lat: float, lon: float) -> dict:
    key = _site_key(lat, lon)
    now = time.time()
    hit = _arc_cache.get(key)
    if hit and now - hit[0] < _ARC_TTL:
        arc = hit[1]
    else:
        async with httpx.AsyncClient(timeout=15) as client:
            arc = await _fetch_archive(client, lat, lon)
        if arc.get("rain") or not hit:
            _arc_cache[key] = (now, arc)
        else:
            arc = hit[1]
    rain = arc.get("rain", [])
    if not rain:
        return {"rain_1d_mm": 0, "rain_3d_mm": 0, "rain_7d_mm": 0, "rain_30d_mm": 0, "saturation_pct": 50,
                "return_days": 0, "series": [], "source": arc.get("source", "unavailable")}
    r1, r3, r7, r30 = (round(sum(rain[-k:]), 1) for k in (1, 3, 7, 30))
    sat = _clamp(round(100 * (0.55 * min(r30, 200) / 200 + 0.30 * min(r7, 60) / 60 + 0.15 * min(r3, 25) / 25) + 8), 5, 100)
    return {"rain_1d_mm": r1, "rain_3d_mm": r3, "rain_7d_mm": r7, "rain_30d_mm": r30,
            "saturation_pct": sat, "return_days": len(rain), "series": rain, "source": arc.get("source")}


async def get_live_conditions(lat: float, lon: float) -> dict:
    """Current weather, next-24h forecast from three NWP models, CAPE, live soil
    moisture, pressure trend and the 15-minute nowcast, in two Open-Meteo calls."""
    key = _site_key(lat, lon)
    now = time.time()
    hit = _live_cache.get(key)
    if hit and now - hit[0] < _LIVE_TTL:
        return hit[1]
    out = {"source": "open_meteo_forecast"}
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            a, b = await asyncio.gather(
                client.get(FORECAST_URL, params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,"
                               "wind_direction_10m,pressure_msl,cloud_cover",
                    "hourly": "precipitation,precipitation_probability,cape,soil_moisture_0_to_7cm,"
                              "soil_moisture_7_to_28cm,pressure_msl",
                    "minutely_15": "precipitation", "forecast_minutely_15": 24,
                    "past_hours": 6, "forecast_days": 2, "timezone": "auto"}),
                client.get(FORECAST_URL, params={
                    "latitude": lat, "longitude": lon, "hourly": "precipitation",
                    "models": "ecmwf_ifs025,gfs_seamless,icon_seamless", "forecast_days": 1, "timezone": "auto"}),
            )
            wx, mm = a.json(), b.json()
            cur = wx.get("current", {})
            h = wx.get("hourly", {})
            times = h.get("time", [])
            # index of the current hour inside the hourly arrays (past_hours shifts the start)
            ct = (cur.get("time") or "")[:13]
            i0 = next((i for i, t in enumerate(times) if t[:13] == ct), 0)

            def seg(name, a_, b_):
                vals = (h.get(name) or [])[i0 + a_:i0 + b_]
                return [v for v in vals if v is not None]
            p6 = seg("precipitation", 0, 6)
            p24 = seg("precipitation", 0, 24)
            past6 = seg("precipitation", -6, 0)
            probs = seg("precipitation_probability", 0, 6)
            cape6 = seg("cape", 0, 6)
            sm0 = seg("soil_moisture_0_to_7cm", 0, 1)
            sm1 = seg("soil_moisture_7_to_28cm", 0, 1)
            pr_now = seg("pressure_msl", 0, 1)
            pr_m3 = seg("pressure_msl", -3, -2)
            m15 = [v for v in (wx.get("minutely_15", {}).get("precipitation") or [])[:8] if v is not None]
            models = {}
            mh = mm.get("hourly", {})
            mt = mh.get("time", [])
            j0 = next((i for i, t in enumerate(mt) if t[:13] == ct), 0)
            for k, v in mh.items():
                if k.startswith("precipitation_"):
                    vals = [x for x in v[j0:j0 + 6] if x is not None]
                    models[k.replace("precipitation_", "")] = round(sum(vals), 1)
            mvals = list(models.values())
            out.update({
                "current_rain": cur.get("precipitation", 0) or 0,
                "temperature": cur.get("temperature_2m", 28),
                "humidity": cur.get("relative_humidity_2m", 70),
                "wind_speed": cur.get("wind_speed_10m", 0) or 0,
                "wind_gusts": cur.get("wind_gusts_10m", 0) or 0,
                "wind_direction": cur.get("wind_direction_10m"),
                "pressure": cur.get("pressure_msl"),
                "cloud_cover": cur.get("cloud_cover"),
                "probability": round(sum(probs) / len(probs)) if probs else 40,
                "next_6h_rain": round(sum(p6), 1),
                "past_6h_rain": round(sum(past6), 1),
                "next_24h_rain": round(sum(p24), 1),
                "peak_intensity": round(max(p24), 1) if p24 else 0.0,
                "nowcast_2h_mm": round(sum(m15), 2) if m15 else None,
                "cape_max_6h": round(max(cape6)) if cape6 else None,
                "soil_moisture_0_7": round(sm0[0], 3) if sm0 else None,
                "soil_moisture_7_28": round(sm1[0], 3) if sm1 else None,
                "pressure_trend_3h": round(pr_now[0] - pr_m3[0], 1) if pr_now and pr_m3 else None,
                "models_next_6h": models,
                "model_spread_mm": round(max(mvals) - min(mvals), 1) if mvals else None,
                "model_agreement": (round(sum(1 for v in mvals if v >= 5) / len(mvals), 2) if mvals else None),
            })
        except Exception as e:
            out.update({"source": "unavailable", "error": str(e), "current_rain": 0, "temperature": 28,
                        "humidity": 70, "wind_speed": 0, "probability": 40, "next_6h_rain": 0.0,
                        "peak_intensity": 0.0, "models_next_6h": {}})
    if out.get("source") != "unavailable" or not hit:
        _live_cache[key] = (now, out)
    return out


async def get_tide(lat: float, lon: float, coastal: bool) -> dict:
    if not coastal:
        return {"applicable": False, "source": "not_coastal"}
    key = _site_key(lat, lon)
    now = time.time()
    hit = _tide_cache.get(key)
    if hit and now - hit[0] < _TIDE_TTL:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(MARINE_URL, params={"latitude": lat, "longitude": lon,
                                                     "hourly": "sea_level_height_msl", "forecast_days": 2,
                                                     "timezone": "auto"})
        h = r.json().get("hourly", {})
        times, vals = h.get("time", []), h.get("sea_level_height_msl", [])
        nowt = datetime.now().strftime("%Y-%m-%dT%H")
        i0 = next((i for i, t in enumerate(times) if t[:13] == nowt), 0)
        win = [(t, v) for t, v in zip(times[i0:i0 + 12], vals[i0:i0 + 12]) if v is not None]
        if not win:
            raise ValueError("no tide data")
        hi = max(win, key=lambda x: x[1])
        out = {"applicable": True, "now_m": round(win[0][1], 2), "max_next_6h_m": round(max(v for _, v in win[:6]), 2),
               "next_high_m": round(hi[1], 2), "next_high_time": hi[0], "rising": len(win) > 1 and win[1][1] > win[0][1],
               "source": "open_meteo_marine"}
        _tide_cache[key] = (now, out)
        return out
    except Exception as e:
        return {"applicable": True, "now_m": None, "source": "unavailable", "error": str(e)}


async def get_upstream_reservoirs(lat: float, lon: float, point_elev: float, radius_km: float = 40.0) -> dict:
    """Reservoirs from the RIIS database that sit upstream (higher) within radius."""
    try:
        from app.database import async_session
        from app.models import Reservoir
        from sqlalchemy import select
        async with async_session() as db:
            rows = (await db.execute(select(Reservoir))).scalars().all()
    except Exception as e:
        return {"reservoirs": [], "source": "unavailable", "error": str(e)}
    near = [r for r in rows if r.lat and r.lon and _haversine_km(lat, lon, r.lat, r.lon) <= radius_km]
    if not near:
        return {"reservoirs": [], "count": 0, "upstream_count": 0, "radius_km": radius_km, "source": "riis_db"}
    need = [(round(r.lat, 3), round(r.lon, 3)) for r in near if (round(r.lat, 3), round(r.lon, 3)) not in _elev_cache]
    if need:
        try:
            q = "&".join(f"latitude={a}&longitude={b}" for a, b in need)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{ELEV_URL}?{q}")
            for pt, e in zip(need, r.json().get("elevation", [])):
                _elev_cache[pt] = e
        except Exception:
            pass
    out = []
    for r in near:
        e = _elev_cache.get((round(r.lat, 3), round(r.lon, 3)))
        upstream = e is None or e >= (point_elev or 0) - 3
        storage = 100 * (r.current_mcft or 0) / max(r.capacity_mcft or 1, 1)
        out.append({"name": r.name, "code": r.code, "distance_km": round(_haversine_km(lat, lon, r.lat, r.lon), 1),
                    "elevation_m": e, "upstream": upstream, "storage_pct": round(storage, 1),
                    "overflow_prob": round(float(r.overflow_prob or 0), 2), "inflow_cms": r.inflow_cms,
                    "outflow_cms": r.outflow_cms, "risk_class": r.risk_class})
    out.sort(key=lambda x: x["distance_km"])
    return {"reservoirs": out, "count": len(out), "upstream_count": sum(1 for x in out if x["upstream"]),
            "source": "riis_db"}


# ── Scoring ───────────────────────────────────────────────────────────────────
CATEGORY_WEIGHTS = {
    "Meteorological": 0.22, "Hydrological": 0.14, "Topographical": 0.13, "Drainage": 0.13,
    "Upstream & Coastal": 0.08, "Land cover": 0.04, "Exposure": 0.07, "Historical": 0.07,
    "Real-time": 0.07, "Model": 0.05,
}
PATTERN_PEAK = {"steady": 1.0, "front": 1.6, "back": 1.4, "burst": 2.2}
BLOCKAGE_BY_MONTH = {1: 0.9, 2: 0.9, 3: 0.9, 4: 0.9, 5: 0.85, 6: 0.85, 7: 0.85, 8: 0.95, 9: 0.95,
                     10: 0.9, 11: 0.8, 12: 0.7}


def _pattern_shape(pattern: str, hours: int) -> list:
    """Hourly share of the event total for a temporal pattern (sums to 1)."""
    if hours <= 1:
        return [1.0]
    if pattern == "front":
        w = [math.exp(-2.5 * i / hours) for i in range(hours)]
    elif pattern == "back":
        w = [math.exp(-2.5 * (hours - 1 - i) / hours) for i in range(hours)]
    elif pattern == "burst":
        w = [1.0 if i < max(1, hours // 3) else 0.15 for i in range(hours)]
    else:
        w = [1.0] * hours
    tot = sum(w)
    return [x / tot for x in w]


def _return_period(series, event_mm):
    if not series or event_mm <= 0:
        return None, None
    exceed = sum(1 for v in series if v >= event_mm)
    years = len(series) / 365.0
    if exceed == 0:
        return years, f">{years:.0f}y (record max in {years:.0f}y series)"
    rp = years / exceed
    if rp < 1:
        return round(rp, 2), f"~{rp * 12:.0f} months"
    return round(rp, 1), f"~{rp:.1f} year{'s' if rp >= 2 else ''}"


def compute_impact(geo: dict, ant: dict, weather: dict, scenario: dict, population: int,
                   ml_score=None, upstream: dict | None = None, tide: dict | None = None,
                   ml_detail: dict | None = None) -> dict:
    """Combine every factor group into an impact score, inundation forecast and
    secondary hazards. All inputs come from the fetchers above."""
    terr = geo.get("terrain") or {}
    terr_ok = terr.get("source", "unavailable") not in ("unavailable",)
    elev = geo["elevation"]
    water = geo["water"]
    soil = geo["soil"]
    land = geo["landuse"]
    infra = geo.get("infra") or {}
    coast = geo.get("coast") or {}
    fh = geo.get("flood_history") or {}
    upstream = upstream or {}
    tide = tide or {}

    rain_event = scenario.get("rainfall_mm", 0.0) or 0.0
    duration_h = scenario.get("duration_h", 6.0) or 6.0
    pattern = scenario.get("pattern") or "steady"
    mean_intensity = scenario.get("intensity_mm_h") or (rain_event / max(duration_h, 0.5))
    peak_intensity = mean_intensity * PATTERN_PEAK.get(pattern, 1.0)
    cape = weather.get("cape_max_6h") or 0
    if cape >= 1500:
        peak_intensity *= 1.15

    impervious = land.get("impervious_pct", 40.0)
    green = land.get("green_pct", 40.0)
    wetland = land.get("wetland_pct", 0.0)
    farmland = land.get("farmland_pct", 0.0)
    elev_m = terr.get("elevation_m", elev.get("elevation_m", 20.0)) if terr_ok else elev.get("elevation_m", 20.0)
    slope_deg = terr.get("slope_deg", math.degrees(math.atan(elev.get("slope_m_km", 1.0) / 1000))) if terr_ok \
        else math.degrees(math.atan(elev.get("slope_m_km", 1.0) / 1000))
    slope_reg = terr.get("slope_deg_regional", slope_deg) if terr_ok else slope_deg
    hand = terr.get("hand_m") if terr_ok else None
    lowness = terr.get("lowness", elev.get("lowness", 0.5)) if terr_ok else elev.get("lowness", 0.5)
    upstream_km2 = terr.get("upstream_area_km2", 0.0) if terr_ok else 0.0
    in_sink = bool(terr.get("in_closed_depression")) if terr_ok else False
    sink_depth = terr.get("depression_depth_m", 0.0) if terr_ok else 0.0
    no_outlet = bool(terr.get("no_outlet_in_window")) if terr_ok else False
    water_dist = water.get("distance_m")
    wcounts = water.get("counts") or {}
    infiltration = soil.get("infiltration_mm_h", 5.0)
    porosity = soil.get("porosity", 0.46)
    prob = weather.get("probability", 0) or 0
    wind = weather.get("wind_speed", 0) or 0
    gusts = weather.get("wind_gusts", wind) or wind
    humidity = weather.get("humidity", 70) or 70
    month = datetime.now().month

    # ── 1. Meteorological ─────────────────────────────────────────────────────
    intensity_score = _clamp(peak_intensity / 45.0, 0, 1) * 100           # 45 mm/h = 100 (cloudburst territory)
    acc_score = _clamp(rain_event / 200.0, 0, 1) * 100                   # IMD "extremely heavy" >= 204.5 mm/day
    dur_score = (1 - math.exp(-duration_h / 12.0)) * 100
    agreement = weather.get("model_agreement")
    forecast_24 = weather.get("next_24h_rain") or 0.0
    scenario_driven = rain_event > max(2.0 * forecast_24, 10.0)
    if scenario_driven:
        prob_score = 55.0   # a what-if event carries its own assumption; the live forecast neither confirms nor denies it
    else:
        prob_score = _clamp(prob, 0, 100) if agreement is None else _clamp(0.5 * prob + 50 * agreement, 0, 100)
    wind_score = _clamp(gusts / 80.0, 0, 1) * 100
    cape_score = _clamp(cape / 3000.0, 0, 1) * 100
    met_score = (0.40 * intensity_score + 0.22 * acc_score + 0.13 * prob_score + 0.10 * dur_score
                 + 0.08 * wind_score + 0.07 * cape_score)

    # ── 2. Hydrological ───────────────────────────────────────────────────────
    sm = weather.get("soil_moisture_0_7")
    sat_est = ant.get("saturation_pct", 45)
    if sm is not None:
        sat_live = _clamp(100 * sm / porosity, 0, 100)
        sat = round(0.65 * sat_live + 0.35 * sat_est)
        sat_source = f"ERA5-Land soil moisture {sm:.2f} m³/m³ (porosity {porosity})"
    else:
        sat = sat_est
        sat_source = "antecedent rain estimate"
    inf_eff = infiltration * (1 - 0.8 * sat / 100.0)
    slope_runoff = _clamp(slope_deg / 15.0, 0, 1) * 0.10
    runoff_c = _clamp(0.15 + 0.50 * (impervious / 100.0) + 0.22 * (sat / 100.0) + soil.get("runoff_adj", 0)
                      + slope_runoff - 0.05 * (wetland / 100.0), 0.05, 0.95)
    hydro_score = _clamp(100 * (0.40 * (sat / 100.0) + 0.35 * runoff_c + 0.25 * (1 - _clamp(inf_eff / 20.0, 0, 1))), 0, 100)

    # ── 3. Topographical ──────────────────────────────────────────────────────
    hand_score = 100 * math.exp(-hand / 8.0) if hand is not None else lowness * 100
    flat_score = (1 - _clamp(slope_deg / 8.0, 0, 1)) * 100
    sink_score = _clamp(60 + 40 * min(sink_depth / 2.0, 1), 0, 100) if in_sink else (50.0 if no_outlet else 0.0)
    up_score = _clamp(math.log10(1 + upstream_km2 * 10) / 1.5, 0, 1) * 100
    low_elev_score = _clamp((80 - elev_m) / 80.0, 0, 1) * 100
    water_score = 40.0 if water_dist is None else 100 * math.exp(-water_dist / 1800.0)
    topo_score = (0.30 * hand_score + 0.20 * flat_score + 0.15 * sink_score + 0.15 * up_score
                  + 0.10 * low_elev_score + 0.10 * water_score)

    # ── 4. Drainage & infrastructure ──────────────────────────────────────────
    drains = wcounts.get("drain", 0) + infra.get("storm_drains", 0)
    waterways = wcounts.get("waterway", 0)
    bpk = infra.get("buildings_per_km2", 0) or 0
    urban_index = _clamp(bpk / 800.0, 0, 1)
    design_cap = 12 + 18 * urban_index + (10 if drains >= 3 else 4 * min(drains, 2)) + (10 if infra.get("storm_drains", 0) else 0)
    design_cap = _clamp(design_cap, 10, 65)
    blockage = BLOCKAGE_BY_MONTH.get(month, 0.9)
    outfall = 1.0
    outfall_notes = []
    if tide.get("applicable") and tide.get("now_m") is not None:
        t_now, t_max = tide["now_m"], tide.get("max_next_6h_m", tide["now_m"])
        if t_max >= 0.4:
            outfall *= 0.6
            outfall_notes.append(f"high tide {t_max:+.2f} m within 6 h blocks sea outfalls")
        elif t_max >= 0.15:
            outfall *= 0.8
            outfall_notes.append(f"tide {t_max:+.2f} m slows outfalls")
    river_near = water.get("type") in ("river", "canal") and water_dist is not None and water_dist < 1500
    if river_near and ant.get("rain_7d_mm", 0) >= 80:
        outfall *= 0.8
        outfall_notes.append(f"{water.get('type')} likely high after {ant.get('rain_7d_mm')} mm in 7 days")
    structural = 1.0
    barriers = infra.get("embankments", 0) + infra.get("railways", 0)
    if barriers and infra.get("culverts", 0) <= 1:
        structural *= 0.85
        outfall_notes.append(f"{barriers} embankment/rail line(s) with {infra.get('culverts', 0)} mapped culvert(s)")
    if infra.get("pumping_stations", 0):
        structural *= 1.15
    if in_sink or no_outlet:
        structural *= 0.7
        outfall_notes.append("closed depression: gravity drainage has no outlet")
    engineered_cap = _clamp(design_cap * blockage * outfall * structural, 4.0, 80.0)
    # natural conveyance: steep ground and ground well above its drainage line shed water without pipes
    # nonlinear: under ~2 degrees ground is hydraulically flat; a 10-degree hillside sheds ~30 mm/h
    natural_cap = 1.5 * max(slope_reg - 2.0, 0.0) ** 1.3 + (6.0 * _clamp((hand - 2.0) / 10.0, 0, 1) if hand is not None else 0.0)
    if in_sink or no_outlet:
        natural_cap *= 0.3
    effective_cap = _clamp(engineered_cap + natural_cap, 4.0, 90.0)
    cap_score = (1 - _clamp(effective_cap / 45.0, 0, 1)) * 100
    underpass_flag = 100.0 if infra.get("underpasses", 0) else 0.0
    barrier_flag = 100.0 if barriers and infra.get("culverts", 0) <= 1 else 0.0
    infra_score = _clamp(0.40 * impervious + 0.40 * cap_score + 0.10 * underpass_flag + 0.10 * barrier_flag, 0, 100)

    # ── 5. Upstream & coastal ─────────────────────────────────────────────────
    res_score, res_note = 0.0, None
    for rv in upstream.get("reservoirs", []):
        if not rv.get("upstream"):
            continue
        s = (0.6 * _clamp(rv["storage_pct"] / 100.0, 0, 1) + 0.4 * _clamp(rv["overflow_prob"], 0, 1)) * 100
        s *= math.exp(-rv["distance_km"] / 25.0)
        if s > res_score:
            res_score, res_note = s, f"{rv['name']} {rv['storage_pct']:.0f}% full, {rv['distance_km']} km upstream"
    tide_score = 0.0
    if tide.get("applicable") and tide.get("now_m") is not None:
        tide_score = _clamp((tide.get("max_next_6h_m", 0) + 0.5) / 1.5, 0, 1) * 100
        tide_score *= math.exp(-(coast.get("coast_km") or 0) / 10.0)
    river_score = 60.0 if river_near and ant.get("rain_7d_mm", 0) >= 80 else (25.0 if river_near else 0.0)
    buffer = 15.0 if wetland > 0 else 0.0
    upstream_score = _clamp(0.50 * res_score + 0.35 * tide_score + 0.15 * river_score - buffer, 0, 100)

    # ── 6. Land cover ─────────────────────────────────────────────────────────
    landcover_score = _clamp(0.6 * impervious + 0.4 * (100 - green) - 10 * (wetland > 0) + 5 * (farmland > 30), 0, 100)

    # ── 7. Exposure ───────────────────────────────────────────────────────────
    cell_km2 = 25.0
    # district population over a typical district area, lifted by mapped building density where OSM has coverage
    density = population / 2000.0 if population else 2000.0
    if bpk:
        density = max(density, bpk * 4.5)
    density_score = _clamp(density / 12000.0, 0, 1) * 100
    building_score = _clamp(bpk / 1500.0, 0, 1) * 100
    crit = infra.get("critical_facilities", 0) or 0
    crit_score = _clamp(crit / 8.0, 0, 1) * 100
    transport_score = _clamp((infra.get("underpasses", 0) * 2 + infra.get("railways", 0)) / 4.0, 0, 1) * 100
    expo_score = 0.45 * density_score + 0.30 * building_score + 0.15 * crit_score + 0.10 * transport_score

    # ── 8. Historical ─────────────────────────────────────────────────────────
    rp_years, rp_label = _return_period(ant.get("series", []), rain_event)
    rp_score = acc_score * 0.5 if rp_years is None else _clamp(100 * (math.log10(max(rp_years, 0.05) + 1) / 1.7), 0, 100)
    fpi = fh.get("flood_prone_index")
    hist_score = rp_score if fpi is None else 0.5 * rp_score + 50 * fpi

    # ── 9. Real-time ──────────────────────────────────────────────────────────
    cur_rain = weather.get("current_rain", 0.0) or 0.0
    now2h = weather.get("nowcast_2h_mm")
    nowcast = _clamp(((now2h or 0) / 2.0) / 25.0, 0, 1) * 100 if now2h is not None else \
        (_clamp(mean_intensity / 40.0, 0, 1) * 100 if cur_rain > 0 else _clamp(mean_intensity / 80.0, 0, 1) * 100)
    hum_score = _clamp((humidity - 55) / 45.0, 0, 1) * 100
    ptrend = weather.get("pressure_trend_3h")
    press_score = _clamp((-ptrend) / 4.0, 0, 1) * 100 if ptrend is not None else 30.0
    rt_score = _clamp(0.5 * nowcast + 0.25 * hum_score + 0.25 * press_score, 0, 100)

    # ── 10. Model + data confidence ───────────────────────────────────────────
    comps = {"terrain": terr_ok, "water": water_dist is not None, "soil": soil.get("source") == "soilgrids",
             "landuse": land.get("source") == "osm_overpass", "infra": infra.get("source") == "osm_overpass",
             "soil_moisture": sm is not None, "forecast": weather.get("source") == "open_meteo_forecast",
             "archive": bool(ant.get("series")), "flood_history": fh.get("district") is not None,
             "coast": coast.get("source") == "osm_overpass"}
    confidence = round(100 * sum(comps.values()) / len(comps))
    model_score = ml_score if ml_score is not None else met_score * 0.8

    cat_scores = {
        "Meteorological": met_score, "Hydrological": hydro_score, "Topographical": topo_score,
        "Drainage": infra_score, "Upstream & Coastal": upstream_score, "Land cover": landcover_score,
        "Exposure": expo_score, "Historical": hist_score, "Real-time": rt_score, "Model": model_score,
    }
    # ── Inundation forecast: hourly water balance ────────────────────────────
    # inflow = runoff from local rain (shaped by the temporal pattern) plus water routed from upstream;
    # outflow = effective drainage capacity, decaying as the receiving system (drains, tanks, river, sea) fills.
    hours = max(1, int(math.ceil(duration_h)))
    shape = _pattern_shape(pattern, hours)
    upstream_mult = 1.0 + 1.0 * _clamp(math.log10(1 + upstream_km2 * 10) / 1.5, 0, 1)   # up to x2 for large catchments
    stored, cum_in, peak_store, hours_ponded, series = 0.0, 0.0, 0.0, 0.0, []
    for h_i in range(hours + 24):  # keep draining for a day after the rain stops
        rain_h = rain_event * shape[h_i] if h_i < hours else 0.0
        inflow = rain_h * runoff_c * upstream_mult
        cap_h = effective_cap / (1 + cum_in / 120.0)   # receiving drains / tanks / river fill as the event proceeds
        outflow = min(stored + inflow, cap_h)
        stored = max(0.0, stored + inflow - outflow)
        cum_in += inflow
        peak_store = max(peak_store, stored)
        if stored >= 15:
            hours_ponded += 1
        series.append(round(stored, 1))
    pond_fraction = _clamp(0.2 + 0.45 * (hand_score / 100.0) + (0.15 if in_sink else 0.0), 0.2, 0.8)
    depth_mean = _clamp(peak_store / 1000.0 / pond_fraction, 0, 5.0)
    depth_max = _clamp(depth_mean * 2.0 + (0.5 * min(sink_depth, 2.0) if in_sink else 0.0), 0, 8.0)
    excess_mm_h = max(0.0, peak_intensity - effective_cap)
    runoff_mm = rain_event * runoff_c
    area = _clamp(pond_fraction * cell_km2 * _clamp(peak_store / 60.0, 0, 1) * (0.6 + 0.4 * lowness), 0, cell_km2)
    structures = round(area * (bpk * 0.7 if bpk else (500 + 900 * impervious / 100.0)))
    roads_km = round(area * (3.5 + 5.5 * impervious / 100.0), 1)
    people = round(density * area * (0.35 + 0.65 * expo_score / 100.0))
    peak_runoff_cms = round(runoff_c * peak_intensity * max(area, 0.25) / 3.6, 1)
    drainage_sat = _clamp(round(100 * peak_intensity / effective_cap), 0, 400)
    ponding_hours = round(hours_ponded, 1)
    # ── Composite: vulnerability-weighted factor groups blended with the simulated inundation severity ──
    severity = _clamp(100 * (0.5 * min(peak_store / 120.0, 1) + 0.3 * min(depth_max / 0.8, 1)
                             + 0.2 * min(ponding_hours / 36.0, 1)), 0, 100)
    weighted = {k: CATEGORY_WEIGHTS[k] * v for k, v in cat_scores.items()}
    total = sum(weighted.values())
    impact_score = _clamp(round(0.6 * total + 0.4 * severity), 0, 100)
    if rain_event < 0.5 and mean_intensity < 0.5:
        impact_score = min(impact_score, 18)
    cls = "extreme" if impact_score >= 75 else "high" if impact_score >= 50 else "mod" if impact_score >= 25 else "safe"
    evac = "Tier-1 Active" if impact_score >= 75 else "Standby" if impact_score >= 50 else "Monitor" if impact_score >= 25 else "None"

    sources = {
        "Meteorological": f"peak {peak_intensity:.0f} mm/h ({pattern}) · models agree {agreement if agreement is not None else 'n/a'} · CAPE {cape}",
        "Hydrological": f"saturation {sat}% ({sat_source}) · C={runoff_c:.2f} · {soil.get('texture')} · infiltration {inf_eff:.1f} mm/h",
        "Topographical": (f"HAND {hand} m · slope {slope_deg:.1f}° · upstream {upstream_km2} km²"
                          + (" · closed depression" if in_sink else "")) if terr_ok else f"elev {elev_m} m (DEM unavailable)",
        "Drainage": f"effective {effective_cap:.0f} mm/h (engineered {engineered_cap:.0f} + natural {natural_cap:.0f}) · design {design_cap:.0f} · blockage x{blockage} · outfall x{outfall:.2f} · drains {drains} culverts {infra.get('culverts', 0)}",
        "Upstream & Coastal": " · ".join(filter(None, [res_note, (f"tide {tide.get('now_m'):+.2f} m" if tide.get('now_m') is not None else None),
                                                       ("river nearby" if river_near else None), ("wetland buffer" if wetland > 0 else None)])) or "no upstream reservoir, inland",
        "Land cover": f"impervious {impervious}% · green {green}% · wetland {wetland}% · farmland {farmland}%",
        "Exposure": f"pop {population:,} in 25 km² · {bpk} buildings/km² · {crit} critical facilities",
        "Historical": (rp_label or "archive pending") + (f" · IFI {fh.get('district')} DFSI {fh.get('dfsi')} ({fh.get('district_events')} events)" if fh.get("district") else ""),
        "Real-time": f"now {cur_rain} mm/h · next 2h {now2h if now2h is not None else 'n/a'} mm · RH {humidity}% · Δp {ptrend if ptrend is not None else 'n/a'} hPa/3h",
        "Model": (f"{ml_detail.get('model_name', 'ML')} heavy-rain p={ml_detail.get('heavy_rain_probability')}" if ml_detail else "heuristic")
                 + f" · data confidence {confidence}%",
    }
    shares = {k: round(weighted[k] / total * 100, 1) if total > 0 else 0 for k in CATEGORY_WEIGHTS}
    categories = [{"name": k, "score": round(cat_scores[k]), "weight": CATEGORY_WEIGHTS[k], "share_pct": shares[k],
                   "source": sources[k]} for k in CATEGORY_WEIGHTS]

    # ── Secondary hazards ─────────────────────────────────────────────────────
    hazards = []

    def hz(name, level, reason):
        hazards.append({"hazard": name, "level": level, "reason": reason})
    if slope_reg >= 15 and (sat >= 60 or rain_event >= 100):
        hz("landslide", "high", f"regional slope {slope_reg:.0f}° with saturation {sat}% and {rain_event:.0f} mm event")
    elif slope_reg >= 10 and rain_event >= 50:
        hz("landslide", "moderate", f"regional slope {slope_reg:.0f}°, {rain_event:.0f} mm event")
    if cape >= 2000:
        hz("lightning", "high", f"CAPE {cape} J/kg")
    elif cape >= 1000:
        hz("lightning", "moderate", f"CAPE {cape} J/kg")
    if infra.get("substations", 0) and (hand is not None and hand < 3 or in_sink) and peak_intensity > 25:
        hz("power_outage", "high", f"{infra['substations']} substation(s) in low ground, {peak_intensity:.0f} mm/h")
    elif gusts >= 50 or (infra.get("substations", 0) and excess_mm_h > 0):
        hz("power_outage", "moderate", f"gusts {gusts:.0f} km/h" if gusts >= 50 else "drainage exceeded near substation")
    if gusts >= 60 and green >= 25:
        hz("tree_fall", "high", f"gusts {gusts:.0f} km/h over {green:.0f}% green cover")
    elif gusts >= 40 and green >= 25:
        hz("tree_fall", "moderate", f"gusts {gusts:.0f} km/h")
    if infra.get("underpasses", 0) and excess_mm_h > 0:
        hz("traffic", "high", f"{infra['underpasses']} underpass(es) will fill first; intensity exceeds drainage")
    elif peak_intensity >= 20:
        hz("traffic", "moderate", f"{peak_intensity:.0f} mm/h reduces visibility, hydroplaning likely")
    if ponding_hours >= 72:
        hz("waterborne_disease", "high", f"standing water ~{ponding_hours:.0f} h; outbreaks typically 1 to 2 weeks after")
    elif ponding_hours >= 24:
        hz("waterborne_disease", "moderate", f"standing water ~{ponding_hours:.0f} h")
    if farmland > 0 and (rain_event >= 100 or ant.get("rain_3d_mm", 0) + rain_event >= 150):
        hz("crop_waterlogging", "high" if rain_event >= 150 else "moderate",
           f"farmland {farmland:.0f}% of area, {rain_event:.0f} mm on {ant.get('rain_3d_mm', 0)} mm in 3 days")
    if res_score >= 60:
        hz("reservoir_release", "high" if res_score >= 80 else "moderate", res_note or "upstream reservoir near full")

    # life-safety hazards lift the class even where ponding is shallow (hill towns, downstream of a full dam)
    lift = 0
    for h in hazards:
        if h["hazard"] in ("landslide", "reservoir_release"):
            lift = max(lift, 60 if h["level"] == "high" else 35)
    if lift > impact_score:
        impact_score = lift
        cls = "extreme" if impact_score >= 75 else "high" if impact_score >= 50 else "mod" if impact_score >= 25 else "safe"
        evac = "Tier-1 Active" if impact_score >= 75 else "Standby" if impact_score >= 50 else "Monitor" if impact_score >= 25 else "None"

    # ── Advisories ────────────────────────────────────────────────────────────
    adv = []
    if runoff_c >= 0.6:
        adv.append(f"High runoff coefficient (C={runoff_c:.2f}): {int(round(runoff_c * 100))}% of rainfall becomes surface runoff — expect rapid street ponding.")
    if sat >= 65:
        adv.append(f"Soil is {sat}% saturated ({sat_source}; {ant.get('rain_7d_mm', 0)} mm in the last 7 days) — infiltration is nearly exhausted.")
    elif sat <= 30:
        adv.append(f"Soil saturation is low ({sat}%) — soils absorb the first ~{int(rain_event * 0.4)} mm before runoff begins.")
    if hand is not None and hand < 2:
        adv.append(f"Point sits {hand:.1f} m above the nearest drainage line — among the first places to flood and the last to drain.")
    if in_sink:
        adv.append(f"Terrain is a closed depression {sink_depth:.1f} m deep — water will pond until pumped or infiltrated.")
    if upstream_km2 >= 1.0:
        adv.append(f"{upstream_km2:.1f} km² drains through this point — flooding depends on upstream rain, not only local rain.")
    for n in outfall_notes:
        adv.append("Drainage outfall limited: " + n + ".")
    if drainage_sat > 100:
        adv.append(f"Peak intensity {peak_intensity:.0f} mm/h exceeds effective drainage capacity ({effective_cap:.0f} mm/h) — surcharging expected for ~{ponding_hours:.0f} h.")
    if water_dist is not None and water_dist < 1000:
        adv.append(f"Nearest {water.get('type', 'water body')} is {water_dist} m away — backwater may slow outfalls.")
    if agreement is not None and agreement < 0.5 and (weather.get("model_spread_mm") or 0) >= 5 and not scenario_driven:
        adv.append(f"Forecast models disagree (spread {weather.get('model_spread_mm')} mm in 6 h) — treat timing as uncertain.")
    if rp_label:
        adv.append(f"A {rain_event:.0f} mm/{duration_h:.0f} h event is a {rp_label} occurrence in the 3-year record.")
    if fh.get("district") and (fh.get("dfsi") or 0) >= 15:
        adv.append(f"{fh['district']} district ranks high on the India Flood Inventory severity index (DFSI {fh['dfsi']}, {fh.get('district_events')} recorded floods).")

    return {
        "engine_version": "2.0",
        "location": {
            "lat": scenario.get("lat"), "lon": scenario.get("lon"),
            "district": (geo.get("district") or {}).get("district"), "state": (geo.get("district") or {}).get("state"),
            "elevation_m": elev_m, "slope_deg": round(slope_deg, 2), "slope_m_km": round(math.tan(math.radians(slope_deg)) * 1000, 1),
            "hand_m": hand, "upstream_area_km2": upstream_km2, "closed_depression": in_sink,
            "nearest_water_m": water_dist, "water_type": water.get("type"), "coast_km": coast.get("coast_km"),
            "soil_texture": soil.get("texture"), "infiltration_mm_h": infiltration,
            "impervious_pct": impervious, "green_pct": green, "wetland_pct": wetland, "farmland_pct": farmland,
            "population_cell": population, "buildings_per_km2": bpk,
        },
        "antecedent": {k: v for k, v in ant.items() if k != "series"},
        "runoff": {"coefficient": round(runoff_c, 2), "runoff_mm": round(runoff_mm, 1),
                   "drainage_capacity_mm_h": round(effective_cap, 1), "peak_runoff_cms": peak_runoff_cms},
        "drainage": {"design_capacity_mm_h": round(design_cap, 1), "blockage_factor": blockage,
                     "outfall_factor": round(outfall, 2), "structural_factor": round(structural, 2),
                     "engineered_capacity_mm_h": round(engineered_cap, 1), "natural_conveyance_mm_h": round(natural_cap, 1),
                     "effective_capacity_mm_h": round(effective_cap, 1), "notes": outfall_notes,
                     "mapped": {k: infra.get(k, 0) for k in ("culverts", "embankments", "railways", "pumping_stations",
                                                             "storm_drains", "underpasses")},
                     "drains_mapped": drains, "waterways_mapped": waterways},
        "categories": categories,
        "impact": {"score": impact_score, "class": cls, "confidence_pct": confidence, "return_period": rp_label,
                   "peak_intensity_mm_h": round(peak_intensity, 1), "pattern": pattern,
                   "factor_composite": round(total), "inundation_severity": round(severity)},
        "inundation": {"depth_mean_m": round(depth_mean, 2), "depth_max_m": round(depth_max, 2),
                       "area_km2": round(area, 2), "structures": structures, "roads_km": roads_km,
                       "people_exposed": people, "drainage_saturation_pct": drainage_sat,
                       "ponding_hours": ponding_hours, "peak_storage_mm": round(peak_store, 1),
                       "ponded_fraction": round(pond_fraction, 2), "storage_series_mm": series[:hours + 12],
                       "evacuation": evac},
        "secondary_hazards": hazards,
        "factors": {"terrain": terr if terr_ok else None, "soil": soil,
                    "soil_moisture": {"m3_m3_0_7cm": sm, "m3_m3_7_28cm": weather.get("soil_moisture_7_28"),
                                      "saturation_pct": sat, "basis": sat_source},
                    "landuse": land, "infrastructure": infra, "coast": coast, "tide": tide,
                    "upstream_reservoirs": upstream, "flood_history": fh,
                    "forecast_models": {"next_6h_mm": weather.get("models_next_6h"), "spread_mm": weather.get("model_spread_mm"),
                                        "agreement": agreement, "cape_max_6h": cape,
                                        "pressure_trend_3h": ptrend, "nowcast_2h_mm": now2h}},
        "data_confidence": comps,
        "advisories": adv,
        "computed_at": datetime.utcnow().isoformat(),
    }
