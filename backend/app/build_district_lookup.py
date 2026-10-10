"""Build app/data/district_lookup.json from the India Flood Inventory files.

    cd backend && python -m app.build_district_lookup

Sources, in order of authority for the canonical spelling:
  1. Dist_Name in DFSI.csv / District_FloodImpact.csv / District_FloodedArea.csv (what
     flood_history.lookup() joins on), with the state from DFSI.State_Name.
  2. The IFI event file's Districts and District_LGD_Codes columns, zipped row by row
     (rows whose two lists differ in length are skipped), which supply the LGD code and,
     for single-state events, the state.
  3. HAND_ALIASES below: Tamil Nadu renamings and transliterations, the RIIS city seeds
     (Bangalore Urban -> Bengaluru Urban, Guwahati -> Kamrup Metropolitan, ...), and new
     districts carved out after the inventory was compiled (parent = the district whose
     flood record applies until the new one has its own).

Every canonical entry: {"lgd_code": str|None, "state": str|None, "aliases": [...], "parent": str|None}.
Hand aliases that do not resolve to a canonical name are printed as warnings so the table
is never silently wrong.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.services.district_lookup import normalise  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_PATH = os.path.join(DATA_DIR, "district_lookup.json")

# canonical (IFI spelling) -> aliases.  Canonical names here must exist in the IFI tables
# unless they also appear in NEW_DISTRICTS.
HAND_ALIASES = {
    # Tamil Nadu
    "Thoothukkudi": ["Tuticorin", "Thoothukudi", "Tuticorin District", "Thoothukkudi District"],
    "Kanniyakumari": ["Kanyakumari", "Kanniyakumariumari", "Kanyakumari District"],
    "Tiruchirappalli": ["Trichy", "Tiruchirapalli", "Tiruchchirappalli", "Thiruchirappalli", "Trichinopoly"],
    "Viluppuram": ["Villupuram", "Vilupuram"],
    "The Nilgiris": ["Nilgiris", "Nilgiri", "Nilgiris District", "Udhagamandalam"],
    "Kancheepuram": ["Kanchipuram", "Kanchipuram District", "Kancheepuram District"],
    "Thiruvallur": ["Tiruvallur", "Tiruvallur District", "Thiruvallur District"],
    "Chengalpattu": ["Chengalpet", "Chingleput", "Chengalpattu District"],
    "Tenkasi": ["Tenkasi District"],
    "Ranipet": ["Ranipet District", "Ranipettai"],
    "Kallakurichi": ["Kallakurichi District", "Kallakuruchi"],
    "Tirupathur": ["Tirupattur", "Tirupathur District", "Thirupathur"],
    "Chennai": ["Madras", "Chennai District", "Greater Chennai"],
    "Coimbatore": ["Kovai", "Coimbatore District"],
    "Madurai": ["Madurai District"],
    "Tirunelveli": ["Nellai", "Thirunelveli", "Tirunelveli District"],
    "Thanjavur": ["Tanjore", "Tanjavur"],
    "Sivaganga": ["Sivagangai"],
    "Tiruppur": ["Tirupur"],
    "Tiruvannamalai": ["Thiruvannamalai"],
    "Thiruvarur": ["Tiruvarur"],
    "Nagapattinam": ["Nagapatnam", "Nagapattinam District"],
    "Vellore": ["Vellore District"],
    "Cuddalore": ["Cuddalore District"],
    "Pudukkottai": ["Pudukottai"],
    "Virudhunagar": ["Virudunagar"],
    "Dindigul": ["Dindugal"],
    "Krishnagiri": ["Krishnagiri District"],
    "Salem": ["Salem District"],
    "Erode": ["Erode District"],
    "Namakkal": ["Namakkal District"],
    "Karur": ["Karur District"],
    "Perambalur": ["Perambalur District"],
    "Ariyalur": ["Ariyalur District"],
    "Theni": ["Theni District"],
    "Dharmapuri": ["Dharmapuri District"],
    "Ramanathapuram": ["Ramnad", "Ramanathapuram District"],
    # RIIS city seeds and common city names (from flood_history.CITY_TO_DISTRICT)
    "Bengaluru Urban": ["Bangalore Urban", "Bangalore", "Bengaluru", "Bangalore Urban District"],
    "Bengaluru Rural": ["Bangalore Rural"],
    "Dharwad": ["Hubli-Dharwad", "Hubballi-Dharwad", "Hubli"],
    "Kamrup Metropolitan": ["Kamrup Metro", "Guwahati", "Kamrup (Metro)"],
    "Darjeeling": ["Siliguri", "Darjiling"],
    "North Goa": ["Panaji", "Panjim"],
    "Krishna": ["Vijayawada"],
    "Mumbai Suburban": ["Mumbai Suburban District", "Bombay Suburban"],
    "Mumbai": ["Bombay", "Mumbai City", "South Mumbai"],
    "Khordha": ["Bhubaneswar", "Khurda"],
    "West Tripura": ["Agartala"],
    "Imphal West": ["Imphal"],
    "East Khasi Hills": ["Shillong"],
    "Mysuru": ["Mysore"],
    "New Delhi": ["Delhi"],
    "Chandigarh": ["Chandigarh UT"],
    "Aizawl": ["Aijal"],
    "Kohima": [],
    "Dibrugarh": [],
    "Hyderabad": ["Hyderabad District"],
    "Kolkata": ["Calcutta"],
    "Pune": ["Poona"],
    "Thiruvananthapuram": ["Trivandrum"],
    "Ernakulam": ["Kochi", "Cochin"],
    "Kozhikode": ["Calicut"],
    "Puducherry": ["Pondicherry"],
    "Visakhapatnam": ["Vizag", "Vishakhapatnam"],
    "Prayagraj": ["Allahabad"],
    "Varanasi": ["Benares", "Banaras"],
    "Ahmedabad": ["Ahmadabad"],
    "Vadodara": ["Baroda"],
    "Kanpur Nagar": ["Kanpur"],
    "Lucknow": [],
    "Patna": [],
    "Gurugram": ["Gurgaon"],
    "Ahmednagar": ["Ahmadnagar"],
}

# Districts created after the inventory was compiled: canonical -> (state, parent whose record applies, aliases)
NEW_DISTRICTS = {
    "Mayiladuthurai": ("Tamil Nadu", "Nagapattinam", ["Mayiladuthurai District", "Mayuram", "Mayavaram"]),
}

STATE_TITLE = {"TAMIL NADU": "Tamil Nadu", "ANDHRA PRADESH": "Andhra Pradesh", "ARUNACHAL PRADESH": "Arunachal Pradesh",
               "HIMACHAL PRADESH": "Himachal Pradesh", "MADHYA PRADESH": "Madhya Pradesh", "UTTAR PRADESH": "Uttar Pradesh",
               "WEST BENGAL": "West Bengal", "JAMMU AND KASHMIR": "Jammu and Kashmir", "JAMMU & KASHMIR": "Jammu and Kashmir",
               "DADRA AND NAGAR HAVELI": "Dadra and Nagar Haveli", "DAMAN AND DIU": "Daman and Diu",
               "ANDAMAN AND NICOBAR ISLANDS": "Andaman and Nicobar Islands", "NCT OF DELHI": "Delhi", "DELHI": "Delhi"}


def _title(state) -> str | None:
    if state is None or (isinstance(state, float) and pd.isna(state)):
        return None
    s = str(state).strip()
    if not s:
        return None
    return STATE_TITLE.get(s.upper(), s.title() if s.isupper() else s)


def _split(cell) -> list:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    return [x.strip() for x in str(cell).split(",") if x.strip()]


def build() -> dict:
    # 1. district tables: canonical spellings and DFSI states
    canon = {}      # normalised -> canonical spelling
    state_of = {}   # normalised -> state
    dfsi = pd.read_csv(os.path.join(DATA_DIR, "DFSI.csv"))
    dfsi = dfsi.rename(columns={dfsi.columns[0]: "Dist_Name"})
    for _, r in dfsi.iterrows():
        k = normalise(r["Dist_Name"])
        if k:
            canon.setdefault(k, str(r["Dist_Name"]).strip())
            if _title(r.get("State_Name")):
                state_of.setdefault(k, _title(r["State_Name"]))
    for fn in ("District_FloodImpact.csv", "District_FloodedArea.csv"):
        df = pd.read_csv(os.path.join(DATA_DIR, fn))
        for name in df["Dist_Name"].dropna().astype(str):
            k = normalise(name)
            if k:
                canon.setdefault(k, name.strip())

    # 2. event file: LGD codes and single-state rows
    ev = pd.read_csv(os.path.join(DATA_DIR, "India_Flood_Inventory_v3.csv"), low_memory=False)
    codes = defaultdict(Counter)
    states = defaultdict(Counter)
    skipped = 0
    for d, c, s in zip(ev["Districts"], ev["District_LGD_Codes"], ev["State"]):
        ds, cs, ss = _split(d), _split(c), _split(s)
        if not ds:
            continue
        if cs and len(cs) != len(ds):
            skipped += 1
            cs = []
        for i, name in enumerate(ds):
            k = normalise(name)
            if not k:
                continue
            canon.setdefault(k, name)
            if cs and re.fullmatch(r"\d+", cs[i]):
                codes[k][cs[i]] += 1
            if len(ss) == 1 and _title(ss[0]):
                states[k][_title(ss[0])] += 1

    districts = {}
    for k, name in canon.items():
        code = codes[k].most_common(1)[0][0] if codes[k] else None
        state = state_of.get(k) or (states[k].most_common(1)[0][0] if states[k] else None)
        districts[name] = {"lgd_code": code, "state": state, "aliases": [], "parent": None}

    # 3. hand aliases.  The event file spells some districts differently from the district
    # tables (Darjeeling / Darjiling, Bengaluru Urban / Bangalore, Kochi / Ernakulam), so each
    # alias group is merged onto the member the tables score on; event-only variants become
    # aliases of it and donate their LGD code when the primary has none.
    in_tables = {normalise(x) for x in dfsi["Dist_Name"].dropna().astype(str)}
    for fn in ("District_FloodImpact.csv", "District_FloodedArea.csv"):
        in_tables |= {normalise(x) for x in pd.read_csv(os.path.join(DATA_DIR, fn))["Dist_Name"].dropna().astype(str)}
    warnings = []
    for target, aliases in HAND_ALIASES.items():
        by_norm = {normalise(n): n for n in districts}
        group = [target] + list(aliases)
        members = list(dict.fromkeys(by_norm[normalise(g)] for g in group if normalise(g) in by_norm))
        if not members:
            warnings.append(f"hand alias target not in inventory: {target}")
            continue
        primary = next((m for m in members if normalise(m) in in_tables), members[0])
        for m in members:
            if m == primary:
                continue
            if normalise(m) in in_tables:
                warnings.append(f"'{m}' and '{primary}' both have flood-table rows; kept separate")
                continue
            e = districts.pop(m)
            districts[primary]["lgd_code"] = districts[primary]["lgd_code"] or e["lgd_code"]
            districts[primary]["state"] = districts[primary]["state"] or e["state"]
            for a in [m] + e["aliases"]:
                if a not in districts[primary]["aliases"]:
                    districts[primary]["aliases"].append(a)
        for a in group:
            if normalise(a) != normalise(primary) and a not in districts[primary]["aliases"]:
                districts[primary]["aliases"].append(a)
    by_norm = {normalise(n): n for n in districts}
    for name, (state, parent, aliases) in NEW_DISTRICTS.items():
        if normalise(name) in by_norm:
            districts[by_norm[normalise(name)]]["aliases"].extend(a for a in aliases if a not in districts[by_norm[normalise(name)]]["aliases"])
            continue
        pname = by_norm.get(normalise(parent))
        if pname is None:
            warnings.append(f"parent not in inventory: {parent} (for {name})")
        districts[name] = {"lgd_code": None, "state": state, "aliases": list(aliases), "parent": pname}

    # a spelling that is both a canonical name and someone else's alias is ambiguous: report it
    seen = {}
    for name, e in districts.items():
        for a in [name] + e["aliases"]:
            k = normalise(a)
            if k in seen and seen[k] != name:
                warnings.append(f"alias '{a}' maps to both {seen[k]} and {name}")
            seen.setdefault(k, name)

    for w in warnings:
        print("WARNING:", w)
    out = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": ["India_Flood_Inventory_v3.csv (Districts, District_LGD_Codes, State)",
                    "DFSI.csv (Dist_Name, State_Name)", "District_FloodImpact.csv", "District_FloodedArea.csv",
                    "HAND_ALIASES / NEW_DISTRICTS in app/build_district_lookup.py"],
        "event_rows_with_mismatched_code_lists": skipped,
        "count": len(districts),
        "districts": dict(sorted(districts.items(), key=lambda kv: kv[0].lower())),
    }
    return out


def main():
    out = build()
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    os.replace(tmp, OUT_PATH)
    with_code = sum(1 for e in out["districts"].values() if e["lgd_code"])
    with_state = sum(1 for e in out["districts"].values() if e["state"])
    print(f"wrote {OUT_PATH}: {out['count']} districts, {with_code} with LGD code, {with_state} with state")


if __name__ == "__main__":
    main()
