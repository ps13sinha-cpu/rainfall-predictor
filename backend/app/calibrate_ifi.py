"""
RIIS - Calibrate the rainfall hazard curve against observed floods.

Joins the India Flood Inventory (IFI-Impacts v4, IIT Delhi, Zenodo 10.5281/zenodo.4742142; events by
district and date) to TNDMA rain-gauge district-days (1991-2023, 38 Tamil Nadu districts) and asks:
when the gauges recorded X mm, how often did a flood get recorded? That gives

  1. the discrimination (AUC) of 1-, 3- and 5-day rain totals and of the engine's accumulation
     score for flood days against dry days,
  2. the observed flood frequency inside each of the engine's four classes,
  3. an isotonic P(flood | 1-day rain) curve, rescaled to 0..100 as a data-driven replacement for
     the hand-set ACCUMULATION_CURVE in app/services/hyperlocal.py,
  4. per-district flood propensity (events per decade) as a check on the Historical modifier.

Only rainfall is calibrated here: the inventory is by district and day, so terrain, drainage and
the other hyperlocal modifiers cannot be fitted from it. The output is honest about that.

Usage:
    cd backend
    python -m app.calibrate_ifi      # writes app/data/calibration.json and docs/IFI_CALIBRATION.md
"""
import os
import re
import sys
import json
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
STATION_CSV = os.path.join(HERE, "..", "cache", "station", "tn_daily_rainfall_1991_2023.csv")
IFI_CSV = os.path.join(HERE, "data", "India_Flood_Inventory_v3.csv")
OUT_JSON = os.path.join(HERE, "data", "calibration.json")
OUT_MD = os.path.join(HERE, "..", "docs", "IFI_CALIBRATION.md")

# the engine's hand-set curves, copied so this script does not import the live engine mid-edit
ACCUMULATION_CURVE = [(0.0, 0.0), (64.5, 25.0), (115.6, 50.0), (204.5, 75.0), (350.0, 100.0)]
CLASS_EDGES = [(0, 25, "safe"), (25, 50, "mod"), (50, 75, "high"), (75, 101, "extreme")]

ALIASES = {  # IFI spelling -> TNDMA spelling
    "thoothukkudi": "Thoothukudi", "tuticorin": "Thoothukudi", "kanniyakumari": "Kanniyakumari", "kanyakumari": "Kanniyakumari",
    "kanniyakumariumari": "Kanniyakumari", "tiruchirappalli": "Thiruchirappalli", "trichy": "Thiruchirappalli",
    "tiruchirapalli": "Thiruchirappalli", "viluppuram": "Villupuram", "villupuram": "Villupuram", "nilgiris": "The Nilgiris",
    "the nilgiris": "The Nilgiris", "kanchipuram": "Kancheepuram", "kancheepuram": "Kancheepuram", "thiruvallur": "Tiruvallur",
    "tiruvallur": "Tiruvallur", "tirupattur": "Tirupathur", "tirupathur": "Tirupathur", "sivaganga": "Sivagangai",
    "sivagangai": "Sivagangai", "tirunelveli": "Tirunelveli", "thiruvarur": "Thiruvarur", "tiruvarur": "Thiruvarur",
    "tiruppur": "Tiruppur", "tirupur": "Tiruppur", "nagapattinam": "Nagapattinam", "nagappattinam": "Nagapattinam",
    "pudukkottai": "Pudukkottai", "pudukottai": "Pudukkottai", "ramanathapuram": "Ramanathapuram", "virudhunagar": "Virudhunagar",
    "tiruvannamalai": "Tiruvannamalai", "thiruvannamalai": "Tiruvannamalai", "dindigul": "Dindigul", "mayiladuthurai": "Mayiladuthurai",
}


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


def norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("*", ""))


def piecewise(curve, x):
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """Rank AUC (Mann-Whitney), ties counted half."""
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order), dtype=float)
    all_s = np.concatenate([pos, neg])[order]
    i = 0
    while i < len(all_s):
        j = i
        while j + 1 < len(all_s) and all_s[j + 1] == all_s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    r_pos = ranks[:len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)))


def isotonic(x: np.ndarray, y: np.ndarray, n_bins: int = 40):
    """Pool-adjacent-violators on binned means: monotone P(flood | rain)."""
    edges = np.unique(np.quantile(x[x > 0], np.linspace(0, 1, n_bins)))
    edges = np.concatenate([[0.0], edges[edges > 0], [x.max() + 1]])
    idx = np.digitize(x, edges) - 1
    xs, ps, ws = [], [], []
    for b in range(len(edges) - 1):
        m = idx == b
        if m.sum() == 0:
            continue
        xs.append(float(x[m].mean())); ps.append(float(y[m].mean())); ws.append(int(m.sum()))
    xs, ps, ws = np.array(xs), np.array(ps), np.array(ws, dtype=float)
    # PAV
    blocks = [[i, i, ps[i] * ws[i], ws[i]] for i in range(len(ps))]
    i = 0
    while i < len(blocks) - 1:
        a, b = blocks[i], blocks[i + 1]
        if a[2] / a[3] > b[2] / b[3]:
            blocks[i] = [a[0], b[1], a[2] + b[2], a[3] + b[3]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    fitted = np.empty(len(ps))
    for lo, hi, s, w in blocks:
        fitted[lo:hi + 1] = s / w
    return xs, fitted, ws


def main():
    d = station_district_daily(STATION_CSV, "1991-01-01", "2023-12-31")
    d = d.rename(columns={"st_mean": "r1", "st_max": "r1max", "st_n": "n_st"})
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["dist", "date"]).reset_index(drop=True)
    # reindex each district to a full daily calendar so rolling sums are honest
    full = []
    for dist, grp in d.groupby("dist"):
        idx = pd.date_range(grp["date"].min(), grp["date"].max(), freq="D")
        s = grp.set_index("date").reindex(idx)
        s["dist"] = dist
        s["gap"] = s["r1"].isna()
        s["r1"] = s["r1"].fillna(0.0); s["r1max"] = s["r1max"].fillna(0.0)
        s["r3"] = s["r1"].rolling(3, min_periods=1).sum()
        s["r5"] = s["r1"].rolling(5, min_periods=1).sum()
        s["r7"] = s["r1"].rolling(7, min_periods=1).sum()
        s["ant30"] = s["r1"].shift(1).rolling(30, min_periods=1).sum().fillna(0.0)
        full.append(s.reset_index().rename(columns={"index": "date"}))
    d = pd.concat(full, ignore_index=True)
    d = d[~d["gap"]]
    tn_dists = set(d["dist"].unique())
    tn_norm = {norm(x): x for x in tn_dists}
    tn_norm.update({norm(k): v for k, v in ALIASES.items()})

    ev = pd.read_csv(IFI_CSV, low_memory=False)
    ev = ev[ev["State"].astype(str).str.contains("Tamil", na=False)].copy()
    ev["start"] = pd.to_datetime(ev["Start Date"], dayfirst=True, errors="coerce")
    ev["dur"] = pd.to_numeric(ev["Duration(Days)"], errors="coerce").fillna(1).clip(1, 10)
    ev = ev.dropna(subset=["start"])
    ev = ev[ev["start"] >= "1991-01-01"]
    flood_days, misses, matched_events = set(), {}, 0
    buffer_days = set()
    for _, e in ev.iterrows():
        names = [n.strip() for n in str(e["Districts"]).split(",") if n.strip()]
        hit = False
        for n in names:
            key = norm(n)
            dist = tn_norm.get(key)
            if dist is None:
                misses[n] = misses.get(n, 0) + 1
                continue
            hit = True
            for k in range(-1, int(e["dur"]) + 1):           # the day before the record through the event
                flood_days.add((dist, (e["start"] + pd.Timedelta(days=k)).normalize()))
            for k in range(-4, int(e["dur"]) + 5):           # excluded from the negatives: timing in the record is coarse
                buffer_days.add((dist, (e["start"] + pd.Timedelta(days=k)).normalize()))
        matched_events += int(hit)
    keys = list(zip(d["dist"], d["date"]))
    d["flood"] = [1 if k in flood_days else 0 for k in keys]
    d["buffer"] = [1 if (k in buffer_days and k not in flood_days) else 0 for k in keys]
    dd = d[d["buffer"] == 0].copy()
    y = dd["flood"].to_numpy()
    print(f"district-days {len(dd)}  flood days {int(y.sum())}  events matched {matched_events}/{len(ev)}  unmatched names {len(misses)}")

    dd["acc_score"] = [max(piecewise(ACCUMULATION_CURVE, a), piecewise(ACCUMULATION_CURVE, b / 3.0 * 1.0 * 3.0 / 3.0),
                           piecewise(ACCUMULATION_CURVE, c / 5.0 * 24.0 / 24.0))
                       for a, b, c in zip(dd["r1"], dd["r3"], dd["r5"])]
    # the engine scales multi-day totals by 24/duration_h; for a 3-day total that is r3/3, for 5-day r5/5
    dd["acc_score"] = [max(piecewise(ACCUMULATION_CURVE, a), piecewise(ACCUMULATION_CURVE, b / 3.0),
                           piecewise(ACCUMULATION_CURVE, c / 5.0)) for a, b, c in zip(dd["r1"], dd["r3"], dd["r5"])]
    dd["acc_score_unscaled3"] = [max(piecewise(ACCUMULATION_CURVE, a), piecewise(ACCUMULATION_CURVE, b))
                                 for a, b in zip(dd["r1"], dd["r3"])]
    aucs = {k: round(auc(y, dd[k].to_numpy(float)), 4) for k in ["r1", "r1max", "r3", "r5", "r7", "acc_score", "acc_score_unscaled3"]}
    aucs["r3_plus_ant30"] = round(auc(y, (dd["r3"] + 0.25 * dd["ant30"]).to_numpy(float)), 4)
    print("AUC:", aucs)

    # flood frequency per engine class (on the 1-day accumulation score) and lift over the base rate
    base = float(y.mean())
    classes = {}
    for lo, hi, name in CLASS_EDGES:
        m = (dd["acc_score"] >= lo) & (dd["acc_score"] < hi)
        n = int(m.sum())
        classes[name] = {"district_days": n, "flood_days": int(dd.loc[m, "flood"].sum()),
                         "flood_rate": round(float(dd.loc[m, "flood"].mean()), 4) if n else None,
                         "lift_over_base": round(float(dd.loc[m, "flood"].mean() / base), 1) if n and base > 0 else None}
    # recall of flood days at each class floor
    recall = {name: round(float(dd.loc[(dd["acc_score"] >= lo) & (dd["flood"] == 1)].shape[0] / max(y.sum(), 1)), 3)
              for lo, _, name in CLASS_EDGES}

    # isotonic P(flood | r1) -> rescaled curve
    xs, ps, ws = isotonic(dd["r1"].to_numpy(float), y.astype(float))
    p_max = float(ps.max()) if len(ps) else 0.0
    cal_curve = [(0.0, 0.0)]
    for x, p, w in zip(xs, ps, ws):
        if w >= 30 and x > 0:
            cal_curve.append((round(float(x), 1), round(100.0 * p / p_max, 1) if p_max > 0 else 0.0))
    # thin to the knots that change value and cap at 100
    thinned, last = [], None
    for x, v in cal_curve:
        if last is None or v > last:
            thinned.append([x, min(v, 100.0)]); last = v
    # the IMD anchors the hand curve used, with the observed flood rate at each
    anchors = {}
    for thr in [64.5, 115.6, 204.5]:
        m = dd["r1"] >= thr
        anchors[str(thr)] = {"district_days": int(m.sum()), "flood_rate": round(float(dd.loc[m, "flood"].mean()), 4) if m.sum() else None}

    # per-district propensity
    per_dist = []
    for dist, grp in dd.groupby("dist"):
        yrs = (grp["date"].max() - grp["date"].min()).days / 365.25
        per_dist.append({"district": dist, "years": round(yrs, 1), "flood_days": int(grp["flood"].sum()),
                         "flood_days_per_decade": round(float(grp["flood"].sum() / max(yrs, 1) * 10), 1),
                         "heavy_days_per_year": round(float((grp["r1"] >= 64.5).sum() / max(yrs, 1)), 2),
                         "flood_rate_on_heavy_days": round(float(grp.loc[grp["r1"] >= 64.5, "flood"].mean()), 3) if (grp["r1"] >= 64.5).sum() else None})
    per_dist.sort(key=lambda r: -r["flood_days_per_decade"])

    out = {
        "computed_at": datetime.utcnow().isoformat(),
        "method": ("India Flood Inventory TN events (district, date, duration) joined to TNDMA Revenue-gauge district-day means 1991-2023 (unreported days = dry); "
                   "flood day = day before through end of a recorded event; +/-4 day buffer excluded from negatives; "
                   "rank AUC of rain totals and of the engine accumulation score; isotonic P(flood|1-day rain) rescaled to 0..100"),
        "n_events": int(matched_events), "n_events_in_inventory": int(len(ev)),
        "n_district_days": int(len(dd)), "n_flood_days": int(y.sum()), "base_flood_rate": round(base, 5),
        "auc": aucs["acc_score"], "auc_by_feature": aucs,
        "class_flood_rates": classes, "flood_day_recall_at_class_floor": recall,
        "imd_threshold_flood_rates": anchors,
        "hand_set_accumulation_curve": ACCUMULATION_CURVE,
        "calibrated_accumulation_curve": thinned,
        "per_district": per_dist, "unmatched_district_names": misses,
        "scope": "rainfall term only: the inventory is by district and day, so elevation, drainage and the other modifiers are not calibrated by this",
        "note": (f"Rainfall accumulation score separates flood days from dry days with AUC {aucs['acc_score']}; "
                 f"flood rate rises from {classes['safe']['flood_rate']} in 'safe' to {classes['extreme']['flood_rate']} in 'extreme'. "
                 "Site-level modifiers remain expert-set."),
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=2)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# Rainfall hazard calibration against the India Flood Inventory\n\n")
        f.write(f"Computed {out['computed_at'][:10]}. {out['method']}.\n\n")
        f.write(f"Events matched: {matched_events} of {len(ev)} Tamil Nadu events since 1991. District-days: {len(dd):,}, "
                f"flood days: {int(y.sum()):,} (base rate {base:.4f}).\n\n")
        f.write("## Discrimination (rank AUC, flood day vs other day)\n\n| Feature | AUC |\n|---|---|\n")
        for k, v in aucs.items():
            f.write(f"| {k} | {v} |\n")
        f.write("\n## Observed flood rate inside each engine class (accumulation score only)\n\n| Class | District-days | Flood days | Flood rate | Lift | Recall at floor |\n|---|---|---|---|---|---|\n")
        for lo, _, name in CLASS_EDGES:
            c = classes[name]
            f.write(f"| {name} | {c['district_days']:,} | {c['flood_days']} | {c['flood_rate']} | {c['lift_over_base']}x | {recall[name]} |\n")
        f.write("\n## Flood rate above IMD thresholds\n\n| 1-day rain >= | District-days | Flood rate |\n|---|---|---|\n")
        for k, v in anchors.items():
            f.write(f"| {k} mm | {v['district_days']} | {v['flood_rate']} |\n")
        f.write("\n## Calibrated accumulation curve (isotonic, rescaled to 100 at the maximum observed flood rate)\n\n")
        f.write("Hand-set: " + ", ".join(f"{x} mm -> {v}" for x, v in ACCUMULATION_CURVE) + "\n\n")
        f.write("Calibrated: " + ", ".join(f"{x} mm -> {v}" for x, v in thinned) + "\n\n")
        f.write("## Per-district flood propensity (top 12)\n\n| District | Years | Flood days / decade | Heavy days / yr | Flood rate on heavy days |\n|---|---|---|---|---|\n")
        for r in per_dist[:12]:
            f.write(f"| {r['district']} | {r['years']} | {r['flood_days_per_decade']} | {r['heavy_days_per_year']} | {r['flood_rate_on_heavy_days']} |\n")
        f.write(f"\n## Scope\n\n{out['scope']}.\n")
        if misses:
            f.write("\nUnmatched inventory district names: " + ", ".join(f"{k} ({v})" for k, v in sorted(misses.items())) + "\n")
    print(f"wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
