"""Historical flood context from the India Flood Inventory with Impacts
(IFI-Impacts v4, IIT Delhi, Zenodo 10.5281/zenodo.4742142), stored in app/data/.

Gives, for a point:
  - events within a radius (from georeferenced IFI events)
  - district-level event count, fatalities, mean duration, DFSI severity index,
    and satellite-derived percent flooded area, matched by district name.
"""
import os
import math
import difflib
from functools import lru_cache

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# RIIS seeds cities; IFI is by administrative district.
CITY_TO_DISTRICT = {
    "bangalore urban": "Bangalore", "hubli-dharwad": "Dharwad", "kamrup metro": "Kamrup Metropolitan",
    "guwahati": "Kamrup Metropolitan", "siliguri": "Darjeeling", "panaji": "North Goa", "gangtok": "Gangtok",
    "vijayawada": "Krishna", "mumbai": "Mumbai Suburban", "bhubaneswar": "Khordha", "agartala": "West Tripura",
    "imphal": "Imphal West", "shillong": "East Khasi Hills", "mysuru": "Mysuru", "delhi": "New Delhi",
    "chandigarh": "Chandigarh", "aizawl": "Aizawl", "kohima": "Kohima", "dibrugarh": "Dibrugarh",
}


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _load():
    try:
        ev = pd.read_csv(os.path.join(DATA_DIR, "India_Flood_Inventory_v3.csv"), low_memory=False)
        ev["start"] = pd.to_datetime(ev["Start Date"], dayfirst=True, errors="coerce")
        ev["year"] = ev["start"].dt.year
        ev["lat"] = pd.to_numeric(ev["Latitude"], errors="coerce")
        ev["lon"] = pd.to_numeric(ev["Longitude"], errors="coerce")
        ev["fatal"] = pd.to_numeric(ev["Human fatality"], errors="coerce").fillna(0)
        imp = pd.read_csv(os.path.join(DATA_DIR, "District_FloodImpact.csv"))
        dfsi = pd.read_csv(os.path.join(DATA_DIR, "DFSI.csv"))
        dfsi = dfsi.rename(columns={dfsi.columns[0]: "Dist_Name"})
        area = pd.read_csv(os.path.join(DATA_DIR, "District_FloodedArea.csv"))
        dist = imp.merge(dfsi, on="Dist_Name", how="outer").merge(area, on="Dist_Name", how="outer")
        dist["key"] = dist["Dist_Name"].astype(str).str.strip().str.lower()
        return ev, dist
    except Exception as e:  # files missing -> engine degrades gracefully
        print(f"[RIIS-flood-history] unavailable: {e}")
        return None, None


def _district_events(ev: pd.DataFrame, name: str) -> pd.DataFrame:
    pat = name.lower()
    mask = ev["Districts"].astype(str).str.lower().str.contains(pat, regex=False, na=False)
    return ev[mask]


def lookup(district_name: str | None) -> dict:
    ev, dist = _load()
    if ev is None:
        return {"source": "unavailable"}

    out = {"source": "india_flood_inventory_v4"}

    # IFI v4 has no event coordinates; everything is by district name.
    # 2. district match
    name = (district_name or "").strip()
    name = CITY_TO_DISTRICT.get(name.lower(), name)
    match = None
    if name:
        keys = dist["key"].tolist()
        cand = [k for k in keys if k == name.lower()] or                [k for k in keys if k.startswith(name.lower()) or name.lower().startswith(k)] or                difflib.get_close_matches(name.lower(), keys, n=1, cutoff=0.75)
        if cand:
            match = dist[dist["key"] == cand[0]].iloc[0]
    if match is not None:
        de = _district_events(ev, str(match["Dist_Name"]))
        years = de["year"].dropna()
        span = max(1.0, float(years.max() - years.min() + 1)) if len(years) else 57.0
        out.update({
            "district": str(match["Dist_Name"]),
            "district_events": int(len(de)),
            "district_events_per_decade": round(10 * len(de) / span, 2),
            "district_events_since_2010": int((de["year"] >= 2010).sum()),
            "district_fatalities": int(match.get("Human_fatality") or 0) if pd.notna(match.get("Human_fatality")) else 0,
            "district_mean_flood_days": (round(float(match["Mean_Flood_Duration"]), 1)
                                         if pd.notna(match.get("Mean_Flood_Duration")) else None),
            "dfsi": round(float(match["DFSI"]), 2) if pd.notna(match.get("DFSI")) else None,
            "flooded_area_pct": (round(float(match["Corrected_Percent_Flooded_Area"]), 2)
                                 if pd.notna(match.get("Corrected_Percent_Flooded_Area")) else None),
        })
    else:
        out["district"] = None

    # 3. one normalised 0..1 "flood-prone" score
    s = 0.0
    if out.get("dfsi") is not None:
        s += 0.50 * min(out["dfsi"] / 15.0, 1.0)           # DFSI tops out near 19
    if out.get("flooded_area_pct") is not None:
        s += 0.20 * min(out["flooded_area_pct"] / 10.0, 1.0)
    if out.get("district_events_per_decade") is not None:
        s += 0.30 * min(out["district_events_per_decade"] / 6.0, 1.0)
    out["flood_prone_index"] = round(min(s, 1.0), 3) if match is not None else None
    return out
