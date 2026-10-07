# Hyperlocal Rainfall Intensity and Impact: Factors, Method, Datasets

Reference for RIIS, 7 October 2026. How to predict rainfall intensity at a hyperlocal point
(such as Potheri), how to turn that into impact, and where to get the data for every factor.

---

## 1. Two problems, not one

| | Rainfall intensity | Rainfall impact |
|---|---|---|
| Question | How many mm per hour will fall here in the next N hours? | What will that rain do here? |
| Field | Meteorology, nowcasting, downscaling | Hydrology, hydraulics, exposure |
| Drivers | Atmosphere, storm motion, terrain forcing, coast | Soil, slope, drains, upstream water, people |
| Your code today | Reads Open-Meteo forecast directly, no model | `hyperlocal.py` 8-category engine, `inundation.py` DEM model |

Drainage, soil and population do **not** change how much rain falls. Keep them out of Stage 1
or the model learns noise. Feed them into Stage 2.

---

## 2. Stage 1: predicting rainfall intensity at a point

### 2.1 Target

Observed rainfall in mm per hour at the point, for lead times 0 to 6 hours, binned to the
classes you already use (safe / mod / high / extreme) or kept continuous for a regressor.
Ground truth comes from the nearest rain gauge, or from GPM IMERG where no gauge exists.

### 2.2 Features that actually move rainfall at a point

**A. Forecast guidance (strongest signal at 1 to 24 hours)**
- Precipitation, precipitation probability, CAPE, convective inhibition, cloud cover by layer,
  humidity at 2 m and at 850/700/500 hPa, wind at 10 m and 850 hPa, pressure tendency.
- From several NWP models at once. ECMWF IFS 9 km, GFS 13 km, ICON 13 km, and the
  high-resolution regional models Open-Meteo blends. The ML learns per-location which model
  is right. This is called multi-model bias correction and it alone beats any single forecast.

**B. Recent observations (strongest signal at 0 to 2 hours)**
- Rain in the last 15, 30, 60, 180 minutes at the point and at surrounding points.
- Storm motion vector, derived from satellite or radar frames, which tells you whether the
  cell is heading toward or away from the point.
- Lightning density nearby, a leading indicator of convective bursts.

**C. Terrain and geography (why two places 10 km apart differ)**
- Elevation, slope, aspect relative to the prevailing wind. Orographic lift on the windward
  side of even small hills raises totals.
- Distance to coast and coastline orientation. Sea breeze convergence lines fire afternoon
  convection inland of Chennai at a fairly repeatable distance.
- Urban heat island intensity, which increases downwind convective rain.

**D. Time and season**
- Hour of day (convective peak late afternoon to evening), day of year, monsoon phase
  (southwest June to September, northeast October to December).
- Large-scale indices: Madden-Julian Oscillation phase, Bay of Bengal sea surface temperature,
  presence of a low or depression. These set the background probability.

### 2.3 Method, in order of build effort

1. **Gradient boosting downscaler.** Rows are (point, time). Features are A plus C plus D,
   target is observed intensity in the next hour. Train on 2 to 3 years of hourly data at every
   gauge you can get. This is a day of work once data is ingested, and it directly produces a
   per-point bias-corrected forecast. Use LightGBM or XGBoost with quantile loss so you get an
   uncertainty band.
2. **Add B for nowcasting.** Same model, extra features from IMERG Early frames. Improves the
   0 to 2 hour range.
3. **ConvLSTM on IMERG or radar frames.** Input last 12 frames over a Tamil Nadu grid, output
   next 6 frames. Sample the output grid at the point. This is the only route to real
   storm-motion skill. Needs the gridded data from `DATASETS_FOR_ML_MODELS.md`.
4. **Blend.** Nowcast weight decays from 1.0 at lead 0 to 0.0 at lead 3 hours, NWP weight the
   reverse. Standard operational practice.

### 2.4 Datasets for Stage 1

| Factor | Dataset | Resolution | Access | Cost |
|---|---|---|---|---|
| Multi-model NWP forecast | Open-Meteo Forecast API with `models=ecmwf_ifs025,gfs_seamless,icon_seamless` and `minutely_15=precipitation` | 9 to 13 km, hourly, 15-min for some | `https://api.open-meteo.com/v1/forecast` | Free, no key |
| Historical forecasts for training | Open-Meteo Previous Runs API and Historical Forecast API | Same | `https://previous-runs-api.open-meteo.com/v1/forecast`, `https://historical-forecast-api.open-meteo.com/v1/forecast` | Free |
| Reanalysis truth and training features | Open-Meteo Archive (ERA5, ERA5-Land) hourly | 0.1 to 0.25 deg | `https://archive-api.open-meteo.com/v1/archive` | Free |
| Satellite rain, near real time | GPM IMERG Early Run V07 | 0.1 deg, 30 min, 4 h latency | NASA GES DISC with Earthdata login, or Earth Engine `NASA/GPM_L3/IMERG_V07` | Free |
| Satellite rain, research quality | GPM IMERG Final Run V07 | 0.1 deg, 30 min, 3.5 month latency | Same | Free |
| Geostationary cloud imagery | INSAT-3D/3DR via MOSDAC | 4 km, 30 min | `https://mosdac.gov.in`, registration | Free |
| Radar | IMD Doppler radar Chennai, Karaikal | 1 km, 10 min | Images only on `https://mausam.imd.gov.in`, no API | Free to view |
| IMD gauges | IMD AWS and ARG network, district-wise rainfall | Station, hourly to daily | `https://mausam.imd.gov.in`, IMD Data Supply Portal `https://dsp.imdpune.gov.in` with registration | Free |
| State gauges | TN SMART, Tamil Nadu State Disaster Management ARG network | Station, hourly | `https://tnsmart.tn.gov.in` public dashboard | Free to view |
| Crowd gauges | Weather Underground Personal Weather Stations | Station, 5 min | PWS API, free key if you contribute a station | Free with condition |
| Crowd gauges | Netatmo Weathermap public stations | Station | Netatmo public API | Free |
| Lightning | Blitzortung community network | Point strikes, real time | `https://www.blitzortung.org`, data access for participants | Free with condition |
| Terrain | Copernicus DEM GLO-30 | 30 m | AWS Open Data `copernicus-dem-30m` | Free |
| Terrain | SRTM via AWS Terrain Tiles | 30 m | Already in `inundation.py` | Free |
| Coastline | OpenStreetMap `natural=coastline`, or Natural Earth | Vector | Overpass, Natural Earth download | Free |
| Sea surface temperature | NOAA OISST v2.1 | 0.25 deg, daily | NOAA PSL, Earth Engine `NOAA/CDR/OISST/V2_1` | Free |
| MJO and monsoon indices | NOAA CPC MJO index, IMD monsoon bulletins | Daily | NOAA CPC text files | Free |
| Urban heat | MODIS land surface temperature | 1 km | Earth Engine `MODIS/061/MOD11A1` | Free |

---

## 3. Stage 2: predicting impact at a point

Take Stage 1 output (intensity, duration, total, probability, uncertainty band) and combine
with the static and dynamic factors below. This is your existing `compute_impact` with real
inputs replacing estimates.

### 3.1 Factor list with datasets

**Hydrological: ground**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Soil texture, infiltration | ISRIC SoilGrids v2 | 250 m | REST API, already in `hyperlocal.py` |
| Soil texture, India specific | NBSS&LUP soil maps via Bhuvan | 1:250k | ISRO Bhuvan, registration |
| Soil moisture, live | Open-Meteo `soil_moisture_0_to_7cm`, `_7_to_28cm` | 0.1 deg, hourly | Free |
| Soil moisture, satellite | NASA SMAP L4 | 9 km, 3 h | Earth Engine `NASA/SMAP/SPL4SMGP/007` |
| Antecedent rain 3 to 7 days | Open-Meteo Archive daily | Point | Already in your code |
| Groundwater depth | CGWB groundwater levels, India-WRIS | Well points, seasonal | `https://indiawris.gov.in` |
| Hydrological soil group for runoff curve number | HYSOGs250m | 250 m | ORNL DAAC, Earthdata |

**Topographical**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Elevation | Copernicus DEM GLO-30, SRTM | 30 m | AWS Open Data, already have SRTM |
| Elevation, India | CartoDEM v3 | 30 m | ISRO Bhuvan, registration |
| HAND, flow accumulation, flow direction | MERIT Hydro | 90 m | Earth Engine `MERIT/Hydro/v1_0_1` |
| Catchment boundaries, stream network | HydroSHEDS, HydroBASINS, HydroRIVERS | 90 m, vector | `https://www.hydrosheds.org`, Earth Engine |
| Slope, aspect, curvature | Derive from DEM | 30 m | Compute with numpy or `richdem` |
| Closed depressions | Derive with priority flood | 30 m | Already in `inundation.py` |
| Distance to water | OSM waterways and water bodies | Vector | Already in your Overpass query |

**Infrastructure and drainage**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Storm drains, ditches, canals | OSM `waterway=drain`, `ditch`, `canal`, `man_made=storm_drain` | Vector | Overpass, already partly used |
| Culverts | OSM `tunnel=culvert`, `waterway=culvert` | Vector | Overpass |
| Embankments, bunds | OSM `embankment=yes`, `man_made=dyke`, `man_made=embankment` | Vector | Overpass |
| Roads, underpasses | OSM `highway=*`, `tunnel=yes`, `layer=-1` | Vector | Overpass |
| Pumping stations | OSM `man_made=pumping_station` | Vector | Overpass |
| Chennai stormwater drain network | Greater Chennai Corporation SWD data, partial on open data portals | Vector | `https://data.opencity.in`, `https://tn.data.gov.in` |
| Drain design capacity | GCC SWD project reports, CMDA Second Master Plan | Document | Manual lookup per zone |
| Impervious surface | ESA WorldCover 2021 built-up class | 10 m | Earth Engine `ESA/WorldCover/v200` |
| Impervious surface, near real time | Dynamic World | 10 m, continuous | Earth Engine `GOOGLE/DYNAMICWORLD/V1` |
| Built-up density and height | GHSL Built-up Surface and Height | 100 m | JRC, Earth Engine `JRC/GHSL/P2023A` |
| Building footprints | Google Open Buildings v3 | Polygon | Earth Engine, direct download |
| Building footprints | Microsoft Global Building Footprints, India | Polygon | GitHub `microsoft/GlobalMLBuildingFootprints` |
| Power infrastructure | OSM `power=substation`, `power=line` | Vector | Overpass |

**Water bodies and upstream systems**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Lakes, tanks, marshes | JRC Global Surface Water | 30 m, 1984 to present | Earth Engine `JRC/GSW1_4/GlobalSurfaceWater` |
| Lakes | HydroLAKES | Vector | `https://www.hydrosheds.org` |
| Tank encroachment over time | JRC GSW occurrence change, Landsat | 30 m | Earth Engine |
| Reservoir levels, Chennai | Chennai Metro Water lake levels, Poondi, Cholavaram, Red Hills, Chembarambakkam, Kannankottai | Daily | `https://chennaimetrowater.tn.gov.in` lake level page |
| Reservoir levels, state | TN Water Resources Department daily reservoir report | Daily | `https://www.wrd.tn.gov.in` |
| Reservoir levels, national | Central Water Commission reservoir bulletin, India-WRIS | Daily to weekly | `https://cwc.gov.in`, `https://indiawris.gov.in` |
| River stage and flood forecast | CWC Flood Forecasting | Hourly at gauge sites | `https://ffs.india-water.gov.in` |
| Tide, sea level | Open-Meteo Marine API `sea_level_height_msl` | Hourly | `https://marine-api.open-meteo.com/v1/marine` |
| Tide tables | INCOIS, Survey of India | Daily | `https://incois.gov.in` |
| Storm surge forecast | INCOIS storm surge early warning | Event based | `https://incois.gov.in` |

**Land cover and vegetation**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Land cover | ESA WorldCover | 10 m | Earth Engine |
| Land cover, India | Bhuvan LULC 1:50k | 50 m class | ISRO Bhuvan |
| Vegetation index | Sentinel-2 NDVI, MODIS NDVI | 10 m to 250 m | Earth Engine |
| Crop type and phase | Bhuvan crop maps, TNAU | Seasonal | Bhuvan, `https://agritech.tnau.ac.in` |

**Exposure: people and assets**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Population | WorldPop constrained | 100 m | Earth Engine `WorldPop/GP/100m/pop`, `https://www.worldpop.org` |
| Population | Meta High Resolution Settlement Layer | 30 m | HDX `https://data.humdata.org` |
| Population | GHSL-POP | 100 m | JRC, Earth Engine |
| Ward-level census | Census of India 2011 PCA by ward | Ward | `https://censusindia.gov.in` |
| Hospitals, schools, shelters | OSM `amenity=hospital`, `school`, `shelter` | Point | Overpass |
| Health facilities | Healthsites.io | Point | `https://healthsites.io` API |
| Night lights as economic proxy | VIIRS Nighttime Lights | 500 m | Earth Engine `NOAA/VIIRS/DNB/MONTHLY_V1` |
| Informal settlements | GCC slum lists, TNUHDB | Polygon or list | State portals, partial |
| Vulnerable population share | Census 2011 age tables | Ward | Census of India |

**Historical and validation**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Flood events by district | India Flood Inventory with Impacts v4 | Event, 1967 to 2023 | `https://zenodo.org/doi/10.5281/zenodo.4742142` |
| Flood extents from satellite | Global Flood Database | 250 m, 2000 to 2018 | Earth Engine `GLOBAL_FLOOD_DB/MODIS_EVENTS/V1` |
| Flood extents, event | Copernicus EMS rapid mapping, UNOSAT | 10 m, per event | `https://emergency.copernicus.eu`, `https://unosat.org` |
| Chennai 2015 and 2023 flood maps | NRSC Bhuvan disaster services | 10 to 50 m | `https://bhuvan.nrsc.gov.in` |
| Flood extents you compute | Sentinel-1 SAR change detection | 10 m | Earth Engine `COPERNICUS/S1_GRD` |
| Global flood events | Dartmouth Flood Observatory | Event | `https://floodobservatory.colorado.edu` |
| Disaster losses | EM-DAT | Event | `https://www.emdat.be`, registration |
| Return periods, India | IMD rainfall intensity-duration-frequency atlases | Station | IMD publications |
| Long station record | TNDMA daily rainfall 1991 to 2023 | Station, daily | `https://data.opencity.in` |

**Secondary hazards**

| Factor | Dataset | Resolution | Access |
|---|---|---|---|
| Landslide susceptibility | GSI Bhukosh landslide susceptibility maps | 1:50k | `https://bhukosh.gsi.gov.in` |
| Landslide inventory | NRSC Landslide Atlas of India, NASA Global Landslide Catalog | Point | Bhuvan, NASA |
| Lightning climatology | ISRO and IITM lightning data, Blitzortung | Point | Limited |
| Disease outbreaks | IDSP weekly outbreak reports | District, weekly | `https://idsp.mohfw.gov.in` |

---

## 4. Putting it together in RIIS

### 4.1 Pipeline

```
Stage 1  Rainfall intensity at point
         inputs:  Open-Meteo multi-model forecast, IMERG Early, gauges, DEM, coast distance, time
         model:   LightGBM quantile regressor (now), ConvLSTM nowcast (later)
         output:  intensity p10/p50/p90 for leads 1h..6h, event total, duration, onset

Stage 2  Impact at point
         inputs:  Stage 1 output + soil + soil moisture + HAND + flow accumulation + impervious
                  + drains/culverts/embankments + reservoir levels + river stage + tide
                  + population + buildings + critical facilities + past floods
         model:   your weighted engine now, calibrated weights later
         output:  impact score, class, ponding depth, inundated area, people exposed

Stage 3  Inundation map
         inputs:  Stage 2 runoff volume + DEM
         model:   priority flood volume matching (now), shallow-water or SWMM (later)
```

### 4.2 Ingestion plan

1. **Static layers, fetch once per site and cache to disk**, not in-process memory:
   DEM, HAND, flow accumulation, soil, land cover, impervious, buildings, OSM drains and
   culverts, population, critical facilities, past flood count. Store as a per-site JSON.
2. **Slow dynamic, refresh daily:** reservoir levels, river stage, soil moisture, NDVI.
3. **Fast dynamic, refresh every 15 to 60 minutes:** multi-model forecast, IMERG Early,
   gauges, tide, lightning.
4. **Training set for Stage 1:** 2 to 3 years of Open-Meteo Previous Runs forecasts joined to
   observed rain at each gauge or IMERG cell at the same time. Features from the forecast,
   target from the observation. Split by time.
5. **Calibration set for Stage 2:** India Flood Inventory events joined to your computed
   impact score on those dates. Tune category weights so flood dates score high and dry
   dates score low. Even a logistic regression on the 8 category scores is a real calibration.

### 4.3 Easiest wins for your current code

| Change | Replaces | Source |
|---|---|---|
| Pull `soil_moisture_0_to_7cm` | Estimated saturation percent | Open-Meteo hourly |
| Pull `sea_level_height_msl` for coastal sites | Nothing | Open-Meteo Marine |
| Compute HAND and flow accumulation from the DEM you already download | `lowness` proxy | numpy D8 routing or MERIT Hydro |
| Query `tunnel=culvert` and `embankment=yes` | Nothing | Overpass, same call |
| Read Chennai Metro Water lake levels daily | Modelled reservoir storage | Public page, scrape |
| Join India Flood Inventory counts per district | Nothing | Zenodo CSV |
| Multi-model forecast with `models=` | Single Open-Meteo default | Same API |

### 4.4 Platform note

Most raster layers above live in Google Earth Engine, which is free for research and
non-commercial use. One Python script with the `ee` and `geemap` packages can sample every
layer at a list of points or export a clipped grid for Tamil Nadu. That is the fastest way
to get HAND, impervious, population, land cover and surface water for all 36 districts and
any hyperlocal site in one pass.
