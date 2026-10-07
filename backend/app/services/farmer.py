"""Farmer advisory engine — live, location-specific, crop- and stage-aware.

For any point it gathers:
  - Open-Meteo forecast: 7 past + 7 future days (rain, probability, temperatures, wind, gusts,
    ET0, radiation, UV), hourly humidity / temperature / wind / soil moisture at three depths
  - hyperlocal geofactors (SoilGrids texture, HAND, land use, flood history, district)
  - antecedent rain from the archive (3 / 7 / 30 days)
  - the ponding model from the impact engine, run on the next 72 h of forecast rain
  - the nearest reservoir in the RIIS table (canal / tank irrigation context)

and turns them into a water balance, waterlogging, heat and cold stress, disease pressure,
spray / sowing / harvest windows, lodging risk and a ranked advisory list.
"""
import math
import time
import asyncio
from datetime import datetime, date

import httpx

from app.services.hyperlocal import (get_geofactors, get_antecedent, get_live_conditions, compute_impact,
                                     _haversine_km, _clamp, UA)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_cache = {}
_TTL = 15 * 60

# ── Crop knowledge base (FAO-56 Kc ranges, agronomic thresholds; Tamil Nadu practice) ─────────
STAGES = ["Sowing", "Vegetative", "Flowering", "Grain-filling", "Harvest"]
CROPS = {
    "paddy": {"name": "Paddy (rice)", "kc": [1.05, 1.10, 1.20, 1.00, 0.70], "root_cm": 40, "standing_water": True,
              "waterlog_tol_h": [72, 120, 96, 72, 24], "t_opt": (22, 32), "t_heat": 35, "t_cold": 15, "lodging_gust": 55,
              "tall_from_stage": 2, "diseases": [("Rice blast", 20, 30, 85, 12), ("Bacterial leaf blight", 25, 34, 80, 10),
                                                 ("Sheath blight", 28, 32, 90, 12)], "pests": ["brown planthopper (humid, dense canopy)", "stem borer"],
              "harvest_dry_days": 3, "flowering_rain_sensitive": True},
    "sugarcane": {"name": "Sugarcane", "kc": [0.40, 1.00, 1.25, 1.10, 0.75], "root_cm": 100, "standing_water": False,
                  "waterlog_tol_h": [24, 72, 72, 72, 48], "t_opt": (24, 34), "t_heat": 38, "t_cold": 12, "lodging_gust": 60,
                  "tall_from_stage": 1, "diseases": [("Red rot", 25, 35, 80, 24), ("Rust", 20, 30, 85, 10)], "pests": ["early shoot borer", "white grub"],
                  "harvest_dry_days": 4, "flowering_rain_sensitive": False},
    "cotton": {"name": "Cotton", "kc": [0.35, 0.80, 1.15, 1.00, 0.60], "root_cm": 90, "standing_water": False,
               "waterlog_tol_h": [12, 24, 24, 36, 24], "t_opt": (21, 32), "t_heat": 36, "t_cold": 14, "lodging_gust": 55,
               "tall_from_stage": 2, "diseases": [("Boll rot", 24, 32, 85, 12), ("Alternaria leaf spot", 20, 30, 80, 8)], "pests": ["pink bollworm", "whitefly (dry, hot)", "jassids"],
               "harvest_dry_days": 3, "flowering_rain_sensitive": True},
    "groundnut": {"name": "Groundnut", "kc": [0.40, 0.80, 1.05, 0.95, 0.60], "root_cm": 60, "standing_water": False,
                  "waterlog_tol_h": [12, 24, 24, 24, 12], "t_opt": (22, 30), "t_heat": 35, "t_cold": 15, "lodging_gust": 70,
                  "tall_from_stage": 9, "diseases": [("Tikka leaf spot", 22, 30, 85, 10), ("Stem rot", 25, 32, 90, 12)], "pests": ["leaf miner", "Spodoptera"],
                  "harvest_dry_days": 4, "flowering_rain_sensitive": False},
    "millets": {"name": "Millets", "kc": [0.30, 0.70, 1.00, 0.85, 0.40], "root_cm": 60, "standing_water": False,
                "waterlog_tol_h": [12, 24, 24, 24, 12], "t_opt": (24, 34), "t_heat": 40, "t_cold": 12, "lodging_gust": 60,
                "tall_from_stage": 2, "diseases": [("Downy mildew", 20, 30, 85, 12), ("Blast", 22, 30, 85, 10)], "pests": ["shoot fly (early)", "stem borer"],
                "harvest_dry_days": 3, "flowering_rain_sensitive": True},
    "tomato": {"name": "Tomato", "kc": [0.60, 0.90, 1.15, 1.05, 0.80], "root_cm": 50, "standing_water": False,
               "waterlog_tol_h": [6, 12, 12, 12, 6], "t_opt": (18, 29), "t_heat": 34, "t_cold": 10, "lodging_gust": 50,
               "tall_from_stage": 1, "diseases": [("Late blight", 12, 24, 90, 8), ("Early blight", 24, 30, 80, 8), ("Bacterial wilt", 28, 35, 80, 10)],
               "pests": ["fruit borer", "whitefly (leaf curl virus)", "thrips"], "harvest_dry_days": 1, "flowering_rain_sensitive": True},
}
# field capacity / wilting point (m3/m3) by SoilGrids texture class, on the ERA5-Land soil-moisture
# scale that Open-Meteo reports (its values run lower than lab FC/WP for the same texture)
SOIL_WATER = {"clay": (0.37, 0.17), "clay_loam": (0.34, 0.14), "loam": (0.30, 0.11), "sandy": (0.20, 0.06)}


def _stage_idx(stage):
    return STAGES.index(stage) if stage in STAGES else 1


async def fetch_forecast(lat, lon) -> dict:
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(FORECAST_URL, params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "past_days": 7, "forecast_days": 7,
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,cloud_cover,apparent_temperature",
            "daily": "precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,"
                     "wind_gusts_10m_max,et0_fao_evapotranspiration,shortwave_radiation_sum,uv_index_max,sunshine_duration",
            "hourly": "precipitation,relative_humidity_2m,temperature_2m,wind_speed_10m,soil_moisture_0_to_7cm,"
                      "soil_moisture_7_to_28cm,soil_moisture_28_to_100cm,soil_temperature_6cm,vapour_pressure_deficit",
        }, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.json()


def _daily_rows(wx):
    d = wx.get("daily", {})
    rows = []
    for i, t in enumerate(d.get("time", [])):
        def g(k):
            v = d.get(k) or []
            return v[i] if i < len(v) else None
        rows.append({"date": t, "rain_mm": g("precipitation_sum") or 0.0, "rain_prob": g("precipitation_probability_max"),
                     "tmax": g("temperature_2m_max"), "tmin": g("temperature_2m_min"), "wind_max": g("wind_speed_10m_max"),
                     "gust_max": g("wind_gusts_10m_max"), "et0_mm": g("et0_fao_evapotranspiration"),
                     "radiation_mj": g("shortwave_radiation_sum"), "uv_max": g("uv_index_max"),
                     "sunshine_h": round((g("sunshine_duration") or 0) / 3600, 1)})
    return rows


def _hourly(wx):
    h = wx.get("hourly", {})
    return {k: h.get(k) or [] for k in ("time", "precipitation", "relative_humidity_2m", "temperature_2m", "wind_speed_10m",
                                       "soil_moisture_0_to_7cm", "soil_moisture_7_to_28cm", "soil_moisture_28_to_100cm",
                                       "soil_temperature_6cm", "vapour_pressure_deficit")}


def _now_index(times, current_time):
    ct = (current_time or "")[:13]
    return next((i for i, t in enumerate(times) if t[:13] == ct), len(times) // 2)


async def nearest_reservoir(lat, lon):
    try:
        from app.database import async_session
        from app.models import Reservoir
        from sqlalchemy import select
        async with async_session() as db:
            rows = (await db.execute(select(Reservoir))).scalars().all()
        best = None
        for r in rows:
            if not r.lat or not r.lon:
                continue
            d = _haversine_km(lat, lon, r.lat, r.lon)
            if best is None or d < best[0]:
                best = (d, r)
        if best is None:
            return None
        d, r = best
        pct = getattr(r, "storage_pct", None) or (round(100 * r.current_mcft / r.capacity_mcft, 1) if r.capacity_mcft else None)
        return {"name": r.name, "distance_km": round(d, 1), "storage_pct": pct, "source": getattr(r, "source", "seed"),
                "observed_at": getattr(r, "observed_at", None), "inflow_cms": r.inflow_cms, "outflow_cms": r.outflow_cms}
    except Exception:
        return None


async def advisory(lat: float, lon: float, crop: str = "paddy", stage: str = "Vegetative", population: int = 0) -> dict:
    crop = crop if crop in CROPS else "paddy"
    stage = stage if stage in STAGES else "Vegetative"
    key = (round(lat, 3), round(lon, 3), crop, stage)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]

    t0 = time.time()
    wx, geo, ant, live, res = await asyncio.gather(
        fetch_forecast(lat, lon), get_geofactors(lat, lon), get_antecedent(lat, lon), get_live_conditions(lat, lon),
        nearest_reservoir(lat, lon))
    C = CROPS[crop]
    si = _stage_idx(stage)
    kc = C["kc"][si]
    cur = wx.get("current", {})
    days = _daily_rows(wx)
    today = (cur.get("time") or datetime.now().isoformat())[:10]
    past = [d for d in days if d["date"] < today]
    future = [d for d in days if d["date"] >= today][:7]
    H = _hourly(wx)
    i0 = _now_index(H["time"], cur.get("time"))

    # ── soil ──────────────────────────────────────────────────────────────────
    soil = geo.get("soil") or {}
    texture = soil.get("texture", "clay_loam")
    fc, wp = SOIL_WATER.get(texture, SOIL_WATER["clay_loam"])
    porosity = soil.get("porosity", 0.46)

    def sm(k):
        vals = [v for v in H[k][max(i0 - 1, 0):i0 + 1] if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None
    sm0, sm1, sm2 = sm("soil_moisture_0_to_7cm"), sm("soil_moisture_7_to_28cm"), sm("soil_moisture_28_to_100cm")
    root = C["root_cm"]
    # root-zone weighted moisture: 0-7, 7-28, 28-100 cm layers
    weights = [min(7, root), max(0, min(28, root) - 7), max(0, min(100, root) - 28)]
    layers = [sm0, sm1, sm2]
    wsum = sum(w for w, v in zip(weights, layers) if v is not None)
    rz = round(sum(w * v for w, v in zip(weights, layers) if v is not None) / wsum, 3) if wsum else None
    paw = _clamp((rz - wp) / (fc - wp), 0, 1) if rz is not None else None       # plant-available water fraction
    sat_pct = round(100 * _clamp(sm0 / porosity, 0, 1)) if sm0 is not None else ant.get("saturation_pct")
    soil_temp = sm("soil_temperature_6cm")

    # ── water balance (next 7 days) ───────────────────────────────────────────
    wb = []
    deficit_cum = 0.0
    for d in future:
        etc = round((d["et0_mm"] or 4.0) * kc, 1)
        eff_rain = round(min(d["rain_mm"] * 0.8, etc * 2.5), 1)
        bal = round(eff_rain - etc, 1)
        deficit_cum = max(0.0, deficit_cum - bal)   # grows with deficit, resets with surplus
        wb.append({"date": d["date"], "etc_mm": etc, "rain_mm": d["rain_mm"], "effective_rain_mm": eff_rain, "balance_mm": bal,
                   "deficit_cum_mm": round(deficit_cum, 1)})
    rain7_future = round(sum(d["rain_mm"] for d in future), 1)
    rain3_future = round(sum(d["rain_mm"] for d in future[:3]), 1)
    etc7 = round(sum(w["etc_mm"] for w in wb), 1)
    readily_avail_mm = (fc - wp) * root * 10 * 0.5          # RAW ~ half of total available water, mm
    stored_mm = ((rz or fc) - wp) * root * 10 if rz is not None else readily_avail_mm
    days_until_stress = None
    run = stored_mm - readily_avail_mm * (1 - 0.5)          # water above the stress threshold
    for i, w in enumerate(wb):
        run += w["balance_mm"]
        if run <= 0:
            days_until_stress = i
            break
    if C["standing_water"]:
        irrigate_mm = 0.0 if (sat_pct or 0) >= 90 or rain3_future >= etc7 * 0.6 else round(max(0.0, etc7 * 0.6 - rain3_future), 0)
    else:
        irrigate_mm = 0.0 if paw is not None and paw > 0.5 and rain3_future >= 10 else round(max(0.0, min(readily_avail_mm, (etc7 - rain7_future * 0.8))), 0)
    irrigation = {"kc": kc, "etc_7d_mm": etc7, "rain_7d_forecast_mm": rain7_future, "rain_3d_forecast_mm": rain3_future,
                  "plant_available_water_pct": round(100 * paw) if paw is not None else None,
                  "root_zone_moisture_m3m3": rz, "field_capacity_m3m3": fc, "wilting_point_m3m3": wp,
                  "days_until_stress": days_until_stress, "recommended_mm": irrigate_mm,
                  "recommended_when": ("not needed this week" if irrigate_mm == 0 else
                                       "today" if (days_until_stress is not None and days_until_stress <= 0) else
                                       f"in {days_until_stress} day(s)" if days_until_stress is not None else "within 2 days"),
                  "daily": wb}

    # ── waterlogging: impact engine ponding on the next 72 h of rain ─────────
    weather = dict(live)
    weather.setdefault("humidity", cur.get("relative_humidity_2m", 70))
    imp = compute_impact(geo, ant, weather, {"rainfall_mm": rain3_future, "duration_h": 72.0, "pattern": "steady", "lat": lat, "lon": lon},
                         population or 500000, upstream=None, tide=None)
    pond_h = imp["inundation"]["ponding_hours"]
    tol = C["waterlog_tol_h"][si]
    hand = (geo.get("terrain") or {}).get("hand_m")
    wl_level = "high" if pond_h >= tol else "moderate" if pond_h >= tol * 0.5 or ((sat_pct or 0) >= 85 and rain3_future >= 40) else "low"
    waterlogging = {"level": wl_level, "ponding_hours_72h": pond_h, "tolerance_hours": tol, "depth_max_m": imp["inundation"]["depth_max_m"],
                    "hand_m": hand, "closed_depression": (geo.get("terrain") or {}).get("in_closed_depression"),
                    "infiltration_mm_h": soil.get("infiltration_mm_h"), "saturation_pct": sat_pct,
                    "drainage_capacity_mm_h": imp["runoff"]["drainage_capacity_mm_h"], "runoff_coefficient": imp["runoff"]["coefficient"]}

    # ── temperature stress, GDD ───────────────────────────────────────────────
    heat_days = [d["date"] for d in future if d["tmax"] is not None and d["tmax"] >= C["t_heat"]]
    cold_days = [d["date"] for d in future if d["tmin"] is not None and d["tmin"] <= C["t_cold"]]
    gdd_past = round(sum(max(0.0, ((d["tmax"] or 0) + (d["tmin"] or 0)) / 2 - 10) for d in past), 0)
    gdd_next = round(sum(max(0.0, ((d["tmax"] or 0) + (d["tmin"] or 0)) / 2 - 10) for d in future), 0)
    stress = {"heat_days": heat_days, "cold_days": cold_days, "t_opt": C["t_opt"], "t_heat": C["t_heat"], "t_cold": C["t_cold"],
              "gdd_past_7d": gdd_past, "gdd_next_7d": gdd_next, "uv_max_next_3d": max([d["uv_max"] or 0 for d in future[:3]] or [0])}

    # ── disease pressure from hourly RH / temperature in the next 72 h ───────
    rh = H["relative_humidity_2m"][i0:i0 + 72]
    tt = H["temperature_2m"][i0:i0 + 72]
    diseases = []
    for name, tlo, thi, rh_min, hours_needed in C["diseases"]:
        hrs = sum(1 for r_, t_ in zip(rh, tt) if r_ is not None and t_ is not None and r_ >= rh_min and tlo <= t_ <= thi)
        level = "high" if hrs >= hours_needed * 2 else "moderate" if hrs >= hours_needed else "low"
        diseases.append({"name": name, "favourable_hours_72h": hrs, "level": level,
                         "condition": f"RH >= {rh_min}% and {tlo}-{thi} °C"})
    wet_hours = sum(1 for r_ in rh if r_ is not None and r_ >= 90)
    disease = {"list": sorted(diseases, key=lambda x: -x["favourable_hours_72h"]), "leaf_wetness_hours_72h": wet_hours,
               "pests_to_watch": C["pests"], "overall": max((d["level"] for d in diseases), key=["low", "moderate", "high"].index, default="low")}

    # ── spray windows (next 48 h): wind < 15 km/h, no rain in the following 6 h, RH 40-85, T < 32 ────
    windows, start = [], None
    n = min(48, len(H["time"]) - i0)
    for k in range(n):
        i = i0 + k
        w = H["wind_speed_10m"][i] if i < len(H["wind_speed_10m"]) else None
        r_ = H["relative_humidity_2m"][i]
        t_ = H["temperature_2m"][i]
        rain_next6 = sum(v or 0 for v in H["precipitation"][i:i + 6])
        ok = (w is not None and w < 15) and rain_next6 < 0.5 and r_ is not None and 40 <= r_ <= 85 and t_ is not None and t_ < 32
        if ok and start is None:
            start = i
        if (not ok or k == n - 1) and start is not None:
            end = i if not ok else i + 1
            if end - start >= 2:
                windows.append({"start": H["time"][start], "end": H["time"][min(end, len(H["time"]) - 1)], "hours": end - start})
            start = None
    gust3 = max([d["gust_max"] or 0 for d in future[:3]] or [0])
    lodging = {"gust_max_3d_kmh": gust3, "threshold_kmh": C["lodging_gust"],
               "level": "high" if (si >= C["tall_from_stage"] and gust3 >= C["lodging_gust"]) else
                        "moderate" if (si >= C["tall_from_stage"] and gust3 >= C["lodging_gust"] * 0.8) else "low"}

    # ── field operation windows ───────────────────────────────────────────────
    def dry_run(k):
        for i in range(len(future) - k + 1):
            blk = future[i:i + k]
            if all(d["rain_mm"] < 2 and (d["rain_prob"] or 0) < 40 for d in blk):
                return blk[0]["date"], blk[-1]["date"]
        return None
    harvest_window = dry_run(C["harvest_dry_days"])
    sow_ok = (paw is None or paw >= 0.35) and rain3_future < 40 and not heat_days[:2] and (soil_temp is None or soil_temp >= 15)
    field = {"harvest_window": harvest_window, "harvest_dry_days_needed": C["harvest_dry_days"],
             "sowing_ok_now": bool(sow_ok), "soil_temperature_c": soil_temp}

    # ── context: flood history, land, reservoir ───────────────────────────────
    fh = geo.get("flood_history") or {}
    land = geo.get("landuse") or {}
    context = {"district": (geo.get("district") or {}).get("district"), "state": (geo.get("district") or {}).get("state"),
               "flood_prone_index": fh.get("flood_prone_index"), "district_floods": fh.get("district_events"),
               "farmland_pct_nearby": land.get("farmland_pct"), "elevation_m": (geo.get("terrain") or {}).get("elevation_m"),
               "reservoir": res, "impact_class_72h": imp["impact"]["class"], "impact_score_72h": imp["impact"]["score"]}

    # ── advisories ────────────────────────────────────────────────────────────
    adv = []

    def add(priority, kind, title, desc, icon):
        adv.append({"priority": priority, "type": kind, "title": title, "desc": desc, "icon": icon})
    if wl_level == "high":
        add(1, "warn", f"Waterlogging likely: ~{pond_h:.0f} h of standing water vs {tol} h {C['name']} tolerance at {stage.lower()}",
            f"{rain3_future} mm forecast over 3 days on {texture.replace('_', ' ')} soil at {sat_pct}% saturation"
            + (f", only {hand} m above the nearest drainage line" if hand is not None else "")
            + ". Open field drains now, stop irrigation, and plan to drain within "
            + (f"{tol} h" if tol < 48 else "two days") + " of ponding.", "droplet")
    elif wl_level == "moderate":
        add(2, "info", f"Watch low patches: ponding ~{pond_h:.0f} h possible", f"{rain3_future} mm over 3 days with soil at {sat_pct}% saturation. Keep drains clear; {C['name']} tolerates about {tol} h at this stage.", "droplet")
    if irrigate_mm > 0:
        add(1 if irrigation["days_until_stress"] in (0, 1) else 2, "info", f"Irrigate about {irrigate_mm:.0f} mm {irrigation['recommended_when']}",
            f"Crop water need {etc7} mm this week (Kc {kc} x ET0) against {rain7_future} mm forecast rain; plant-available water "
            + (f"{round(100 * paw)}%" if paw is not None else "unknown") + f" in the top {root} cm.", "droplet")
    else:
        add(3, "good", "No irrigation needed this week",
            f"Forecast rain {rain7_future} mm covers the {etc7} mm crop demand" + (f"; root zone at {round(100 * paw)}% available water" if paw is not None else "") + ".", "droplet")
    if heat_days:
        add(1 if si in (2, 3) else 2, "warn", f"Heat stress on {len(heat_days)} day(s): max >= {C['t_heat']} °C",
            f"{', '.join(d[5:] for d in heat_days)}. " + ("Flowering / grain fill is heat-sensitive: irrigate in the evening, keep standing water shallow, consider a light foliar KNO3." if si in (2, 3) else "Mulch, irrigate early morning, avoid midday operations."), "sun")
    if cold_days:
        add(2, "warn", f"Cold nights on {len(cold_days)} day(s): min <= {C['t_cold']} °C", f"{', '.join(d[5:] for d in cold_days)}. Delay sowing / transplanting; cold slows germination and sets back seedlings.", "sun")
    for dz in disease["list"][:2]:
        if dz["level"] != "low":
            add(1 if dz["level"] == "high" else 2, "warn", f"{dz['name']} pressure {dz['level']}: {dz['favourable_hours_72h']} favourable hours in 72 h",
                f"{dz['condition']}; {wet_hours} h of leaf wetness expected. Scout now and spray a protectant in the next dry window.", "bug")
    if windows:
        w0 = windows[0]
        add(2, "good", f"Spray window: {w0['start'][5:].replace('T', ' ')} to {w0['end'][11:]} ({w0['hours']} h)",
            "Wind under 15 km/h, no rain for 6 h after, humidity 40 to 85%, under 32 °C. " + (f"{len(windows) - 1} more window(s) in the next 48 h." if len(windows) > 1 else ""), "flame")
    else:
        add(2, "warn", "No good spray window in the next 48 h", "Rain, wind or humidity rule out foliar sprays; wash-off and drift risk. Wait for the next dry calm spell.", "flame")
    if lodging["level"] != "low":
        add(1 if lodging["level"] == "high" else 2, "warn", f"Lodging risk {lodging['level']}: gusts up to {gust3:.0f} km/h",
            f"Tall crop at {stage.lower()} with gusts near the {C['lodging_gust']} km/h threshold. Drain standing water, avoid top-dressing nitrogen now, stake or earth-up where practical.", "wind")
    if stage == "Harvest":
        if harvest_window:
            add(1, "good", f"Harvest window: {harvest_window[0][5:]} to {harvest_window[1][5:]}", f"{C['harvest_dry_days']} consecutive dry days with low rain probability. Harvest and dry produce inside this window.", "calendar")
        else:
            add(1, "warn", "No dry harvest window in the next 7 days", "Every run of days has rain in it. Harvest the driest day available and arrange covered drying.", "calendar")
    if stage == "Sowing":
        add(1, "good" if sow_ok else "warn", "Sowing conditions " + ("favourable" if sow_ok else "unfavourable"),
            ("Soil moisture adequate, no heavy rain in the next 3 days, no heat spike." if sow_ok else
             "Hold off: " + "; ".join(x for x in [("root zone too dry" if paw is not None and paw < 0.35 else None), ("heavy rain forecast" if rain3_future >= 40 else None),
                                                   ("heat spike" if heat_days[:2] else None), ("soil too cold" if soil_temp is not None and soil_temp < 15 else None)] if x)), "calendar")
    if si == 2 and C["flowering_rain_sensitive"] and rain3_future >= 25:
        add(2, "warn", "Rain during flowering", f"{rain3_future} mm over 3 days can wash pollen and raise flower drop in {C['name']}. Nothing to spray for it; avoid other stress and drain promptly.", "leaf")
    if res and res.get("storage_pct") is not None and res["distance_km"] <= 40:
        add(3, "info" if res["storage_pct"] >= 50 else "warn", f"{res['name']} at {res['storage_pct']}% ({res['distance_km']} km)",
            ("Canal / tank supply is comfortable." if res["storage_pct"] >= 50 else "Low storage: expect restricted canal releases, plan on-farm water.") + (f" Report of {res['observed_at']}." if res.get("observed_at") else " Seeded value, no live feed."), "chart")
    if fh.get("flood_prone_index") and fh["flood_prone_index"] >= 0.6 and rain3_future >= 60:
        add(2, "warn", f"{context['district'] or 'This district'} is flood-prone and heavy rain is coming", f"{fh.get('district_events', 0)} recorded floods in the India Flood Inventory. Move harvested produce and inputs off low ground.", "shield")
    adv.sort(key=lambda a: a["priority"])

    out = {
        "location": {"lat": lat, "lon": lon, "district": context["district"], "state": context["state"]},
        "crop": {"key": crop, "name": C["name"], "stage": stage, "kc": kc, "root_depth_cm": root},
        "now": {"temperature": cur.get("temperature_2m"), "feels_like": cur.get("apparent_temperature"), "humidity": cur.get("relative_humidity_2m"),
                "rain_mm_h": cur.get("precipitation"), "wind_kmh": cur.get("wind_speed_10m"), "gusts_kmh": cur.get("wind_gusts_10m"),
                "cloud_pct": cur.get("cloud_cover"), "vpd_kpa": (H["vapour_pressure_deficit"][i0] if i0 < len(H["vapour_pressure_deficit"]) else None),
                "time": cur.get("time")},
        "past_7d": {"rain_mm": round(sum(d["rain_mm"] for d in past), 1), "gdd": gdd_past, "days": past,
                    "rain_3d_mm": ant.get("rain_3d_mm"), "rain_30d_mm": ant.get("rain_30d_mm")},
        "forecast_7d": future,
        "soil": {"texture": texture, "infiltration_mm_h": soil.get("infiltration_mm_h"), "source": soil.get("source"),
                 "moisture_0_7": sm0, "moisture_7_28": sm1, "moisture_28_100": sm2, "root_zone": rz, "saturation_pct": sat_pct,
                 "plant_available_water_pct": irrigation["plant_available_water_pct"], "soil_temperature_c": soil_temp},
        "irrigation": irrigation, "waterlogging": waterlogging, "stress": stress, "disease": disease,
        "spray_windows": windows, "lodging": lodging, "field": field, "context": context,
        "advisories": adv,
        "data_sources": {"forecast": "Open-Meteo (ECMWF/GFS blend, ERA5-Land soil moisture)", "soil": soil.get("source"),
                         "terrain": (geo.get("terrain") or {}).get("source"), "flood_history": fh.get("source"),
                         "reservoir": res.get("source") if res else None, "still_loading": geo.get("still_loading", [])},
        "computed_in_s": round(time.time() - t0, 1), "computed_at": datetime.utcnow().isoformat(),
    }
    _cache[key] = (time.time(), out)
    if len(_cache) > 200:
        _cache.pop(next(iter(_cache)))
    return out
