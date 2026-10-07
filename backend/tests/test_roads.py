"""Unit tests for the Safe Routes service (no network, no database).

Covers: graph build from fixture Overpass JSON, segment scoring on a synthetic DEM
with one pit, status thresholds, one-way handling, routing around a closed edge,
`reachable: false` when the only path is closed, and Nominatim proxy throttling.

    cd backend
    python -m pytest tests/test_roads.py -q
"""
import os
import sys
import time
import asyncio
import math

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.services import roads as R  # noqa: E402
from app.services.inundation import depth_grid  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────
def synthetic_grid(n=60, res_m=10.0, base=20.0, pit_depth=1.0, pit_center=(30, 30), pit_r=6):
    """Flat DEM with one round pit; lats descending, lons ascending like get_dem()."""
    dem = np.full((n, n), base, dtype=np.float32)
    yy, xx = np.mgrid[0:n, 0:n]
    d = np.sqrt((yy - pit_center[0]) ** 2 + (xx - pit_center[1]) ** 2)
    dem[d <= pit_r] -= pit_depth * (1 - d[d <= pit_r] / pit_r)   # cone-shaped pit
    lat0, lon0 = 12.8300, 80.0400
    dlat = res_m / 110_540.0
    dlon = res_m / (111_320.0 * math.cos(math.radians(lat0)))
    lats = np.array([lat0 - i * dlat for i in range(n)])          # descending
    lons = np.array([lon0 + j * dlon for j in range(n)])
    return {"dem": dem, "lats": lats, "lons": lons, "cell_w_m": res_m, "cell_h_m": res_m, "z": 14, "n": n,
            "res_m": res_m, "span_km": round(n * res_m / 1000, 2), "source": "synthetic"}


def _pt(grid, r, c):
    return {"lat": float(grid["lats"][r]), "lon": float(grid["lons"][c])}


def fixture_osm(grid):
    """Three ways: a straight road through the pit (A-B-C), a detour above it (A-D-C), and a one-way spur."""
    A, B, C, D, E = _pt(grid, 30, 5), _pt(grid, 30, 30), _pt(grid, 30, 55), _pt(grid, 10, 30), _pt(grid, 50, 30)
    def way(wid, tags, pts, ids):
        return {"type": "way", "id": wid, "tags": tags, "nodes": ids, "geometry": pts}
    return {"roads": [
        way(1, {"highway": "residential", "name": "Pit Road"}, [A, B, C], [1, 2, 3]),
        way(2, {"highway": "residential", "name": "Detour Road"}, [A, D, C], [1, 4, 3]),
        way(3, {"highway": "service", "name": "Spur", "oneway": "yes"}, [B, E], [2, 5]),
    ], "culvert_pts": [], "water_pts": []}


def make_bundle(grid, segs_list):
    segs = {i + 1: dict(s) for i, s in enumerate(segs_list)}
    graph, nodes = R.build_graph(segs)
    from scipy.spatial import cKDTree
    ids = list(nodes)
    tree = cKDTree(np.array([[nodes[i][0], nodes[i][1]] for i in ids]))
    return {"site": {"id": 1, "lat": float(grid["lats"][30]), "lon": float(grid["lons"][30]),
                     "bbox": {"south": float(grid["lats"].min()), "north": float(grid["lats"].max()),
                              "west": float(grid["lons"].min()), "east": float(grid["lons"].max())}},
            "segments": segs, "graph": graph, "nodes": nodes, "node_ids": ids, "tree": tree, "grid": grid}


# ── Tests ─────────────────────────────────────────────────────────────────────
def test_build_segments_and_graph():
    grid = synthetic_grid()
    segs = R.build_segments(fixture_osm(grid), grid, impervious_pct=50.0)
    assert len(segs) == 5                      # 2 + 2 + 1 node-to-node segments
    assert all(s["length_m"] > 0 for s in segs)
    assert all(s["elev_m"] is not None for s in segs)
    # HAND proxy = midpoint elevation minus the 150 m window minimum: the Pit Road segment's
    # midpoint is flat ground 1 m above the pit floor inside its window, so HAND is the pit depth
    pit_seg = next(s for s in segs if s["name"] == "Pit Road" and s["to_node"] == 2)
    assert pit_seg["hand_m"] == pytest.approx(1.0, abs=0.05)
    assert all(0.0 <= s["hand_m"] <= 1.0 for s in segs)
    graph, nodes = R.build_graph({i + 1: s for i, s in enumerate(segs)})
    assert graph.has_edge(1, 2) and graph.has_edge(2, 1)      # two-way residential
    assert graph.has_edge(2, 5) and not graph.has_edge(5, 2)  # one-way spur
    assert len(nodes) == 5


def test_classify_thresholds():
    seg = {"tunnel": False, "bridge": False, "layer": 0, "culvert_near": False}
    assert R.classify(0.0, 0, seg) == "open"
    assert R.classify(0.149, 0, seg) == "open"
    assert R.classify(0.15, 0, seg) == "caution"
    assert R.classify(0.30, 0, seg) == "closed_cars"
    assert R.classify(0.60, 0, seg) == "closed_all"
    assert R.classify(0.06, 0, dict(seg, culvert_near=True)) == "caution"
    assert R.classify(2.0, 1, dict(seg, bridge=True)) == "open"                     # bridges stay open
    under = dict(seg, tunnel=True, layer=-1)
    assert R.classify(0.0, 0, under) == "caution"                                   # underpass at least caution
    assert R.classify(0.0, 0, under, any_wet_near=True) == "closed_cars"


def test_depth_grid_fills_the_pit():
    grid = synthetic_grid()
    dg = depth_grid(grid, net_mm=5.0)
    depth = dg["depth"]
    assert depth[30, 30] > 0.3                 # water concentrates in the pit
    assert depth[5, 5] == 0.0                  # flat ground stays dry while the pit has capacity


def test_routing_avoids_closed_edge_and_reports_unreachable():
    grid = synthetic_grid()
    segs = R.build_segments(fixture_osm(grid), grid, 50.0)
    b = make_bundle(grid, segs)
    # mark the two Pit Road segments closed, everything else open
    status = {sid: {"status": "closed_all" if s["name"] == "Pit Road" else "open", "max_depth_m": 0.8 if s["name"] == "Pit Road" else 0.0}
              for sid, s in b["segments"].items()}
    A, C = _pt(grid, 30, 5), _pt(grid, 30, 55)
    res = R.find_routes(b, status, (A["lat"], A["lon"]), (C["lat"], C["lon"]), "car")
    assert res["snapped"] and res["reachable"]
    assert res["normal_route"]["closed_segments"] == 2
    assert res["safe_route"]["closed_segments"] == 0
    assert all(s["name"] == "Detour Road" for s in res["safe_route"]["segments"])
    assert res["safe_route"]["length_m"] > res["normal_route"]["length_m"]
    assert len(res["closed_avoided"]) == 2
    # close the detour too: nothing passable remains for a car
    for sid, s in b["segments"].items():
        if s["name"] == "Detour Road":
            status[sid] = {"status": "closed_cars", "max_depth_m": 0.4}
    res2 = R.find_routes(b, status, (A["lat"], A["lon"]), (C["lat"], C["lon"]), "car")
    assert res2["reachable"] is False and res2["normal_route"] is not None
    assert len(res2["blocking_segments"]) == 2
    # a pedestrian may still wade through closed_cars at 4x cost
    res3 = R.find_routes(b, status, (A["lat"], A["lon"]), (C["lat"], C["lon"]), "walk")
    assert res3["reachable"] is True and res3["safe_route"]["worst_status"] == "closed_cars"


def test_snap_rejects_far_points():
    grid = synthetic_grid()
    b = make_bundle(grid, R.build_segments(fixture_osm(grid), grid, 50.0))
    node, dist = R.snap(b, float(grid["lats"][30]) + 0.05, float(grid["lons"][30]))   # ~5.5 km north
    assert node is None and dist > R.SNAP_MAX_M


def test_nominatim_throttle(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return [{"lat": "12.8", "lon": "80.0", "display_name": "x", "type": "place"}]

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, headers=None):
            calls.append(time.time())
            assert headers["User-Agent"].startswith("RIIS-SafeRoutes")
            return FakeResp()

    monkeypatch.setattr(R.httpx, "AsyncClient", FakeClient)
    R._geocode_cache.clear()
    R._nominatim_last = 0.0

    async def run():
        t0 = time.time()
        await asyncio.gather(R.geocode("a", 12.8, 80.0), R.geocode("b", 12.8, 80.0), R.geocode("c", 12.8, 80.0))
        return time.time() - t0
    elapsed = asyncio.run(run())
    assert len(calls) == 3
    assert elapsed >= 1.9                          # three requests cannot complete in under two seconds
    assert all(b - a >= 0.95 for a, b in zip(calls, calls[1:]))
    # cached: a repeat is instant and makes no request
    asyncio.run(R.geocode("a", 12.8, 80.0))
    assert len(calls) == 3
