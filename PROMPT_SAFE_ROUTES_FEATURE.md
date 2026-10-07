# Claude Code prompt: Flood-aware Safe Routes feature for RIIS

Copy everything below the line into Claude Code, run from the repo root
`C:\Users\Piyush\OneDrive\Desktop\rainfall predictor`.

---

## Task

Add a **Safe Routes** feature to RIIS (Rainfall Impact Intelligence System). It must:

1. Fetch the real road network around a hyperlocal site from OpenStreetMap.
2. Score every road segment against the flood depth grid that `backend/app/services/inundation.py` already computes, and classify it open / caution / closed.
3. Compute a flood-avoiding route from the user's current location to a destination the user picks on the map or searches by name, and show it next to the normal shortest route.
4. Train and serve a gradient-boosting **road flood-risk model** that scores segments instantly from static features, with the physics simulation as the training teacher and community reports as real labels when available.
5. Add a new **Safe Routes** page to the website with a Leaflet map, origin and destination pickers, route comparison, and a ranked list of the most affected roads.

Read the repo first. Match existing patterns exactly. Do not introduce a bundler, TypeScript, or a new frontend framework.

## Repo facts you must respect

- **Frontend** is in `project/`. No build step. React 18 UMD plus Babel standalone, every screen is a `.jsx` file listed as a `<script type="text/babel">` tag in `project/index.html` with a `?v=` cache-buster. Components are global functions. Leaflet is loaded locally from `project/src/leaflet.js` and `project/src/leaflet.css`. Global state lives on `window.RIIS` (see `project/src/data.js`), and `window.RIIS.location` holds the user's `lat`, `lon`, `city`. The API client is `window.RIIS_API` in `project/src/api.js`, built on an `apiFetch(path, opts)` helper. Screens are routed in `project/src/app.jsx` via a `switch(active)` block and a `navItems` array. Map components live in `project/src/maps.jsx`; study `RealFloodMap` because the new page extends that pattern (user location marker, inundation GeoJSON layer, `window.RIIS_API.getInundation`). Shared UI primitives are in `project/src/primitives.jsx` and styles in `project/src/styles.css`.
- **Backend** is FastAPI in `backend/app/`. Async SQLAlchemy with aiosqlite, DB file `backend/riis.db`, models in `backend/app/models/__init__.py`, routers in `backend/app/routes/` registered in `backend/app/main.py`. Services in `backend/app/services/`. Existing hyperlocal routers use the prefix `/api/hyperlocal`. `backend/app/services/hyperlocal.py` already has an Overpass client `_overpass(client, ql)` with mirror fallback, in-process TTL caches, and `get_geofactors(lat, lon)`. `backend/app/services/inundation.py` has `get_dem(lat, lon, z=15, n=384)` returning a dict with `dem` (n×n float32 metres), `lats`, `lons`, `cell_w_m`, `cell_h_m`, and `simulate(dem_grid, net_mm)` returning GeoJSON wet polygons plus stats. The route `backend/app/routes/inundation.py` shows how runoff and net ponding are derived from geofactors. ML code is in `backend/app/services/ml.py` and `backend/app/train_ml.py`, models saved under `backend/app/ml_models/`. Dependencies are pinned in `backend/requirements.txt` (xgboost 2.1, scikit-learn 1.5, numpy, httpx, scipy, Pillow already present).
- Run backend with `cd backend; uvicorn app.main:app --reload --port 8000`, frontend with `node project/server.js` on port 5173. `start-riis.ps1` launches both.

## Part 1: Backend data layer

### 1.1 New tables in `backend/app/models/__init__.py`

```
RoadSite        id, lat, lon, radius_m, bbox_json, fetched_at, n_ways, n_nodes, source
RoadSegment     id, site_id (FK), osm_way_id, seg_index, from_node, to_node,
                name, highway, oneway (bool), tunnel (bool), bridge (bool), layer (int),
                length_m, geom_json (list of [lon,lat]), mid_lat, mid_lon,
                elev_m, hand_m, slope_pct, dist_water_m, impervious_pct, culvert_near (bool)
RoadStatusCache id, site_id, scenario_key (str: rainfall_mm|duration_h|intensity),
                computed_at, status_json (segment_id -> {status, max_depth_m, wet_fraction})
RoadReport      id, segment_id (FK nullable), lat, lon, status (open|caution|closed),
                depth_cm (nullable), source (user|admin|sensor), note, created_at, expires_at
RouteLog        id, site_id, from_lat, from_lon, to_lat, to_lon, scenario_key,
                safe_len_m, normal_len_m, closed_avoided, created_at
RoadRiskSample  id, segment_id, scenario_key, features_json, label (0 open,1 caution,2 closed),
                label_source (sim|report), created_at
```

Create tables on startup the same way existing tables are created. Add an Alembic migration only if the repo already uses Alembic migrations for schema changes; otherwise follow the existing `create_all` pattern.

### 1.2 External datasets to wire up

| Need | Source | How |
|---|---|---|
| Road network | OpenStreetMap via Overpass | Reuse `_overpass`. Query below. Cache per site in `RoadSite` and `RoadSegment`, refresh after 7 days. |
| Elevation grid | AWS Terrain Tiles via existing `get_dem` | Call with `z=14, n=384` so the grid spans about 3.5 km. Keep z=15 for the inundation map if it is already used there; the roads grid may be coarser. |
| Flood depth | `inundation.simulate` | Run once per scenario, sample along segments. |
| Soil, impervious, water distance | existing `get_geofactors` | Per site, applied to segments as site-level features, plus per-segment water distance computed from OSM water features already fetched. |
| Geocoding for destination search | Nominatim `https://nominatim.openstreetmap.org/search?format=json&q=...&viewbox=...&bounded=1` | Proxy through backend endpoint `GET /api/routes/geocode?q=` with a `User-Agent: RIIS-SafeRoutes/1.0` header and 1 request per second throttle. Never call Nominatim from the browser directly. |
| Reverse geocoding for labels | Nominatim reverse | Same proxy, endpoint `GET /api/routes/reverse?lat=&lon=`. |
| Baseline long-distance route (optional) | OSRM public demo `https://router.project-osrm.org/route/v1/driving/{lon},{lat};{lon},{lat}?overview=full&geometries=geojson` | Only when origin or destination falls outside the site grid. Mark it `source: osrm` and do not apply flood scoring outside the grid. |

Overpass query for roads, bounding box from the DEM grid extent:

```
[out:json][timeout:60];
(
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service)$"]
     ({south},{west},{north},{east});
);
out geom tags;
```

A second query, same bbox, for `way["tunnel"="culvert"]` and `way["waterway"="culvert"]` to populate `culvert_near` for segments within 40 m.

### 1.3 Graph construction, `backend/app/services/roads.py`

- Split each OSM way into segments between consecutive nodes. Node identity is the OSM node id, which makes intersections shared automatically.
- Compute `length_m` with the haversine formula. Compute `mid_lat`, `mid_lon`.
- Sample static features per segment from the DEM grid: `elev_m` at the midpoint, `slope_pct` from the two endpoint elevations, `hand_m` as midpoint elevation minus the minimum elevation within a 150 m window (a cheap HAND proxy, document it as such), `dist_water_m` as distance to the nearest OSM water or waterway feature from `get_geofactors`.
- Build a `networkx.DiGraph`. Add `networkx` to `requirements.txt`. For `oneway=yes` add one edge; for `oneway=-1` add the reverse; otherwise both. Edge attributes: `segment_id`, `length_m`, `highway`, `tunnel`, `bridge`.
- Cache the graph per site in a module-level dict keyed by site id, rebuilt from `RoadSegment` rows on startup or first request.

### 1.4 Flood scoring, same file

`score_segments(site, scenario) -> dict[segment_id, {status, max_depth_m, wet_fraction}]`

- Run the same runoff and net ponding derivation as `routes/inundation.py` (refactor that math into a shared helper in `services/inundation.py` called `net_ponding_mm(geo, ant, rainfall_mm, duration_h)` and use it from both places so they cannot drift).
- Compute the depth grid: `depth = max(0, water_level_surface - dem)` using the same filled-surface logic that `simulate` uses. Expose a helper `depth_grid(dem_grid, net_mm) -> np.ndarray` from `simulate`'s internals rather than duplicating.
- For each segment, interpolate points every 10 m along `geom_json`, look up the nearest cell depth, record `max_depth_m` and `wet_fraction` (share of sample points with depth over 0.05 m).
- Classify:

```
closed_all  if max_depth_m >= 0.60
closed_cars if max_depth_m >= 0.30
caution     if max_depth_m >= 0.15 or (culvert_near and max_depth_m >= 0.05)
open        otherwise
Overrides:
  tunnel and not bridge and layer < 0  -> at least caution; closed_cars if any wet cell within 60 m
  bridge                               -> open regardless of depth under it
  active RoadReport within 25 m and not expired -> report status wins over simulation
```

Use the four statuses `open | caution | closed_cars | closed_all`. Store the result in `RoadStatusCache` keyed by site and scenario, TTL 6 hours or until a new `RoadReport` lands on the site.

### 1.5 Routing, same file

`find_routes(site, scenario, from_latlon, to_latlon, mode) -> dict`

- Snap origin and destination to the nearest graph node within 300 m. If none, return `snapped: false` with a clear error.
- Weights. `mode` is `car` (default), `bike`, or `walk`. Penalty multipliers on `length_m`:

| status | car | bike | walk |
|---|---|---|---|
| open | 1.0 | 1.0 | 1.0 |
| caution | 3.0 | 4.0 | 2.0 |
| closed_cars | removed | removed | 4.0 |
| closed_all | removed | removed | removed |

  Exclude `motorway`, `motorway_link`, `trunk` for bike and walk.
- Safe route: `networkx.astar_path` with haversine heuristic on the penalised graph. Normal route: same algorithm on raw `length_m` with nothing removed.
- Response:

```json
{
  "site_id": 3, "scenario": {"rainfall_mm": 80, "duration_h": 3},
  "origin": {"lat":..,"lon":..,"snapped_node":..}, "destination": {...},
  "safe_route":   {"geojson": {LineString}, "length_m": 2310, "eta_min": 7.4,
                   "segments": [{"segment_id":..,"name":..,"status":..,"max_depth_m":..}],
                   "worst_status": "caution"},
  "normal_route": {"geojson": {...}, "length_m": 1840, "eta_min": 5.1,
                   "closed_segments": 3, "worst_status": "closed_cars"},
  "closed_avoided": [{"segment_id":..,"name":"GST Road underpass","max_depth_m":0.72}],
  "reachable": true,
  "computed_at": "..."
}
```

- When no safe path exists, return `reachable: false`, still return `normal_route`, and return `blocking_segments` (the closed segments on the normal route) so the UI can explain why.
- ETA: 30 km/h car, 15 km/h bike, 5 km/h walk on open segments, half speed on caution.
- Write a `RouteLog` row for every request.

### 1.6 Endpoints, `backend/app/routes/safe_routes.py`, prefix `/api/routes`

```
GET  /api/routes/site?lat&lon                              -> ensure site exists, fetch roads if needed, return site meta
GET  /api/routes/roads?lat&lon&rainfall_mm&duration_h&intensity_mm_h&mode
                                                           -> GeoJSON FeatureCollection of segments with status, depth,
                                                              wet_fraction, name, highway, tunnel, bridge, risk_ml (see Part 2)
                                                              plus "most_affected": top 15 named roads by max_depth_m
GET  /api/routes/route?from_lat&from_lon&to_lat&to_lon&rainfall_mm&duration_h&intensity_mm_h&mode
                                                           -> find_routes response
GET  /api/routes/geocode?q&lat&lon                         -> Nominatim proxy bounded to 15 km around lat/lon, max 5 results
GET  /api/routes/reverse?lat&lon                           -> Nominatim reverse proxy
POST /api/routes/report  {lat, lon, status, depth_cm, note} -> create RoadReport, expires_at = now + 6 h, invalidate status cache
GET  /api/routes/reports?lat&lon                           -> active reports within the site
```

Register the router in `main.py`. All GET endpoints public, POST report requires the same auth the community reports use if one exists, otherwise public with rate limiting via the existing middleware pattern.

Keep cold-start fast: fire `get_dem`, `get_geofactors`, `get_antecedent`, and the Overpass fetch concurrently with `asyncio.gather` the way `routes/inundation.py` does. Log timings to `SystemLog`.

## Part 2: Road flood-risk model

Purpose: score a segment's flood risk in under a millisecond from static features so the roads layer can render before the full DEM simulation finishes, and so the model can later learn from real reports. Be explicit in code comments and in the metrics file that the initial training labels come from the physics simulation (a surrogate model), not from observed floods, and that `label_source` tracks this.

### 2.1 Training data generation, `backend/app/train_roads.py`

- For every `RoadSite` in the DB (seed at least 6 sites across Chennai and Tamil Nadu: Potheri 12.823,80.044; Velachery 12.979,80.221; T Nagar 13.040,80.234; Tambaram 12.925,80.127; Madurai centre 9.925,78.120; Coimbatore centre 11.017,76.956), fetch roads if missing.
- For each site run `score_segments` for a scenario grid: rainfall_mm in {20, 40, 60, 80, 100, 150, 200}, duration_h in {1, 3, 6, 12}. That is 28 scenarios per site.
- For each (segment, scenario) write a `RoadRiskSample` with features:

```
rainfall_mm, duration_h, intensity_mm_h, elev_m, hand_m, slope_pct, dist_water_m,
impervious_pct, culvert_near, tunnel, bridge, layer, highway_class (ordinal 0..8),
length_m, site_saturation_pct, site_infiltration_mm_h, site_drain_count
```

  and label 0 open, 1 caution, 2 closed (merge closed_cars and closed_all), `label_source = sim`.
- Also ingest every `RoadReport` as a sample with `label_source = report`, matched to the scenario that was active when it was filed (store the active scenario on the report at creation time).

### 2.2 Training, `backend/app/services/roads_ml.py`

- `XGBClassifier`, 3 classes, `n_estimators=300`, `max_depth=5`, `learning_rate=0.05`, class weights inversely proportional to frequency.
- Split **by site**, not randomly: hold out one whole site for testing so the metric reflects generalisation to a new place. Report macro F1, per-class recall, and confusion matrix. Weight `report` samples 5x in training.
- Save `backend/app/ml_models/road_risk.pkl` and `road_risk_metrics.json` with `label_sources: {"sim": n, "report": m}` and `held_out_site` recorded.
- `predict_segments(features_df) -> probs` returns P(closed) and P(caution) per segment. The roads endpoint returns `risk_ml` = P(closed) + 0.5 P(caution) alongside the simulated status.
- Expose `POST /api/routes/train` (admin) and `GET /api/routes/model` (metrics). Add a `python -m app.train_roads` CLI with `generate | train | all` like `train_ml.py`.

## Part 3: Frontend Safe Routes page

### 3.1 Files

- New `project/src/screens_routes.jsx`, add a `<script type="text/babel" src="src/screens_routes.jsx?v=1.0">` tag in `index.html` after `maps.jsx` and before `app.jsx`.
- New map component `SafeRouteMap` in `project/src/maps.jsx` modelled on `RealFloodMap`.
- New API methods in `project/src/api.js`: `getRoadSite`, `getRoads`, `getRoute`, `geocode`, `reverseGeocode`, `postRoadReport`, `getRoadReports`, `getRoadModel`.
- Register the screen in `app.jsx`: `case "routes": screen = <RoutesScreen/>` and a nav item `{id:"routes", label:"Safe Routes", hash:"#routes"}` placed right after the Simulate entry. Match the icon style of the other nav items.
- Bump `?v=` on every file you touch.

### 3.2 Layout

Two-column layout consistent with the Simulate screen. Left column 2/3 is the map. Right column 1/3 is controls and results. Stack on screens under 900 px wide.

**Controls panel**
- Origin: default is "Your location" using `window.RIIS.location`. A button "Pick on map" lets the user click to override. Show the reverse-geocoded label.
- Destination: a search input calling the geocode proxy with a 400 ms debounce, showing up to 5 results. Or "Pick on map". Show the label.
- Mode toggle: Car, Bike, Walk.
- Scenario: rainfall mm and duration sliders. Default to the live forecast values from `window.RIIS.prediction.rainfall_mm` and 3 h, with a "Use live forecast" button that resets them. Changing a slider refetches roads and route after 500 ms debounce.
- "Find safe route" button, disabled until both points are set.

**Map**
- OSM tiles, user marker, inundation polygons from `getInundation` at the same scenario, drawn translucent blue under everything.
- Roads layer from `getRoads`, styled by status: open `#6B7280` weight 2, caution `#F59E0B` weight 4, closed_cars `#EF4444` weight 5, closed_all `#7F1D1D` weight 6, tunnels dashed. Hover tooltip with name, status, depth. Click opens a popup with the segment details and a "Report condition" mini-form posting to `/api/routes/report`.
- Routes: safe route solid `#22D3EE` weight 6 with a white casing; normal route dashed `#94A3B8` weight 3. Fit bounds to both routes when they load.
- Origin pin green, destination pin red, draggable; dragging refetches the route.
- Legend box bottom-left with the four statuses and the two route styles.
- Loading overlay while roads or routes are fetching, consistent with `RealFloodMap`'s state handling. Error state with retry.

**Results panel**
- Route comparison card: two rows, Safe and Normal, each with distance, ETA, worst status, number of closed segments. Highlight the difference, for example "+470 m, avoids 3 flooded segments".
- If `reachable` is false: a red banner "Destination cut off under this scenario" listing the blocking roads.
- "Most affected roads" list from the roads response, name, highway class, max depth, status chip. Clicking pans and flashes the segment.
- Small "Model" line showing `risk_ml` coverage and the road model metrics from `getRoadModel`, labelled honestly as "surrogate model trained on simulated scenarios, N community labels".
- Share button copying a URL with `#routes?from=lat,lon&to=lat,lon&rain=80&dur=3&mode=car`. The page must read these params on load and run the route automatically.

### 3.3 Behaviour details

- All backend calls go through `window.RIIS_API`. No direct fetches to Nominatim, Overpass or OSRM from the browser.
- Reuse `Panel`, `Chip`, `Button` and other primitives from `primitives.jsx` where they exist. Match the dark theme tokens in `styles.css`.
- Keep the map instance in a ref and never recreate it on re-render, following `RealFloodMap`.
- Also add a compact "Safe Routes" shortcut card to the Disaster screen that deep-links to `#routes` with the current location prefilled.

## Part 4: Tests and verification

- Backend unit tests in `backend/tests/test_roads.py` using pytest: graph build from a fixture Overpass JSON, segment scoring against a synthetic DEM with one pit, status thresholds, one-way handling, routing avoids a closed edge, `reachable: false` when the only path is closed, Nominatim proxy throttling.
- A smoke script `backend/scripts/smoke_routes.py` that hits site, roads, route for Potheri and prints timings. Target under 8 s cold, under 1 s warm.
- Run the existing backend tests to make sure nothing regressed.
- Start both servers, open `http://localhost:5173/#routes`, set a destination 1.5 km away, and confirm the roads layer, both routes and the affected-roads list render at rainfall 80 mm and 3 h. Take a screenshot into `project/screenshots/04-routes.jpg`.
- Run `python -m app.train_roads all`, confirm `road_risk_metrics.json` is written with a held-out site and macro F1, and that `risk_ml` appears in the roads response.

## Part 5: Documentation

- Add a "Safe Routes" section to `backend/README.md` covering endpoints, tables, datasets, thresholds, and the surrogate-model caveat.
- Add the new endpoints to the API table in `RIIS_MOBILE_APP_REPORT.md`.
- Add `networkx` and any other new dependency to `requirements.txt` with pinned versions.

## Constraints

- Do not change the existing inundation endpoint's response shape.
- Do not call paid APIs. Everything above is free.
- Respect Overpass and Nominatim usage policies: custom User-Agent, caching, at most one Nominatim request per second.
- Keep all new in-process caches bounded.
- Commit in logical steps with clear messages: data layer, scoring and routing, endpoints, model, frontend, tests and docs.
- When done, summarise what was built, the measured cold and warm timings, the model metrics, and anything left unfinished.
