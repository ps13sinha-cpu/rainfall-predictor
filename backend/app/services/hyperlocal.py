"""Hyperlocal Rainfall Impact Engine.

Predicts the impact of rainfall at hyperlocal resolution (e.g. Potheri)
considering all major factor categories:

  1. Meteorological   — intensity, duration, accumulation, probability, wind
  2. Hydrological     — antecedent saturation, soil infiltration, runoff coeff, drainage
  3. Topographical    — elevation, slope, distance to water, lowness (HAND proxy)
  4. Infrastructure   — impervious surface, drainage network density
  5. Socioeconomic    — population exposure in the impacted cell
  6. Historical       — return period of the event vs archive record
  7. Real-time        — live conditions nowcast blend
  8. Model            — XGBoost model score + data confidence

All external lookups (elevation, OSM Overpass, SoilGrids, Open-Meteo archive)
are cached in-process so the endpoint stays fast.
"""
import math
import time
import asyncio
from datetime import datetime, timedelta

import httpx

# ── Cache ─────────────────────────────────────────────────────────────────────
_GEO_TTL = 60 * 30        # static geofactors: 30 min
_ARC_TTL = 60 * 60 * 6    # archive series: 6 h
_geo_cache = {}           # key -> (timestamp, payload)
_arc_cache = {}           # key -> (timestamp, payload)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_UA = "RIIS-Hyperlocal/1.0 (rainfall impact research)"


async def _overpass(client: httpx.AsyncClient, ql: str) -> list:
    """POST an Overpass QL query, trying mirrors in order."""
    for url in OVERPASS_URLS:
        try:
            r = await client.post(url, data={"data": ql},
                                  headers={"User-Agent": OVERPASS_UA})
            if r.status_code == 200:
                return r.json().get("elements", [])
        except Exception:
            continue
    return []
ELEV_URL = "https://api.open-meteo.com/v1/elevation"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOIL_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

# Regional soil fallback (Tamil Nadu plains / Potheri area: clayey alluvial)
DEFAULT_SOIL = {
    "texture": "clay_loam",
    "infiltration_mm_h": 4.0,
    "runoff_adj": 0.10,
    "source": "regional_default",
}


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── Live geofactor fetchers ───────────────────────────────────────────────────
async def _fetch_elevation(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    """Center + 4 cardinal points ~1.1 km away → elevation + slope."""
    d = 0.01  # ~1.1 km
    pts = [(lat, lon), (lat + d, lon), (lat - d, lon), (lat, lon + d), (lat, lon - d)]
    q = "&".join(f"latitude={p[0]}&longitude={p[1]}" for p in pts)
    try:
        r = await client.get(f"{ELEV_URL}?{q}")
        elevs = r.json().get("elevation", [])
        if not elevs:
            raise ValueError("empty")
        center = elevs[0]
        ring = elevs[1:]
        # slope: max elevation difference over ~1.1 km → m/km
        spread = max(ring) - min(ring)
        slope = abs(center - sum(ring) / len(ring)) / 1.1  # m per km toward ring avg
        return {
            "elevation_m": round(center, 1),
            "ring_min_m": round(min(ring), 1),
            "ring_max_m": round(max(ring), 1),
            "slope_m_km": round(max(slope, spread / 2.2), 2),
            "lowness": _clamp((max(ring) - center) / 12.0 + (1.0 if center < 60 else 0.0) * 0.3, 0, 1),
            "source": "open_meteo_elevation",
        }
    except Exception as e:
        return {"elevation_m": 20.0, "slope_m_km": 1.0, "lowness": 0.5,
                "source": "fallback", "error": str(e)}


async def _fetch_water(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    """Nearest water body / waterway from OSM Overpass (3 km search radius)."""
    ql = (
        '[out:json][timeout:15];'
        f'(way(around:3000,{lat},{lon})[natural=water];'
        f'relation(around:3000,{lat},{lon})[natural=water];'
        f'way(around:3000,{lat},{lon})[waterway~"river|stream|canal|drain"];'
        ');out center 40;'
    )
    try:
        elements = await _overpass(client, ql)
        best = None
        count_by_type = {"drain": 0, "waterway": 0, "water": 0}
        for el in elements:
            c = el.get("center") or {}
            if "lat" not in c:
                continue
            dist_m = _haversine_km(lat, lon, c["lat"], c["lon"]) * 1000
            tags = el.get("tags", {})
            if tags.get("natural") == "water":
                kind = tags.get("water") or "water"
                bucket = "water"
            else:
                kind = tags.get("waterway", "waterway")
                bucket = "drain" if kind == "drain" else "waterway"
            count_by_type[bucket] += 1
            cand = {"distance_m": round(dist_m), "type": kind, "osm_id": el.get("id")}
            if best is None or cand["distance_m"] < best["distance_m"]:
                best = cand
        if best is None:
            return {"distance_m": None, "type": None, "features_3km": 0,
                    "counts": count_by_type, "source": "osm_overpass"}
        best["features_3km"] = len(elements)
        best["counts"] = count_by_type
        best["source"] = "osm_overpass"
        return best
    except Exception as e:
        return {"distance_m": None, "type": None, "source": "unavailable", "error": str(e)}


async def _fetch_soil(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    """SoilGrids: sand/clay fractions → infiltration class. Falls back to regional default."""
    try:
        r = await client.get(
            SOIL_URL,
            params={"lon": lon, "lat": lat, "property": ["clay", "sand"],
                    "depth": "0-5cm", "value": "mean"},
        )
        layers = r.json().get("properties", {})
        clay = sand = None
        for lay in layers.values() if isinstance(layers, dict) else []:
            pass
        # SoilGrids v2 response shape: {"properties": {"clay": {"depths": [{"values": {"mean": v}}]}}}
        def _val(prop):
            try:
                return layers[prop]["depths"][0]["values"]["mean"]
            except (KeyError, IndexError, TypeError):
                return None
        clay, sand = _val("clay"), _val("sand")
        if clay is None and sand is None:
            raise ValueError("no soil values")
        clay /= 10.0  # cg/kg → %
        sand /= 10.0
        silt = max(0.0, 100.0 - clay - sand)
        # Texture class (simplified USDA) + infiltration estimate
        if clay >= 40:
            texture, inf, radj = "clay", 2.0, 0.18
        elif sand >= 65:
            texture, inf, radj = "sandy", 18.0, -0.12
        elif clay >= 27:
            texture, inf, radj = "clay_loam", 5.0, 0.10
        else:
            texture, inf, radj = "loam", 9.0, 0.0
        return {"texture": texture, "clay_pct": round(clay, 1), "sand_pct": round(sand, 1),
                "silt_pct": round(silt, 1), "infiltration_mm_h": inf,
                "runoff_adj": radj, "source": "soilgrids"}
    except Exception:
        return dict(DEFAULT_SOIL)


async def _fetch_landuse(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    """OSM landuse mix within 2 km → impervious / green fractions."""
    ql = (
        '[out:json][timeout:15];'
        f'way(around:2000,{lat},{lon})[landuse];'
        'out tags 120;'
    )
    try:
        elements = await _overpass(client, ql)
        impervious_tags = {"residential", "industrial", "commercial", "retail",
                           "railway", "quarry", "construction"}
        green_tags = {"farmland", "forest", "meadow", "orchard", "vineyard",
                      "greenhouse_horticulture", "grass", "recreation_ground"}
        imp = green = other = 0
        for el in elements:
            lu = (el.get("tags") or {}).get("landuse", "")
            if lu in impervious_tags:
                imp += 1
            elif lu in green_tags:
                green += 1
            else:
                other += 1
        total = imp + green + other
        if total == 0:
            return {"impervious_pct": 35.0, "green_pct": 45.0, "features": 0,
                    "source": "osm_overpass_sparse"}
        return {
            "impervious_pct": round(100 * imp / total, 1),
            "green_pct": round(100 * green / total, 1),
            "features": total,
            "source": "osm_overpass",
        }
    except Exception as e:
        return {"impervious_pct": 40.0, "green_pct": 40.0, "source": "fallback",
                "error": str(e)}


async def _fetch_archive(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    """3 years of daily precipitation → antecedent rain + return-period series."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=3 * 365)
    try:
        r = await client.get(ARCHIVE_URL, params={
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "precipitation_sum", "timezone": "auto",
        })
        daily = r.json().get("daily", {})
        times = daily.get("time", [])
        vals = [v or 0.0 for v in daily.get("precipitation_sum", [])]
        if not vals:
            raise ValueError("empty archive")
        return {"times": times, "rain": vals, "source": "open_meteo_archive"}
    except Exception as e:
        return {"times": [], "rain": [], "source": "unavailable", "error": str(e)}


async def get_geofactors(lat: float, lon: float, force: bool = False) -> dict:
    """All static/semi-static geospatial factors for a point (cached per component).

    Each component (elevation / water / soil / landuse) carries its own TTL so a
    transient Overpass 504 doesn't evict the components that did succeed — the
    previous all-or-nothing cache re-fetched everything on every failure.
    """
    key = (round(lat, 3), round(lon, 3))
    now = time.time()
    store = _geo_cache.setdefault(key, {})

    async with httpx.AsyncClient(timeout=12) as client:
        jobs = {}
        specs = {
            "elevation": (15 * 60, lambda: _fetch_elevation(client, lat, lon)),
            "water":     (6 * 60 * 60, lambda: _fetch_water(client, lat, lon)),
            "soil":      (6 * 60 * 60, lambda: _fetch_soil(client, lat, lon)),
            "landuse":   (6 * 60 * 60, lambda: _fetch_landuse(client, lat, lon)),
        }
        for name, (ttl, fn) in specs.items():
            hit = store.get(name)
            fresh = False
            if hit and not force:
                # Degraded hits only buy a short grace period before we retry.
                eff_ttl = min(ttl, 10 * 60) if _is_degraded(name, hit[1]) else ttl
                fresh = now - hit[0] < eff_ttl
            if not fresh:
                jobs[name] = fn()
        if jobs:
            results = await asyncio.gather(*jobs.values(), return_exceptions=True)
            for name, res in zip(jobs, results):
                if isinstance(res, Exception):
                    continue  # keep last-good value if any
                if _is_degraded(name, res):
                    # Don't clobber a good cached value with a degraded one.
                    if not (store.get(name) and not _is_degraded(name, store[name][1])):
                        store[name] = (now, res)
                else:
                    store[name] = (now, res)

    payload = {
        name: store[name][1]
        for name in ("elevation", "water", "soil", "landuse")
        if name in store
    }
    # Sensible fills for anything still missing.
    payload.setdefault("elevation", {"elevation_m": 20.0, "slope_m_km": 1.0, "lowness": 0.5, "source": "fallback"})
    payload.setdefault("water", {"distance_m": None, "type": None, "source": "unavailable"})
    payload.setdefault("soil", dict(DEFAULT_SOIL))
    payload.setdefault("landuse", {"impervious_pct": 40.0, "green_pct": 40.0, "source": "fallback"})
    payload["fetched_at"] = datetime.utcnow().isoformat()
    return payload


def _is_degraded(name: str, val: dict) -> bool:
    """True when a component came back as a degraded/fallback result."""
    src = (val or {}).get("source", "")
    if name == "water":
        return val.get("distance_m") is None
    if name == "elevation":
        return src != "open_meteo_elevation"
    if name == "landuse":
        return src != "osm_overpass"
    if name == "soil":
        return src == "regional_default"   # acceptable, but prefer SoilGrids when reachable
    return False


async def get_antecedent(lat: float, lon: float) -> dict:
    """Recent rainfall history: 3/7/30-day sums + saturation estimate (cached 6h)."""
    key = (round(lat, 3), round(lon, 3))
    now = time.time()
    hit = _arc_cache.get(key)
    if hit and now - hit[0] < _ARC_TTL:
        arc = hit[1]
    else:
        async with httpx.AsyncClient(timeout=12) as client:
            arc = await _fetch_archive(client, lat, lon)
        _arc_cache[key] = (now, arc)

    rain = arc.get("rain", [])
    if not rain:
        return {"rain_3d_mm": 0, "rain_7d_mm": 0, "rain_30d_mm": 0,
                "saturation_pct": 50, "return_days": 0, "series": []}
    r3 = round(sum(rain[-3:]), 1)
    r7 = round(sum(rain[-7:]), 1)
    r30 = round(sum(rain[-30:]), 1)
    # Saturation: 30-day rain vs 150 mm field-capacity proxy for tropical plains
    sat = _clamp(round(100 * (0.55 * min(r30, 200) / 200 + 0.30 * min(r7, 60) / 60
                              + 0.15 * min(r3, 25) / 25) + 8), 5, 100)
    return {"rain_3d_mm": r3, "rain_7d_mm": r7, "rain_30d_mm": r30,
            "saturation_pct": sat, "return_days": len(rain), "series": rain,
            "source": arc.get("source")}


def _return_period(series, event_mm):
    """Years between days as wet as this event (from daily archive series)."""
    if not series or event_mm <= 0:
        return None, None
    exceed = sum(1 for v in series if v >= event_mm)
    years = len(series) / 365.0
    if exceed == 0:
        return years, f">{years:.0f}y (record max in {years:.0f}y series)"
    per_year = exceed / years
    rp = 1.0 / per_year if per_year > 0 else None
    if rp is None:
        return None, None
    if rp < 1:
        return round(rp, 2), f"~{rp * 12:.0f} months"
    return round(rp, 1), f"~{rp:.1f} year{'s' if rp >= 2 else ''}"


# ── Category scoring ──────────────────────────────────────────────────────────
CATEGORY_WEIGHTS = {
    "Meteorological": 0.30,
    "Hydrological": 0.18,
    "Topographical": 0.16,
    "Infrastructure": 0.10,
    "Real-time": 0.08,
    "Historical": 0.07,
    "Socioeconomic": 0.06,
    "Model": 0.05,
}


def compute_impact(geo: dict, ant: dict, weather: dict, scenario: dict,
                   population: int, ml_score=None) -> dict:
    """Combine every factor category into an impact score + inundation forecast.

    geo       — from get_geofactors()
    ant       — from get_antecedent()
    weather   — live conditions: next_6h_rain, peak_intensity, probability, humidity, wind, temperature
    scenario  — user what-if: rainfall_mm (event total), duration_h, intensity_mm_h
    population— population of the containing administrative unit
    ml_score  — optional XGBoost 0-100 score
    """
    elev = geo["elevation"]
    water = geo["water"]
    soil = geo["soil"]
    land = geo["landuse"]

    rain_event = scenario.get("rainfall_mm", 0.0) or 0.0
    duration_h = scenario.get("duration_h", 6.0) or 6.0
    intensity = scenario.get("intensity_mm_h") or (rain_event / max(duration_h, 0.5))

    impervious = land.get("impervious_pct", 40.0)
    sat = ant.get("saturation_pct", 45)
    slope = elev.get("slope_m_km", 1.0)
    lowness = elev.get("lowness", 0.5)
    elev_m = elev.get("elevation_m", 20.0)
    water_dist = water.get("distance_m")
    infiltration = soil.get("infiltration_mm_h", 5.0)
    prob = weather.get("probability", 0)
    wind = weather.get("wind_speed", 0)
    humidity = weather.get("humidity", 70)

    # ── 1. Meteorological (0-100) ─────────────────────────────────────────────
    intensity_score = _clamp(intensity / 2.0, 0, 100)              # 2 mm/hr = 100
    dur_score = _clamp(duration_h / 12.0, 0, 1) * 100
    acc_score = _clamp(rain_event / 100.0, 0, 1) * 100
    prob_score = _clamp(prob, 0, 100)
    wind_score = _clamp(wind / 60.0, 0, 1) * 100
    met_score = (0.45 * intensity_score + 0.20 * acc_score
                 + 0.15 * prob_score + 0.12 * dur_score + 0.08 * wind_score)

    # ── 2. Hydrological (0-100) ───────────────────────────────────────────────
    # Runoff coefficient C: impervious + saturation + soil texture adjustment
    runoff_c = _clamp(0.18 + 0.55 * (impervious / 100.0)
                      + 0.22 * (sat / 100.0) + soil.get("runoff_adj", 0), 0.05, 0.95)
    infiltrating = _clamp(infiltration / 20.0, 0, 1)
    hydro_score = _clamp(
        100 * (0.40 * (sat / 100.0) + 0.35 * runoff_c + 0.25 * (1 - infiltrating)),
        0, 100)

    # ── 3. Topographical (0-100) ──────────────────────────────────────────────
    flat_score = _clamp(slope / 10.0, 0, 1) * 100          # steep = drains better
    low_score = _clamp(lowness, 0, 1) * 100
    low_elev_score = _clamp((80 - elev_m) / 80.0, 0, 1) * 100
    if water_dist is None:
        water_score = 40.0   # unknown → neutral
    else:
        # distance decay: full effect < 500 m, flattens past 3 km
        water_score = 100 * math.exp(-water_dist / 1800.0)
    topo_score = (0.30 * low_score + 0.25 * low_elev_score
                  + 0.25 * water_score + 0.20 * (100 - flat_score))

    # ── 4. Infrastructure (0-100) ─────────────────────────────────────────────
    drains = (water.get("counts") or {}).get("drain", 0)
    waterways = (water.get("counts") or {}).get("waterway", 0)
    # More mapped drains = better conveyance (lowers risk); high impervious raises load
    drain_relief = _clamp((drains + waterways) / 8.0, 0, 1) * 100
    infra_score = _clamp(0.65 * impervious + 0.35 * (100 - drain_relief), 0, 100)

    # ── 5. Socioeconomic (0-100) — exposure density of the 5×5 km cell ────────
    cell_km2 = 25.0
    density = population / cell_km2 if population else 4000
    expo_score = _clamp(density / 15000.0, 0, 1) * 100

    # ── 6. Historical (0-100) + return period ────────────────────────────────
    rp_years, rp_label = _return_period(ant.get("series", []), rain_event)
    if rp_years is None:
        hist_score = acc_score * 0.5
    else:
        hist_score = _clamp(100 * (math.log10(max(rp_years, 0.05) + 1) / 1.7), 0, 100)

    # ── 7. Real-time (0-100) — live conditions consistency ───────────────────
    cur_rain = weather.get("current_rain", 0.0)
    nowcast = _clamp(intensity / 1.5, 0, 100) if cur_rain > 0 else _clamp(intensity / 3.0, 0, 100)
    hum_score = _clamp((humidity - 55) / 45.0, 0, 1) * 100
    rt_score = _clamp(0.6 * nowcast + 0.4 * hum_score, 0, 100)

    # ── 8. Model (0-100) — XGBoost score blended with data confidence ────────
    sources = [elev.get("source"), water.get("source"), soil.get("source"),
               land.get("source"), ant.get("source")]
    known = sum(1 for s in sources if s and "fallback" not in s and "unavailable" not in s)
    confidence = round(100 * known / len(sources))
    model_score = ml_score if ml_score is not None else met_score * 0.8

    # ── Weighted composite ────────────────────────────────────────────────────
    cat_scores = {
        "Meteorological": met_score,
        "Hydrological": hydro_score,
        "Topographical": topo_score,
        "Infrastructure": infra_score,
        "Socioeconomic": expo_score,
        "Historical": hist_score,
        "Real-time": rt_score,
        "Model": model_score,
    }
    total = 0.0
    weighted = {}
    for k, w in CATEGORY_WEIGHTS.items():
        weighted[k] = w * cat_scores[k]
        total += weighted[k]

    impact_score = _clamp(round(total), 0, 100)
    # With no rain in scenario, floor the score at a baseline
    if rain_event < 0.5 and intensity < 0.5:
        impact_score = min(impact_score, 18)

    if impact_score >= 75:
        cls = "extreme"
    elif impact_score >= 50:
        cls = "high"
    elif impact_score >= 25:
        cls = "mod"
    else:
        cls = "safe"

    shares = {k: round(weighted[k] / total * 100, 1) if total > 0 else 0
              for k in CATEGORY_WEIGHTS}
    categories = [
        {"name": k, "score": round(cat_scores[k]), "weight": CATEGORY_WEIGHTS[k],
         "share_pct": shares[k],
        "source": {
            "Meteorological": "Open-Meteo forecast",
            "Hydrological": f"saturation {sat}% · C={runoff_c:.2f} · soil {soil.get('texture')}",
            "Topographical": f"elev {elev_m}m · slope {slope} m/km"
                             + (f" · water {water_dist}m" if water_dist else ""),
            "Infrastructure": f"impervious {impervious}% · drains mapped {drains + waterways}",
            "Socioeconomic": f"pop {population:,} in 25 km² cell",
            "Historical": rp_label or "archive pending",
            "Real-time": "live nowcast + humidity",
            "Model": ("XGBoost v1.0" if ml_score is not None else "heuristic")
                     + f" · data confidence {confidence}%",
        }[k]}
        for k in CATEGORY_WEIGHTS
    ]

    # ── Inundation forecast (rational method + ponding balance) ───────────────
    drainage_cap_mm_h = max(8.0, 30.0 + 3.0 * drains - 0.06 * impervious * 30 / 100 * 10)
    drainage_cap_mm_h = _clamp(drainage_cap_mm_h, 8.0, 45.0)
    excess_mm_h = max(0.0, intensity - drainage_cap_mm_h)
    runoff_mm = rain_event * runoff_c
    ponding_m = (excess_mm_h * duration_h / 1000.0) * (0.55 + 0.45 * lowness)
    depth_max = _clamp(ponding_m * 1.6, 0, 8.0)
    depth_mean = _clamp(ponding_m * 0.7, 0, 5.0)

    # Inundated area: excess runoff volume spreads; flat+low + proximate water spreads wider
    spread = (0.4 + 0.6 * lowness) * (1 + 0.35 * (water_score / 100.0)) * (1 - 0.25 * min(slope, 8) / 8)
    area = _clamp(0.9 * (max(rain_event - drainage_cap_mm_h * duration_h * 0.5, 0) / 40.0) ** 0.8
                  * spread, 0, cell_km2)

    structures = round(area * (500 + 900 * impervious / 100.0))
    roads_km = round(area * (3.5 + 5.5 * impervious / 100.0), 1)
    people = round(density * area * (0.35 + 0.65 * expo_score / 100.0))
    peak_runoff_cms = round(runoff_c * intensity * area / 3.6, 1)
    drainage_sat = _clamp(round(100 * intensity / drainage_cap_mm_h), 0, 100)

    if impact_score >= 75:
        evac = "Tier-1 Active"
    elif impact_score >= 50:
        evac = "Standby"
    elif impact_score >= 25:
        evac = "Monitor"
    else:
        evac = "None"

    adv = []
    if runoff_c >= 0.6:
        adv.append(f"High runoff coefficient (C={runoff_c:.2f}): {int(round(runoff_c * 100))}% of rainfall becomes surface runoff — expect rapid street ponding.")
    if sat >= 65:
        adv.append(f"Soil is {sat}% saturated from {ant.get('rain_7d_mm', 0)}mm rain in the last 7 days — infiltration capacity is nearly exhausted.")
    elif sat <= 30:
        adv.append(f"Antecedent soil saturation is low ({sat}%) — soils will absorb the first ~{int(rain_event * 0.4)}mm before runoff begins.")
    if water_dist is not None and water_dist < 1000:
        adv.append(f"Nearest {water.get('type', 'water body')} is only {water_dist}m away — backwater effect may slow drain outfalls.")
    if lowness > 0.6:
        adv.append("Terrain is locally low-lying — water will pond rather than drain away.")
    if drainage_sat > 100:
        adv.append(f"Rainfall intensity exceeds drainage capacity ({drainage_cap_mm_h:.0f} mm/hr) — surcharging expected.")
    if rp_label:
        adv.append(f"A {rain_event:.0f}mm/{duration_h:.0f}h event is a {rp_label} occurrence in the 3-year record.")

    return {
        "location": {
            "lat": scenario.get("lat"), "lon": scenario.get("lon"),
            "elevation_m": elev_m, "slope_m_km": slope,
            "nearest_water_m": water_dist, "water_type": water.get("type"),
            "soil_texture": soil.get("texture"),
            "infiltration_mm_h": infiltration,
            "impervious_pct": impervious, "green_pct": land.get("green_pct"),
            "population_cell": population,
        },
        "antecedent": {k: v for k, v in ant.items() if k != "series"},
        "runoff": {
            "coefficient": round(runoff_c, 2),
            "runoff_mm": round(runoff_mm, 1),
            "drainage_capacity_mm_h": round(drainage_cap_mm_h, 1),
            "peak_runoff_cms": peak_runoff_cms,
        },
        "categories": categories,
        "impact": {
            "score": impact_score,
            "class": cls,
            "confidence_pct": confidence,
            "return_period": rp_label,
        },
        "inundation": {
            "depth_mean_m": round(depth_mean, 2),
            "depth_max_m": round(depth_max, 2),
            "area_km2": round(area, 2),
            "structures": structures,
            "roads_km": roads_km,
            "people_exposed": people,
            "drainage_saturation_pct": drainage_sat,
            "evacuation": evac,
        },
        "advisories": adv,
        "computed_at": datetime.utcnow().isoformat(),
    }
