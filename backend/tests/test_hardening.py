"""Offline unit tests for the hardening modules: budget, monitoring / drift, reservoir row
contract and freshness, MET Norway parsing, provider fallback and the retention job.

No network; the budget state and the retention database are redirected to temp files.

    cd backend
    python -m pytest tests/test_hardening.py -q
"""
import os
import sys
import json
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.services import budget as B  # noqa: E402
from app.services import monitoring as M  # noqa: E402
from app.services import reservoir_live as RL  # noqa: E402
from app.services import forecast_providers as FP  # noqa: E402


@pytest.fixture(autouse=True)
def _no_db_persistence(monkeypatch):
    """Keep monitoring rows out of the real riis.db (and off its write lock) during unit tests."""
    monkeypatch.setattr(M, "PERSIST_ENABLED", False)
    monkeypatch.delenv("RIIS_ALERT_WEBHOOK", raising=False)


# ── Budget ────────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "STATE_PATH", str(tmp_path / "budget.json"))
    monkeypatch.setattr(B, "LOCK_PATH", str(tmp_path / "budget.json.lock"))
    monkeypatch.setattr(B, "CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("RIIS_OPENMETEO_DAILY_CAP", raising=False)
    monkeypatch.delenv("RIIS_BUDGET_OVERRIDE", raising=False)
    M.reset_for_tests()
    return tmp_path


def test_estimate_units_matches_open_meteo_accounting():
    assert B.estimate_units() == 1                                    # forecast call
    assert B.estimate_units("2024-01-01", "2024-01-14") == 1          # exactly two weeks
    assert B.estimate_units("2024-01-01", "2024-01-15") == 2
    assert B.estimate_units("2024-01-01", "2024-12-31") == 27         # 366 days / 14
    assert B.estimate_units("2024-01-01", "2024-01-31", n_locations=121) == 3 * 121
    assert B.estimate_units("2024-01-01", "2024-12-31", n_vars=12) == 54


def test_reserve_charges_and_refuses(tmp_budget, monkeypatch):
    monkeypatch.setenv("RIIS_OPENMETEO_DAILY_CAP", "100")
    used = B.reserve(40, "a")
    assert used["day"] == 40
    B.reserve(60, "b")
    with pytest.raises(B.BudgetExhausted) as e:
        B.reserve(1, "c")
    assert e.value.window == "day"
    st = B.status()
    assert st["used"]["day"] == 100 and st["remaining"]["day"] == 0
    assert st["refused_today"] == 1
    assert st["by_label_today"] == {"a": 40, "b": 60}
    assert M.counters()["open_meteo_budget_refused"]["count"] == 1
    assert os.path.exists(B.STATE_PATH)
    assert not os.path.exists(B.LOCK_PATH)


def test_minute_limit_refuses_bursts(tmp_budget):
    with pytest.raises(B.BudgetExhausted) as e:
        B.reserve(601, "burst")
    assert e.value.window == "minute"
    assert B.status()["used"]["minute"] == 0


def test_record_429_and_require_bulk(tmp_budget, monkeypatch, capsys):
    B.record_429("x")
    st = B.status()
    assert st["n_429_today"] == 1 and st["last_429"]
    assert M.counters()["open_meteo_429"]["count"] == 1
    monkeypatch.setenv("RIIS_OPENMETEO_DAILY_CAP", "50")
    assert B.require_bulk(50, "fits") is True
    assert B.require_bulk(51, "too big") is False
    assert "REFUSED" in capsys.readouterr().err
    monkeypatch.setenv("RIIS_BUDGET_OVERRIDE", "1")
    assert B.require_bulk(51, "forced") is True


def test_budgeted_get_records_429(tmp_budget):
    class Resp:
        status_code = 429
        request = None

    class Client:
        async def get(self, url, **kw):
            return Resp()

    with pytest.raises(B.OpenMeteoRateLimited):
        asyncio.run(B.budgeted_get(Client(), "http://x", 1, "t"))
    assert B.status()["n_429_today"] == 1
    assert B.status()["used"]["day"] == 1


# ── Monitoring / drift ────────────────────────────────────────────────────────
def test_counters_and_scraper_keying():
    M.reset_for_tests()
    M.incr("scraper_parse_failure", detail={"scraper": "kseb"})
    M.incr("scraper_parse_failure", detail={"scraper": "kseb"})
    M.incr("overpass_empty")
    c = M.counters()
    assert c["scraper_parse_failure:kseb"]["count"] == 2
    assert c["overpass_empty"]["count"] == 1


def test_baseline_distribution_from_registry():
    base = M.baseline_class_distribution()
    if base is None:
        pytest.skip("model_registry.json not available")
    assert set(base["counts"]) == {"safe", "mod", "high", "extreme"}
    assert abs(sum(base["shares"].values()) - 1.0) < 1e-9
    assert base["counts"]["safe"] > base["counts"]["extreme"]


def test_check_drift_flags_shifted_distribution():
    M.reset_for_tests()
    if M.baseline_class_distribution() is None:
        pytest.skip("model_registry.json not available")
    ok = M.check_drift({"safe": 700, "mod": 220, "high": 70, "extreme": 10}, do_alert=False)
    assert ok["status"] == "ok" and ok["tvd"] < 0.25
    bad = M.check_drift({"safe": 10, "mod": 10, "high": 400, "extreme": 400}, do_alert=False)
    assert bad["drifted"] and bad["status"] == "drift"
    few = M.check_drift({"extreme": 5}, do_alert=False)
    assert few["status"] == "insufficient_samples"
    for _ in range(40):
        M.record_prediction("extreme")
    M.record_prediction("not-a-class")
    assert M.served_class_counts()["extreme"] == 40
    assert M.check_drift(do_alert=False)["drifted"] is True


# ── Reservoir contract ────────────────────────────────────────────────────────
def _good_row(**over):
    row = {"full_level_ft": 140.0, "capacity_mcft": 3231.0, "level_ft": 128.8, "storage_mcft": 682.0,
           "storage_pct": 21.11, "inflow_cms": 0.0, "outflow_cms": 15.0, "rainfall_mm": 0.0,
           "observed_at": datetime.utcnow().date().isoformat(), "source": "cmwssb"}
    row.update(over)
    return row


def test_validate_row_accepts_good_and_rejects_bad():
    RL.validate_row(_good_row(), "cmwssb")
    for bad in ({"storage_pct": None}, {"storage_pct": 250.0}, {"storage_mcft": 5000.0}, {"rainfall_mm": -1},
                {"observed_at": "2019-01-01"}, {"observed_at": None}, {"observed_at": "yesterday"},
                {"capacity_mcft": None, "storage_mcft": None}):
        with pytest.raises(RL.RowSchemaError):
            RL.validate_row(_good_row(**bad), "cmwssb")


def test_parse_cmwssb_rows_pass_the_schema():
    today = datetime.utcnow().date()
    page = f"""<html>As On - {today.strftime('%d/%m/%Y')}
    <table><tr><th>RESERVOIR</th><th>FRL</th><th>CAP</th><th>LEVEL</th><th>STORAGE</th><th>%</th><th>INFLOW</th><th>OUTFLOW</th><th>RAIN</th><th>LY</th></tr>
    <tr><td>POONDI</td><td>140.00</td><td>3231.00</td><td>128.80</td><td>682.00</td><td>21.11</td><td>-</td><td>530.00</td><td>0.0</td><td>2507</td></tr>
    <tr><td>TOTAL</td><td></td><td>11757</td><td></td><td>5000</td><td>42</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
    </table></html>"""
    parsed = RL.parse_cmwssb(page)
    assert parsed["as_on"] == today.isoformat()
    row = parsed["rows"]["POONDI"]
    RL.validate_row(row, "cmwssb")
    assert row["observed_at"] == today.isoformat() and row["source"] == "cmwssb"
    assert abs(row["outflow_cms"] - 530 * RL.CUSEC_TO_CMS) < 1e-6


def test_freshness_contract():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    fr = RL.freshness("2026-10-09", "cmwssb", now=now, limit_h=48)
    assert fr["live"] is True and fr["stale"] is False and fr["age_h"] == 9.5
    old = RL.freshness("2026-10-06", "kseb", now=now, limit_h=48)
    assert old["stale"] is True and old["live"] is False and old["age_h"] > 48
    seed = RL.freshness(None, "seed", now=now)
    assert seed == {"age_h": None, "stale": True, "live": False, "max_age_h": RL.max_age_h()}
    seeded_with_date = RL.freshness("2026-10-09", "seed", now=now)
    assert seeded_with_date["live"] is False and seeded_with_date["stale"] is True
    full = RL.freshness("2026-10-09T10:00:00+00:00", "cmwssb", now=now, limit_h=48)
    assert full["age_h"] == 2.0


def test_row_to_dict_carries_contract_keys():
    class R:
        id = 1; code = "MT"; name = "Mettur"; lat = 11.8; lon = 77.8; capacity_mcft = 93470.0; current_mcft = 60000.0
        inflow_cms = 0.0; outflow_cms = 0.0; overflow_prob = 0.0; risk_class = "safe"; source = "seed"
        observed_at = None; storage_pct = None; fetched_at = None
    d = RL.row_to_dict(R())
    for k in ("observed_at", "age_h", "stale", "live", "source", "storage_pct", "freshness"):
        assert k in d
    assert d["stale"] is True and d["live"] is False and d["storage_pct"] == 64.2


def test_max_age_env(monkeypatch):
    monkeypatch.setenv("RIIS_RESERVOIR_MAX_AGE_H", "6")
    assert RL.max_age_h() == 6.0
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert RL.freshness("2026-10-09", "cmwssb", now=now)["stale"] is True


# ── MET Norway parsing + fallback ─────────────────────────────────────────────
def _metno_doc(n_hours=50):
    t0 = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    series = []
    for i in range(n_hours):
        entry = {"time": (t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "data": {"instant": {"details": {"air_temperature": 28.0 + i * 0.1, "relative_humidity": 80.0,
                                                  "wind_speed": 5.0, "wind_from_direction": 90.0,
                                                  "air_pressure_at_sea_level": 1008.0, "cloud_area_fraction": 60.0}}}}
        if i < 48:
            entry["data"]["next_1_hours"] = {"summary": {"symbol_code": "rain"}, "details": {"precipitation_amount": 1.5 if i < 6 else 0.0}}
        entry["data"]["next_6_hours"] = {"summary": {"symbol_code": "rain"}, "details": {"precipitation_amount": 9.0}}
        series.append(entry)
    return {"properties": {"meta": {"units": {}}, "timeseries": series}}


def test_parse_metno_matches_parse_weather_shape():
    out = FP.parse_metno(_metno_doc())
    for k in FP.PARSE_WEATHER_KEYS:
        assert k in out, k
    assert out["temperature"] == 28.0 and out["humidity"] == 80 and out["wind_speed"] == 18.0
    assert out["next_6h_rain"] == 9.0 and out["peak_intensity"] == 1.5
    for k in ("aqi", "uv_index", "wind_gusts", "weather_code", "max_probability", "pm2_5"):
        assert out[k] is None
    assert len(out["hourly_data"]["time"]) == 48
    assert set(out["hourly_data"]) == set(FP.HOURLY_KEYS)
    assert out["hourly_data"]["dew_point_2m"][0] is None


def test_fetch_with_fallback_uses_metno_on_budget_exhausted(monkeypatch):
    M.reset_for_tests()
    import app.services.weather as W

    async def boom(lat, lon):
        raise B.BudgetExhausted("day", 1, 8000, 8000)

    async def fake_metno_raw(lat, lon, client=None):
        return _metno_doc()

    monkeypatch.setattr(W, "fetch_weather", boom)
    monkeypatch.setattr(FP, "fetch_metno_raw", fake_metno_raw)
    out = asyncio.run(FP.fetch_with_fallback(13.08, 80.27))
    assert out["source"] == "met_norway" and out["provider_fallback"] is True
    assert out["fallback_reason"] == "BudgetExhausted"
    assert M.counters()["forecast_provider_fallback"]["count"] == 1


def test_fetch_with_fallback_primary_path(monkeypatch):
    import app.services.weather as W

    async def ok(lat, lon):
        return {"weather": {"current": {"temperature_2m": 30, "time": "2026-10-09T06:00"},
                            "hourly": {"time": ["2026-10-09T06:00"], "precipitation": [2.0], "precipitation_probability": [40]}},
                "air_quality": {}}

    monkeypatch.setattr(W, "fetch_weather", ok)
    out = asyncio.run(FP.fetch_with_fallback(13.08, 80.27))
    assert out["source"] == "open_meteo" and out["provider_fallback"] is False and out["temperature"] == 30.0


def test_metno_disk_cache_honours_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(FP, "METNO_CACHE_DIR", str(tmp_path))
    calls = []

    class Resp:
        status_code = 200
        headers = {"Expires": "Thu, 01 Jan 2099 00:00:00 GMT", "Last-Modified": "Thu, 09 Oct 2026 06:00:00 GMT"}

        def json(self):
            return _metno_doc(3)

        def raise_for_status(self):
            pass

    class Client:
        async def get(self, url, params=None, headers=None):
            calls.append(headers)
            return Resp()

        async def aclose(self):
            pass

    c = Client()
    asyncio.run(FP.fetch_metno_raw(12.34567, 80.1, client=c))
    asyncio.run(FP.fetch_metno_raw(12.34567, 80.1, client=c))
    assert len(calls) == 1, "second call must be served from the cache until Expires"
    assert calls[0]["User-Agent"] == FP.METNO_UA
    assert os.path.exists(os.path.join(str(tmp_path), "12.3457_80.1000.json"))


# ── Retention ─────────────────────────────────────────────────────────────────
def test_retention_dry_run_and_apply(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.database import Base
    from app.models import CommunityReport, RoadReport, RouteLog, SystemLog
    from app.services import retention as RT

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime(2026, 10, 9, 12, 0)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with Session() as s:
            s.add_all([
                CommunityReport(latitude=12.123456, longitude=80.123456, report_type="flood", title="old", description="text",
                                location_name="home", author_id=None, created_at=now - timedelta(days=400)),
                CommunityReport(latitude=12.123456, longitude=80.123456, report_type="flood", title="mid", description="text",
                                created_at=now - timedelta(days=40)),
                CommunityReport(latitude=12.123456, longitude=80.123456, report_type="flood", title="new", description="text",
                                created_at=now - timedelta(days=2)),
                RoadReport(lat=12.9, lon=80.123456, status="closed", note="deep", created_at=now - timedelta(days=400)),
                RouteLog(from_lat=12.111111, from_lon=80.1, to_lat=12.2, to_lon=80.222222, created_at=now - timedelta(days=45)),
                RouteLog(from_lat=12.1, from_lon=80.1, to_lat=12.2, to_lon=80.2, created_at=now - timedelta(days=400)),
                RouteLog(from_lat=12.111111, from_lon=80.1, to_lat=12.2, to_lon=80.2, created_at=now - timedelta(days=1)),
            ])
            await s.commit()

    asyncio.run(setup())

    async def run(dry):
        async with Session() as s:
            return await RT.run_retention(dry_run=dry, now=now, db=s)

    dry = asyncio.run(run(True))
    assert dry["community_reports_coarsened"] == 2
    assert dry["road_reports_coarsened"] == 1
    assert dry["route_logs_from_coarsened"] == 1 and dry["route_logs_to_coarsened"] == 1
    assert dry["route_logs_deleted"] == 1
    assert dry["community_reports_stripped"] == 1 and dry["road_reports_stripped"] == 1

    async def unchanged():
        async with Session() as s:
            from sqlalchemy import select, func
            return (await s.execute(select(func.count()).select_from(RouteLog))).scalar()
    assert asyncio.run(unchanged()) == 3, "dry run must not delete"

    applied = asyncio.run(run(False))
    assert applied["route_logs_deleted"] == 1

    async def verify():
        from sqlalchemy import select
        async with Session() as s:
            reps = (await s.execute(select(CommunityReport).order_by(CommunityReport.id))).scalars().all()
            logs = (await s.execute(select(RouteLog))).scalars().all()
            syslog = (await s.execute(select(SystemLog))).scalars().all()
            return reps, logs, syslog
    reps, logs, syslog = asyncio.run(verify())
    assert reps[0].latitude == 12.12 and reps[0].description == "" and reps[0].location_name == ""
    assert reps[1].latitude == 12.12 and reps[1].description == "text"
    assert reps[2].latitude == 12.123456
    assert len(logs) == 2 and all(l.created_at > now - timedelta(days=365) for l in logs)
    assert any(r.source == "retention" for r in syslog)
    assert asyncio.run(run(True))["route_logs_deleted"] == 0

    asyncio.run(engine.dispose())
