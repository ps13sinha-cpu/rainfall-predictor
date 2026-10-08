# RIIS Backend

FastAPI backend for the Real-time Indian Infrastructure Intelligence System.

## Quick Start

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

From the repository root on Windows, `./start-riis.ps1` starts both the API
and the static frontend. Then open `http://127.0.0.1:5173`. The frontend API
target can be overridden before loading the page with `window.RIIS_API_BASE`.

The server auto-creates the SQLite database, seeds 36 districts + 15 reservoirs,
and starts polling Open-Meteo for live weather every 5 minutes.

## API Endpoints

### Auth
- `POST /api/auth/register` — Create account (username, email, password, full_name)
- `POST /api/auth/login` — Get JWT token
- `GET /api/auth/me` — Current user (requires Bearer token)

### Districts & Weather
- `GET /api/districts/states` — Risk index per state / UT, aggregated from the live district risks (0.6 x worst district + 0.4 x state mean), with the worst district and the district list
- `GET /api/districts/` — List all districts with risk indices (query: ?state=X&risk_class=X)
- `GET /api/districts/{code}` — District detail + full weather data
- `GET /api/districts/{code}/hourly` — 168-hour hourly forecast for charts
- `POST /api/weather/refresh` — Trigger immediate weather poll for all districts
- `POST /api/weather/refresh/{code}` — Refresh one district

### Reservoirs (live daily reports)
- `GET /api/reservoirs/` — All reservoirs; rows carry `source` (`cmwssb`, `kseb`, `manual`, `seed`), `observed_at`, level, storage %, rainfall, last-year storage, KSEB alert level
- `GET /api/reservoirs/live/status` — Last fetch time and per-source outcome
- `POST /api/reservoirs/sync` — Fetch Chennai Metro Water (cmwssb.tn.gov.in/lake-level) and KSEB (dams.kseb.in) now; the scheduler does this every 6 h and 5 s after start
- `GET /api/reservoirs/{code}/history?days=14` — Daily storage history (Chennai Metro Water reservoirs)
- `GET /api/reservoirs/{code}` / `PUT /api/reservoirs/{code}` — Single reservoir / manual override (marks the row `manual`)

### Community Reports
- `POST /api/reports/` — Submit report (requires reporter role)
- `GET /api/reports/` — List reports (?status=pending&severity=high)
- `GET /api/reports/{id}` — Report detail
- `POST /api/reports/{id}/upvote` — Upvote
- `PUT /api/reports/{id}/moderate?action=approve` — Moderate (admin)

### Alerts
- `POST /api/alerts/` — Create alert (admin)
- `GET /api/alerts/` — List active alerts
- `PUT /api/alerts/{id}/deactivate` — Deactivate (admin)

### Historical
- `GET /api/historical/{code}?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` — Historical data
- `POST /api/historical/ingest/{code}?start_date=...&end_date=...` — Ingest from Open-Meteo archive

### ML models
- `GET /api/ml/predict/{code}?model=ensemble_vote` — Next-day rainfall-class prediction (`xgboost`, `random_forest`, `gradient_boost`, `ensemble_vote`)
- `GET /api/ml/predict-all/{code}` — All four tabular models side by side
- `GET /api/ml/shap/{code}` — SHAP attributions for the predicted class
- `GET /api/ml/models` — Registry of every trained model with held-out metrics (also LSTM, Transformer, ConvLSTM, ConvGRU)
- `GET /api/ml/metrics` — Legacy metrics shape plus the registry summary
- `POST /api/ml/train` — Retrain the tabular models

Training scripts and results: see [TRAINING.md](TRAINING.md).

### Hyperlocal impact (engine v2)
- `GET /api/hyperlocal/impact?lat=&lon=&rainfall_mm=&duration_h=&pattern=steady|front|back|burst` — Ten-factor impact score, hourly ponding model, secondary hazards
- `GET /api/hyperlocal/factors?lat=&lon=` — Every raw input: terrain hydrology, soil and soil moisture, OSM drainage and facilities, tide, upstream reservoirs, flood history, multi-model forecast
- `GET /api/hyperlocal/geofactors?lat=&lon=` — Static layers and antecedent rain

Design and data sources: see [HYPERLOCAL_ENGINE.md](HYPERLOCAL_ENGINE.md).

### Safe Routes — `/api/routes` (flood-aware routing)
- `GET /api/routes/site?lat&lon` — Build or load the road site (~3.6 km SRTM window): OSM roads, culverts, water; cached 7 days
- `GET /api/routes/roads?lat&lon&rainfall_mm&duration_h&intensity_mm_h&mode` — GeoJSON of every segment with `status` (open | caution | closed_cars | closed_all), `max_depth_m`, `wet_fraction`, `risk_ml`, plus `most_affected`
- `GET /api/routes/route?from_lat&from_lon&to_lat&to_lon&rainfall_mm&duration_h&mode` — Safe route (closed removed, caution penalised) next to the normal shortest route; `reachable:false` + `blocking_segments` when cut off. Destinations beyond the ~3.6 km site use the public OSRM router for the baseline (`source: osrm+local`), flood-checked and locally detoured inside every mapped area the route crosses; the destination area is mapped in the background and `scored_fraction` says how much of the route is checked
- `GET /api/routes/geocode?q&lat&lon` / `GET /api/routes/reverse?lat&lon` — Nominatim proxies (custom User-Agent, 1 request/s, cached)
- `POST /api/routes/report` `{lat, lon, status, depth_cm, note}` / `GET /api/routes/reports?lat&lon` — Field reports override the simulation within 25 m for 6 h
- `GET /api/routes/model` / `POST /api/routes/train` — Road flood-risk surrogate metrics / retrain (admin)

Tables: `road_sites`, `road_segments`, `road_status_cache`, `road_reports`, `route_logs`, `road_risk_samples`.
Thresholds: closed_all >= 0.60 m, closed_cars >= 0.30 m, caution >= 0.15 m (or >= 0.05 m next to a culvert); underpasses are at least caution and closed to cars when any wet cell is within 60 m; bridges stay open.
Depth comes from the same `net_ponding_mm` + `depth_grid` the inundation map uses. The road risk model is a **surrogate trained on simulated scenarios** (28 per site, six seed sites, one site held out); `label_source` records which samples are real community reports. See `python -m app.train_roads`.

### Farmer advisory — `/api/farmer`
- `GET /api/farmer/advisory?lat&lon&crop&stage` — Live, location-specific advice: 7-day forecast (rain, probability, temperatures, ET0, wind, UV), soil moisture at 0-7 / 7-28 / 28-100 cm, FAO-56 water balance (Kc x ET0) and irrigation amount / timing, waterlogging hours from the ponding model vs crop tolerance, heat and cold stress days, disease pressure from hourly humidity and temperature, spray / harvest / sowing windows, lodging risk, flood history and the nearest reservoir, plus ranked advisories. Crops: paddy, sugarcane, cotton, groundnut, millets, tomato; stages: Sowing, Vegetative, Flowering, Grain-filling, Harvest. Cached 15 min.
- `GET /api/farmer/geocode?q=` — India-wide place search for the field location box
- `GET /api/farmer/crops` — crop and stage lists

### System
- `GET /api/health` — Health check
- `GET /api/stats` — System-wide statistics

## Architecture

```
backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, lifespan
│   ├── config.py            # Settings from env / .env
│   ├── database.py          # SQLAlchemy async engine
│   ├── models/__init__.py   # All ORM models
│   ├── routes/
│   │   ├── auth.py          # Register, login, JWT
│   │   ├── districts.py     # District CRUD + weather data
│   │   ├── reservoirs.py    # Reservoir CRUD
│   │   ├── reports.py       # Community reports
│   │   ├── alerts.py        # Alert management
│   │   ├── historical.py    # Historical data + ingestion
│   │   └── weather.py       # Manual refresh trigger
│   ├── services/
│   │   ├── weather.py       # Open-Meteo proxy, risk calc, caching
│   │   ├── auth.py          # JWT + password hashing
│   │   └── scheduler.py     # APScheduler background jobs
│   ├── seed.py              # Seed districts + reservoirs
│   └── middleware/          # (reserved)
├── requirements.txt
├── .env.example
└── riis.db                  # SQLite database (auto-created)
```

## Roles
- **public** — Read-only access to approved reports and alerts
- **reporter** — Can submit community reports
- **admin** — Full access: moderation, alerts, reservoir updates, historical ingestion

## Background Scheduler
Polls Open-Meteo every 5 minutes for all 36 districts. Updates weather cache,
recomputes risk indices, and scales reservoir inflow based on rainfall.
