"""Historical flood context from the India Flood Inventory with Impacts
(IFI-Impacts v4, IIT Delhi, Zenodo 10.5281/zenodo.4742142), stored in app/data/.

Gives, for a point:
  - district-level event count, fatalities, mean duration, DFSI severity index,
    and satellite-derived percent flooded area, matched by district name.

District names come from Nominatim (or the RIIS seed) in any spelling; they are resolved
to the inventory's spelling and LGD code through app/data/district_lookup.json
(services/district_lookup.py), never by substring or fuzzy matching. A name the table
does not know is reported as a `district_miss` and the context degrades to None.
"""
import os
import math
from functools import lru_cache

import pandas as pd

from app.services.district_lookup import normalise, resolve

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# RIIS seeds cities; IFI is by administrative district.  Kept for older imports; the same
# mappings live in district_lookup.json as aliases, which is what lookup() uses.
CITY_TO_DISTRICT = {
    "bangalore urban": "Bangalore", "hubli-dharwad": "Dharwad", "kamrup metro": "Kamrup Metropolitan",
    "guwahati": "Kamrup Metropolitan", "siliguri": "Darjiling", "panaji": "North Goa", "gangtok": "Gangtok",
    "vijayawada": "Krishna", "mumbai": "Mumbai", "bhubaneswar": "Khordha", "agartala": "West Tripura",
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
        # normalised district tokens per event, for exact (not substring) matching
        ev["district_keys"] = ev["Districts"].apply(
            lambda d: frozenset(normalise(x) for x in str(d).split(",") if x.strip()) if pd.notna(d) else frozenset())
        imp = pd.read_csv(os.path.join(DATA_DIR, "District_FloodImpact.csv"))
        dfsi = pd.read_csv(os.path.join(DATA_DIR, "DFSI.csv"))
        dfsi = dfsi.rename(columns={dfsi.columns[0]: "Dist_Name"})
        area = pd.read_csv(os.path.join(DATA_DIR, "District_FloodedArea.csv"))
        dist = imp.merge(dfsi, on="Dist_Name", how="outer").merge(area, on="Dist_Name", how="outer")
        dist["key"] = dist["Dist_Name"].astype(str).map(normalise)
        return ev, dist
    except Exception as e:  # files missing -> engine degrades gracefully
        print(f"[RIIS-flood-history] unavailable: {e}")
        return None, None


def _district_events(ev: pd.DataFrame, name: str) -> pd.DataFrame:
    key = normalise(name)
    mask = ev["district_keys"].apply(lambda s: key in s)
    return ev[mask]


def lookup(district_name: str | None, state: str | None = None) -> dict:
    ev, dist = _load()
    if ev is None:
        return {"source": "unavailable"}

    out = {"source": "india_flood_inventory_v4", "district_code": None,
           "district_match": {"query": district_name, "canonical": None, "method": "none"}}

    # IFI v4 has no event coordinates; everything is by district name, resolved by alias.
    name = (district_name or "").strip()
    res = resolve(name, state) if name else None
    match = None
    if res:
        out["district_code"] = res.get("lgd_code")
        out["district_match"].update({"canonical": res["district"], "state": res.get("state"),
                                      "matched_alias": res.get("matched_alias"), "method": "lookup"})
        candidates = [res["district"]] + ([res["parent"]] if res.get("parent") else [])
        for i, cand in enumerate(candidates):
            rows = dist[dist["key"] == normalise(cand)]
            if len(rows):
                match = rows.iloc[0]
                if i:
                    out["district_match"].update({"method": "parent", "record_of": cand})
                break
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

    # one normalised 0..1 "flood-prone" score
    s = 0.0
    if out.get("dfsi") is not None:
        s += 0.50 * min(out["dfsi"] / 15.0, 1.0)           # DFSI tops out near 19
    if out.get("flooded_area_pct") is not None:
        s += 0.20 * min(out["flooded_area_pct"] / 10.0, 1.0)
    if out.get("district_events_per_decade") is not None:
        s += 0.30 * min(out["district_events_per_decade"] / 6.0, 1.0)
    out["flood_prone_index"] = round(min(s, 1.0), 3) if match is not None else None
    return out
