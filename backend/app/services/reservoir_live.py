"""Live reservoir telemetry from public daily reports.

Sources (both plain HTML tables, no API, no login):
  - Chennai Metro Water (CMWSSB) lake levels: https://cmwssb.tn.gov.in/lake-level
    Poondi, Cholavaram, Puzhal (Red Hills), Kannankottai Thervoy Kandigai,
    Chembarambakkam, Veeranam. Daily. `?date=dd-mm-yyyy` gives past days.
  - KSEB dam safety daily report: https://dams.kseb.in/?page_id=45
    Idukki, Idamalayar, Kakki, Sholayar, ... with alert levels and spill. Daily.

The Tamil Nadu WRD statewide table and India-WRIS were checked on 7 Oct 2026 and
did not return data, so Mettur / Bhavanisagar stay on their seeded values and are
labelled `seed`.

Units: CMWSSB reports mcft and cusecs; KSEB reports MCM and MCM/day. Everything is
stored as mcft and m3/s to match the Reservoir model.
"""
import os
import re
import json
import html
import time
import asyncio
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, text

CMWSSB_URL = "https://cmwssb.tn.gov.in/lake-level"
KSEB_INDEX = "https://dams.kseb.in/?page_id=45"
UA = "RIIS-Reservoirs/1.0 (rainfall impact research)"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cache")
STATE_PATH = os.path.join(CACHE_DIR, "reservoirs_live.json")
HISTORY_DIR = os.path.join(CACHE_DIR, "reservoir_history")

MCM_TO_MCFT = 35.3147
CUSEC_TO_CMS = 0.0283168

# Reservoirs we track, keyed by the name each source prints.
CMWSSB_MAP = {  # source name -> (code, display name, lat, lon)
    "POONDI": ("PO", "Poondi", 13.25, 80.07),
    "CHOLAVARAM": ("CH", "Cholavaram", 13.23, 80.23),
    "PUZHAL": ("RD", "Puzhal (Red Hills)", 13.18, 80.18),
    "KANNANKOTTAI THERVOY KANDIGAI": ("KT", "Kannankottai Thervoy Kandigai", 13.33, 80.03),
    "CHEMBARAMBAKKAM": ("CB", "Chembarambakkam", 13.00, 80.06),
    "VEERANAM": ("VR", "Veeranam", 11.33, 79.55),
}
KSEB_MAP = {
    "IDUKKI": ("ID", "Idukki", 9.85, 76.98),
    "IDAMALAYAR": ("IM", "Idamalayar", 10.22, 76.70),
    "KAKKI": ("KK", "Kakki-Anathode", 9.34, 77.15),
    "SHOLAYAR": ("SY", "Sholayar (Kerala)", 10.30, 76.78),
}
# Seeded rows with no live source behind them (kept, labelled "seed")
KEEP_SEED = {"MB", "ML", "BM"}
# Seeded rows that are duplicates or not identifiable reservoirs (removed on first sync)
DROP_SEED = {"SH", "KR", "AK", "VB", "PE", "ER", "TK", "HK"}

_state = {"fetched_at": None, "sources": {}, "rows": {}}


# ── Parsing ───────────────────────────────────────────────────────────────────
def _cells(row_html):
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
            for c in re.findall(r"<t[hd].*?</t[hd]>", row_html, flags=re.S | re.I)]


def _num(s):
    if s is None:
        return None
    s = s.replace(",", "").replace("ft", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_cmwssb(page: str) -> dict:
    tables = re.findall(r"<table.*?</table>", page, flags=re.S | re.I)
    as_on = None
    m = re.search(r"As On\s*-?\s*(\d{2}/\d{2}/\d{4})", page)
    if m:
        as_on = datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
    rows = {}
    for t in tables:
        trs = re.findall(r"<tr.*?</tr>", t, flags=re.S | re.I)
        if not trs or "RESERVOIR" not in _cells(trs[0])[0].upper():
            continue
        for tr in trs[1:]:
            c = _cells(tr)
            if len(c) < 9 or c[0].upper() == "TOTAL":
                continue
            name = c[0].upper().strip()
            rows[name] = {
                "full_level_ft": _num(c[1]), "capacity_mcft": _num(c[2]), "level_ft": _num(c[3]),
                "storage_mcft": _num(c[4]), "storage_pct": _num(c[5]),
                "inflow_cms": (_num(c[6]) or 0.0) * CUSEC_TO_CMS, "outflow_cms": (_num(c[7]) or 0.0) * CUSEC_TO_CMS,
                "inflow_raw": c[6], "outflow_raw": c[7],
                "rainfall_mm": _num(c[8]), "last_year_mcft": _num(c[9]) if len(c) > 9 else None,
                "observed_at": as_on, "source": "cmwssb",
            }
    return {"as_on": as_on, "rows": rows}


def parse_kseb_index(page: str):
    links = re.findall(r'href="([^"]+)"[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</a>', page, flags=re.S | re.I)
    if not links:
        return None, None
    url, d = links[0]
    return url.replace("&#038;", "&"), datetime.strptime(d, "%d.%m.%Y").date().isoformat()


def parse_kseb_daily(page: str, observed_at: str) -> dict:
    rows = {}
    for t in re.findall(r"<table.*?</table>", page, flags=re.S | re.I):
        trs = re.findall(r"<tr.*?</tr>", t, flags=re.S | re.I)
        if not trs or "Reservoir" not in " ".join(_cells(trs[0])):
            continue
        for tr in trs[1:]:
            c = _cells(tr)
            if len(c) < 12 or not c[0].isdigit() or c[1].strip().isdigit():
                continue   # skip the column-numbering row under the header
            name = re.sub(r"\s*\(.*?\)", "", c[1]).split("–")[0].split("-")[0].strip().upper()
            level = _num(c[5]); frl = _num(c[3])
            storage_mcm = _num(c[9]); pct = _num(c[10])
            inflow_mcm = _num(c[11]) or 0.0
            avg_in_cumecs = _num(c[12]) if len(c) > 12 else None
            # 14 power house discharge, 15 spill, 17 = 14 + 15 total discharge (MCM/day), 18 rainfall (mm)
            spill = _num(c[14]) if len(c) > 14 else None
            total_out_mcm = _num(c[16]) if len(c) > 16 else None
            if total_out_mcm is None:
                total_out_mcm = (_num(c[13]) or 0.0) + (spill or 0.0)
            rain_mm = _num(c[17]) if len(c) > 17 else None
            blue, orange, red = _num(c[6]), _num(c[7]), _num(c[8])
            alert = None
            if level is not None:
                if red is not None and level >= red:
                    alert = "red"
                elif orange is not None and level >= orange:
                    alert = "orange"
                elif blue is not None and level >= blue:
                    alert = "blue"
            cap_mcft = (storage_mcm / (pct / 100.0) * MCM_TO_MCFT) if storage_mcm and pct else None
            rows[name] = {
                "full_level_ft": frl, "level_ft": level, "level_unit": "ft" if "ft" in c[3] else "m",
                "capacity_mcft": round(cap_mcft, 1) if cap_mcft else None,
                "storage_mcft": round(storage_mcm * MCM_TO_MCFT, 1) if storage_mcm is not None else None,
                "storage_pct": pct,
                "inflow_cms": round(avg_in_cumecs if avg_in_cumecs is not None else inflow_mcm * 1e6 / 86400, 2),
                "outflow_cms": round((total_out_mcm or 0.0) * 1e6 / 86400, 2),
                "spill_mcm": spill, "rainfall_mm": rain_mm, "alert_level": alert,
                "alert_levels": {"blue": blue, "orange": orange, "red": red},
                "remarks": c[-1][:160] if c[-1] and not c[-1].replace(".", "").isdigit() else None,
                "observed_at": observed_at, "source": "kseb",
            }
    return rows


# ── Fetching ──────────────────────────────────────────────────────────────────
async def fetch_cmwssb(client: httpx.AsyncClient, date: str | None = None) -> dict:
    params = {"date": date} if date else None   # dd-mm-yyyy
    r = await client.get(CMWSSB_URL, params=params, headers={"User-Agent": UA})
    r.raise_for_status()
    return parse_cmwssb(r.text)


async def fetch_kseb(client: httpx.AsyncClient) -> dict:
    r = await client.get(KSEB_INDEX, headers={"User-Agent": UA})
    r.raise_for_status()
    url, observed = parse_kseb_index(r.text)
    if not url:
        raise ValueError("no dated report link on KSEB index")
    r2 = await client.get(url, headers={"User-Agent": UA})
    r2.raise_for_status()
    return {"as_on": observed, "url": url, "rows": parse_kseb_daily(r2.text, observed)}


# ── Risk model ────────────────────────────────────────────────────────────────
def overflow_probability(pct, inflow_cms, outflow_cms, alert=None, rainfall_mm=0.0):
    """0-100. Storage fraction is the base; net inflow and alert levels push it up."""
    pct = pct or 0.0
    p = max(0.0, (pct - 60.0) / 40.0) ** 1.5 * 70.0           # 60% -> 0, 100% -> 70
    net = (inflow_cms or 0.0) - (outflow_cms or 0.0)
    if net > 0 and pct >= 75:
        p += min(20.0, net / 5.0)                              # filling while already high
    if (rainfall_mm or 0) >= 25 and pct >= 70:
        p += 8.0
    p += {"blue": 15.0, "orange": 30.0, "red": 45.0}.get(alert, 0.0)
    return round(min(100.0, p), 1)


def risk_class(pct, prob):
    if pct > 95 or prob > 80:
        return "extreme"
    if pct > 85 or prob > 50:
        return "high"
    if pct > 70 or prob > 20:
        return "mod"
    return "safe"


# ── Schema + sync ─────────────────────────────────────────────────────────────
EXTRA_COLUMNS = {
    "source": "VARCHAR(16) DEFAULT 'seed'", "observed_at": "VARCHAR(10)", "level_ft": "FLOAT",
    "full_level_ft": "FLOAT", "storage_pct": "FLOAT", "rainfall_mm": "FLOAT", "last_year_mcft": "FLOAT",
    "alert_level": "VARCHAR(8)", "remarks": "VARCHAR(200)", "source_url": "VARCHAR(200)",
}


async def ensure_schema(db):
    cols = {row[1] for row in (await db.execute(text("PRAGMA table_info(reservoirs)"))).fetchall()}
    for name, ddl in EXTRA_COLUMNS.items():
        if name not in cols:
            await db.execute(text(f"ALTER TABLE reservoirs ADD COLUMN {name} {ddl}"))
    await db.commit()


def _save_state():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(_state, f, indent=1, default=str)
    except Exception as e:
        print(f"[RIIS-Reservoirs] state save failed: {e}")


def load_state():
    global _state
    if _state["fetched_at"] is None and os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                _state = json.load(f)
        except Exception:
            pass
    return _state


async def sync_reservoirs(db) -> dict:
    """Fetch both sources and upsert the reservoirs table. Returns a summary."""
    from app.models import Reservoir
    await ensure_schema(db)
    summary = {"fetched_at": datetime.utcnow().isoformat(), "sources": {}, "updated": [], "added": [], "removed": []}
    live = {}
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        results = await asyncio.gather(fetch_cmwssb(client), fetch_kseb(client), return_exceptions=True)
    for key, res, mapping, url in (("cmwssb", results[0], CMWSSB_MAP, CMWSSB_URL), ("kseb", results[1], KSEB_MAP, KSEB_INDEX)):
        if isinstance(res, Exception):
            summary["sources"][key] = {"ok": False, "error": str(res)[:160]}
            continue
        matched = 0
        for src_name, (code, disp, lat, lon) in mapping.items():
            row = res["rows"].get(src_name)
            if row:
                live[code] = dict(row, name=disp, lat=lat, lon=lon, source_url=res.get("url", url))
                matched += 1
        summary["sources"][key] = {"ok": True, "as_on": res.get("as_on"), "rows_parsed": len(res["rows"]), "matched": matched}

    existing = {r.code: r for r in (await db.execute(select(Reservoir))).scalars().all()}
    for code in DROP_SEED:
        if code in existing and (getattr(existing[code], "source", "seed") or "seed") == "seed":
            await db.delete(existing[code])
            summary["removed"].append(code)
            existing.pop(code)

    for code, row in live.items():
        pct = row.get("storage_pct")
        cap = row.get("capacity_mcft")
        cur = row.get("storage_mcft")
        if cap is None and cur is not None and pct:
            cap = cur / (pct / 100.0)
        if cur is None and cap is not None and pct is not None:
            cur = cap * pct / 100.0
        if cap is None or cur is None:
            continue
        prob = overflow_probability(pct, row.get("inflow_cms"), row.get("outflow_cms"), row.get("alert_level"), row.get("rainfall_mm") or 0)
        r = existing.get(code)
        if r is None:
            r = Reservoir(code=code, name=row["name"], lat=row["lat"], lon=row["lon"], capacity_mcft=cap, current_mcft=cur,
                          inflow_cms=row.get("inflow_cms") or 0.0, outflow_cms=row.get("outflow_cms") or 0.0,
                          baseline_inflow=row.get("inflow_cms") or 0.0, baseline_outflow=row.get("outflow_cms") or 0.0)
            db.add(r)
            summary["added"].append(code)
        else:
            summary["updated"].append(code)
        r.name = row["name"]; r.lat = row["lat"]; r.lon = row["lon"]
        r.capacity_mcft = round(cap, 1); r.current_mcft = round(cur, 1)
        r.inflow_cms = round(row.get("inflow_cms") or 0.0, 2); r.outflow_cms = round(row.get("outflow_cms") or 0.0, 2)
        r.overflow_prob = prob; r.risk_class = risk_class(pct or 0, prob)
        r.source = row["source"]; r.observed_at = row.get("observed_at"); r.level_ft = row.get("level_ft")
        r.full_level_ft = row.get("full_level_ft"); r.storage_pct = pct; r.rainfall_mm = row.get("rainfall_mm")
        r.last_year_mcft = row.get("last_year_mcft"); r.alert_level = row.get("alert_level")
        r.remarks = row.get("remarks"); r.source_url = row.get("source_url")
        r.updated_at = datetime.utcnow()
    for code, r in existing.items():
        if code not in live and not getattr(r, "source", None):
            r.source = "seed"
            r.storage_pct = round(100 * r.current_mcft / r.capacity_mcft, 1) if r.capacity_mcft else None
    await db.commit()

    _state.update({"fetched_at": summary["fetched_at"], "sources": summary["sources"],
                   "rows": {k: {kk: vv for kk, vv in v.items() if kk != "alert_levels"} for k, v in live.items()}})
    _save_state()
    print(f"[RIIS-Reservoirs] sync: {summary['sources']} updated={len(summary['updated'])} added={summary['added']} removed={summary['removed']}")
    return summary


# ── History (CMWSSB only; one request per day, cached on disk) ────────────────
async def cmwssb_history(code: str, days: int = 14) -> list:
    src_name = next((k for k, v in CMWSSB_MAP.items() if v[0] == code), None)
    if src_name is None:
        return []
    os.makedirs(HISTORY_DIR, exist_ok=True)
    out = []
    today = datetime.now().date()
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        for i in range(days, -1, -1):
            d = today - timedelta(days=i)
            path = os.path.join(HISTORY_DIR, f"cmwssb_{d.isoformat()}.json")
            data = None
            if os.path.exists(path) and (i > 0 or time.time() - os.path.getmtime(path) < 3600):
                try:
                    with open(path) as f:
                        data = json.load(f)
                except Exception:
                    data = None
            if data is None:
                try:
                    res = await fetch_cmwssb(client, d.strftime("%d-%m-%Y"))
                    data = res["rows"]
                    if res.get("as_on") == d.isoformat() or i == 0:
                        with open(path, "w") as f:
                            json.dump(data, f)
                    elif res.get("as_on") != d.isoformat():
                        data = None   # site returned a different day (no record)
                except Exception:
                    data = None
            row = (data or {}).get(src_name)
            if row:
                out.append({"date": d.isoformat(), "storage_mcft": row.get("storage_mcft"), "storage_pct": row.get("storage_pct"),
                            "level_ft": row.get("level_ft"), "inflow_cms": round(row.get("inflow_cms") or 0, 2),
                            "outflow_cms": round(row.get("outflow_cms") or 0, 2), "rainfall_mm": row.get("rainfall_mm")})
    return out
