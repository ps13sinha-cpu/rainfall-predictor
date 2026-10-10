# Forecast providers — licensing, fallback and self-hosted paths

## The plain facts

- **Open-Meteo's free API is for non-commercial use only.** Its terms allow personal,
  research and educational projects under the 10,000-call-units-a-day limit; a public
  deployment that serves the general public as a product, or anything commercial, needs
  the [Open-Meteo API commercial plan](https://open-meteo.com/en/pricing) (paid, higher
  limits, dedicated endpoints) **or a second data source**. Everything the live screens show
  today (district weather, farmer advisory, hyperlocal forecast models, the historical and
  hourly training archives) comes from Open-Meteo.
- The free tier is accounted in call units: 1 unit per location per two weeks of data per
  10 variables; 600 / minute, 5,000 / hour, 10,000 / day, resetting at 00:00 UTC. The
  backend enforces a soft cap of 8,000 a day (`RIIS_OPENMETEO_DAILY_CAP`) in
  `app/services/budget.py`; every call site reserves units first and the bulk ingest
  scripts refuse to start when their estimate does not fit (`RIIS_BUDGET_OVERRIDE=1` forces).
- **MET Norway is wired as the live fallback.** `app/services/forecast_providers.py`
  calls Locationforecast 2.0 (compact) when Open-Meteo raises, answers 429 or the budget is
  exhausted. MET's data is CC BY 4.0 and free for commercial use provided the attribution
  ("Data from MET Norway") is shown and their terms are honoured: identifying User-Agent
  (`RIIS/1.0 sinhapiyush987@gmail.com`), coordinates with at most four decimals, respect
  of `Expires` and `If-Modified-Since` (the module keeps a small on-disk cache in
  `backend/cache/metno/`). MET gives temperature, humidity, pressure, wind, cloud cover and
  1-hourly / 6-hourly precipitation; it does not give air quality, UV, gusts, a WMO code,
  precipitation probability, dew point or visibility, and those fields are `None` rather
  than defaults when MET served the row. `weather_cache.provider` and
  `weather_cache.provider_fallback` record which provider filled each district.
- The `/api/health/monitoring` route reports `forecast_provider_fallback` counts, the
  Open-Meteo budget status and the three-model smoke check (ECMWF IFS 0.25, GFS, ICON).

## Self-hosted paths (no third-party API in the serving path)

### Forecast: ECMWF Open Data (free, CC BY 4.0)

ECMWF publishes its operational IFS forecast (0.25 deg, 4 runs a day, up to 15 days) at
`https://data.ecmwf.int/forecasts` as GRIB2.

1. `pip install ecmwf-opendata eccodes cfgrib xarray` and install the ecCodes binaries
   (`conda install -c conda-forge eccodes`, or the OS package `libeccodes`).
2. Download the latest run for the fields the engine uses (`tp` total precipitation,
   `2t`, `2d` / `r`, `10u`, `10v`, `msl`, `tcc`):
   ```python
   from ecmwf.opendata import Client
   Client(source="ecmwf").retrieve(
       type="fc", step=list(range(0, 145, 3)),
       param=["tp", "2t", "2d", "10u", "10v", "msl", "tcc"],
       target="ifs_latest.grib2")
   ```
3. Open with `xarray.open_dataset("ifs_latest.grib2", engine="cfgrib")`, pick the nearest
   grid point to each district / site, and difference the accumulated `tp` between steps to
   get per-step precipitation (metres, so multiply by 1000 for mm).
4. Write a `fetch_ecmwf(lat, lon)` in `app/services/forecast_providers.py` that returns the
   same dict shape as `parse_weather` (see `parse_metno` for the mapping pattern) and add it
   to `fetch_with_fallback`'s chain. Refresh the GRIB file from a scheduler job every 6 h
   (about 100-300 MB per run for a regional subset; use the `area` option to crop to India).

### Training archive: Copernicus CDS ERA5 / ERA5-Land (free, needs an account)

The historical and hourly tables were built from Open-Meteo's archive endpoint, which is
itself ERA5 / ERA5-Land. The same data comes straight from Copernicus:

1. Register at https://cds.climate.copernicus.eu, accept the ERA5 licence, and put the key
   in `~/.cdsapirc` (`url: https://cds.climate.copernicus.eu/api` and `key: <uid>:<key>`).
2. `pip install cdsapi netCDF4 xarray`.
3. Request hourly single-level variables over India (one request per year keeps you inside
   CDS's queue limits):
   ```python
   import cdsapi
   cdsapi.Client().retrieve("reanalysis-era5-land", {
       "variable": ["total_precipitation", "2m_temperature", "2m_dewpoint_temperature",
                    "surface_pressure", "10m_u_component_of_wind", "10m_v_component_of_wind",
                    "volumetric_soil_water_layer_1"],
       "year": "2024", "month": [f"{m:02d}" for m in range(1, 13)],
       "day": [f"{d:02d}" for d in range(1, 32)], "time": [f"{h:02d}:00" for h in range(24)],
       "area": [37, 68, 6, 98], "format": "netcdf"}, "era5land_2024.nc")
   ```
4. Sample the NetCDF at each district's lat/lon (`xarray.Dataset.sel(..., method="nearest")`),
   convert units (precipitation m -> mm, temperatures K -> C, wind components -> speed and
   direction, pressure Pa -> hPa) and insert into `historical_hourly` with the same column
   names `app/ingest_hourly.py` uses; the daily aggregates for `historical_weather` follow
   from that table. The sequence and grid trainers do not care where the rows came from.

## Where this lives in the code

| Concern | File |
| --- | --- |
| Budget accounting, `reserve`, `budgeted_get` | `app/services/budget.py` |
| MET Norway fetch + parse, `fetch_with_fallback`, NWP smoke | `app/services/forecast_providers.py` |
| District poller using the fallback chain | `app/services/weather.py` (`update_district_weather`) |
| Provider columns | `weather_cache.provider`, `weather_cache.provider_fallback` |
| Monitoring counters and alerts | `app/services/monitoring.py`, `GET /api/health/monitoring` |
