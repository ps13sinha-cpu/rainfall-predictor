# Hyperlocal impact engine v2

`GET /api/hyperlocal/impact?lat=&lon=&rainfall_mm=&duration_h=&pattern=` scores what a rainfall
event does at a point. Rainfall intensity is the input (a what-if scenario or the live forecast);
the engine turns it into ponding depth, flooded area, people exposed, secondary hazards and a
0 to 100 impact score. It replaces the eight-category engine with ten factor groups, each fed by
a real dataset where one exists, and an hourly water balance instead of a static ponding formula.

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
| Land cover | 0.04 | impervious, green, wetland, farmland shares | OSM landuse and natural tags | 7 d |
| Exposure | 0.07 | population density, buildings per km², critical facilities (hospitals, clinics, schools, shelters, fire, police, substations), underpasses and rail | District seed, OSM building count, OSM amenity and power tags | 7 d |
| Historical | 0.07 | return period from the 3-year archive, district flood frequency, DFSI severity index, flooded-area share | Open-Meteo archive, India Flood Inventory v4 (`app/data/`) | 6 h / static |
| Real-time | 0.07 | current rain, 15-minute nowcast, humidity, 3-hour pressure trend | Open-Meteo forecast | 10 min |
| Model | 0.05 | tabular ensemble heavy-rain probability, data confidence | `app/services/ml.py` | live |

District name comes from Nominatim reverse geocoding, which is what the flood inventory keys on.

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
   and people exposed.
3. **Composite.** The ten weighted group scores form the vulnerability composite. The final score
   is 0.6 x composite + 0.4 x inundation severity (from peak storage, maximum depth and ponding
   hours), so a dry scenario stays low and a 2015-scale event reaches `extreme` where the ground
   and drainage warrant it. Classes: safe < 25, mod < 50, high < 75, extreme.
4. **Secondary hazards.** Landslide (regional slope >= 10 or 15 degrees with saturation), lightning
   (CAPE), power outage (substations in low ground, gusts), tree fall, traffic (underpasses,
   intensity), waterborne disease (standing water >= 24 or 72 hours), crop waterlogging (farmland
   share and 3-day totals), reservoir release.

## Caching and latency

Static layers are cached per site under `backend/cache/hyperlocal/<lat>_<lon>.json` with per-layer
TTLs (terrain 30 days, OSM 7 days, soil 30 days). `get_geofactors` waits at most 25 seconds; any
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

- Population is district-level divided by a typical district area, lifted by OSM building density.
  WorldPop's API was unreachable during the build; a 100 m population raster would replace this.
- Impervious cover comes from OSM landuse polygons, not from ESA WorldCover; sparse areas fall back
  to a default.
- River stage is inferred from recent rain, not read from CWC gauges (no public API).
- Drain design capacity is a context lookup, not a per-ward register.
- The category weights are expert-set. Joining the India Flood Inventory event dates to computed
  scores at the 36 districts would calibrate them; the data is already in `app/data/`.
