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

    # static terrain feature for the risk model: depth of the depression the segment midpoint sits in
    # (depression-filled surface minus ground), i.e. how much water can pond there before it spills
    filled = grid.get("filled")
    if filled is None:
        from app.services.inundation import priority_flood
        filled = priority_flood(grid["dem"].astype(np.float64))
        grid["filled"] = filled
    for sg in segs.values():
        idx = _grid_index(grid, sg["mid_lat"], sg["mid_lon"])
        sg["pit_depth_m"] = round(float(filled[idx] - grid["dem"][idx]), 2) if idx else 0.0

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
SCORE_CLASS = ((75, "closed_all"), (50, "closed_cars"), (25, "caution"))   # engine classes -> road status


def classify_score(score: float, seg: dict, any_wet_near: bool = False, elevation_term: float | None = None) -> str:
    """Road status from the two-tier hazard score (primary x supporting), plus structural rules.

    Bridges stay open. Underpasses (tunnel below grade) are at least caution and close to cars when
    water is simulated nearby. A culvert crossing lifts a low score to caution. Thresholds are the
    engine's own classes: safe < 25 open, mod < 50 caution, high < 75 closed to cars, extreme closed to all.
    """
    if seg.get("bridge"):
        return "open"
    st = "open"
    for floor, name in SCORE_CLASS:
        if score >= floor:
            st = name
            break
    if seg.get("culvert_near") and score >= 15:
        st = max(st, "caution", key=STATUS_ORDER.get)
    if elevation_term is not None and elevation_term < ROAD_CLOSE_MIN_ELEV and STATUS_ORDER[st] >= STATUS_ORDER["closed_cars"]:
        st = "caution"                       # high ground does not close on rain alone
    if seg.get("tunnel") and not seg.get("bridge") and (seg.get("layer") or 0) < 0:
        st = max(st, "caution", key=STATUS_ORDER.get)
        if any_wet_near:
            st = max(st, "closed_cars", key=STATUS_ORDER.get)
    return st


def site_hazard_context(bundle: dict, rainfall_mm: float, duration_h: float, intensity_mm_h=None) -> dict:
    """Supporting modifiers for the whole site, from the impact engine, for this scenario.

    Every segment shares them except 'Duration & ponding', which is re-driven per segment by the
    DEM-simulated depth on that segment (the one physical thing that differs road by road).
    """
    from app.services.hyperlocal import compute_impact, MODIFIER_RANGES
    scenario = {"rainfall_mm": rainfall_mm, "duration_h": duration_h, "intensity_mm_h": intensity_mm_h,
                "pattern": "steady", "lat": bundle["site"]["lat"], "lon": bundle["site"]["lon"]}
    try:
        imp = compute_impact(bundle["geo"], bundle["ant"], {}, scenario, 0, upstream=None, tide=None)
        rows = {r["name"]: r for r in imp["modifiers"]["rows"]}
        product_rest = 1.0
        for name, r in rows.items():
            if name != "Duration & ponding":
                product_rest *= r["multiplier"]
        return {"ok": True, "peak_intensity_mm_h": imp["impact"]["peak_intensity_mm_h"],
                "site_severity": imp["impact"]["inundation_severity"], "product_rest": product_rest,
                "dp_range": MODIFIER_RANGES["Duration & ponding"], "rows": imp["modifiers"]["rows"],
                "water_type": (bundle["geo"].get("water") or {}).get("type"),
                "lowness": (bundle["geo"].get("elevation") or {}).get("lowness", 0.5),
                "site_score": imp["impact"]["score"], "site_class": imp["impact"]["class"]}
    except Exception as e:
        mean = intensity_mm_h or rainfall_mm / max(duration_h, 0.5)
        return {"ok": False, "error": str(e)[:160], "peak_intensity_mm_h": mean, "site_severity": 0.0,
                "product_rest": 1.0, "dp_range": (0.9, 1.2), "rows": [], "water_type": None, "lowness": 0.5,
                "site_score": None, "site_class": None}


ROAD_HAND_SCALE_M = 4.0      # road-to-road differences are sub-metre: 100 at the drainage line, 0 at the median HAND
ROAD_PIT_SCALE_M = 0.5       # a half-metre depression under the carriageway is a full pit
ROAD_CLOSE_MIN_ELEV = 30.0   # a road only closes when its own elevation term says it is genuinely low


def road_elevation_term(seg: dict) -> float:
    """The engine's relative-elevation primary at road scale (0..100)."""
    from app.services.hyperlocal import _clamp
    hand_low = _clamp(1 - (seg.get("hand_m") or 0.0) / ROAD_HAND_SCALE_M, 0, 1) * 100
    pit = _clamp((seg.get("pit_depth_m") or 0.0) / ROAD_PIT_SCALE_M, 0, 1) * 100
    elev = seg.get("elev_m") if seg.get("elev_m") is not None else 20.0
    abs_low = _clamp((40.0 - elev) / 35.0, 0, 1) * 100
    return max(0.5 * hand_low + 0.4 * pit + 0.1 * abs_low, 3.0)


def segment_hazard(seg: dict, ctx: dict, max_depth_m: float, rainfall_mm: float, duration_h: float) -> dict:
    """Two-tier score for one road segment: its own primaries x the site's modifiers.

    Rainfall and distance-to-water terms come straight from the engine's primary_hazard; the
    elevation term is the same formula at road scale (see ROAD_* constants), because the engine's
    8 m HAND scale calls a whole coastal plain 'low' and cannot tell one road from the next.
    """
    from app.services.hyperlocal import primary_hazard, PRIMARY_EXPONENTS, MODIFIER_PRODUCT_RANGE, _clamp
    terrain_ok = seg.get("hand_m") is not None and seg.get("elev_m") is not None
    prim = primary_hazard(ctx["peak_intensity_mm_h"], seg.get("hand_m"), seg.get("pit_depth_m") or 0.0,
                          seg.get("elev_m") if seg.get("elev_m") is not None else 20.0, seg.get("dist_water_m"),
                          ctx.get("water_type"), ctx.get("lowness", 0.5), terrain_ok,
                          event_mm=rainfall_mm, duration_h=duration_h)
    terms = {t["name"]: float(t["score"]) for t in prim["terms"]}
    e_road = road_elevation_term(seg) if terrain_ok else terms["Elevation (relative)"]
    terms["Elevation (relative)"] = round(e_road)
    base = 100 * ((terms["Rainfall intensity"] / 100) ** PRIMARY_EXPONENTS["intensity"]
                  * (e_road / 100) ** PRIMARY_EXPONENTS["elevation"]
                  * (terms["Distance to water"] / 100) ** PRIMARY_EXPONENTS["water"])
    lo, hi = ctx["dp_range"]
    dp_driver = max(float(ctx["site_severity"]), 100.0 * min(max_depth_m / 0.6, 1.0))
    dp_mult = lo + (hi - lo) * dp_driver / 100.0
    product = _clamp(ctx["product_rest"] * dp_mult, *MODIFIER_PRODUCT_RANGE)
    score = _clamp(round(base * product), 0, 100)
    return {"score": score, "base": round(base), "modifier_product": round(product, 3),
            "primary": {k: round(v) for k, v in terms.items()}, "terrain_ok": terrain_ok, "elevation_term": round(e_road)}


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
    from app.services.inundation import routed_depth_grid
    depth = routed_depth_grid(grid, forcing["net_mm"])["depth"]     # water routed high to low, not spread evenly
    wet_mask = depth >= 0.05
    res = float(grid["res_m"])
    near_cells = max(1, int(60 / res))

    reports = await active_reports(db, bundle["site"]["bbox"])
    rep_tree = cKDTree(np.array([[r.lat, r.lon] for r in reports])) if reports else None
    mlat, mlon = _m_per_deg(bundle["site"]["lat"])
    ctx = site_hazard_context(bundle, rainfall_mm, duration_h, intensity_mm_h)

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
        hz = segment_hazard(seg, ctx, max_d, rainfall_mm, duration_h)
        if hz["terrain_ok"]:
            st, basis = classify_score(hz["score"], seg, any_wet_near, hz["elevation_term"]), "two_tier"
        else:
            st, basis = classify(max_d, wet_frac, seg, any_wet_near), "depth_fallback"   # no DEM for this segment
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
        out[sid] = {"status": st, "max_depth_m": round(max_d, 2), "wet_fraction": round(wet_frac, 2), "source": source,
                    "score": hz["score"], "base": hz["base"], "modifier_product": hz["modifier_product"],
                    "primary": hz["primary"], "basis": basis}

    _status[(site_id, key)] = (time.time(), out)
    await db.execute(delete(RoadStatusCache).where(RoadStatusCache.site_id == site_id, RoadStatusCache.scenario_key == key))
    db.add(RoadStatusCache(site_id=site_id, scenario_key=key, status_json={str(k): v for k, v in out.items()}))
    await db.commit()
    await _log(db, f"scored site {site_id} scenario {key}", {"seconds": round(time.time() - t0, 2), "segments": len(out),
                                                            "net_ponding_mm": forcing["net_ponding_mm"],
                                                            "site_score": ctx.get("site_score"), "modifiers_ok": ctx.get("ok")})
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
    d = 60 / 111.0   # 60 km search box: far destinations route via OSRM
    data = await nominatim("search", {"format": "json", "q": q, "limit": limit, "bounded": 1,
                                      "viewbox": f"{lon - d},{lat + d},{lon + d},{lat - d}", "addressdetails": 0})
    return [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"]), "type": x.get("type"),
             "distance_km": round(_haversine_km(lat, lon, float(x["lat"]), float(x["lon"])), 2)} for x in data]


async def reverse(lat: float, lon: float) -> dict:
    data = await nominatim("reverse", {"format": "json", "lat": lat, "lon": lon, "zoom": 17})
    a = data.get("address", {}) if isinstance(data, dict) else {}
    short = ", ".join([x for x in (a.get("road"), a.get("suburb") or a.get("neighbourhood"), a.get("city") or a.get("town")) if x])
    return {"name": data.get("display_name") if isinstance(data, dict) else None, "short": short or None, "address": a}


# ── Long-distance routes: OSRM baseline + local flood-aware detours ──────────
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
OSRM_UA = "RIIS-SafeRoutes/1.0 (rainfall impact research)"
ROUTE_SAMPLE_M = 15.0
ROUTE_MATCH_M = 30.0
_building = {}   # site key -> asyncio.Task building a destination site in the background


async def osrm_route(from_latlon, to_latlon) -> dict:
    """Shortest driving route from the public OSRM demo server (car profile only)."""
    (fla, flo), (tla, tlo) = from_latlon, to_latlon
    url = f"{OSRM_URL}{flo},{fla};{tlo},{tla}"
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(url, params={"overview": "full", "geometries": "geojson", "steps": "false"},
                             headers={"User-Agent": OSRM_UA})
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM: {data.get('code')} {data.get('message', '')}")
    rt = data["routes"][0]
    return {"coords": rt["geometry"]["coordinates"], "distance_m": float(rt["distance"]), "duration_s": float(rt["duration"])}


def _seg_tree(bundle):
    """KD-tree over segment midpoints (built once per site bundle)."""
    if "seg_tree" not in bundle:
        ids = list(bundle["segments"])
        pts = np.array([[bundle["segments"][i]["mid_lat"], bundle["segments"][i]["mid_lon"]] for i in ids]) if ids else np.zeros((0, 2))
        bundle["seg_tree"] = (cKDTree(pts) if len(pts) else None, ids)
    return bundle["seg_tree"]


def _in_bbox(bbox, lat, lon):
    return bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]


def _polyline_len(coords):
    return sum(_haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(coords[:-1], coords[1:])) * 1000.0


def score_polyline(bundle, status, coords):
    """Attach scored segment statuses to the part of a polyline that crosses this site.

    Returns {"runs": [(i0, i1)], "segments": [...], "scored_m": metres inside the site, "points": sampled pts}."""
    tree, ids = _seg_tree(bundle)
    bbox = bundle["site"]["bbox"]
    mlat, mlon = _m_per_deg(bundle["site"]["lat"])
    pts = _interp_points(coords, ROUTE_SAMPLE_M)
    inside = [_in_bbox(bbox, p[1], p[0]) for p in pts]
    runs, start = [], None
    for i, flag in enumerate(inside + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    seen, segs = set(), []
    if tree is not None:
        for i, (lon, lat) in enumerate(pts):
            if not inside[i]:
                continue
            d, j = tree.query([lat, lon])
            if d * (mlat + mlon) / 2 <= ROUTE_MATCH_M:
                sid = ids[int(j)]
                if sid not in seen:
                    seen.add(sid)
                    seg = bundle["segments"][sid]
                    st = status.get(sid, {})
                    segs.append({"segment_id": sid, "name": seg["name"], "highway": seg["highway"], "status": st.get("status", "open"),
                                 "max_depth_m": st.get("max_depth_m", 0.0), "length_m": seg["length_m"]})
    scored_m = sum(1 for f in inside if f) * ROUTE_SAMPLE_M
    return {"runs": runs, "segments": segs, "scored_m": scored_m, "points": pts}


def splice_detours(bundle, status, coords, mode):
    """Where the route crosses this site and touches closed roads, replace that stretch with the
    local flood-aware path between the stretch's entry and exit points. Returns (coords, avoided, detoured)."""
    sc = score_polyline(bundle, status, coords)
    closed = [s for s in sc["segments"] if s["status"].startswith("closed")]
    if not closed or not sc["runs"]:
        return coords, [], False
    pts = sc["points"]
    new_pts = list(pts)
    offset = 0
    avoided = []
    for (i0, i1) in sc["runs"]:
        a, b = pts[i0], pts[i1]
        res = find_routes(bundle, status, (a[1], a[0]), (b[1], b[0]), mode)
        if not res.get("reachable") or not res.get("safe_route"):
            continue
        local = res["safe_route"]["geojson"]["coordinates"]
        safe_ids = {s["segment_id"] for s in res["safe_route"]["segments"]}
        avoided.extend([c for c in closed if c["segment_id"] not in safe_ids])
        new_pts[i0 + offset:i1 + 1 + offset] = local
        offset += len(local) - (i1 - i0 + 1)
    return new_pts, avoided, bool(avoided)


def _site_key_for(lat, lon):
    return f"{round(lat, 2)},{round(lon, 2)}"


async def long_route(db, origin_bundle, status_fn, from_latlon, to_latlon, mode, scenario) -> dict:
    """Flood-aware long-distance route: OSRM baseline, scored and locally detoured through every
    site we have (origin always; destination once its site has been built in the background)."""
    try:
        base = await osrm_route(from_latlon, to_latlon)
    except Exception as e:
        return {"snapped": False, "reachable": False, "source": "osrm", "error": f"long-distance router unavailable: {e}"}
    coords = base["coords"]
    sites = [origin_bundle]

    # destination site: use it if present, otherwise build it in the background for the next call
    dest_state = "none"
    dkey = _site_key_for(*to_latlon)
    dest_bundle = None
    for b in _sites.values():
        if b is not origin_bundle and _in_bbox(b["site"]["bbox"], *to_latlon):
            dest_bundle = b
            break
    if dest_bundle is not None:
        sites.append(dest_bundle)
        dest_state = "ready"
    else:
        task = _building.get(dkey)
        if task is None or task.done():
            from app.database import async_session

            async def _build():
                async with async_session() as db2:
                    try:
                        await ensure_site(db2, to_latlon[0], to_latlon[1])
                    except Exception as e:
                        print(f"[RIIS-SafeRoutes] destination site build failed: {e}")
            _building[dkey] = asyncio.create_task(_build())
        dest_state = "building"

    scored_m, segments, avoided, detoured = 0.0, [], [], False
    for b in sites:
        st = await status_fn(b)
        coords, av, det = splice_detours(b, st, coords, mode)
        sc = score_polyline(b, st, coords)
        scored_m += sc["scored_m"]
        segments.extend(sc["segments"])
        avoided.extend(av)
        detoured = detoured or det

    length = _polyline_len(coords)
    speed = SPEED_KMH[mode]
    caution_m = sum(s["length_m"] for s in segments if s["status"] == "caution")
    if mode == "car":
        eta = base["duration_s"] / 60.0 * (length / max(base["distance_m"], 1.0)) + caution_m / 1000.0 / (speed / 2) * 60.0
    else:
        eta = length / 1000.0 / speed * 60.0 + caution_m / 1000.0 / speed * 60.0
    worst = "open"
    for s in segments:
        worst = max(worst, s["status"], key=STATUS_ORDER.get)
    closed_left = [s for s in segments if s["status"].startswith("closed")]
    note = "Flood status is known inside the mapped area around the origin"
    note += " and the destination" if dest_state == "ready" else ""
    note += "; the rest of the route is unscored."
    if dest_state == "building":
        note += " The destination area is being mapped now (1 to 4 min) and will be scored on the next refresh."
    return {
        "snapped": True, "reachable": not closed_left, "source": "osrm+local", "mode": mode, "scenario": scenario or {},
        "origin": {"lat": from_latlon[0], "lon": from_latlon[1]}, "destination": {"lat": to_latlon[0], "lon": to_latlon[1]},
        "safe_route": {"geojson": {"type": "LineString", "coordinates": coords}, "length_m": round(length), "eta_min": round(eta, 1),
                       "segments": segments, "worst_status": worst, "closed_segments": len(closed_left)},
        "normal_route": {"geojson": {"type": "LineString", "coordinates": base["coords"]}, "length_m": round(base["distance_m"]),
                         "eta_min": round(base["duration_s"] / 60.0, 1), "worst_status": None, "closed_segments": None, "segments": []},
        "closed_avoided": avoided, "detoured": detoured, "blocking_segments": closed_left,
        "scored_fraction": round(min(1.0, scored_m / max(length, 1.0)), 2), "destination_site": dest_state, "note": note,
        "computed_at": datetime.utcnow().isoformat(),
    }
