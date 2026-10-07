"""Safe Routes: road network, flood scoring and flood-avoiding routing.

Data flow for a site (a hyperlocal point and the ~3.6 km DEM window around it):

  Overpass (OSM roads, culverts, water)  ─┐
  AWS Terrain Tiles via get_dem(z=14)    ─┼─► RoadSegment rows + networkx graph (cached)
  get_geofactors / get_antecedent        ─┘
                                            │
  scenario (rainfall, duration)  ──► net_ponding_mm ──► depth_grid ──► sample along
                                            segments ──► status per segment (cached)
                                            │
  origin, destination, mode ──► A* on the penalised graph (safe) and on raw length (normal)

Everything external is free: OSM via Overpass, Nominatim for geocoding (proxied,
one request per second), terrain tiles from AWS Open Data.
"""
import math
import time
import json
import asyncio
from datetime import datetime, timedelta

import httpx
import numpy as np
import networkx as nx
from scipy.spatial import cKDTree
from sqlalchemy import select, delete

import app.models  # noqa: F401  (registers the road tables for Base.metadata.create_all)
from app.services.hyperlocal import _overpass, get_geofactors, get_antecedent, _haversine_km
from app.services.inundation import get_dem, net_ponding_mm, depth_grid

# ── Config ────────────────────────────────────────────────────────────────────
DEM_Z, DEM_N = 14, 384                       # ~9.5 m cells, ~3.6 km window
SITE_REFRESH_DAYS = 7
SITE_MATCH_KM = 1.0                           # reuse a site whose centre is within this distance
STATUS_TTL = 6 * 3600
MAX_SITES_IN_MEMORY = 8
SNAP_MAX_M = 300.0
SAMPLE_STEP_M = 10.0
REPORT_MATCH_M = 25.0
CULVERT_NEAR_M = 40.0
HAND_WINDOW_M = 150.0

HIGHWAY_RE = ("motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|"
              "tertiary|tertiary_link|unclassified|residential|living_street|service")
HIGHWAY_CLASS = {"motorway": 0, "motorway_link": 0, "trunk": 1, "trunk_link": 1, "primary": 2, "primary_link": 2,
                 "secondary": 3, "secondary_link": 3, "tertiary": 4, "tertiary_link": 4, "unclassified": 5,
                 "residential": 6, "living_street": 7, "service": 8}
NO_BIKE_WALK = {"motorway", "motorway_link", "trunk"}
STATUS_ORDER = {"open": 0, "caution": 1, "closed_cars": 2, "closed_all": 3}
PENALTY = {  # multiplier on length; None = edge removed
    "car":  {"open": 1.0, "caution": 3.0, "closed_cars": None, "closed_all": None},
    "bike": {"open": 1.0, "caution": 4.0, "closed_cars": None, "closed_all": None},
    "walk": {"open": 1.0, "caution": 2.0, "closed_cars": 4.0, "closed_all": None},
}
SPEED_KMH = {"car": 30.0, "bike": 15.0, "walk": 5.0}

NOMINATIM = "https://nominatim.openstreetmap.org"
NOMINATIM_UA = "RIIS-SafeRoutes/1.0 (rainfall impact research)"   # Nominatim blocks placeholder contact addresses

# ── In-process caches (bounded) ───────────────────────────────────────────────
_sites = {}        # site_id -> {"site": dict, "segments": {id: dict}, "graph": DiGraph, "nodes": {id: (lat, lon)},
                   #             "tree": cKDTree, "node_ids": [...], "grid": dem grid, "geo": .., "ant": .., "loaded": ts}
_status = {}       # (site_id, scenario_key) -> (ts, {segment_id: {...}})
_geocode_cache = {}
_nominatim_lock = asyncio.Lock()
_nominatim_last = 0.0


def scenario_key(rainfall_mm: float, duration_h: float, intensity_mm_h=None) -> str:
    inten = intensity_mm_h if intensity_mm_h else round(rainfall_mm / max(duration_h, 0.5), 1)
    return f"{float(rainfall_mm):g}|{float(duration_h):g}|{float(inten):g}"


def _touch(site_id):
    if site_id in _sites:
        _sites[site_id]["loaded"] = time.time()
    while len(_sites) > MAX_SITES_IN_MEMORY:
        oldest = min(_sites, key=lambda k: _sites[k]["loaded"])
        _sites.pop(oldest)


async def _log(db, message, details=None, level="info"):
    try:
        from app.models import SystemLog
        db.add(SystemLog(level=level, source="safe_routes", message=message, details=details or {}))
        await db.commit()
    except Exception:
        pass


# ── Geometry helpers ──────────────────────────────────────────────────────────
def _m_per_deg(lat):
    return 110_540.0, 111_320.0 * math.cos(math.radians(lat))


def _grid_index(grid, lat, lon):
    """Nearest DEM cell (row, col) for a point; None when outside the window."""
    lats, lons = grid["lats"], grid["lons"]
    dlat = lats[1] - lats[0]
    dlon = lons[1] - lons[0]
    r = int(round((lat - lats[0]) / dlat))
    c = int(round((lon - lons[0]) / dlon))
    n = grid["n"]
    if 0 <= r < n and 0 <= c < n:
        return r, c
    return None


def _bbox(grid):
    return {"south": float(grid["lats"].min()), "north": float(grid["lats"].max()),
            "west": float(grid["lons"].min()), "east": float(grid["lons"].max())}


def _interp_points(coords, step_m):
    """Points every `step_m` along a [lon, lat] polyline, including both ends."""
    pts = [tuple(coords[0])]
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        seg_m = _haversine_km(y0, x0, y1, x1) * 1000.0
        n = max(1, int(seg_m // step_m))
        for k in range(1, n + 1):
            t = k / n
            pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return pts


# ── OSM fetch ─────────────────────────────────────────────────────────────────
async def fetch_osm(client, bbox) -> dict:
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    roads_ql = (f'[out:json][timeout:60];(way["highway"~"^({HIGHWAY_RE})$"]({s},{w},{n},{e}););out body geom;')
    extra_ql = (f'[out:json][timeout:40];('
                f'way["tunnel"="culvert"]({s},{w},{n},{e});way["waterway"="culvert"]({s},{w},{n},{e});'
                f'way["natural"="water"]({s},{w},{n},{e});way["waterway"~"^(river|stream|canal|drain|ditch)$"]({s},{w},{n},{e});'
                f');out body geom;')
    roads = await _overpass(client, roads_ql, start=0)       # Overpass serialises per IP: run the two sequentially
    if not roads:
        raise RuntimeError("Overpass returned no roads (rate limited or all mirrors down); site not saved")
    extra = await _overpass(client, extra_ql, start=1)
    culverts, water = [], []
    for el in extra:
        t = el.get("tags") or {}
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) or []]
        if not pts:
            continue
        if t.get("tunnel") == "culvert" or t.get("waterway") == "culvert":
            culverts.extend(pts)
        else:
            water.extend(pts[::max(1, len(pts) // 20)])        # thin long shorelines
    return {"roads": roads, "culvert_pts": culverts, "water_pts": water}


# ── Segment construction ──────────────────────────────────────────────────────
def build_segments(osm: dict, grid: dict, impervious_pct: float) -> list:
    """Split OSM ways into node-to-node segments with static flood features."""
    dem = grid["dem"]
    n = grid["n"]
    res = float(grid["res_m"])
    win = max(1, int(HAND_WINDOW_M / res))
    culvert_tree = cKDTree(np.array(osm["culvert_pts"])) if osm["culvert_pts"] else None
    water_tree = cKDTree(np.array(osm["water_pts"])) if osm["water_pts"] else None
    mlat, mlon = _m_per_deg(float(grid["lats"][n // 2]))

    def elev_at(lat, lon):
        idx = _grid_index(grid, lat, lon)
        return float(dem[idx]) if idx else None

    def hand_at(lat, lon, z):
        idx = _grid_index(grid, lat, lon)
        if idx is None or z is None:
            return None
        r, c = idx
        block = dem[max(r - win, 0):r + win + 1, max(c - win, 0):c + win + 1]
        return round(max(0.0, z - float(block.min())), 2)

    def near_m(tree, lat, lon):
        if tree is None:
            return None
        d, _ = tree.query([lon, lat])
        # degrees -> metres (approximate, mixed axes): scale by the mean metres per degree
        return round(float(d) * (mlat + mlon) / 2, 1)

    segments = []
    for way in osm["roads"]:
        tags = way.get("tags") or {}
        geom = way.get("geometry") or []
        nodes = way.get("nodes") or []
        if len(nodes) != len(geom):
            # node ids missing (some mirrors drop them): key nodes by rounded coordinate so
            # shared intersections still resolve to the same graph node
            nodes = [int(round(p["lat"] * 1e6)) * 1_000_000_007 + int(round(p["lon"] * 1e6)) for p in geom]
        if len(nodes) < 2:
            continue
        hw = tags.get("highway", "")
        oneway_tag = tags.get("oneway", "no")
        oneway = oneway_tag in ("yes", "true", "1", "-1") or hw in ("motorway", "motorway_link")
        reverse = oneway_tag == "-1"
        tunnel = tags.get("tunnel") not in (None, "no")
        bridge = tags.get("bridge") not in (None, "no")
        try:
            layer = int(tags.get("layer", 0))
        except ValueError:
            layer = 0
        name = tags.get("name") or tags.get("ref") or ""
        for i in range(len(nodes) - 1):
            a, b = nodes[i], nodes[i + 1]
            pa, pb = geom[i], geom[i + 1]
            if reverse:
                a, b, pa, pb = b, a, pb, pa
            length = _haversine_km(pa["lat"], pa["lon"], pb["lat"], pb["lon"]) * 1000.0
            if length < 0.5:
                continue
            mid_lat, mid_lon = (pa["lat"] + pb["lat"]) / 2, (pa["lon"] + pb["lon"]) / 2
            za, zb, zm = elev_at(pa["lat"], pa["lon"]), elev_at(pb["lat"], pb["lon"]), elev_at(mid_lat, mid_lon)
            slope = round(abs(za - zb) / length * 100, 2) if za is not None and zb is not None else None
            cul = near_m(culvert_tree, mid_lat, mid_lon)
            segments.append({
                "osm_way_id": way["id"], "seg_index": i, "from_node": a, "to_node": b,
                "name": name[:128], "highway": hw, "oneway": oneway, "tunnel": tunnel, "bridge": bridge, "layer": layer,
                "length_m": round(length, 1),
                "geom_json": [[round(pa["lon"], 6), round(pa["lat"], 6)], [round(pb["lon"], 6), round(pb["lat"], 6)]],
                "mid_lat": round(mid_lat, 6), "mid_lon": round(mid_lon, 6),
                "elev_m": round(zm, 1) if zm is not None else None, "hand_m": hand_at(mid_lat, mid_lon, zm),
                "slope_pct": slope, "dist_water_m": near_m(water_tree, mid_lat, mid_lon),
                "impervious_pct": impervious_pct, "culvert_near": bool(cul is not None and cul <= CULVERT_NEAR_M),
            })
    return segments


def build_graph(segments: dict) -> tuple:
    """DiGraph from segment dicts (keyed by id). One-way ways get a single edge."""
    g = nx.DiGraph()
    nodes = {}
    for sid, s in segments.items():
        (x0, y0), (x1, y1) = s["geom_json"][0], s["geom_json"][-1]
        nodes.setdefault(s["from_node"], (y0, x0))
        nodes.setdefault(s["to_node"], (y1, x1))
        attrs = {"segment_id": sid, "length_m": s["length_m"], "highway": s["highway"], "tunnel": s["tunnel"], "bridge": s["bridge"]}
        g.add_edge(s["from_node"], s["to_node"], **attrs)
        if not s["oneway"]:
            g.add_edge(s["to_node"], s["from_node"], **attrs)
    for nid, (lat, lon) in nodes.items():
        g.add_node(nid, lat=lat, lon=lon)
    return g, nodes


# ── Site lifecycle ────────────────────────────────────────────────────────────
async def ensure_site(db, lat: float, lon: float, force: bool = False) -> dict:
    """Return the in-memory site bundle for a point, fetching roads when needed."""
    from app.models import RoadSite, RoadSegment
    t0 = time.time()
    # 1. existing site near this point?
    rows = (await db.execute(select(RoadSite))).scalars().all()
    site = None
    for r in rows:
        if _haversine_km(lat, lon, r.lat, r.lon) <= SITE_MATCH_KM:
            site = r
            break
    fresh = site is not None and not force and site.fetched_at and \
        (datetime.utcnow() - site.fetched_at) < timedelta(days=SITE_REFRESH_DAYS)
    if site is not None and site.id in _sites and fresh:
        _touch(site.id)
        return _sites[site.id]

    # 2. terrain + factors + roads, concurrently where the sources allow
    clat, clon = (site.lat, site.lon) if site else (lat, lon)
    grid_t = asyncio.create_task(get_dem(clat, clon, z=DEM_Z, n=DEM_N))
    geo_t = asyncio.create_task(get_geofactors(clat, clon))
    ant_t = asyncio.create_task(get_antecedent(clat, clon))
    grid = await grid_t
    bbox = _bbox(grid)
    timings = {"dem_s": round(time.time() - t0, 1)}

    segs = {}
    if site is not None and fresh:
        seg_rows = (await db.execute(select(RoadSegment).where(RoadSegment.site_id == site.id))).scalars().all()
        for s in seg_rows:
            segs[s.id] = {c.name: getattr(s, c.name) for c in RoadSegment.__table__.columns}
        timings["segments_from_db"] = len(segs)
    geo, ant = await geo_t, await ant_t
    if not segs:
        t1 = time.time()
        async with httpx.AsyncClient(timeout=90) as client:
            osm = await fetch_osm(client, bbox)
        timings["overpass_s"] = round(time.time() - t1, 1)
        built = build_segments(osm, grid, (geo.get("landuse") or {}).get("impervious_pct", 40.0))
        node_ids = {s["from_node"] for s in built} | {s["to_node"] for s in built}
        if site is None:
            site = RoadSite(lat=clat, lon=clon, radius_m=round(grid["span_km"] * 500, 0), bbox_json=bbox,
                            n_ways=len(osm["roads"]), n_nodes=len(node_ids), source="osm_overpass")
            db.add(site)
            await db.flush()
        else:
            await db.execute(delete(RoadSegment).where(RoadSegment.site_id == site.id))
            site.bbox_json = bbox; site.n_ways = len(osm["roads"]); site.n_nodes = len(node_ids)
            site.fetched_at = datetime.utcnow()
        objs = [RoadSegment(site_id=site.id, **s) for s in built]
        db.add_all(objs)
        await db.commit()
        for o in objs:
            segs[o.id] = {c.name: getattr(o, c.name) for c in RoadSegment.__table__.columns}
        _status.clear()
        timings["segments_built"] = len(segs)

    graph, nodes = build_graph(segs)
    node_ids = list(nodes)
    coords = np.array([[nodes[i][0], nodes[i][1]] for i in node_ids]) if node_ids else np.zeros((0, 2))
    tree = cKDTree(coords) if len(coords) else None
    bundle = {"site": {"id": site.id, "lat": site.lat, "lon": site.lon, "bbox": bbox, "n_ways": site.n_ways,
                       "n_nodes": site.n_nodes, "n_segments": len(segs), "fetched_at": site.fetched_at.isoformat() if site.fetched_at else None,
                       "span_km": grid["span_km"], "dem_res_m": grid["res_m"]},
              "segments": segs, "graph": graph, "nodes": nodes, "node_ids": node_ids, "tree": tree,
              "grid": grid, "geo": geo, "ant": ant, "loaded": time.time()}
    _sites[site.id] = bundle
    _touch(site.id)
    timings["total_s"] = round(time.time() - t0, 1)
    await _log(db, f"site {site.id} ready: {len(segs)} segments", timings)
    return bundle


# ── Flood scoring ─────────────────────────────────────────────────────────────
def classify(max_depth, wet_fraction, seg, any_wet_near=False):
    if seg.get("bridge"):
        return "open"
    if max_depth >= 0.60:
        st = "closed_all"
    elif max_depth >= 0.30:
        st = "closed_cars"
    elif max_depth >= 0.15 or (seg.get("culvert_near") and max_depth >= 0.05):
        st = "caution"
    else:
        st = "open"
    if seg.get("tunnel") and not seg.get("bridge") and (seg.get("layer") or 0) < 0:
        st = max(st, "caution", key=STATUS_ORDER.get)
        if any_wet_near:
            st = max(st, "closed_cars", key=STATUS_ORDER.get)
    return st


async def active_reports(db, bbox) -> list:
    from app.models import RoadReport
    now = datetime.utcnow()
    rows = (await db.execute(select(RoadReport).where(RoadReport.lat >= bbox["south"], RoadReport.lat <= bbox["north"],
                                                       RoadReport.lon >= bbox["west"], RoadReport.lon <= bbox["east"])
                             )).scalars().all()
    return [r for r in rows if r.expires_at is None or r.expires_at > now]


async def score_segments(db, bundle: dict, rainfall_mm: float, duration_h: float, intensity_mm_h=None, force=False) -> dict:
    """{segment_id: {status, max_depth_m, wet_fraction, source}} for a scenario, cached 6 h."""
    from app.models import RoadStatusCache
    site_id = bundle["site"]["id"]
    key = scenario_key(rainfall_mm, duration_h, intensity_mm_h)
    hit = _status.get((site_id, key))
    if hit and not force and time.time() - hit[0] < STATUS_TTL:
        return hit[1]
    if not force:
        row = (await db.execute(select(RoadStatusCache).where(RoadStatusCache.site_id == site_id,
                                                               RoadStatusCache.scenario_key == key))).scalar_one_or_none()
        if row and (datetime.utcnow() - row.computed_at).total_seconds() < STATUS_TTL:
            out = {int(k): v for k, v in row.status_json.items()}
            _status[(site_id, key)] = (time.time(), out)
            return out

    t0 = time.time()
    grid = bundle["grid"]
    forcing = net_ponding_mm(bundle["geo"], bundle["ant"], rainfall_mm, duration_h)
    depth = depth_grid(grid, forcing["net_mm"])["depth"]
    wet_mask = depth >= 0.05
    res = float(grid["res_m"])
    near_cells = max(1, int(60 / res))

    reports = await active_reports(db, bundle["site"]["bbox"])
    rep_tree = cKDTree(np.array([[r.lat, r.lon] for r in reports])) if reports else None
    mlat, mlon = _m_per_deg(bundle["site"]["lat"])

    out = {}
    for sid, seg in bundle["segments"].items():
        pts = _interp_points(seg["geom_json"], SAMPLE_STEP_M)
        depths = []
        for lon, lat in pts:
            idx = _grid_index(grid, lat, lon)
            depths.append(float(depth[idx]) if idx else 0.0)
        max_d = max(depths) if depths else 0.0
        wet_frac = sum(1 for d in depths if d > 0.05) / max(len(depths), 1)
        any_wet_near = False
        if seg.get("tunnel"):
            idx = _grid_index(grid, seg["mid_lat"], seg["mid_lon"])
            if idx:
                r, c = idx
                any_wet_near = bool(wet_mask[max(r - near_cells, 0):r + near_cells + 1, max(c - near_cells, 0):c + near_cells + 1].any())
        st = classify(max_d, wet_frac, seg, any_wet_near)
        source = "sim"
        if rep_tree is not None:
            d, i = rep_tree.query([seg["mid_lat"], seg["mid_lon"]])
            if d * (mlat + mlon) / 2 <= REPORT_MATCH_M:
                rep = reports[int(i)]
                st = {"open": "open", "caution": "caution", "closed": "closed_cars"}.get(rep.status, st)
                if rep.status == "closed" and (rep.depth_cm or 0) >= 60:
                    st = "closed_all"
                if rep.depth_cm is not None:
                    max_d = max(max_d, rep.depth_cm / 100.0)
                source = f"report:{rep.id}"
        out[sid] = {"status": st, "max_depth_m": round(max_d, 2), "wet_fraction": round(wet_frac, 2), "source": source}

    _status[(site_id, key)] = (time.time(), out)
    await db.execute(delete(RoadStatusCache).where(RoadStatusCache.site_id == site_id, RoadStatusCache.scenario_key == key))
    db.add(RoadStatusCache(site_id=site_id, scenario_key=key, status_json={str(k): v for k, v in out.items()}))
    await db.commit()
    await _log(db, f"scored site {site_id} scenario {key}", {"seconds": round(time.time() - t0, 2), "segments": len(out),
                                                            "net_ponding_mm": forcing["net_ponding_mm"]})
    return out


def invalidate_status(site_id=None):
    for k in list(_status):
        if site_id is None or k[0] == site_id:
            _status.pop(k, None)


# ── Routing ───────────────────────────────────────────────────────────────────
def snap(bundle, lat, lon):
    if bundle["tree"] is None:
        return None, None
    mlat, mlon = _m_per_deg(lat)
    d, i = bundle["tree"].query([lat, lon])
    dist_m = d * (mlat + mlon) / 2
    if dist_m > SNAP_MAX_M:
        return None, round(dist_m)
    return bundle["node_ids"][int(i)], round(dist_m)


def _heuristic(nodes):
    def h(a, b):
        la, lo = nodes[a]; lb, lob = nodes[b]
        return _haversine_km(la, lo, lb, lob) * 1000.0
    return h


def _path_detail(bundle, path, status, mode):
    segs = bundle["segments"]
    g = bundle["graph"]
    coords, items, length, minutes = [], [], 0.0, 0.0
    worst = "open"
    closed = 0
    for a, b in zip(path[:-1], path[1:]):
        e = g[a][b]
        sid = e["segment_id"]
        seg = segs[sid]
        st = status.get(sid, {}).get("status", "open")
        pts = seg["geom_json"] if seg["from_node"] == a else list(reversed(seg["geom_json"]))
        if not coords:
            coords.extend(pts)
        else:
            coords.extend(pts[1:])
        length += seg["length_m"]
        speed = SPEED_KMH[mode] * (0.5 if st == "caution" else 1.0)
        minutes += seg["length_m"] / 1000.0 / speed * 60.0
        worst = max(worst, st, key=STATUS_ORDER.get)
        if st.startswith("closed"):
            closed += 1
        items.append({"segment_id": sid, "name": seg["name"], "highway": seg["highway"], "status": st,
                      "max_depth_m": status.get(sid, {}).get("max_depth_m", 0.0), "length_m": seg["length_m"]})
    return {"geojson": {"type": "LineString", "coordinates": coords}, "length_m": round(length),
            "eta_min": round(minutes, 1), "segments": items, "worst_status": worst, "closed_segments": closed}


def find_routes(bundle: dict, status: dict, from_latlon, to_latlon, mode: str = "car", scenario=None) -> dict:
    mode = mode if mode in PENALTY else "car"
    g = bundle["graph"]
    nodes = bundle["nodes"]
    o, od = snap(bundle, *from_latlon)
    d, dd = snap(bundle, *to_latlon)
    base = {"site_id": bundle["site"]["id"], "scenario": scenario or {}, "mode": mode,
            "origin": {"lat": from_latlon[0], "lon": from_latlon[1], "snapped_node": o, "snap_m": od},
            "destination": {"lat": to_latlon[0], "lon": to_latlon[1], "snapped_node": d, "snap_m": dd},
            "computed_at": datetime.utcnow().isoformat()}
    if o is None or d is None:
        base.update({"snapped": False, "reachable": False,
                     "error": "origin or destination is more than 300 m from a mapped road inside this site"})
        return base
    base["snapped"] = True
    h = _heuristic(nodes)

    # normal route: raw length, nothing removed (but bike/walk still avoid motorways)
    def w_normal(u, v, e):
        if mode != "car" and e["highway"] in NO_BIKE_WALK:
            return None
        return e["length_m"]
    try:
        p_norm = nx.astar_path(g, o, d, heuristic=h, weight=w_normal)
        normal = _path_detail(bundle, p_norm, status, mode)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        normal = None

    pen = PENALTY[mode]

    def w_safe(u, v, e):
        if mode != "car" and e["highway"] in NO_BIKE_WALK:
            return None
        st = status.get(e["segment_id"], {}).get("status", "open")
        m = pen.get(st, 1.0)
        return None if m is None else e["length_m"] * m
    try:
        p_safe = nx.astar_path(g, o, d, heuristic=h, weight=w_safe)
        safe = _path_detail(bundle, p_safe, status, mode)
        reachable = True
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        safe, reachable = None, False

    closed_avoided = []
    if normal and safe:
        safe_ids = {s["segment_id"] for s in safe["segments"]}
        closed_avoided = [{"segment_id": s["segment_id"], "name": s["name"] or s["highway"], "max_depth_m": s["max_depth_m"],
                           "status": s["status"]} for s in normal["segments"]
                          if s["status"].startswith("closed") and s["segment_id"] not in safe_ids]
    base.update({"safe_route": safe, "normal_route": normal, "closed_avoided": closed_avoided, "reachable": reachable})
    if not reachable and normal:
        base["blocking_segments"] = [s for s in normal["segments"] if s["status"].startswith("closed")]
    return base


# ── Nominatim proxy (1 request per second, cached) ───────────────────────────
async def nominatim(path: str, params: dict) -> list | dict:
    global _nominatim_last
    key = (path, json.dumps(params, sort_keys=True))
    hit = _geocode_cache.get(key)
    if hit and time.time() - hit[0] < 24 * 3600:
        return hit[1]
    async with _nominatim_lock:
        wait = 1.0 - (time.time() - _nominatim_last)
        if wait > 0:
            await asyncio.sleep(wait)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{NOMINATIM}/{path}", params=params, headers={"User-Agent": NOMINATIM_UA})
        _nominatim_last = time.time()
        r.raise_for_status()
        data = r.json()
    if len(_geocode_cache) > 500:
        _geocode_cache.pop(next(iter(_geocode_cache)))
    _geocode_cache[key] = (time.time(), data)
    return data


async def geocode(q: str, lat: float, lon: float, limit: int = 5) -> list:
    d = 15 / 111.0
    data = await nominatim("search", {"format": "json", "q": q, "limit": limit, "bounded": 1,
                                      "viewbox": f"{lon - d},{lat + d},{lon + d},{lat - d}", "addressdetails": 0})
    return [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"]), "type": x.get("type"),
             "distance_km": round(_haversine_km(lat, lon, float(x["lat"]), float(x["lon"])), 2)} for x in data]


async def reverse(lat: float, lon: float) -> dict:
    data = await nominatim("reverse", {"format": "json", "lat": lat, "lon": lon, "zoom": 17})
    a = data.get("address", {}) if isinstance(data, dict) else {}
    short = ", ".join([x for x in (a.get("road"), a.get("suburb") or a.get("neighbourhood"), a.get("city") or a.get("town")) if x])
    return {"name": data.get("display_name") if isinstance(data, dict) else None, "short": short or None, "address": a}
