# RIIS — Rainfall Impact Intelligence System
## Detailed Project Report

**Workspace:** `C:\Users\Piyush\OneDrive\Desktop\rainfall predictor`
**Report date:** 25 September 2026
**Reference location:** Potheri, Tamil Nadu (12.8207567, 80.0368745)

---

## 1. Executive Summary

RIIS is a full-stack rainfall-impact prediction platform for India: a React (no build step) frontend served by a Node server on **:5173**, and a FastAPI backend on **:8000** backed by SQLite (SQLAlchemy async), APScheduler, XGBoost+SHAP ML, and a physics-based DEM inundation engine.

The system is **operational end-to-end and verified live at Potheri**. Its most significant recent milestone is the **DEM-driven flood extent map** — the pipeline the project previously listed as its biggest gap is now built, verified, and rendering real terrain-based flood polygons. The highest-value remaining work is **reservoir telemetry** (no live dam data yet) and **flipping alerting from simulation to live** (code complete; needs credentials only).

**Status at a glance:**

| Area | Status |
|---|---|
| Live weather ingestion (Open-Meteo) | ✅ Live |
| Hyperlocal geofactors (elevation/soil/landuse/water) | ✅ Live, cached, degraded-fallback |
| Impact engine (8 weighted categories) | ✅ Live — Potheri 51/100 HIGH |
| DEM inundation map (AWS Terrain Tiles) | ✅ Live & verified — 4.6 m/px |
| ML: XGBoost rainfall→risk + SHAP | ✅ Built, train-on-demand |
| Alerting (SMS/WhatsApp/Push) | 🟡 Wired, simulation mode |
| Reservoir telemetry | 🔴 Not built (modelled values only) |
| Historical climate indicators (SST/cyclones) | 🔴 Not ingested |
| Chat assistant | 🟡 Rule-based, not LLM |
| Ops/CMS institutional feeds | 🟡 Computed, not institutional |

---

## 2. System Architecture

```
┌─────────────────────────────  FRONTEND  (:5173)  ─────────────────────────────┐
│  Node server (project/server.js) serving static JSX modules, no build step    │
│                                                                                │
│  app.jsx ─── rail navigation + TopBar + Clock                                  │
│   ├─ dashboard.jsx            Live weather cards, impact gauge, AI status      │
│   ├─ screens_map_city.jsx     City map + RadarSweep / WindCompass primitives   │
│   ├─ screens_simulate_…       Flood Simulator + RealFloodMap + Farmer Advisory │
│   ├─ screens_disaster_…       Alerts, Emergency contacts, Ops/CMS              │
│   ├─ screens_community_…      Community reports, history, admin                │
│   ├─ screens_xai_timeline.jsx XAI (SHAP) + timeline screens                     │
│   ├─ chat.jsx                 ChatPanel — rule-based live assistant            │
│   ├─ charts.jsx / primitives.jsx   Line/Bar/Donut/Heatmap, gauges, Sparkline   │
│   └─ maps.jsx                 Leaflet maps incl. RealFloodMap (DEM flood view) │
│                                                                                │
│  api.js — single fetch wrapper: /api/weather, /hyperlocal, /inundation, /ml …  │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                    │ fetch (JSON)
┌───────────────────────────────────▼────────────────────────────────────────────┐
│                            BACKEND  (:8000, FastAPI)                           │
│                                                                                │
│  main.py — lifespan: init_db → seed → APScheduler (district weather poll)      │
│  12 routers: auth · districts · reservoirs · reports · alerts · historical ·   │
│              weather · ml · uploads · subscriptions · hyperlocal · inundation  │
│                                                                                │
│  Services:                                                                     │
│   hyperlocal.py   geofactors (Open-Meteo, per-component TTL cache)             │
│   inundation.py   DEM download → priority-flood fill → water-level search      │
│   ml.py           XGBoost training + SHAP attribution                          │
│   alerting.py     Twilio SMS/WhatsApp + Firebase FCM (simulated w/o creds)     │
│   weather.py      district weather refresh loop                                │
│   scheduler.py    background polling                                           │
│   auth.py         JWT (python-jose) + bcrypt                                   │
│                                                                                │
│  SQLite (aiosqlite) — Districts, Reservoirs, Reports, Alerts, Users,           │
│  HistoricalWeather, Subscriptions, Uploads                                     │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                    │
              External: Open-Meteo forecast · Open-Meteo marine/Elevation ·
              AWS Terrain Tiles (terrarium DEM) · (Twilio/Firebase — pending)
```

**Stack:** FastAPI 0.115 · SQLAlchemy 2 async + aiosqlite · APScheduler · XGBoost 2.1 / scikit-learn 1.5 / SHAP 0.46 · numpy 2.2.6 · httpx · Twilio 9 + firebase-admin 6.5 (optional) — React 18 (CDN, no bundler) · Leaflet 1.9 (vendored) · custom SVG charts.

---

## 3. What Works Today (Verified)

### 3.1 Live data pipeline
- **Open-Meteo forecast ingestion** for districts, refreshed by APScheduler at a configurable interval (`backend/app/services/weather.py`, `scheduler.py`).
- **Hyperlocal geofactors** (`backend/app/services/hyperlocal.py`):
  - Elevation & slope from Open-Meteo Elevation API.
  - Soil texture, landuse/imperviousness, water proximity — live sources with **regional fallbacks** (e.g. Tamil Nadu clayey-alluvial profile) and a `source` flag on every component.
  - **Per-component TTL cache** (elevation 15 min; water/soil/landuse 6 h) with a 10-minute grace window on degraded results, so one flaky upstream can't stall the endpoint.
  - **Antecedent rainfall** from Open-Meteo archives drives a saturation estimate.
- Verified Potheri snapshot: elevation **46 m**, slope **4.09 m/km**, nearest water **426 m**, clay loam **4 mm/h** infiltration, impervious **63.6%**, 12 mapped drains, saturation **77%**, runoff coefficient **C = 0.80**.

### 3.2 Impact engine
- Weighted 8-category model in `hyperlocal.py`: **Meteorological .30, Hydrological .18, Topographical .16, Infrastructure .10, Real-time .08, Historical .07, Socioeconomic .06, Model .05**.
- Potheri baseline: **51/100 — HIGH**.

### 3.3 DEM inundation engine — the flagship ✅
`backend/app/services/inundation.py` implements a complete hydrology pipeline:

1. **DEM acquisition** — AWS Terrain Tiles (terrarium PNG, `elev = r·256 + g + b/256 − 32768`) at **z=15 → 384×384 grid at ~4.6 m/px (~1.78 km span)**; 24 h in-memory tile cache.
2. **Depression filling** — Barnes **priority-flood** algorithm (filled grid cached on the DEM object).
3. **Volume-balance water level search** — binary search over water level (~50 iterations) until ponded volume matches event runoff; handles both *pit-filling* and *spilling* regimes.
4. **Wet-cell mask** — depth ≥ 5 cm; converted to GeoJSON MultiPolygons via ring tracing.
5. **Per-event runoff forcing** (`routes/inundation.py`):
   - `runoff_c = clamp(0.18 + 0.55·imperv/100 + 0.22·sat/100 + soil_adj, 0.05, 0.95)`
   - `drainage_cap = clamp(30 + 3·drains − 0.06·imperv, 8, 45) mm/h`
   - `net_mm = max(0, rain·C − cap·duration)`
- **Endpoint:** `GET /api/hyperlocal/inundation?lat&lon&rainfall_mm&duration_h[&intensity_mm_h]` — returns grid, water balance (`mode, level_m, net_runoff_mm, volume_m3, pit_storage_m3, spilled_m3`), stats (`wet_area_km2, max_depth_m, mean_depth_m, ponded_volume_m3`), GeoJSON, and a `forcing` block. Geofactors + antecedent + DEM fetch run as **3 parallel asyncio tasks**.
- **Performance:** cold ~21 s (tile download + fill), warm ~1.8 s.
- **Verified live at Potheri:** 55 mm/h → *"NO PONDING — DRAINAGE ABSORBS THIS EVENT"* (105 mm runoff < 135 mm drainage capacity — hydrologically correct); 180 mm/h → **1 polygon, 3.18 km², max depth 6.06 m, SPILLING**.

### 3.4 Frontend flood map — `RealFloodMap` (maps.jsx)
- Leaflet with **OSM tiles + CSS filter** (`invert(1) hue-rotate(180deg) saturate(.65) brightness(.92) contrast(1.12)`) for the dark theme (CARTO dark now requires an API key — OSM+filter chosen instead).
- 600 ms debounced fetch, **out-of-order response guard**, `L.geoJSON` polygons colored by depth (`depthColor`: ≥1.5 m red, ≥0.8 orange, ≥0.4 amber, ≥0.15 cyan, else blue), status badge `N POLYGONS · X KM² · MAX Y M · SPILLING`, depth legend, user marker at `RIIS.location`.
- Graceful fallback to the schematic `FloodSimMap` if Leaflet fails to load.
- `SimulateScreen` prefers DEM stats in the Results panel ("DEM 4.6 m/px" subtitle) and falls back to engine numbers for structures/roads/evacuation/people/drainage.
- **One correction to earlier notes:** the flood map is **no longer schematic** — it renders real DEM-derived extents. This item can be struck from the gap list.

### 3.5 ML layer
- `services/ml.py` trains an **XGBoost** classifier on historical daily weather (11 engineered features incl. lag-1 rainfall, rain², humidity×rain, wind×rain), labels = next-day risk class.
- **SHAP** feature attribution served per district; formula fallback when the model isn't trained.
- Routes: `GET /api/ml/predict/{code}`, `/shap/{code}`, `/metrics`; `POST /api/ml/train`.

### 3.6 Community + alerts + admin
- Community reports: submit, list, upvote, moderate (`/api/reports/*`), image uploads served statically.
- Alerts CRUD + broadcast (`/api/alerts/*/broadcast`) → alerting service.
- Subscriptions: phone (SMS/WhatsApp) and push tokens (`/api/subscriptions/*`).
- JWT auth with admin role gating reservoir updates and moderation.

---

## 4. Gaps — Not Yet Built / Still Needed

*(Item 6 of the earlier list — "flood map is schematic" — is resolved; the map is DEM-driven as of the current build.)*

### 4.1 🔴 Reservoir telemetry — not built
`/api/reservoirs` currently serves **DB-seeded, modelled values**. There is **no ingestion** of CMWSSB (Chennai Metro Water) or India-WRIS live levels; the hydrological factor infers saturation from rainfall archives rather than actual reservoir storage/release.

**Findings from source testing:** India-WRIS times out; CWC's `/en/reservoir-storage` returns 404; data.gov.in redirects. **Recommended path:** modelled fallback first — compute levels from archive rainfall + seasonal rule curves, explicitly labelled `MODELL` in the UI — then swap in a live scraper when a stable endpoint (or RTDAS/State agency feed) is available.

### 4.2 🟡 Real alerting — code complete, credentials pending
Twilio SMS + WhatsApp and Firebase FCM are fully implemented (`services/alerting.py`) with graceful `"status": "simulated"` responses when unconfigured. **Nothing is missing in code** — only `TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER` and `FIREBASE_CREDENTIALS_PATH` in `backend/.env` (setup guide: `backend/SETUP.md`).

### 4.3 🟡 Historical climate indicators — not ingested
No SST or cyclone-frequency data. Viable sources identified:
- **SST:** Open-Meteo Marine API (`marine-api.open-meteo.com/v1/marine?...&current=sea_surface_temperature`) — verified working; needs a coastal-point cache.
- **Cyclone history:** **IBTrACS NI list v04r01** CSV (27.9 MB, NOAA NCEI) — viable as a one-time download + cached parse for Bay-of-Bengal storm frequency/intensity near a district.

### 4.4 🟢 Chat assistant — rule-based, not LLM
`chat.jsx` calls `getDynamicBotResponse(q)` — pattern-matched replies over live local data (weather, risk, irrigation), 400 ms fake latency, no LLM call. The UI, citations, and suggestion chips are solid; only the reply generator needs replacing (e.g. RAG over the impact/geofactors payloads, or a hosted LLM with a strict JSON tool-call contract).

### 4.5 🟢 Ops/CMS institutional feeds — synthetic
The Ops screen displays computed/derived values, not institutional feeds (no TN SDMA / IMD bulletins / TNDRB ingestion). Useful for credibility, not blocking.

---

## 5. Priority Table (updated)

| Priority | Item | Why | Effort |
|---|---|---|---|
| ~~🔴 High~~ ✅ **DONE** | ~~DEM-driven flood extent map~~ | ~~Numbers real, picture schematic~~ → **Built & verified: DEM 4.6 m/px, depth-coloured polygons, spilling mode** | — |
| 🔴 High | **Reservoir telemetry** | Blind spot near dams; downstream risk invisible without live storage/release | Medium — modelled fallback first, scraper later |
| 🟡 Medium | **Real alerting credentials** | Functionally complete; low effort, high payoff once live | Config only (`backend/.env`) |
| 🟡 Medium | **Historical climate indicators** (SST + IBTrACS cyclones) | Coastal & seasonal long-range signal | Medium |
| 🟢 Lower | **LLM-backed chat** | UX polish; predictions unaffected | Small–Medium |
| 🟢 Lower | **Institutional Ops/CMS feeds** | Legitimacy/completeness | Medium–Large |

---

## 6. Operational Notes

- **Run:** frontend `node project/server.js` (:5173) · backend `python -m uvicorn app.main:app` in `backend/` (:8000). `start-riis.ps1` and `project.zip` sit at the workspace root.
- **Health:** `GET /api/health` → `{"status":"ok","version":"1.0.0"}`; `GET /api/stats` for admin counts.
- **Caching behaviour:** DEM tiles 24 h; geofactors per-component TTL (15 min – 6 h); inundation filled-DEM cached per grid.
- **Frontend cache-busting:** bump `?v=` on `src/*.jsx` script tags in `project/index.html` on any JSX edit (currently api.js **8.0**, maps.jsx **7.1**, simulate **7.1**).
- **Known gotchas:** India-WRIS/CWC unreachable from this network; screenshots of the live map may lag the DOM — trust live DOM values.
- **Secrets:** `backend/.env` (Twilio/Firebase placeholders) — do not commit; `SETUP.md` walks through both providers.

---

## 7. Suggested Roadmap (next 3 milestones)

1. **Reservoir telemetry v1** — modelled storage from archive rainfall + seasonal rule curves, `MODELL` badge; API shape unchanged so a live scraper can drop in later.
2. **Climate indicators** — Open-Meteo Marine SST (cached coastal points) + one-time IBTrACS NI download → per-district cyclone-frequency features surfaced in the impact engine's Historical category.
3. **Go-live alerting** — add Twilio/Firebase credentials per `backend/SETUP.md`, send test broadcasts, then wire scheduler-driven automatic alerts on risk-class transitions.

*Report generated from direct code inspection of `backend/app/**` and `project/src/**`.*
