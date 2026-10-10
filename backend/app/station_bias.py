"""
RIIS - ERA5 (Open-Meteo archive) bias against TNDMA rain-gauge stations, per district.

Every weather model in RIIS learns Open-Meteo's reanalysis as its rain label. This script measures
how far that reanalysis sits from observed gauges, district by district, so the number can be shown
next to every score instead of assumed away.

Station data: Tamil Nadu daily rainfall 1990-2023, 629 stations in 38 districts, published by TNDMA
through OpenCity (public domain). Download once to backend/cache/station/tn_daily_rainfall_1991_2023.csv:
  https://data.opencity.in/dataset/chennai-rainfall-data (resource "Tamil Nadu Daily Rainfall from 1991 to 2023")

Reanalysis: daily precipitation_sum from the Open-Meteo archive at each RIIS district centroid for
the overlap window (default 2021-01-01 to 2023-12-26), cached under backend/cache/station/era5_<id>.json
so reruns cost no budget. One district-window costs ceil(days/14) budget units (about 78 for 3 years).

Usage:
    cd backend
    python -m app.station_bias            # writes app/data/station_bias.json and docs/ERA5_STATION_BIAS.md
"""
import os
import sys
import json
import math
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "riis.db")
STATION_CSV = os.path.join(HERE, "..", "cache", "station", "tn_daily_rainfall_1991_2023.csv")
ERA5_CACHE = os.path.join(HERE, "..", "cache", "station")
OUT_JSON = os.path.join(HERE, "data", "station_bias.json")
OUT_MD = os.path.join(HERE, "..", "docs", "ERA5_STATION_BIAS.md")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
START = os.environ.get("RIIS_BIAS_START", "2021-01-01")
END = os.environ.get("RIIS_BIAS_END", "2023-12-26")

# RIIS district name -> TNDMA district name
DISTRICT_MAP = {
    "Chennai": "Chennai", "Kanchipuram": "Kancheepuram", "Madurai": "Madurai", "Coimbatore": "Coimbatore",
    "Cuddalore": "Cuddalore", "Thanjavur": "Thanjavur", "Nilgiris (Ooty)": "The Nilgiris",
}
WET_MM, HEAVY_MM, VERY_HEAVY_MM = 2.5, 64.5, 115.6   # IMD definitions


def station_district_daily(csv_path: str, start: str, end: str, districts=None) -> "pd.DataFrame":
    """District-day rainfall from the TNDMA file, done honestly.

    The file holds only rainy station-days (no zero rows) and the municipal 'GCC' and 'CMWSSB' zone
    gauges report a few weeks a year, so a naive mean of reporting stations triples the totals.
    This keeps the Revenue-department network (complete records whose annual sums match IMD normals),
    treats a day with no row as 0 mm inside each station's active span, and averages over the
    stations active that day. Returns columns dist, date, st_mean, st_max, st_n.
    """
    df = pd.read_csv(csv_path, usecols=["dept", "dist", "station", "value", "date"], low_memory=False)
    df = df[df["dept"] == "Revenue"]
    if districts is not None:
        df = df[df["dist"].isin(districts)]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df[(df["value"] >= 0) & (df["value"] < 700)]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    out = []
    for (dist, stn), g in df.groupby(["dist", "station"]):
        a, b = max(g["date"].min(), lo), min(g["date"].max(), hi)
        if a > b or (b - a).days < 300:
            continue                                         # a gauge active under a year adds noise, not signal
        idx = pd.date_range(a, b, freq="D")
        s = g.groupby("date")["value"].sum().reindex(idx, fill_value=0.0)
        out.append(pd.DataFrame({"dist": dist, "station": stn, "date": idx, "value": s.values}))
    if not out:
        return pd.DataFrame(columns=["dist", "date", "st_mean", "st_max", "st_n"])
    allst = pd.concat(out, ignore_index=True)
    g = allst.groupby(["dist", "date"])["value"]
    res = pd.DataFrame({"st_mean": g.mean(), "st_max": g.max(), "st_n": g.size()}).reset_index()
    res["date"] = res["date"].dt.strftime("%Y-%m-%d")
    return res


def load_station_daily(districts: list) -> pd.DataFrame:
    return station_district_daily(STATION_CSV, START, END, districts)


def fetch_era5_daily(did: int, lat: float, lon: float) -> pd.DataFrame:
    path = os.path.join(ERA5_CACHE, f"era5_{did}_{START}_{END}.json")
    if os.path.exists(path):
        with open(path) as f:
            d = json.load(f)
    else:
        import httpx
        units = math.ceil((pd.Timestamp(END) - pd.Timestamp(START)).days / 14)
        try:
            from app.services.budget import reserve
            reserve(units, f"station_bias district {did}")
        except ImportError:
            pass
        url = (f"{ARCHIVE}?latitude={lat}&longitude={lon}&start_date={START}&end_date={END}"
               f"&daily=precipitation_sum,rain_sum&timezone=Asia%2FKolkata")
        r = httpx.get(url, timeout=60)
        r.raise_for_status()
        d = r.json()["daily"]
        os.makedirs(ERA5_CACHE, exist_ok=True)
        with open(path, "w") as f:
            json.dump(d, f)
    return pd.DataFrame({"date": d["time"], "era5": d["precipitation_sum"]})


def contingency(obs: np.ndarray, est: np.ndarray, thr: float) -> dict:
    o, e = obs >= thr, est >= thr
    hits, miss, fa = int((o & e).sum()), int((o & ~e).sum()), int((~o & e).sum())
    pod = hits / (hits + miss) if hits + miss else None
    far = fa / (hits + fa) if hits + fa else None
    csi = hits / (hits + miss + fa) if hits + miss + fa else None
    return {"threshold_mm": thr, "obs_days": int(o.sum()), "est_days": int(e.sum()), "hits": hits,
            "pod": None if pod is None else round(pod, 3), "far": None if far is None else round(far, 3),
            "csi": None if csi is None else round(csi, 3)}


def district_stats(m: pd.DataFrame) -> dict:
    st, er = m["st_mean"].to_numpy(float), m["era5"].to_numpy(float)
    wet = (st >= WET_MM) | (er >= WET_MM)
    q = [0.5, 0.9, 0.95, 0.99]
    out = {
        "n_days": int(len(m)), "stations_mean": round(float(m["st_n"].mean()), 1),
        "station_mean_mm_day": round(float(st.mean()), 3), "era5_mean_mm_day": round(float(er.mean()), 3),
        "bias_mm_day": round(float(er.mean() - st.mean()), 3),
        "ratio_era5_over_station": round(float(er.sum() / st.sum()), 3) if st.sum() > 0 else None,
        "annual_total_station_mm": round(float(st.mean() * 365.25)), "annual_total_era5_mm": round(float(er.mean() * 365.25)),
        "pearson_r_daily": round(float(np.corrcoef(st, er)[0, 1]), 3),
        "pearson_r_wet_days": round(float(np.corrcoef(st[wet], er[wet])[0, 1]), 3) if wet.sum() > 10 else None,
        "mae_mm_day": round(float(np.abs(er - st).mean()), 3),
        "quantiles_station_mm": {f"p{int(x*100)}": round(float(np.quantile(st, x)), 1) for x in q},
        "quantiles_era5_mm": {f"p{int(x*100)}": round(float(np.quantile(er, x)), 1) for x in q},
        "quantile_ratio_era5_over_station": {f"p{int(x*100)}": (round(float(np.quantile(er, x) / np.quantile(st, x)), 3)
                                                                 if np.quantile(st, x) > 0 else None) for x in q},
        "wet_day": contingency(st, er, WET_MM), "heavy_day": contingency(st, er, HEAVY_MM),
        "very_heavy_day": contingency(st, er, VERY_HEAVY_MM),
        "station_max_mm_day": round(float(m["st_max"].max()), 1), "era5_max_mm_day": round(float(er.max()), 1),
    }
    mm = m.assign(month=pd.to_datetime(m["date"]).dt.month).groupby("month")[["st_mean", "era5"]].mean()
    out["monthly_bias_mm_day"] = {int(k): round(float(v), 2) for k, v in (mm["era5"] - mm["st_mean"]).items()}
    return out


def main():
    conn = sqlite3.connect(DB_PATH)
    districts = conn.execute("SELECT id, name, lat, lon FROM districts").fetchall()
    conn.close()
    riis = [(i, n, la, lo) for i, n, la, lo in districts if n in DISTRICT_MAP]
    st = load_station_daily(list(DISTRICT_MAP.values()))
    print(f"station district-days: {len(st)} for {st['dist'].nunique()} districts, {START}..{END}")
    report = {"computed_at": datetime.utcnow().isoformat(), "window": [START, END],
              "station_source": "TNDMA daily rainfall via OpenCity (public domain), Revenue-department gauges only, unreported days = 0 inside each gauge's active span, district mean of active gauges",
              "reanalysis_source": "Open-Meteo archive daily precipitation_sum at the RIIS district centroid (ERA5 / ERA5-Land)",
              "method": ("district mean of all reporting gauges per day vs reanalysis at the centroid; "
                         "bias = era5 - station; contingency at IMD thresholds 2.5 / 64.5 / 115.6 mm"),
              "districts": {}}
    for did, name, lat, lon in riis:
        era = fetch_era5_daily(did, lat, lon)
        m = st[st["dist"] == DISTRICT_MAP[name]].merge(era, on="date", how="inner").dropna()
        if len(m) < 100:
            print(f"  {name}: only {len(m)} overlapping days, skipped")
            continue
        s = district_stats(m)
        s.update({"district_id": did, "tndma_name": DISTRICT_MAP[name], "lat": lat, "lon": lon})
        report["districts"][name] = s
        print(f"  {name:16s} n={s['n_days']}  station {s['annual_total_station_mm']} mm/y  era5 {s['annual_total_era5_mm']} mm/y  "
              f"ratio {s['ratio_era5_over_station']}  r={s['pearson_r_daily']}  heavy POD {s['heavy_day']['pod']} FAR {s['heavy_day']['far']}  "
              f"p99 ratio {s['quantile_ratio_era5_over_station']['p99']}")
    ds = report["districts"]
    if ds:
        ratios = [d["ratio_era5_over_station"] for d in ds.values() if d["ratio_era5_over_station"]]
        p99 = [d["quantile_ratio_era5_over_station"]["p99"] for d in ds.values() if d["quantile_ratio_era5_over_station"]["p99"]]
        pods = [d["heavy_day"]["pod"] for d in ds.values() if d["heavy_day"]["pod"] is not None]
        report["summary"] = {
            "n_districts": len(ds), "median_ratio_era5_over_station": round(float(np.median(ratios)), 3),
            "median_p99_ratio": round(float(np.median(p99)), 3) if p99 else None,
            "median_heavy_day_pod": round(float(np.median(pods)), 3) if pods else None,
            "reading": ("ratio < 1 means the reanalysis under-reports rain; a p99 ratio well under 1 means it "
                        "flattens the heavy days the impact engine cares about most"),
        }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# ERA5 reanalysis vs TNDMA gauges, per district\n\n")
        f.write(f"Computed {report['computed_at'][:10]} over {START} to {END}. Station: district mean of the active Revenue-department TNDMA gauges, unreported days counted as dry "
                "(OpenCity, public domain). Reanalysis: Open-Meteo archive at the district centroid. "
                "This is the label every RIIS weather model learns, so its bias is the models' bias.\n\n")
        f.write("| District | Days | Gauges/day | Station mm/yr | ERA5 mm/yr | Ratio | r daily | p99 ratio | Heavy-day POD | Heavy-day FAR |\n|---|---|---|---|---|---|---|---|---|---|\n")
        for n, d in ds.items():
            f.write(f"| {n} | {d['n_days']} | {d['stations_mean']} | {d['annual_total_station_mm']} | {d['annual_total_era5_mm']} | "
                    f"{d['ratio_era5_over_station']} | {d['pearson_r_daily']} | {d['quantile_ratio_era5_over_station']['p99']} | "
                    f"{d['heavy_day']['pod']} | {d['heavy_day']['far']} |\n")
        if "summary" in report:
            s = report["summary"]
            f.write(f"\nMedian ratio {s['median_ratio_era5_over_station']}, median p99 ratio {s['median_p99_ratio']}, "
                    f"median heavy-day POD {s['median_heavy_day_pod']}. {s['reading']}.\n")
        f.write("\nPOD = share of observed heavy days (>= 64.5 mm) that the reanalysis also shows as heavy; FAR = share of reanalysis "
                "heavy days with no gauge support. The JSON at app/data/station_bias.json carries monthly bias and quantile tables "
                "and is served with every impact response for the district.\n")
    print(f"\nwrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
