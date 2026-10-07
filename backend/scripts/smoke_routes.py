"""Smoke test for Safe Routes: site build, scoring, routing and geocoding for Potheri.

Runs in-process (no server needed) and prints timings. Target: under 8 s cold
after the first ever fetch is cached on disk / DB, under 1 s warm.

    cd backend
    python scripts/smoke_routes.py [lat lon]
"""
import os
import sys
import time
import asyncio
import collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import app.models  # noqa: F401
from app.database import init_db, async_session
from app.services import roads as R


async def main():
    lat = float(sys.argv[1]) if len(sys.argv) > 2 else 12.823
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else 80.044
    await init_db()
    async with async_session() as db:
        t = time.time()
        b = await R.ensure_site(db, lat, lon)
        print(f"site (cold or db) {time.time()-t:.1f}s", {k: b["site"][k] for k in ("id", "n_ways", "n_nodes", "n_segments", "span_km", "dem_res_m")})
        segs = b["segments"]
        print("  highway mix", collections.Counter(s["highway"] for s in segs.values()).most_common(6))
        print("  culvert_near", sum(1 for s in segs.values() if s["culvert_near"]), "tunnel", sum(1 for s in segs.values() if s["tunnel"]),
              "bridge", sum(1 for s in segs.values() if s["bridge"]), "oneway", sum(1 for s in segs.values() if s["oneway"]))
        print("  elev missing", sum(1 for s in segs.values() if s["elev_m"] is None),
              "hand sample", [s["hand_m"] for s in list(segs.values())[:6]], "water_m sample", [s["dist_water_m"] for s in list(segs.values())[:4]])
        t = time.time(); await R.ensure_site(db, lat, lon); print(f"site warm {time.time()-t:.3f}s")

        for mm, dur in [(80, 3), (150, 3), (240, 3)]:
            t = time.time()
            st = await R.score_segments(db, b, mm, dur)
            c = collections.Counter(v["status"] for v in st.values())
            print(f"score {mm}mm/{dur}h {time.time()-t:.2f}s", dict(c), "max depth", max(v["max_depth_m"] for v in st.values()))
        t = time.time(); await R.score_segments(db, b, 80, 3); print(f"score cached {time.time()-t:.3f}s")

        st = await R.score_segments(db, b, 240, 3)
        dest = (lat + 0.011, lon + 0.008)   # ~1.5 km NE
        t = time.time()
        r = R.find_routes(b, st, (lat, lon), dest, "car", {"rainfall_mm": 240, "duration_h": 3})
        print(f"route {time.time()-t:.3f}s snapped={r['snapped']} reachable={r['reachable']} snap_m origin={r['origin']['snap_m']} dest={r['destination']['snap_m']}")
        if r.get("normal_route"):
            n = r["normal_route"]; print(f"  normal {n['length_m']} m {n['eta_min']} min worst={n['worst_status']} closed={n['closed_segments']}")
        if r.get("safe_route"):
            s = r["safe_route"]; print(f"  safe   {s['length_m']} m {s['eta_min']} min worst={s['worst_status']} points={len(s['geojson']['coordinates'])}")
        print("  closed_avoided", [(x["name"], x["max_depth_m"]) for x in r["closed_avoided"][:4]])
        for mode in ("bike", "walk"):
            r2 = R.find_routes(b, st, (lat, lon), dest, mode)
            print(f"  {mode}: reachable={r2['reachable']} eta={(r2['safe_route'] or {}).get('eta_min')}")
        t = time.time(); g = await R.geocode("railway station", lat, lon); print(f"geocode {time.time()-t:.1f}s", [(x['name'][:40], x['distance_km']) for x in g[:2]])
        t = time.time(); rv = await R.reverse(lat, lon); print(f"reverse {time.time()-t:.1f}s", rv["short"])


if __name__ == "__main__":
    asyncio.run(main())
