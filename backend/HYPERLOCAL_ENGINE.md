# Hyperlocal impact engine v3

`GET /api/hyperlocal/impact?lat=&lon=&rainfall_mm=&duration_h=&pattern=` scores what a rainfall
event does at a point. Rainfall intensity is the input (a what-if scenario or the live forecast);
the engine turns it into ponding depth, flooded area, people exposed, secondary hazards and a
0 to 100 impact score. Ten factor groups are still computed from the same datasets, but since v3
the score is two-tier: three primaries (rainfall, relative elevation, distance to water) form a
base hazard by geometric mean, and the other groups are bounded multipliers on it.

Code: `app/services/hyperlocal.py` (engine), `app/services/terrain.py` (DEM hydrology),
`app/services/flood_history.py` (India Flood Inventory), `app/routes/hyperlocal.py` (routes).

## Factor groups and their data

| Group | Weight | Inputs | Dataset | Refresh |
|---|---|---|---|---|
| Meteorological | 0.22 | peak intensity (pattern-shaped), event total, duration, model agreement, CAPE, gusts | Open-Meteo forecast, 3 NWP models (ECMWF IFS, GFS, ICON) | 10 min |
| Hydrological | 0.14 | live soil moisture 0-7 cm vs porosity, antecedent 3/7/30-day rain, texture, effective infiltration, runoff coefficient | Open-Meteo ERA5-Land soil moisture, Open-Meteo archive, ISRIC SoilGrids 250 m | 10 min / 6 h / 30 d |
| Topographical | 0.13 | HAND, slope, upstream area, closed depression, low elevation, distance to water | SRTM via AWS Terrain Tiles (D8 routing in `terrain.py`), OSM water | 30 d |
| Drainage | 0.13 | design capacity by urban context, seasonal blockage, outfall state (tide, river), culverts vs embankments and rail, pumping stations, underpasses, impervious cover | OSM Overpass, Open-Meteo Marine | 7 d / 1 h |
| Upstream and coastal | 0.08 | reservoirs upstream (storage, overflow risk, distance), tide stage, river backwater, wetland buffer | RIIS reservoirs table, Open-Meteo Marine `sea_level_height_msl`, OSM | live / 1 h |
| Land cover | 0.04 | impervious (built-up), green, wetland, farmland shares | ESA WorldCover 10 m 2021, windowed read from S3; OSM landuse only where the raster is unavailable | 180 d |
| Exposure | reported, not scored | population density within 2.5 km, buildings per km², critical facilities (hospitals, clinics, schools, shelters, fire, police, substations), underpasses and rail | JRC GHS-POP 2020 (3 arc-second) local tiles; OSM building count, OSM amenity and power tags; district seed only as a fallback | 180 d / 7 d |
| Historical | 0.07 | return period from the 3-year archive, district flood frequency, DFSI severity index, flooded-area share | Open-Meteo archive, India Flood Inventory v4 (`app/data/`) | 6 h / static |
| Real-time | 0.07 | current rain, 15-minute nowcast, humidity, 3-hour pressure trend | Open-Meteo forecast | 10 min |
| Model | 0.05 | tabular ensemble heavy-rain probability, data confidence | `app/services/ml.py` | live |

District name comes from Nominatim reverse geocoding and is resolved through `app/data/district_lookup.json` (aliases and LGD codes; misses are logged as `district_miss`), which is what the flood inventory keys on.

## How the score is built

1. **Drainage capacity.** `design_capacity` is 12 to 65 mm/h from building density and mapped drains
   (Indian city drains are typically built for 20 to 25 mm/h, newer stormwater zones higher).
   It is multiplied by a seasonal blockage factor (0.7 in December, 0.95 right after pre-monsoon
   desilting), an outfall factor (0.6 when the next six hours bring a tide above 0.4 m, 0.8 when a
   nearby river is likely high) and a structural factor (0.85 when embankments or rail lines cross
   the area with at most one mapped culvert, 1.15 with a pumping station, 0.7 in a closed
   depression). Natural conveyance from slope and HAND is added, so steep ground sheds water
   without pipes.
2. **Hourly water balance.** Rain is shaped by the pattern (`steady`, `front`, `back`, `burst`),
   multiplied by the runoff coefficient and by an upstream factor (up to 2x for a large catchment
   through the point). Outflow is the effective capacity, decaying as cumulative inflow fills the
   receiving system. Peak storage, hours above 15 mm of standing water, and a ponded fraction of
   the cell (larger where HAND is low) give mean and maximum depth, flooded area, structures, roads
   and people exposed. Its severity (peak storage, maximum depth, ponding hours) drives the
   "Duration & ponding" modifier below.
3. **Primary hazard** (`primary_hazard` in `hyperlocal.py`). Three terms on 0 to 100:
   - *Rainfall intensity*: piecewise on the pattern-shaped peak rate, 25 at 10 mm/h, 50 at 25,
     75 at 50, 100 at 80 and above (the breakpoints bracket real drain capacities). A long steady
     deluge is not light rain, so the event total is also mapped on the IMD daily classes (25 at
     64.5 mm, 50 at 115.6, 75 at 204.5, 100 at 350, scaled down for events longer than a day) and
     the larger of the two is used.
   - *Elevation, relative not absolute*: 0.6 x lowness from HAND (100 at the drainage line, 0 at
     8 m above it) + 0.3 x closed-depression depth (100 at 1 m) + 0.1 x absolute low ground (100
     under 5 m, 0 above 40 m). Floor 3 for DEM noise; falls back to the coarse lowness index when
     the DEM is unavailable.
   - *Distance to water*: 100 x exp(-d / 1800 m), type-aware (river and canal 1.0, stream 0.9,
     lake or tank 0.8, drain or ditch 0.5). Floored at 15 because pluvial flooding happens far
     from any mapped water and OSM water coverage is patchy; 40 when nothing is mapped within 3 km.

   `base = 100 x (I/100)^0.5 x (E/100)^0.3 x (W/100)^0.2`. The geometric form is the point: any
   primary near zero pulls the whole hazard down. No rain means no flood regardless of terrain, and
   a ridge does not flood regardless of rain. The exponents are the primary weights and sum to 1.
4. **Supporting modifiers** (`modifiers`). Each remaining factor group maps its 0 to 100 score onto
   a bounded multiplier: saturation and soil 0.85 to 1.25, drainage 0.80 to 1.20, impervious cover
   0.95 to 1.15, upstream and tide 1.00 to 1.30, duration and ponding 0.90 to 1.20, historical
   0.95 to 1.15, real-time 0.95 to 1.10, model 0.95 to 1.10. Their product is capped to 0.6 to 1.6,
   so supporting factors can move a score by about a class but never create a flood from nothing.
   `impact = clamp(base x product, 0, 100)`. Classes: safe < 25, mod < 50, high < 75, extreme.
   Life-safety hazards (landslide, reservoir release) still lift the class as before.
5. **Exposure is not in the hazard.** Population density, buildings and critical facilities are
   reported in the `exposure` block as people at risk, structures and road kilometres, next to the
   score rather than inside it.
6. **Secondary hazards.** Landslide (regional slope >= 10 or 15 degrees with saturation), lightning
   (CAPE), power outage (substations in low ground, gusts), tree fall, traffic (underpasses,
   intensity), waterborne disease (standing water >= 24 or 72 hours), crop waterlogging (farmland
   share and 3-day totals), reservoir release.

The response keeps `categories` (the ten group scores with their v2 weights) and reports
`impact.legacy_additive_score` so the two formulas can be compared on any site. `CATEGORY_WEIGHTS`
no longer drives the score.

### Why the structure changed

Probing v2 with synthetic sites under identical rain (150 mm in 6 h) gave a 12-degree hilltop 25 m
above its drainage line and 6 km from water a score of 35, and a low basin 0.5 m above a river 34.
A 2015-scale 350 mm/24 h event in that basin reached 39. The static groups (hydrological,
topographical, land cover, exposure) held the same values whether it rained 0 or 350 mm, so the
additive sum could neither separate terrain under rain nor reach `extreme`. The same probes on v3:

| Scenario | v2 | v3 |
|---|---|---|
| Dry, low basin near river | 18 (hard cap) | 0 |
| 10 mm/6 h, low basin | 23 | 18 |
| 150 mm/6 h, hilltop 12 deg, 6 km from water | 35 | 35 (landslide lift; base 17) |
| 150 mm/6 h, flat urban, 4 km from water | 32 | 47 |
| 150 mm/6 h, low basin near river | 34 | 74 |
| 150 mm/6 h, closed depression | 47 | 87 |
| 350 mm/24 h, low basin (Chennai 2015 scale) | 39 | 99 |
| 60 mm/1 h burst, low basin | 36 | 100 |

This is ordering and discrimination, not validated accuracy: there is still no hyperlocal
flood-observation set to score either version against (see Known gaps).

## Data quality, provenance and validation (engine 3.1)

Every impact response also carries:

- `data_quality`: which inputs came from fallbacks or defaults (`terrain unavailable`, `water unmapped`,
  `soil default`, `landuse default`, `population proxy`, `infra default`, `soil moisture missing`,
  `forecast missing`, `archive missing`, `flood history unmatched`, `reservoirs stale`, `tide unavailable`),
  the count, `key_inputs_imputed`, and `cap_reason`. When terrain, the forecast or soil moisture is
  missing, the class and evacuation tier are capped at `mod`; the score number is left as computed.
- `provenance`: one row per layer with source, url, fetched_at, cache age, TTL, licence and status.
  Stale reservoir rows (older than `RIIS_RESERVOIR_MAX_AGE_H`, default 48 h, or seeded) are dropped
  from the upstream modifier and listed with their age.
- `validation_status`: read from `app/data/calibration.json` (produced by `python -m app.calibrate_ifi`
  from the India Flood Inventory joined to TNDMA gauges). Without that file the status is
  `untested_hypothesis` and the UI shows an amber banner.
- `reanalysis_bias`: the district's ERA5-vs-gauge ratio from `app/data/station_bias.json`
  (`python -m app.station_bias`), because the reanalysis is the label every RIIS weather model learned.

The calibration validates only the rainfall term: the inventory is by district and day. The
elevation and water primaries, and all modifiers, remain expert-set. See `docs/IFI_CALIBRATION.md`
and `docs/ERA5_STATION_BIAS.md` for the numbers, and `docs/PRODUCTION_READINESS.md` for the status
of every review item.

## Water routed from high ground to low ground (engine 3.2)

`app/services/routing.py` follows every cell's runoff downslope on the SRTM window and is used in
three places:

- **Impact engine.** The terrain layer now carries `routing`: D8 flow accumulation at the point
  (how many cells' runoff arrives there), its percentile in the window (`flow_convergence_pct`),
  the upslope catchment (cells, km², relief) and a time of concentration at 0.5 m/s. Flow
  convergence enters the relative-elevation primary at 15 percent weight (HAND 50, pit 25,
  absolute height 10), and the hourly water balance multiplies local runoff by
  `1 + 0.8 log10(accumulation cells)`, capped at 3.5, instead of the old log-area guess. The
  response carries a `routing` block and the Topographical source line names the multiplier.
- **Flood simulator.** `inundation.simulate` now routes net runoff by D8 on the raw DEM (pits are
  sinks), fills each depression with what its own catchment delivers, and spills a full
  depression's overflow along the filled surface to the next one downstream (fill-and-spill),
  until water leaves the window. The response adds `routing` (pits, overflows, exited volume),
  `flow_paths` (GeoJSON lines where at least 2 percent of the window's runoff passes), `catchment`
  (the point's upslope polygon) and `point` metrics; the map draws the paths in blue and the
  catchment as a dashed violet outline. The uniform model stays as `depth_grid` and is the
  fallback if routing fails.
- **Safe Routes.** Road depths come from the same routed grid, so a road at the foot of a slope
  floods before one on the crest even when both sit in pits.

On the Potheri window (384 x 384 cells at 4.6 m) routing takes about 2 s per scenario after a
one-off D8 pass; the depression-filled surface is now saved with the DEM on disk so a restart
does not repeat it. Overland flow speed and the 2 percent path threshold are set in `routing.py`.

## Consumers: Safe Routes and the farmer advisory

Both take their verdicts from the same two tiers, nothing else.

- **Safe Routes** (`services/roads.py`): each road segment gets its own primary hazard from the
  scenario rain, the segment's HAND, pit depth and elevation from the DEM, and its distance to
  water; the site's supporting modifiers come from `compute_impact` at the site centre, except
  "Duration & ponding", which is re-driven per segment by the DEM-simulated depth on that
  segment. The elevation primary is the engine's formula at road scale (HAND 100 at the drainage
  line and 0 at 4 m, the median road; pit depth 100 at 0.5 m), because the site-level 8 m scale
  calls a whole coastal plain "low" and cannot tell one road from the next. Status follows the
  engine classes: score < 25 open, < 50 caution, < 75 closed to cars, otherwise closed to all, and
  a road closes only when its own elevation term is at least 30 (high ground never closes on rain
  alone). Bridges stay open; underpasses are at least caution and close to cars when water is
  simulated nearby; a culvert crossing lifts a low score to caution. Community reports still
  override the model. Segments without a DEM sample (`basis: depth_fallback`) keep
  the old depth thresholds. Every segment reports `score`, `base`, `modifier_product` and its
  three primaries; the road-risk surrogate is retrained on these labels.
- **Farmer advisory** (`services/farmer.py`): the waterlogging level is the two-tier score of the
  next 72 h of forecast rain at the field (low < 25, moderate < 50, high from 50). The block carries
  the three primaries, every modifier, and a `drivers_text` naming the strongest ones; simulated
  ponding hours against the crop's tolerance are reported beside it, not scored.

## Caching and latency

Static layers are cached per site in the `site_cache` table of riis.db (WAL, shared across workers; legacy
`backend/cache/hyperlocal/*.json` files are imported on first read) with per-layer TTLs (terrain 30 days,
OSM 7 days, soil 30 days, WorldCover and GHS-POP 180 days). The Overpass chain takes a lock row so two
workers never fetch the same site at once. `get_geofactors` waits at most 25 seconds; any
fetcher still running keeps going in the background and its result lands in the cache for the next
call, and the response lists it under `still_loading`. A warm site answers in about one second.

Overpass serialises queries per IP, so the three OSM calls (bundle, coastline, building count) run
one after another and rotate mirrors. SoilGrids masks built-up pixels as NoData, so the fetcher
samples a ring of nearby points and reports `soilgrids_nearby` with the offset.

## Endpoints

- `GET /api/hyperlocal/impact` with `rainfall_mm`, `duration_h`, optional `intensity_mm_h`,
  `pattern` and `ml_score`. Returns `impact`, `categories`, `inundation` (with the hourly storage
  series), `drainage` breakdown, `secondary_hazards`, `factors` (every raw input), `data_confidence`,
  `advisories`, `weather`.
- `GET /api/hyperlocal/factors` returns every input without scoring.
- `GET /api/hyperlocal/geofactors` returns the static layers and antecedent rain (unchanged path).

## Known gaps

- Population comes from GHS-POP tiles held locally; a site outside the downloaded tiles triggers a
  20 to 160 MB download on first use. Impervious cover is WorldCover built-up share, which under-counts
  paved ground outside built-up pixels.
- River stage is inferred from recent rain, not read from CWC gauges (no public API).
- Drain design capacity is a context lookup, not a per-ward register.
- The primary exponents, modifier ranges and curve breakpoints are expert-set, like the v2 weights
  were. Joining the India Flood Inventory event dates to computed scores at the 36 districts would
  calibrate them; the data is already in `app/data/`. Until then the engine is validated on ordering
  (the table above), not on observed depths.
