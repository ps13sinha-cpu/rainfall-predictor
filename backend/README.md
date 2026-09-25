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
- `GET /api/districts/` — List all districts with risk indices (query: ?state=X&risk_class=X)
- `GET /api/districts/{code}` — District detail + full weather data
- `GET /api/districts/{code}/hourly` — 168-hour hourly forecast for charts
- `POST /api/weather/refresh` — Trigger immediate weather poll for all districts
- `POST /api/weather/refresh/{code}` — Refresh one district

### Reservoirs
- `GET /api/reservoirs/` — List all reservoirs
- `GET /api/reservoirs/{code}` — Reservoir detail
- `PUT /api/reservoirs/{code}` — Update reservoir telemetry (admin)

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
