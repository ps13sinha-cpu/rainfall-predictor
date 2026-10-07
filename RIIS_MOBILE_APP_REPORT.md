# RIIS — Complete Project Report & Mobile App Blueprint

**Project:** RIIS — Rainfall Impact Intelligence System
**Report written:** 29 September 2026
**Scope:** Every component of the existing system, the complete UI inventory, the notification
and user-feedback pipelines, what blocks a mobile app today, and a concrete mobile blueprint.

---

## 0. How to read this document

| Section | Answers |
|---|---|
| 1–3 | What RIIS is, how it runs, what the files are |
| 4–8 | Backend: data model, every endpoint, every prediction engine, auth |
| 9 | **Notifications** — the exact pipeline a mobile app must plug into |
| 10 | **User input / reviews** — how citizen feedback works today and where it breaks |
| 11 | **UI** — every screen, every component, the full design system |
| 12 | Defects & blockers ranked by "does this stop a mobile app" |
| 13 | Mobile app blueprint: architecture, screens, API contract, push, offline |
| 14 | Phased roadmap |
| 15 | Appendix: env vars, ports, run commands, endpoint quick index |

Everything below was derived by reading the source directly. Where the code does not do what
the UI or docs claim, it is flagged explicitly as **[GAP]** or **[BUG]**.

---

## 1. Executive summary

RIIS is a full-stack, India-focused rainfall-impact **decision-support platform**. It has two
halves that run as separate processes:

- **Frontend** — a React 18 "operations terminal" UI. No bundler, no build step: React and
  Babel are loaded from CDN, and 11 `.jsx` files are transpiled **in the browser**. Served as
  static files by a 26-line Node HTTP server on **:5173**.
- **Backend** — a FastAPI service on **:8000/:8001** with SQLite (async SQLAlchemy),
  APScheduler, XGBoost + SHAP, and a physics-based DEM flood model.

**What is genuinely live and real:**

- Open-Meteo forecast ingestion for 36 seeded districts, refreshed every 300 s by APScheduler.
- Hyperlocal geofactors from real open APIs — Open-Meteo Elevation, OSM Overpass (drainage,
  land use), ISRIC SoilGrids, Open-Meteo archive (3 years of daily rainfall).
- An 8-category weighted impact engine producing a 0–100 score with per-category sourcing.
- A DEM-driven inundation engine: AWS Terrain Tiles (terrarium) at ~4.6 m/pixel, priority-flood
  depression filling, volume-balance water-level search, GeoJSON flood polygons.
- A trained XGBoost 4-class risk classifier served with SHAP attributions.
- Live Leaflet maps with RainViewer radar, live GPS, reverse geocoding, and search.

**What looks live in the UI but is decorative, hardcoded, or synthetic:**

- Community report submission — the entire submit path is non-functional (see §10).
- Alert broadcast buttons in the Alerts screen — no `onClick` handler at all.
- History, Admin, and most of Disaster Ops screens — hardcoded arrays of realistic-looking numbers.
- The "AI System Status" panel, model accuracy tables, retraining queue, system logs — all static.
- Reservoir telemetry — seeded modelled values, no live dam feed.
- The chat assistant — pattern-matching over local data, not an LLM (§11.14).

**The single most important finding for your goal:** the feature you want to build the mobile app
around — *users submitting reviews/observations that feed back into the system* — **cannot work
today**. `POST /api/reports/` requires a `reporter` or `admin` role, but `POST /api/auth/register`
hardcodes every new user to `role="public"`, and no endpoint exists to promote a role. Every
registered app user would receive HTTP 403. This is a 5-line fix, but it must be fixed first.

---

## 2. Repository map

```
rainfall predictor/
├── REPORT.md                     # prior project report (accurate on architecture, optimistic on gaps)
├── start-riis.ps1                # Windows launcher: node :5173 + uvicorn :8001
├── project.zip                   # archived snapshot of the frontend
│
├── backend/                      # ── FastAPI service ──────────────────────────────
│   ├── app/
│   │   ├── main.py               # app factory, lifespan (init_db → seed → scheduler), 12 routers
│   │   ├── config.py             # pydantic-settings; all env vars and external URLs
│   │   ├── database.py           # async engine, session factory, get_db dependency, init_db
│   │   ├── seed.py               # 36 districts + 15 reservoirs, idempotent
│   │   ├── train_ml.py           # CLI: ingest 2 yrs Open-Meteo archive → train XGBoost
│   │   ├── ingest_remaining.py   # CLI: retry 16 districts that hit 429 rate limits
│   │   ├── models/__init__.py    # 8 SQLAlchemy ORM models
│   │   ├── services/
│   │   │   ├── weather.py        # Open-Meteo proxy, WMO codes, risk formula, batch poll
│   │   │   ├── hyperlocal.py     # geofactors + antecedent + the 8-category impact engine
│   │   │   ├── inundation.py     # DEM fetch, priority-flood, water-level search, GeoJSON
│   │   │   ├── ml.py             # XGBoost train/predict + SHAP attribution
│   │   │   ├── alerting.py       # Twilio SMS/WhatsApp + FCM push + in-memory subscribers
│   │   │   ├── auth.py           # JWT (python-jose), bcrypt, role dependencies
│   │   │   └── scheduler.py      # APScheduler job
│   │   ├── routes/               # 12 routers (auth, districts, reservoirs, reports, alerts,
│   │   │                         #   historical, weather, ml, uploads, subscriptions,
│   │   │                         #   hyperlocal, inundation)
│   │   └── ml_models/            # risk_model.pkl + metrics.json (trained artifact)
│   ├── requirements.txt          # pinned deps   ← missing Pillow & scipy (see §12.1)
│   ├── docker-compose.yml        # postgres:16 + backend, named volumes
│   ├── Dockerfile                # python:3.11-slim, uvicorn --workers 4
│   ├── SETUP.md                  # step-by-step Twilio / Firebase / Postgres / EC2 guide
│   ├── README.md                 # endpoint list, roles, architecture
│   ├── riis.db                   # SQLite database (auto-created/seeded)
│   └── .env.example              # template (note: PORT=8001 here vs 8000 default in config.py)
│
├── project/                      # ── Frontend (no build step) ──────────────────────
│   ├── index.html                # 36 lines: CDN React/Babel, 11 cache-busted script tags
│   ├── server.js                 # static file server :5173
│   ├── serve-local.js            # alternate static server
│   ├── src/
│   │   ├── api.js     (229)      # window.RIIS_API — 30 fetch wrappers, JWT from localStorage
│   │   ├── data.js    (1146)     # window.RIIS global state + all live-data orchestration
│   │   ├── app.jsx    (198)      # Rail nav, TopBar, hash router, ChatPanel mount
│   │   ├── primitives.jsx (259)  # 40 SVG icons, gauges, sparkline, radar, rain animation
│   │   ├── charts.jsx (174)      # LineChart, BarChart, Donut, Heatmap (hand-rolled SVG)
│   │   ├── maps.jsx   (559)      # IndiaMap, ChennaiMap, FloodSimMap, RealFloodMap (Leaflet)
│   │   ├── dashboard.jsx (325)   # DashboardScreen
│   │   ├── screens_map_city.jsx (265)
│   │   ├── screens_xai_timeline.jsx (304)
│   │   ├── screens_simulate_farmer_reservoir.jsx (495)
│   │   ├── screens_disaster_alerts_emergency.jsx (626)
│   │   ├── screens_community_history_admin.jsx (363)
│   │   ├── chat.jsx   (137)      # rule-based assistant
│   │   ├── styles.css (512)      # design system
│   │   └── leaflet.js / leaflet.css  # vendored Leaflet 1.9
│   └── screenshots/              # 01-dashboard, 02-map, 03-simulate (JPEG)
└── outputs/                      # two .pptx concept decks
```

**Frontend LOC:** ~5,176 across 15 files. **Backend:** 12 routers, 7 services, 8 models.

---

## 3. Runtime topology

```
┌──────── BROWSER (fixed 1440px viewport) ────────┐
│  index.html → Babel transpiles 11 .jsx files    │
│  window.RIIS (state)  ← data.js                 │
│  window.RIIS_API      → api.js                  │
│  Leaflet 1.9 + OSM tiles + RainViewer radar     │
└───────┬──────────────────────┬──────────────────┘
        │ direct fetch         │ fetch JSON (+Bearer JWT)
        ▼                      ▼
  Open-Meteo / Nominatim /   FastAPI :8000 (documented) / :8001 (script)
  ipinfo / RainViewer        │
                             ├── SQLite riis.db (async)
                             ├── APScheduler → Open-Meteo poll / 300 s
                             ├── In-process caches (geofactors, DEM, archive)
                             └── Twilio / Firebase  (optional, "simulated" w/o creds)
```

The frontend **dual-sources** live weather: it prefers the backend district list, and falls
back to calling Open-Meteo directly from the browser if the backend is down
(`_fetchDistrictsDirect` in [data.js](project/src/data.js)). That makes the frontend resilient but
also means the browser holds a second, divergent copy of the risk formula (client
`calcDistrictRisk` must be kept in sync with server `calculate_risk` — they are currently
identical, which is a maintenance hazard).

---

## 4. Data layer

Eight ORM models in [models/__init__.py](backend/app/models/__init__.py):

| Model | Purpose | Mobile relevance |
|---|---|---|
| `User` | id, username, email, hashed_password, full_name, **role**, is_active, created_at | **Add `device_tokens`, `fcm_topic`, notification prefs, home lat/lon** |
| `District` | 36 seeded; code, name, state, lat, lon, pop, risk, rain, risk_class | Maps 1:1 to app "location" objects |
| `WeatherCache` | 1:1 with District; 25 columns incl. full hourly JSON | The payload your app's home screen needs |
| `Reservoir` | 15 seeded; capacity/current mcft, inflow/outflow cms, overflow_prob, risk_class | Dam-release alerts |
| `CommunityReport` | author_id, lat/lon, location_name, report_type, title, description, severity, media_url, media_type, is_verified, verified_by, verification_note, upvotes, ai_classified, **ai_class**, status, created_at | **This is your reviews/inputs table — see §10** |
| `Alert` | severity, title, body, area, lat/lon, radius_km, channels JSON, is_broadcast, is_active, expires_at | **This is your push-notification source — see §9** |
| `HistoricalWeather` | district_id + date unique; rainfall, temps, humidity, wind, precip hours | Training data + climate context |
| `SystemLog` | level, source, message, details | **Defined but never written to anywhere** |

**Seeded data.** 36 districts across 16 states (all codes prefixed `IN-<STATE>-<XX>`).
15 reservoirs (Poondi, Sholavaram, Red Hills, Cholavaram, Chembarambakkam, Mullaperiyar, Idukki, …).
`seed()` is idempotent — it only inserts codes that are absent.

**[BUG] Frontend/backend district code mismatch.** The frontend ships its own 35-district list
with short codes (`TN-CH`, `KL-TR`, …). The backend uses `IN-TN-CH` and, for example, labels
Thiruvananthapuram as `IN-TN-TN` with `state="Kerala"`. The merge logic in
`fetchDistrictsLiveData` strips the `IN-` prefix and matches on the remainder, so most districts
line up, but several (e.g. Thiruvananthapuram, Tiruvallur, Vellore) either mismatch or get
**duplicated** — a new district is pushed instead of updating the existing one. A mobile app
should consume the backend code as the single identifier and drop the frontend list entirely.

---

## 5. Complete API reference

Base URL is `http://<host>:8000` by default. **Auth** = `Authorization: Bearer <JWT>`.
"Guarded?" shows what the code actually enforces, not what the docstring claims.

### 5.1 Auth — `/api/auth`

| Method | Path | Body / Query | Guarded? | Returns |
|---|---|---|---|---|
| POST | `/register` | `{username,email,password,full_name}` | public — **role forced to `"public"`** | user object (201) |
| POST | `/login` | `{username,password}` | public | `{access_token, token_type, user}` |
| GET | `/me` | — | `require_user` | current user |

Token: HS256, `exp` = now + 480 min, payload `{sub: "<user id>", role}`. Passwords: bcrypt.

### 5.2 Districts & weather — `/api/districts`, `/api/weather`

| Method | Path | Notes |
|---|---|---|
| GET | `/api/districts/?state=&risk_class=&limit=` | list, ordered by risk desc. **Primary app poll target.** |
| GET | `/api/districts/{code}` | `{district, weather}` — the full home-screen payload |
| GET | `/api/districts/{code}/hourly` | raw Open-Meteo hourly arrays (168 h-ish) |
| POST | `/api/weather/refresh` | **unguarded** — triggers a full 36-district refetch |
| POST | `/api/weather/refresh/{code}` | **unguarded** — single district |

### 5.3 Reservoirs — `/api/reservoirs`

| Method | Path | Guarded? |
|---|---|---|
| GET | `/` | public |
| GET | `/{code}` | public |
| PUT | `/{code}` | **[BUG] not enforced** — `_admin=None, # Would use Depends(require_admin)` |

### 5.4 Community reports — `/api/reports` *(your inputs table)*

| Method | Path | Guarded? | Notes |
|---|---|---|---|
| POST | `/` | **`require_reporter`** | **Public users get 403. See §10.** |
| GET | `/?status=&severity=&limit=` | public | unauthenticated → approved only; authenticated `public` → also approved only |
| GET | `/{id}` | public | |
| POST | `/{id}/upvote` | **none** | increments by 1, no dedupe, no auth |
| PUT | `/{id}/moderate?action=approve\|reject&note=` | `require_admin` | |

### 5.5 Uploads — `/api/uploads`

| Method | Path | Guarded? | Limits |
|---|---|---|---|
| POST | `/` | **[BUG] not enforced** (`user=None`) | jpeg/png/webp/gif/mp4/webm, ≤ 25 MB, saved to `uploads/YYYY-MM/<uuid>.<ext>`, served at `/uploads/...` |

The `/uploads` static mount is only registered **if the directory exists at startup** — on a
fresh clone the first upload creates it, but the mount is already fixed for that process run.

### 5.6 Alerts — `/api/alerts` *(your notification source)*

| Method | Path | Guarded? | Notes |
|---|---|---|---|
| POST | `/` | `require_admin` | creates with `is_broadcast=True` immediately (misleading) |
| GET | `/?active_only=&severity=&limit=` | public | |
| PUT | `/{id}/deactivate` | `require_admin` | |
| POST | `/{id}/broadcast` | `require_admin` | body `{channels:[...]}`, channels ⊂ `web,sms,whatsapp,push` |

### 5.7 Subscriptions — `/api/subscriptions` *(your device registry today)*

| Method | Path | Guarded? | Notes |
|---|---|---|---|
| POST | `/phone` | none | `{phone, name}` |
| POST | `/push` | none | `{token, name}` — FCM/APNs device token |
| GET | `/` | **none** | **returns every subscriber including phone numbers — privacy issue** |
| DELETE | `/{sub_id}` | none | |

**[GAP] Subscribers live in a module-level Python list.** They vanish on every restart, are not
per-user, are not tied to a `User` row, and are not scoped by geography. This is the single
biggest backend change needed for a real mobile app.

### 5.8 Historical — `/api/historical`

| Method | Path | Guarded? |
|---|---|---|
| GET | `/{code}?start_date=&end_date=` | public |
| POST | `/ingest/{code}?start_date=&end_date=` | **[BUG] not enforced** (`user=None`) — writes DB rows |

### 5.9 ML — `/api/ml`

| Method | Path | Guarded? | Notes |
|---|---|---|---|
| GET | `/predict/{code}` | public | class + confidence + per-class probabilities + formula comparison |
| GET | `/shap/{code}` | public | normalised feature attributions (SHAP or formula fallback) |
| POST | `/train?district_code=&start_date=&end_date=` | **[BUG] not enforced** (`user=None`) | CPU-heavy, DoS-able |
| GET | `/metrics` | public | reads `ml_models/metrics.json` |

### 5.10 Hyperlocal — `/api/hyperlocal` *(the strongest part of the backend)*

| Method | Path | Params | Notes |
|---|---|---|---|
| GET | `/geofactors` | `lat, lon, force?` | elevation, slope, lowness, nearest water + counts, soil, land use, antecedent rain |
| GET | `/impact` | `lat, lon, rainfall_mm(0-500), duration_h(0.5-72), intensity_mm_h?, ml_score?` | full 8-category assessment + inundation forecast + advisories |
| GET | `/inundation` | `lat, lon, rainfall_mm(0-600), duration_h, intensity_mm_h?` | DEM flood grid, water balance, stats, **GeoJSON polygons** |

Performance: cold DEM ≈ 21 s (tile download + priority-flood), warm ≈ 1.8 s. Geofactors are
cached per component (elevation 15 min; water/soil/land use 6 h; archive 6 h; DEM 24 h;
filled-DEM memoised on the grid object). The `/inundation` route parallelises geofactors +
antecedent + DEM with three `asyncio` tasks.

### 5.10b Safe Routes — `/api/routes` *(flood-aware navigation)*

| Method | Path | Notes |
|---|---|---|
| GET | `/api/routes/site?lat&lon` | ensure the road site exists (first call fetches OSM + DEM, ~1 to 4 min cold, cached 7 days) |
| GET | `/api/routes/roads?lat&lon&rainfall_mm&duration_h&mode` | GeoJSON segments with flood status + `most_affected` named roads |
| GET | `/api/routes/route?from_lat&from_lon&to_lat&to_lon&rainfall_mm&duration_h&mode` | safe vs normal route, `closed_avoided`, `reachable` |
| GET | `/api/routes/geocode?q&lat&lon` | Nominatim search proxy, 15 km bounded, max 5 |
| GET | `/api/routes/reverse?lat&lon` | Nominatim reverse proxy |
| POST | `/api/routes/report` | road condition report, 6 h override within 25 m |
| GET | `/api/routes/reports?lat&lon` | active reports near a point |
| GET | `/api/routes/model` | road risk surrogate metrics |
| POST | `/api/routes/train` | admin: regenerate samples + retrain |

### 5.11 System

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | `{"status":"ok","version":"1.0.0"}` |
| GET | `/api/stats` | counts + risk distribution — ideal for an ops app, not end users |
| — | `/uploads/*` | static media mount |

---

## 6. Prediction engines

### 6.1 Synoptic risk formula (per district)

Implemented **twice** — server `calculate_risk` in [weather.py](backend/app/services/weather.py) and
client `calcDistrictRisk` in [data.js](project/src/data.js). Identical logic:

```
rain_score = min(60, next_6h_rain / 50 * 60)
prob_score = min(15, min(100, next_6h_rain * 5) / 100 * 15)
hum_score  = max(0, (humidity - 65) * 0.25)
wind_score = min(15, wind_speed / 50 * 15)
risk       = clamp(round(rain+prob+hum+wind), 5, 100)

class: next_6h > 50 or peak > 35  → extreme
       next_6h > 20 or peak > 15  → high
       next_6h >  5 or peak >  4  → mod
       else                        → safe
then floors: extreme→≥75, high→≥50, mod→≥25, safe→≤22
```

Risk classes used consistently across the whole product: **safe <25, mod 25–49, high 50–74,
extreme ≥75**.

### 6.2 The 8-category hyperlocal impact engine

[hyperlocal.py](backend/app/services/hyperlocal.py) `compute_impact()`. Weights:

| Category | Weight | Inputs | Data source |
|---|---|---|---|
| Meteorological | 0.30 | intensity, accumulation, probability, duration, wind | Open-Meteo forecast |
| Hydrological | 0.18 | saturation, runoff coefficient C, infiltration | archive + SoilGrids |
| Topographical | 0.16 | lowness, low elevation, water distance (exponential decay e^(−d/1800)), inverse slope | Open-Meteo Elevation + OSM |
| Infrastructure | 0.10 | impervious %, mapped drain/waterway relief | OSM Overpass |
| Real-time | 0.08 | nowcast intensity + humidity | live current conditions |
| Historical | 0.07 | return period of the event vs 3-yr archive | Open-Meteo archive |
| Socioeconomic | 0.06 | population density in a 25 km² cell | nearest seeded district pop |
| Model | 0.05 | optional XGBoost score, else heuristic; plus a data-confidence figure | ml.py |

Key derived quantities:

```
runoff_c     = clamp(0.18 + 0.55·impervious/100 + 0.22·saturation/100 + soil.runoff_adj, 0.05, 0.95)
drainage_cap = clamp(30 + 3·drains − 0.18·impervious, 8, 45) mm/h
saturation   = clamp(100·(0.55·min(30d,200)/200 + 0.30·min(7d,60)/60 + 0.15·min(3d,25)/25) + 8, 5, 100)
return_period = days_in_archive / count(days ≥ event_mm)
```

**[BUG] `drainage_cap` disagrees with REPORT.md.** The code reads
`30.0 + 3.0 * drains - 0.06 * impervious * 30 / 100 * 10`, which equals
`30 + 3·drains − 0.18·impervious`. The documented formula is `30 + 3·drains − 0.06·impervious`.
The implemented penalty is ~3× larger than documented. The same expression is duplicated in
[inundation.py](backend/app/routes/inundation.py), so the simulator and the impact engine agree
with each other but not with the documentation.

Output shape (what your app should render):

```jsonc
{
  "location": { "lat","lon","elevation_m","slope_m_km","nearest_water_m","water_type",
                "soil_texture","infiltration_mm_h","impervious_pct","green_pct","population_cell" },
  "antecedent": { "rain_3d_mm","rain_7d_mm","rain_30d_mm","saturation_pct","return_days","source" },
  "runoff": { "coefficient","runoff_mm","drainage_capacity_mm_h","peak_runoff_cms" },
  "categories": [ { "name","score","weight","share_pct","source" } ×8 ],
  "impact": { "score","class","confidence_pct","return_period" },
  "inundation": { "depth_mean_m","depth_max_m","area_km2","structures","roads_km",
                  "people_exposed","drainage_saturation_pct","evacuation" },
  "advisories": [ "…human-readable strings…" ],
  "weather": { …live point conditions… },
  "computed_at": "ISO-8601"
}
```

### 6.3 DEM inundation engine

[inundation.py](backend/app/services/inundation.py) — the flagship. Pipeline:

1. **DEM acquisition** — AWS Terrain Tiles terrarium PNG, `elev = r·256 + g + b/256 − 32768`,
   zoom 15 → 384×384 grid, ~4.6 m/pixel, ~1.78 km span, tiled and stitched, 24 h cache
   (max 8 sites in memory).
2. **Depression filling** — Barnes priority-flood over a min-heap seeded from the grid boundary;
   produces the spill elevation `F` per cell.
3. **Volume-balance search** — binary search (50 iterations) for water surface `W` such that
   `Σ min(W,F) − dem⁺` equals the event volume; two regimes: *contained* (pits absorb it) and
   *spilling* (excess spread uniformly as a sheet).
4. **Wet mask** — `depth ≥ 0.05 m`, connected-component labelling, boundary traced into rings,
   collinear points dropped, converted to `MultiPolygon` GeoJSON with lon/lat corner coordinates.
5. **Forcing** — `net_mm = max(0, rainfall·C − drainage_cap·duration_h)`.

Verified behaviour (from the prior report, still consistent with the code): 55 mm/h at Potheri →
"no ponding" (runoff 105 mm < drainage 135 mm); 180 mm/h → 1 polygon, 3.18 km², max depth 6.06 m,
SPILLING.

**[BUG]** `peak_intensity` in [routes/hyperlocal.py](backend/app/routes/hyperlocal.py):
`max(hourly.get("precipitation") or [0][:12])` — Python parses `[0][:12]` as `[0]`, so the
intended "next 12 hours" slice never happens and the max spans the whole two-day series. The
`or` fallback also silently becomes `[0]`.

### 6.4 ML layer — and an honest assessment of it

[ml.py](backend/app/services/ml.py). XGBoost `XGBClassifier`, 4 classes, `n_estimators=100`,
`max_depth=4`, `lr=0.1`, `multi:softprob`. 11 features:

```
rainfall_mm, temp_max, temp_min, humidity_avg, wind_speed_max, precipitation_hours,
rain_lag1, temp_range, rain_squared, humidity_x_rain, wind_x_rain
```

Stored metrics: **accuracy 0.9995 ± 0.0003 on 26,315 samples**, trained 2026-08-28.

**This number is not meaningful.** The label is derived directly from the same row's rainfall:

```python
if   rain > 50: label = 3   # extreme
elif rain > 20: label = 2   # high
elif rain >  5: label = 1   # mod
else:           label = 0   # safe
```

…while `rainfall_mm` is *feature #0*, and `rain_squared`, `humidity_x_rain` and `wind_x_rain`
are deterministic functions of it. The model is being asked to rediscover three threshold
comparisons on a variable it is handed. ~100% accuracy is the expected result of circular
labeling, not evidence of forecasting skill. Additionally, the docstring says the label is
"next-day risk", but the code labels on the **current** row's rain.

**What this means for your product:** do not surface this model's confidence to end users as if
it were validated. Either (a) relabel truthfully — label day *t+k* from rainfall measured on
day *t+k*, with features strictly from ≤ *t* — or (b) present the impact engine (which is
physically grounded) as the primary signal and keep XGBoost as a secondary, clearly-labelled
component. The `predict()`/`get_shap_explanations()` contract is otherwise clean and mobile-ready,
including a formula fallback when no model is trained.

---

## 7. External dependencies & data sources

| Source | Used for | Auth | Cache |
|---|---|---|---|
| Open-Meteo Forecast | current, hourly, daily, per point | none | 300 s poll → `WeatherCache` |
| Open-Meteo Archive | 3-yr daily rainfall, antecedent, return periods; ML training | none | 6 h in-process |
| Open-Meteo Elevation | elevation + slope + lowness (5 sample points) | none | 15 min |
| Open-Meteo Air Quality | US AQI, PM2.5, PM10 | none | 300 s poll |
| Open-Meteo Marine | *(identified in REPORT.md as the SST option)* | none | not implemented |
| OSM Overpass | drains, waterways, water bodies, land use | none | 6 h; 3 mirror URLs |
| ISRIC SoilGrids | clay/sand fractions → texture & infiltration | none | 6 h; regional fallback |
| AWS Terrain Tiles | terrarium DEM for inundation | none | 24 h |
| OpenStreetMap raster tiles | map basemap | none | browser |
| RainViewer | radar overlay on maps | none | per-map-load |
| Nominatim | geocoding, reverse geocoding, search | none | browser/localStorage |
| ipinfo.io / ipapi.co | IP geolocation fallback | none | browser |
| Twilio | SMS + WhatsApp alerts | **SID/token/number** | — |
| Firebase Cloud Messaging | push notifications | **service-account JSON** | — |
| India-WRIS / CWC | reservoir telemetry | — | **unreachable; not implemented** |

Every OSM/SoilGrids call has a regional fallback (Tamil Nadu clay-loam profile, `infiltration
4 mm/h`, `runoff_adj +0.10`) with a `source` flag, so the impact engine degrades gracefully
rather than failing. That design is worth preserving in the mobile backend.

---

## 8. Authentication & roles

- **Roles:** `public` (default), `reporter`, `admin`. Dependencies in
  [auth.py](backend/app/services/auth.py): `get_current_user` (optional), `require_user`,
  `require_reporter`, `require_admin`.
- **JWT:** HS256, 480-minute expiry, `sub` = user id. `decode_token` raises 401 on failure.
- **Storage:** the frontend keeps the token and user object in `localStorage` under
  `riis_token` / `riis_user`, and `api.js` injects the Bearer header on every call.

**[GAP] There is no way to become a `reporter` or an `admin`.** No seed admin user, no role
update endpoint, no CLI. Everything gated behind `require_admin` (alerts, moderation, reservoir
updates, ML training) is unreachable until someone edits the SQLite row by hand.

**[GAP] Unguarded endpoints.** Nine routes accept state-changing or expensive operations with no
auth: `weather/refresh`, `weather/refresh/{code}`, `reservoirs PUT`, `uploads POST`,
`historical/ingest POST`, `ml/train POST`, `reports/{id}/upvote POST`, `subscriptions POST/GET/DELETE`.

**[GAP] CORS.** `allow_origins=["*"]` **with** `allow_credentials=True`. Browsers reject that
combination for credentialed requests. Irrelevant to a native mobile client (no CORS), but it
will bite a PWA or a web dashboard.

---

## 9. Notifications — the full current pipeline

This is the section that matters most for your mobile app. Here is exactly what exists.

### 9.1 The chain

```
Alert row (DB)  ──POST /api/alerts/{id}/broadcast {channels}──►  alerting.broadcast_alert()
                                                                        │
        ┌───────────────────────┬──────────────────────┬───────────────┘
        ▼                       ▼                      ▼
   channel="sms"          channel="whatsapp"      channel="push"
   Twilio REST            Twilio REST             Firebase FCM v1
   (form-encoded)         (whatsapp: prefix)      (google-auth token)
        │                       │                      │
   _subscribers[]         _subscribers[]        _subscribers[].push_token
   where phone set        where phone set       → tokens list
```

If credentials are absent, every channel returns
`{"status": "simulated", "note": "…set TWILIO_ACCOUNT_SID in .env"}` and logs instead of sending.

### 9.2 Message formats

SMS / WhatsApp body (identical, single string):

```
RIIS Alert [EXTREME] — <area>

<title>

<body>
```

Push payload sent to `POST https://fcm.googleapis.com/v1/projects/{fcm_sender_id}/messages:send`:

```jsonc
{
  "message": {
    "token": "<device token>",
    "notification": { "title": "Alert: <title>", "body": "<body>" },
    "data": { "severity": "<severity>", "area": "<area>" },
    "android": {
      "priority": "high",
      "notification": { "channel_id": "riis_alerts", "priority": "high" }
    }
  }
}
```

**Good news for mobile:** the FCM payload already targets Android with a named channel
(`riis_alerts`) and high priority, and it carries a `data` block. So a React Native / Flutter
client can register a token today and receive a real push the moment Firebase credentials are
supplied — no code change required. **You only need credentials** (`FIREBASE_CREDENTIALS_PATH`,
`FCM_SENDER_ID`) per [SETUP.md](backend/SETUP.md).

### 9.3 What is missing for a production mobile experience

| Gap | Impact |
|---|---|
| Subscribers are an **in-memory list** | Every backend restart wipes all devices → push silently stops |
| No **iOS** payload (`apns` block absent) | iPhone users get nothing |
| `data` block lacks **alert_id / lat / lon / deep-link** | Tap can't route to the relevant screen |
| No **topic** subscriptions (district/state/severity) | Broadcasting to everyone, not to affected users |
| No **geo-filtering** despite `radius_km` on the Alert model | An alert for Assam can be pushed to a Kerala user |
| No **device token cleanup** | FCM `UNREGISTERED` responses are never pruned |
| No **automatic alert generation** | Scheduler only polls weather; nothing creates an `Alert` on escalation |
| No **dedupe / rate limit / quiet hours** | Risk of notification storms |
| Broadcast is **synchronous and serial** | `for token in tokens: await post(...)` — slow for thousands of devices |
| `GET /api/subscriptions/` exposes **phone numbers unauthenticated** | Privacy/security incident |
| `Alert.is_broadcast` set `True` at creation | Field is meaningless |

### 9.4 The missing piece: risk-transition alerting

`services/scheduler.py` runs exactly one job — `scheduled_weather_poll` → `update_all_districts`.
Nothing compares the previous `risk_class` to the new one. A mobile app whose entire value
proposition is *"notify me before it floods"* needs this job:

```
every N seconds:
  for each district:
    previous = last known risk_class
    current  = district.risk_class
    if severity_rank(current) > severity_rank(previous):
        create Alert(...) if not suppressed by dedupe window
        broadcast(channels=["push","sms"]) to subscribers in radius_km
```

Right now that loop does not exist in any form. This is the highest-value backend work for the
mobile product, and it is roughly a day of effort.

---

## 10. User inputs & reviews — the full current state

Your request says *"their reviews are taken as inputs in this project."* Here is the honest
inventory of what that means today.

### 10.1 What the schema supports (good bones)

`CommunityReport` already has the fields a review system needs:
`report_type`, `title`, `description`, `severity`, `latitude`/`longitude`, `location_name`,
`media_url` + `media_type`, `upvotes`, `is_verified` + `verified_by` + `verification_note`,
`ai_classified` + `ai_class`, and `status` (pending/approved/rejected).

### 10.2 What actually works

| Capability | Status |
|---|---|
| Create a report (API) | Works **only** for role `reporter`/`admin` |
| List reports (public sees approved only) | ✅ works |
| Upvote | ✅ works, but unauthenticated and unlimited |
| Admin moderation (approve/reject + note) | ✅ works |
| Media upload | Endpoint works (unguarded); **the UI never calls it** |
| AI classification of a report | **[GAP]** `ai_classified` is never set to `True`; `ai_class` always `""` |
| Review rating (stars / usefulness) | **[GAP]** no rating field at all — only a counter |
| Feedback → model retraining | **[GAP]** no code path exists |
| Feedback → live impact engine | **[GAP]** not wired into the Real-time category |
| Reporter reputation / abuse controls | **[GAP]** none |

### 10.3 The blocking defect

```
POST /api/auth/register   →  role = "public"          (hardcoded)
POST /api/reports/        →  require_reporter         (role ∈ {reporter, admin})
no endpoint exists        →  to change a user's role
```

**Consequence:** no user who installs your app can ever submit a report. They will see 403
"Reporter role required". The Community screen in the desktop UI cheerfully says *"1,284 reports
today · 847 AI-verified"* while the underlying submit path is unreachable.

Minimum fix: either allow `public` to create reports, or grant `reporter` on first successful
report / email verification, and add an admin-only `PUT /api/users/{id}/role`.

### 10.4 The feedback loops that are claimed but do not exist

Three loops are advertised in the UI, and **none** is implemented:

1. **"Verified reports flow back into training data for continuous model retraining"**
   (Community screen) — no ingest from `CommunityReport` into ML training. `train_ml.py` reads
   only `HistoricalWeather`.
2. **"Fed into Retrain?"** column in the reports table — rendered from `r.verified` boolean,
   purely decorative.
3. **"Retrain nightly at 02:00 IST"** (Admin screen) — no such scheduled job; the scheduler has
   exactly one job.

To make reviews genuinely "inputs", you need: a moderation-approved → feature-store path, a
geo-temporal join of reports to the district/point they describe, and a retraining trigger. That
is real work, but the schema is already 80% of the way there.

---

## 11. The UI — complete walkthrough

### 11.1 Design language

A dark "emergency operations terminal". Deliberately dense, data-first, monospace-accented.

**Tokens** ([styles.css](project/src/styles.css) `:root`):

| Token | Value | Role |
|---|---|---|
| `--bg-0 / 1 / 2 / 3` | `#05090F` `#0A121C` `#101B2B` `#16253A` | page → panel → raised |
| `--stroke` / `--stroke-2` | `rgba(120,180,255,.10)` / `.18` | hairline borders |
| `--text-hi / mid / lo` | `#E8F1FF` `#9DB3CC` `#5A7593` | three-level type hierarchy |
| `--cyan` | `#22D3EE` | the brand/primary accent, glows everywhere |
| `--blue` / `--sky` | `#3B82F6` `#7DD3FC` | secondary/soft accents |
| `--safe / mod / high / extreme` | `#10B981` `#F59E0B` `#F97316` `#EF4444` | the 4-level risk ramp |
| `--violet` | `#A78BFA` | AI/ML accent |

**Type:** Inter (300–800) for UI, JetBrains Mono (400–600) for all numerics via
`.mono`/`.num` (tabular figures). Base size 13 px, tight negative letter-spacing on big numbers.

**Surface treatment:** panels are translucent gradients with `backdrop-filter: blur(20px)`,
16 px radius, and a `::before` top highlight. `.brackets` adds four corner ticks in cyan at 50%
opacity — a HUD motif used on nearly every panel. `body` carries two large radial glows
(cyan top-left, blue bottom-right).

**Motion:** pulsing status dots, an animated radar sweep (rAF-driven), simulated rain
(`raindrop` keyframes), a pulsing red EMERGENCY button (`emergpulse`), a 3 s section fade-in,
and staggered pulse animations on storm blobs.

### 11.2 Layout shell

- `.app` = `grid-template-columns: 72px 1fr`.
- **Rail** (72 px, sticky): a gradient logo tile "R", then 13 nav items (44 px each) with
  hover tooltips sliding out to the right, an active state with a glowing cyan left bar, and an
  avatar chip "OP" pinned to the bottom.
- **TopBar** (60 px, sticky, blurred): breadcrumb → search input (city / district / or raw
  `lat,lon` coordinates, with a clear ✕) → circular GPS locate button (spinner while locating,
  cyan ring when live) → an error ⚠️ tooltip → a green "ALL SYSTEMS NOMINAL · LIVE METRICS ACTIVE"
  chip → a live Clock showing **IST and UTC simultaneously** → notification bell with a count
  badge → layers button → a red pulsing **EMERGENCY** button.
- **Router:** hash-based (`#/dashboard`, `#/map`, …), with the last route persisted in
  `localStorage` under `riis:route`.
- Global mounts: `ChatPanel` (floating) and `EmergencyOverlay` (full-screen).

### 11.3 Screen-by-screen inventory

#### `#/dashboard` — DashboardScreen
The flagship screen, five bands top to bottom.
1. **Title block** — city/state/country breadcrumb, `<h1>City — Rainfall Impact Intelligence</h1>`,
   a GPS badge button (`Fetch Device Location` → spinner → `Live GPS Connected`), coordinates +
   elevation, live weather description, and a rotating session ID `RIIS-#####` with an elapsed
   `T+mm:ss` counter.
2. **Live weather row** — five `wxcard`s: Temperature (feels-like, dew point, trend arrow),
   Humidity (inline gradient bar), Pressure (with a system-state string like "Falling ·
   Low-pressure cyclone/trough"), Wind (a mini `WindCompass` + gusts), Visibility (with a
   scatter warning when < 5 km).
3. **Second weather row** — Cloud Cover, Radar Activity (`ACTIVE`/`QUIET` + dBZ text),
   INSAT/Satellite, Air Quality (US-AQI + colour), UV Index.
4. **Prediction hero + right column** — left: a large `pred-hero` panel with a grid overlay, an
   `AI Rainfall Prediction` header badged ConvLSTM, Now/+3h/+12h/+24h tabs, a huge gradient
   rainfall number (`mm / 6h`), a confidence/probability strip, a 6-cell metadata grid
   (current time, category, storm movement, duration, precip onset, peak intensity), and on the
   right a `RainCurtain` rain animation layered *behind* an animated `RadarSweep`. Right column:
   **Risk Index** panel (a `HalfGauge` 0–100 + classification + scope chips Local/District/State/
   National) and the **AI System Status** panel (10 named feeds — IMD, Doppler, INSAT-3DR, AWS,
   ARG, ERA5, DEM, Land Use, Reservoir, "ConvLSTM + XGBoost v4.2-Live" — each with status dot and
   latency/count).
5. **Impact Intelligence Engine** — a 9-card `impact-grid`, each card a `CircularGauge` +
   name + severity pill + a `Sparkline`. Vectors: Urban Flood, Waterlogging, Crop Stress,
   Reservoir Inflow (m³/s), Traffic Disruption, Landslide Prob., River Overflow, Infra. Damage,
   Public Safety. Header actions: `Export Data` (no handler) and `Simulate Flood →`.

#### `#/map` — MapScreen + DistrictPanel
Filter tabs (All/Extreme/High/Moderate/Safe), layer chips, a "X/35 SHOWN" counter. Canvas is
`IndiaMap`: Leaflet + OSM tiles behind a CSS filter, RainViewer radar layer toggleable, custom
`divIcon` markers sized and coloured by risk class with pulse animations for extreme/high and a
distinct pulsing cyan **user** marker, permanent tooltips on the user dot, hover tooltips
(positioned from raw client coords), a control stack (zoom ±, radar toggle, fly-to-my-location,
refresh radar), a live badge strip (`LIVE · OpenStreetMap · N DISTRICTS`, rain-radar timestamp),
and a bottom-left risk legend. Right: `DistrictPanel` with a `HalfGauge`, population, and six
derived tiles (predicted rainfall, flood risk, drainage status, waterlogging index, population at
risk, infrastructure load). Below: a top-8 risk table with inline risk bars and a per-row
`Load Live ⚡` button that re-centres the whole app on that district.

#### `#/city` — CityScreen + WardPanel
Hyperlocal view. `ChennaiMap` flies to the user's live coordinates at z13 and plots eight
generated "wards" (`<City> Central`, `North`, `South`, `East`, `West`, `NE`, `NW`, `SE`) at
±0.02–0.03° offsets around the user, each with colour, size and tooltip by risk. Right:
`WardPanel` with a `HalfGauge` flood probability and four tiles (predicted depth, drainage
efficiency, population exposed, response level). Below: a sortable ward table.

#### `#/explainable` — ExplainableScreen (XAI)
Left: **Live Feature Importance** — numbered `reason-bar` rows with weight bars, driven by
`RIIS.prediction.reasons`, which is computed **client-side** from humidity, precip probability,
pressure, cloud cover, wind, dew point, a stability index and a convective anomaly. Right:
Prediction Summary tiles (predicted rain, probability, confidence, uncertainty σ, "6 of 6 models"
agreement, storm movement), and a **Model Ensemble Consensus** donut plus six model bars
(ConvLSTM, ConvGRU, Transformer, XGBoost, Random Forest, Gradient Boost). Below: a generated
prose "Real-Time Meteorological Explanation", then three uncertainty panels (Aleatoric,
Epistemic, Telemetry Freshness).

> **Important:** this screen does **not** call `/api/ml/shap/{code}`. The real SHAP endpoint
> exists and returns proper attributions, but the UI shows client-frontend heuristics. The
> "6 of 6 models" ensemble is a fixed string and the model bars are `confidence − k` offsets.

#### `#/timeline` — TimelineScreen
Horizon chips 6/12/24/48/72 h; five KPI tiles (total rain, peak hourly rain, max risk, avg
humidity, avg confidence); a 4-series `LineChart` (rainfall, risk, confidence, cumulative rain)
with crosshair tooltip and legend; then Atmospheric Trajectory (humidity/pressure/temp),
Hydrological Inflow Trajectory (fill %, inflow, outflow), and Precipitation Probability & Wind
charts; finally a collapsible 10-column hourly table with a sticky header and inline risk bars.
Data comes from `RIIS.timeline`, built hour-by-hour from real Open-Meteo hourly arrays.

#### `#/simulate` — SimulateScreen *(the second-most important screen for mobile)*
Left panel: **`RealFloodMap`** + a rainfall-intensity slider.
- `RealFloodMap` (Leaflet, OSM tiles filter-inverted to dark) fetches
  `/api/hyperlocal/inundation` on a **600 ms debounce**, guards against out-of-order responses,
  draws depth-coloured GeoJSON polygons (≥1.5 m red, ≥0.8 orange, ≥0.4 amber, ≥0.15 cyan, else
  blue), binds per-polygon popups, shows a status badge (`N POLYGONS · X KM² · MAX Y M ·
  SPILLING` or `NO PONDING — DRAINAGE ABSORBS THIS EVENT`), a 5-step depth legend, a
  `4.6 M/PIXEL · AWS TERRAIN TILES` source badge, and a user marker. Falls back to the
  schematic `FloodSimMap` SVG if Leaflet fails.
- Slider 0–300 mm/h with quick-pick chips (30/75/120/180/250) and a colour-ramped track
  (safe→extreme).

Right column: **Simulation Results** — 8 tiles that prefer DEM statistics when available
(mean/max depth, inundated area) and fall back to engine estimates, plus structures impacted,
roads affected, evacuation status, people exposed, drainage saturation. Then **Cascade System
Effects** — a bucket-driven list of four consequence strings plus `Export Simulation Report →`
(no handler).

Below, full width: **Hyperlocal Factor Analysis — All 8 Categories**, fed by
`/api/hyperlocal/impact`. Eight location-fact tiles (elevation, slope, nearest water + type,
soil texture + infiltration, impervious %, antecedent rain + saturation, runoff coefficient,
drainage capacity), eight weighted category bars showing `score/100`, weight %, share of total,
**and a human-readable provenance string per category**, and finally a list of generated
advisories. This is the single richest data view in the product.

#### `#/farmer` — FarmerScreen
Inputs: target location (free text + `Sync Weather ⚡`), crop chips (Paddy, Sugarcane, Cotton,
Groundnut, Millets, Tomato), growth-stage chips (Sowing → Harvest). Main panel: **Live
Meteorological Recommendations** — 7 advisory cards, each with an icon, colour-coded left border,
title, long description and `PRIORITY 1|2`. The first advisory is driven by real
`/api/hyperlocal/geofactors` data (field saturation, antecedent rain, soil texture,
infiltration). Right: **Microclimate & Crop Health** — five gradient gauges (soil moisture,
canopy temp, vapour deficit, fungal risk, pesticide wash-off risk).

#### `#/reservoir` — ReservoirScreen
A 5-wide grid of reservoir cards (fill % `CircularGauge`, capacity, current, inflow +, outflow −,
risk pill), a `LineChart` of storage % and inflow from −24 h to +24 h, and a **Gate Management
Guidance** panel with an overflow-probability `HalfGauge` and a text recommendation
("Open 2 Gates × 1.5m" … "Normal Gate Configuration"). **[GAP]** The screen reads
`RIIS.reservoirs`, which starts as frontend sample data and is replaced by
`/api/reservoirs/` when the backend responds — but the *gate recommendation* is a pure
client-side `if` on the risk class, and no live dam feed exists.

#### `#/disaster` — DisasterScreen (SDMA command view)
KPI strip (districts at risk, population exposed, critical roads, affected schools, shelters
active, NDRF teams — all **arithmetically derived** from the live district list). Then: **Live
Rescue Operations** table (up to 12 rows generated deterministically from risky districts with
team/status/personnel/assets/ETA/priority), **Resource Allocation** (8 bars scaled by risk
count), **Shelter Capacity** and **Hospital Bed Availability** (both generated from live counts),
a **District Risk Overview** chip cloud (top 20 by risk, colour-coded), **Live Road Closures** /
**Safe Routes** (derived from district rainfall and risk), and **Live Condition Alerts** cards
generated from real weather thresholds (heat > 35 °C, rain > 15 mm, AQI > 100, wind > 30 km/h).
Rescue-team names, statuses and ETAs are randomised — this screen presents invented operational
data with the visual authority of a government console.

#### `#/alerts` — AlertsScreen
Three confidence buckets (≥90% immediate, 70–90% monitor, <70% observation) with counts and
`HalfGauge`s, then a filterable **Live Alert Feed** of alert cards, each with severity pill,
confidence, relative timestamp, area, body text, and four buttons: `SMS Broadcast`, `Push`,
`WhatsApp`, `Escalate →`. **[GAP]** None of those buttons has an `onClick`. The real broadcast
API exists (`POST /api/alerts/{id}/broadcast`) but is not called from the UI.

#### `#/community` — CommunityScreen *(the surface for your reviews feature)*
Left: **Submit a Report** — an 8-tile report-type grid (Rainfall, Flood Photo, Flood Video,
Waterlogging, Road Damage, Tree Fall, Crop Damage, River Overflow) with hover effects, a dashed
**"Drop photo or video here"** dropzone (`JPG · PNG · MP4 · MAX 25 MB · GPS AUTO-TAGGED`),
read-only GPS and timestamp fields, a description textarea, and a `Submit Report` button.
**[GAP] None of these controls has a handler** — no file input, no state, no API call.
Right: **Report Stats · Today** — "1,284 reports today", "847 AI-verified", "68% verification
rate", "+412 training samples", a `Donut` type-distribution and its legend. **All hardcoded.**
Below: **Recent Verified Reports** table with columns Time, User, Ward, Type, Depth/Note,
AI Status, Upvotes, **Fed into Retrain?** — populated from `/api/reports/` when the backend is up
(via `syncRiisBackendData`), otherwise from two sample rows.

#### `#/history` — HistoryScreen
Four KPI tiles (avg annual rain, extreme events, crop loss index, reservoir fill) and four
charts (10-yr rainfall vs mean line, flood events per year bar chart, crop damage index, average
reservoir fill) driven by `RIIS.historical` **static arrays**; a 12×12 seasonal heatmap generated
from a sine function; and a **Climate-Change Indicators** row (+38% extreme events, +22% dry-spell
length, +0.9 °C coastal SST, 2.1× cyclone landfalls) — hardcoded. Header claims
"IMD 2014–2026 · +ERA5"; no IMD or ERA5 ingestion exists.

#### `#/admin` — AdminScreen
Six-item sensor health strip (AWS 47/47, ARG 110/112, Doppler, INSAT-3DR, Reservoirs 14/14,
Rivers 28/30), an 8-row **Model Performance** table (ConvLSTM v4.2 96.4% … Ensemble Vote 96.8%),
an **Alert Throughput** block (24,182 sent / 23,940 delivered / …) with a sparkline, a
**Retraining Queue** (running/queued with progress bars and ETAs), and a **System Logs** stream.
**Entirely hardcoded** — note it does not even reference the real `/api/ml/metrics` or
`/api/stats` values, and `SystemLog` is never written to.

#### ChatPanel
Floating 400×600 panel: header with avatar, "RIIS Live Assistant", `Live · <city>`; a scrolling
message list with bot/user bubbles and a `↳ citation` line under each bot message; four
suggestion chips; and an input with a send button. Responses come from
`getDynamicBotResponse(q)` — substring matching on `flood|waterlog|safe`, `irrigat|water|farm|crop`,
`rain|weather|temp|forecast`, `road|traffic|transit`, `reservoir|dam|inflow`, interpolating real
`RIIS` values. A 400 ms `setTimeout` simulates thinking. No LLM, no retrieval.
Markdown-bold (`**…**`) is rendered via `dangerouslySetInnerHTML`.

#### EmergencyOverlay
Full-screen red-tinted overlay: `● SOS · EMERGENCY MODE ACTIVE` badge, a 180 px pulsing **SOS**
disc (**[GAP]** no handler), a six-number helpline list (1078, 100, 101, 108, 1913, 1091),
Nearby Safe Shelters, a live-weather 2×2 tile grid, Nearest Hospitals with `Call` buttons
(**[GAP]** no handler), and an **Offline Mode** panel claiming "Offline maps CACHED (86 MB)" and
an "SMS FALLBACK: text RIIS HELP to 51969". No offline caching and no SMS gateway exist.

### 11.4 Component library

Primitives ([primitives.jsx](project/src/primitives.jsx)):
`Ic` (SVG factory) · 40 `Icon` glyphs (home, map, city, brain, clock, wave, leaf, droplet, shield,
bell, users, chart, gear, siren, search, send, bot, cloud, wind, sun, storm, radar, eye, pin, plus,
minus, layer, hospital, phone, fire, file, camera, arrow, x, flame, check, play, pause, route) ·
`CircularGauge` · `HalfGauge` · `Sparkline` · `RadarSweep` · `WindCompass` · `RainCurtain` ·
`riskColor()` · `riskLabel()`.

Charts ([charts.jsx](project/src/charts.jsx)) — all hand-rolled SVG, zero chart libraries:
`LineChart` (multi-series, area fills, mouse-tracked crosshair, floating tooltip, legend, empty
state) · `BarChart` (glow, value labels) · `Donut` (arc segments + centred label) · `Heatmap`
(row/col labels, configurable colour scale).

Primitive classes: `.panel`, `.panel-hd` (with `.live` pulsing badge and `.sub` monospace
caption), `.panel-bd`, `.brackets`, `.wxcard`, `.impact`, `.chip`, `.tabs`, `.btn`
(primary/ghost), `.sev`, `.k`, `.mono`, `.num`, `.data` table, `.alert-item`, `.crop-gauge`,
`.rail`, `.topbar`, `.chat-*`, `.emerg-*`, `.sos-big`, `.spinner-mini`.

### 11.5 The UI's biggest structural problem for mobile

`index.html` declares **`<meta name="viewport" content="width=1440">`**. The entire layout is a
desktop console: a permanently visible 72 px rail, a 60 px top bar with a long status chip and a
two-line clock, and grids hardcoded to 5, 6 and 9 columns
(`repeat(5,1fr)`, `repeat(2,1fr)`, `grid-template-columns:1.55fr 1fr`, `.impact-grid` min 200 px,
`.wxrow` min 130 px). `styles.css` contains **no `@media` queries at all**.

There is therefore **no path to "just point the existing UI at a phone"**. Two honest options:

1. **Build a native client** (recommended) that consumes the same JSON APIs and reimplements a
   small, curated subset of these screens. The API is genuinely well-shaped for this.
2. **Ship a mobile web app** — but this requires a real responsive rebuild: a bottom tab bar
   instead of the rail, collapsing the two weather rows into a horizontal snap-scroller,
   stacking every `1.5fr 1fr` grid, making the impact grid 2-up, converting the 10-column tables
   to cards, and rewriting the `viewport` meta. That is a substantial rewrite that also drags
   along the in-browser Babel compile cost (~11 files transpiled on every cold load — slow
   first paint on mobile).

---

## 12. Defects & blockers, ranked for a mobile app

### Tier 1 — must fix before any mobile client ships

| # | Issue | Where | Impact |
|---|---|---|---|
| 1.1 | **`requirements.txt` omits `Pillow` and `scipy`**, but `services/inundation.py` imports both at module import time, and `main.py` imports that router at startup | [requirements.txt](backend/requirements.txt), [inundation.py](backend/app/services/inundation.py) | **The server cannot boot on a clean install.** `pip install -r requirements.txt` is not sufficient. |
| 1.2 | **No user can submit a report** (register → `public`; create report → `require_reporter`; no role-change endpoint) | [auth.py](backend/app/routes/auth.py), [reports.py](backend/app/routes/reports.py) | Directly blocks your "reviews as inputs" feature. 403 for every app user. |
| 1.3 | **Device subscriptions are an in-memory list**, unauthenticated, and globally enumerable | [alerting.py](backend/app/services/alerting.py), [subscriptions.py](backend/app/routes/subscriptions.py) | Push dies on restart; phone numbers exposed via `GET /api/subscriptions/`. |
| 1.4 | **No risk-transition alert job** — nothing ever auto-creates or auto-broadcasts an alert | [scheduler.py](backend/app/services/scheduler.py) | The app can't notify users unless an admin manually creates and broadcasts an alert. |
| 1.5 | **No admin/reporter account can be created** | [seed.py](backend/app/seed.py) | Alerts, moderation, reservoir updates and ML training are all unreachable. |

### Tier 2 — fix before public users

| # | Issue | Impact |
|---|---|---|
| 2.1 | 9 unguarded endpoints incl. `ml/train` (CPU DoS), `reservoirs PUT`, `uploads POST`, `historical/ingest` | Abuse / data corruption |
| 2.2 | Upvote has no auth, no dedupe, no idempotency | Vote counts are meaningless; a script can inflate them |
| 2.3 | `allow_origins=["*"] + allow_credentials=True` | Invalid CORS for any credentialed browser client |
| 2.4 | FCM payload lacks `alert_id`, coordinates and a deep link; no APNs block | Notifications can't route on tap; iOS unsupported |
| 2.5 | `api.js` defaults to `:8000`; `.env.example` / `start-riis.ps1` / README use `:8001` | Broken out of the box following the docs |
| 2.6 | No rate limiting anywhere; `reports` list `limit` up to 200, `districts` up to 200 | Scraping / load |
| 2.7 | `SECRET_KEY` default is a committed string | Trivially forgeable JWTs if not overridden |
| 2.8 | No alert dedupe, expiry enforcement, or quiet hours | Notification storms; `expires_at` is never honoured when listing |

### Tier 3 — correctness / credibility

| # | Issue |
|---|---|
| 3.1 | **ML accuracy 99.95% is circular** — the label is a threshold function of feature #0 (§6.4). Do not present this as validated forecasting skill. |
| 3.2 | `drainage_cap` in code (`−0.18·impervious`) contradicts the documented `−0.06·impervious` (§6.2) |
| 3.3 | `peak_intensity` slice bug from operator precedence (§6.3) |
| 3.4 | Frontend/backend district code duplication and mismatches (§4) |
| 3.5 | Dual risk formula (client + server) must be kept manually in sync |
| 3.6 | XAI screen ignores the real `/api/ml/shap` endpoint and shows client heuristics; "6 of 6 models" is a constant |
| 3.7 | Admin/History/Disaster screens present hardcoded data as live telemetry |
| 3.8 | `SystemLog` model is never written to |
| 3.9 | `ai_classified`/`ai_class` on reports never populated — no AI triage of user reports |
| 3.10 | Community/upload/emergency/SOS/`Call`/`Export` buttons have no handlers |
| 3.11 | `Alert.is_broadcast=True` set at creation, before any broadcast |
| 3.12 | No DB migrations applied — `alembic` is a dependency but there is no `alembic/` directory; schema comes from `create_all` |

---

## 13. Mobile app blueprint

### 13.1 Recommended shape

Two viable paths; pick one and commit:

- **React Native (Expo)** — reuse the domain logic you already have in JS
  (`calcDistrictRisk`, the `data.js` transforms, the risk colour/label ramps, the WMO code table
  and wind-direction helper are all directly portable). Fastest route to a working app.
- **Flutter** — better raw map/animation performance and one codebase for both platforms, at the
  cost of rewriting all the JS logic and the hand-rolled SVG charts.

Either way the backend contract below is unchanged.

### 13.2 Backend changes required (in build order)

**1. Fix Tier-1 defects** (§12) — `Pillow`/`scipy` in requirements, role handling, subscriber
persistence, a risk-transition job, a seeded admin.

**2. Add a real device registry.** New `Device` model + endpoints:

```
POST   /api/devices            {token, platform, app_version, lat, lon, radius_km, prefs{}}
PUT    /api/devices/{id}/prefs {districts[], severities[], quiet_hours, channels[]}
DELETE /api/devices/{id}
GET    /api/me/devices         (authenticated, own devices only)
```

Bound to `User`, unique on `token`, storing `platform` (`android`/`ios`/`web`),
`last_seen_at`, and a `failure_count` for pruning.

**3. Rewrite `broadcast_alert` for scale.**

- Query devices with `ST_Distance` (or a Haversine filter) against `Alert.lat/lon/radius_km`.
- Fan out with `asyncio.gather` + a bounded semaphore, not a serial `for` loop.
- Send platform-appropriate payloads: FCM v1 with an `android` block **and** an `apns` block.
- Prune tokens on `UNREGISTERED` / `INVALID_ARGUMENT`.
- Record delivery attempts (`AlertDelivery` table) so the Admin screen can show real throughput.

**4. Enrich the push payload** so a tap deep-links:

```jsonc
{
  "type": "alert",
  "alert_id": 42,
  "severity": "high",
  "title": "Heavy Rain Alert — Potheri",
  "body": "…",
  "area": "Potheri",
  "lat": 12.8207, "lon": 80.0368, "radius_km": 25,
  "deep_link": "riis://alert/42",
  "risk_score": 68,
  "expires_at": "2026-09-29T18:00:00Z"
}
```

**5. Add notification-worthy endpoints.**

```
GET  /api/me/feed?since=          # merged alert + risk-transition timeline
GET  /api/me/districts            # user's followed districts with current risk
POST /api/me/follow/{code}        # topic subscribe (maps to FCM topic `district_IN-TN-CH`)
GET  /api/alerts/nearby?lat&lon   # geo-filtered active alerts
```

**6. Auto-alerting job.** Add `scheduled_risk_transitions` alongside the weather poll:
snapshot each district's `risk_class`, compare after each poll, and on an *upgrade* past a
severity threshold, create an `Alert` (respecting a per-district dedupe window, e.g. 3 h) and
broadcast to devices inside `radius_km`. Downgrades can emit a "cleared" notification.

**7. Make reviews first-class (your feature).**

- Relax `POST /api/reports/` so any authenticated user may submit (or grant `reporter` on
  verified email / first accepted report).
- Add `GET /api/reports/mine`.
- Add a `rating` (1–5) and `tags[]` to `CommunityReport`, plus a `ReportVote` table with a
  unique `(report_id, user_id)` constraint to replace the raw `upvotes` counter.
- Add an AI triage step on submit: classify `report_type`/`severity` and set
  `ai_classified`/`ai_class`; flag implausible reports (e.g. a "flood" report from a pixel where
  the inundation engine predicts no ponding) into a moderation queue.
- Add the **feedback → model** path: on moderation approval, write a feature row
  `(district, timestamp, observed_severity, lat, lon, media)`, and expose it as an input to
  retraining. This is the loop the UI already advertises.

**8. Security hardening.** Lock down the 9 unguarded routes; add rate limiting; rotate
`SECRET_KEY`; replace the wildcard-with-credentials CORS with an explicit origin list; add
pagination cursors to the list endpoints.

### 13.3 Proposed mobile screen map

| Mobile tab | Built from | APIs |
|---|---|---|
| **Home** | Dashboard (weather row, risk gauge, 9 impact vectors, top alert) | `/api/districts/{code}`, `/api/hyperlocal/impact` |
| **Radar / Map** | MapScreen + RealFloodMap | `/api/districts/`, `/api/hyperlocal/inundation` |
| **Alerts** | AlertsScreen (read-only feed + filters) | `/api/alerts/`, `/api/me/feed` |
| **Report** | CommunityScreen submit flow (camera + GPS + rating + tags) | `/api/uploads/`, `/api/reports/` |
| **Profile** | New | `/api/auth/me`, `/api/devices`, `/api/me/districts` |
| Secondary | Timeline (forecast), Farmer advisory, Reservoir cards, Emergency (call/SOS/share location) | as above |

Deliberately leave History, Admin and Disaster Ops out of v1 — they are ops surfaces built
largely on synthetic data.

### 13.4 Offline & resilience strategy

The desktop app already degrades gracefully (per-component fallbacks, `Promise.allSettled`).
Mirror that on mobile:

- **Cache the last good `GET /api/districts/{code}` and `/api/hyperlocal/geofactors` response**
  per followed location; show a "last updated 14 min ago" stamp.
- **Queue reports offline** (photo + text + queued GPS) and flush on reconnect — this is the
  single highest-value offline feature, because reports are most needed exactly when connectivity
  is worst.
- **Do not promise offline maps** until tiling is actually implemented; the current UI's
  "86 MB cached" claim is false.
- Add a short-TTL `ETag` / `If-None-Match` on `/api/districts/` so a 300 s poll costs almost
  nothing.

### 13.5 Auth on mobile

Today's flow is username/password → JWT in `localStorage`. For an app you need:
secure storage (Keychain / Keystore) instead of `localStorage`; a refresh token (currently a
single 480-minute access token with no refresh); and — because the product is SMS-first —
**phone-number + OTP login**, which fits the existing Twilio integration and removes the
password entirely. An OTP login also cleanly unblocks the `reporter` role: verified phone →
allowed to submit reports.

### 13.6 Analytics & trust

Because report quality is what makes the product, track per-user: reports submitted, approved
rate, upvotes received, and a lightweight reputation score. Surface a "verified contributor"
badge (the `is_verified` field already exists). Feed approval rate back into moderation priority
so reliable users are reviewed faster.

---

## 14. Phased roadmap

**Phase 0 — make the backend bootable and reachable (½ day)**
Add `Pillow` + `scipy` to requirements. Add a seeded admin. Reconcile the port (`8000` vs
`8001`) across `api.js`, `.env.example`, `start-riis.ps1` and the README. Lock down the
unguarded routes. Smoke-test `/api/health`, `/api/districts/`, `/api/hyperlocal/impact`,
`/api/hyperlocal/inundation`.

**Phase 1 — notifications that actually work (2–3 days)**
Persist devices in a `Device` table tied to `User`. Rewrite `broadcast_alert` with geo-filtering,
parallel fan-out, APNs support, an enriched deep-link payload, and token pruning. Add the
risk-transition scheduler job with dedupe windows. Add `GET /api/me/feed`. Go live with Twilio +
Firebase credentials.

**Phase 2 — reviews that actually flow (2–3 days)**
Unblock report submission with phone-OTP auth. Add rating, tags, and a unique-constraint vote
table. Wire media upload into the submit flow. Add AI triage on submit and a real moderation
queue. Instrument the approval → training-sample path.

**Phase 3 — the app (1–2 weeks)**
React Native/Expo or Flutter client against the Phase 1–2 contract: Home, Radar/Map, Alerts,
Report, Profile. Push registration on first launch with a permission primer. Offline report queue.
Secure token storage.

**Phase 4 — model integrity & polish (ongoing)**
Re-derive the ML labels properly (`t+k` rainfall as truth, features from ≤ `t`) and re-report
honest metrics. Replace the client-side XAI screen with the real `/api/ml/shap` data. De-duplicate
the risk formula into one shared, versioned implementation. Add real reservoir telemetry (or a
`MODELL` badge, per the prior report's plan). Implement SST + IBTrACS climate indicators.

---

## 15. Appendix

### 15.1 Environment variables

```bash
DATABASE_URL=sqlite+aiosqlite:///./riis.db          # or postgresql+asyncpg://…
SECRET_KEY=…                                        # MUST override the default
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
OPENMETEO_BASE_URL=https://api.open-meteo.com/v1
OPENMETEO_ARCHIVE_URL=https://archive-api.open-meteo.com/v1
AIR_QUALITY_URL=https://air-quality-api.open-meteo.com/v1
NOMINATIM_URL=https://nominatim.openstreetmap.org
RAINVIEWER_URL=https://api.rainviewer.com/public/weather-maps.json
WEATHER_POLL_INTERVAL=300
DISTRICT_POLL_INTERVAL=300
TWILIO_ACCOUNT_SID=                                 # SMS + WhatsApp
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
FIREBASE_CREDENTIALS_PATH=./service-account.json    # push
FCM_SENDER_ID=
FCM_VAPID_KEY=
HOST=0.0.0.0
PORT=8000
```

### 15.2 Run commands

```bash
# Frontend (static, :5173)
cd project && node server.js

# Backend (:8001 per the docs; config default is 8000)
cd backend && pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Both on Windows
./start-riis.ps1

# Historical ingest + ML training (2 years × 36 districts, then train)
cd backend && python -m app.train_ml ingest
python -m app.train_ml train

# Docker (Postgres + backend)
cd backend && docker-compose up -d
```

The frontend API target can be overridden at runtime:
`window.RIIS_API_BASE = "https://api.example.com"` (or `localStorage.setItem('riis_api_base', …)`).

### 15.3 Endpoint quick index

```
GET    /api/health
GET    /api/stats
POST   /api/auth/register            POST /api/auth/login            GET /api/auth/me
GET    /api/districts/               GET  /api/districts/{code}       GET /api/districts/{code}/hourly
POST   /api/weather/refresh          POST /api/weather/refresh/{code}
GET    /api/reservoirs/              GET  /api/reservoirs/{code}      PUT /api/reservoirs/{code}
POST   /api/reports/                 GET  /api/reports/               GET /api/reports/{id}
POST   /api/reports/{id}/upvote      PUT  /api/reports/{id}/moderate
POST   /api/uploads/
POST   /api/alerts/                  GET  /api/alerts/
PUT    /api/alerts/{id}/deactivate   POST /api/alerts/{id}/broadcast
POST   /api/subscriptions/phone      POST /api/subscriptions/push
GET    /api/subscriptions/           DELETE /api/subscriptions/{id}
GET    /api/historical/{code}        POST /api/historical/ingest/{code}
GET    /api/ml/predict/{code}        GET  /api/ml/shap/{code}
POST   /api/ml/train                 GET  /api/ml/metrics
GET    /api/hyperlocal/geofactors    GET  /api/hyperlocal/impact
GET    /api/hyperlocal/inundation
GET    /uploads/{YYYY-MM}/{file}
```

### 15.4 Risk vocabulary (used everywhere — reuse it verbatim in the app)

| Class | Score | Colour | Label |
|---|---|---|---|
| `safe` | 0–24 | `#10B981` | SAFE |
| `mod` | 25–49 | `#F59E0B` | MODERATE |
| `high` | 50–74 | `#F97316` | HIGH |
| `extreme` | 75–100 | `#EF4444` | EXTREME |

### 15.5 Cache lifetimes (as implemented)

| Data | TTL |
|---|---|
| Weather poll | 300 s (scheduler) + 300 s (config) |
| Elevation (geofactor) | 15 min |
| Water / soil / land use | 6 h (10 min grace for degraded results) |
| Rainfall archive (3 yr) | 6 h |
| DEM tiles | 24 h, max 8 sites in memory |
| Filled DEM | memoised on the grid object (lifetime of the DEM cache entry) |
| Frontend districts refresh | 5 min interval in `App` |

---

*End of report. All findings are from direct source inspection of `backend/app/**` and
`project/src/**`. Items marked **[GAP]**/**[BUG]** are verified discrepancies between the code,
the UI's claims, and the prior `REPORT.md`.*
