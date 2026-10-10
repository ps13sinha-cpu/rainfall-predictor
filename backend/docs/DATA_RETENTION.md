# Data retention and privacy

RIIS stores three kinds of rows that can identify where a person was:

| Table | What it holds | Why it is sensitive |
| --- | --- | --- |
| `community_reports` | Flooding reports with latitude / longitude, free-text title and description, optional photo, the reporting user (`author_id`) and the moderator (`verified_by`) | Pins a person to a place at a time, linked to their account |
| `road_reports` | Field reports on a road segment with coordinates, depth and a free-text note | Same, without an account link |
| `route_logs` | Every safe-route request: origin and destination coordinates, scenario and timestamp | **Movement data** — an origin / destination pair with a time is a trip, and repeated trips reveal home, work and habits |

Nothing else the backend stores is tied to a person: district weather, reservoir levels,
road geometry and training samples are public, aggregated data.

## The policy

The daily retention job (`app/services/retention.py`, scheduled by
`app/services/scheduler.py` at 03:30 local time) applies two steps:

1. **Coarsen after 30 days** (`RIIS_RETENTION_COARSEN_DAYS`). Latitude and longitude on
   community reports, road reports and route logs older than 30 days are rounded to two
   decimals, about 1.1 km. The row still says "near here", which is all the risk model
   needs, but no longer which house or gate.
2. **Delete or strip after 365 days** (`RIIS_RETENTION_DELETE_DAYS`).
   - `route_logs` rows are **deleted outright**. They exist only to measure how often the
     safe route differs from the shortest one; a year of aggregate counts is enough, and
     movement data is not kept longer than that.
   - Community reports keep their structured fields (type, severity, coarse location,
     status, dates, upvotes) because they are the flood-history record, but the free
     text (`description`, `verification_note`, `location_name`) is emptied and the user
     linkage (`author_id`, `verified_by`) is set to NULL.
   - Road reports keep status, depth and coarse location; the free-text `note` is emptied.

Every run writes its counts to the server log and to `system_logs`
(`source='retention'`, `message='retention_run'`).

## Checking before it runs

- `GET /api/health/retention/dry-run` returns the number of rows each step would touch
  right now without changing anything.
- From Python: `await app.services.retention.run_retention(dry_run=True)`.

## What is not covered (yet)

- Uploaded photos under `backend/uploads/` are referenced by `media_url` and are not
  deleted by this job; removing the file when a report is stripped is a follow-up.
- Accounts (`users`) are kept until deleted by an administrator.
- The SQLite file is unencrypted on disk; back-ups inherit whatever retention the host has.
