"""Schema and sanity checks on the real riis.db (opened read-only, no network).

Skips cleanly when the database has not been created yet.

    cd backend
    python -m pytest tests/test_schema_tables.py -q
"""
import os
import sqlite3

import pytest

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")

REQUIRED = {
    # table: {column: notnull_required}
    "historical_weather": {"id": True, "district_id": True, "date": True, "rainfall_mm": False, "temp_max": False,
                           "temp_min": False, "humidity_avg": False, "wind_speed_max": False, "precipitation_hours": False},
    "historical_hourly": {"district_id": True, "time": True, "temperature_2m": False, "relative_humidity_2m": False,
                          "precipitation": False, "pressure_msl": False, "wind_speed_10m": False,
                          "soil_moisture_0_to_7cm": False, "weather_code": False},
    "reservoirs": {"id": True, "code": True, "name": True, "capacity_mcft": True, "current_mcft": True,
                   "source": False, "observed_at": False, "storage_pct": False, "overflow_prob": False, "risk_class": False},
    "road_risk_samples": {"id": True, "segment_id": True, "scenario_key": True, "features_json": False,
                          "label": False, "label_source": False},
}
SAMPLE = 20000
# Leh (IN-LA-LE) records -18 C in winter, so the temperature floor is -30, not -10; 55 C stays the ceiling.
TEMP_MIN, TEMP_MAX = -30, 55


@pytest.fixture(scope="module")
def db():
    if not os.path.exists(DB_PATH):
        pytest.skip("riis.db not present")
    conn = sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro", uri=True)
    yield conn
    conn.close()


def _columns(db, table):
    return {row[1]: {"type": row[2], "notnull": bool(row[3]), "pk": row[5]} for row in db.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize("table", sorted(REQUIRED))
def test_required_columns_and_not_null(db, table):
    cols = _columns(db, table)
    assert cols, f"table {table} missing"
    for name, must_notnull in REQUIRED[table].items():
        assert name in cols, f"{table}.{name} missing"
        if must_notnull:
            c = cols[name]
            assert c["notnull"] or c["pk"], f"{table}.{name} should be NOT NULL (or part of the primary key)"


def test_historical_weather_ranges_and_uniqueness(db):
    n = db.execute("SELECT COUNT(*) FROM historical_weather").fetchone()[0]
    if n == 0:
        pytest.skip("historical_weather empty")
    dup = db.execute("SELECT COUNT(*) FROM (SELECT district_id, date FROM historical_weather GROUP BY 1, 2 HAVING COUNT(*) > 1)").fetchone()[0]
    assert dup == 0, f"{dup} duplicate (district_id, date) pairs"
    bad = db.execute(
        "SELECT COUNT(*) FROM (SELECT * FROM historical_weather ORDER BY id DESC LIMIT ?) "
        f"WHERE rainfall_mm < 0 OR temp_max < {TEMP_MIN} OR temp_max > {TEMP_MAX} OR temp_min < {TEMP_MIN} OR temp_min > {TEMP_MAX} "
        "OR temp_min > temp_max + 0.01 OR date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'", (SAMPLE,)).fetchone()[0]
    assert bad == 0, f"{bad} historical_weather rows out of range in the sample"
    nulls = db.execute("SELECT COUNT(*) FROM historical_weather WHERE district_id IS NULL OR date IS NULL").fetchone()[0]
    assert nulls == 0
    orphan = db.execute("SELECT COUNT(*) FROM historical_weather h LEFT JOIN districts d ON d.id = h.district_id WHERE d.id IS NULL").fetchone()[0]
    assert orphan == 0, f"{orphan} rows reference a missing district"


def test_historical_hourly_ranges(db):
    n = db.execute("SELECT COUNT(*) FROM historical_hourly").fetchone()[0]
    if n == 0:
        pytest.skip("historical_hourly empty")
    bad = db.execute(
        "SELECT COUNT(*) FROM (SELECT * FROM historical_hourly ORDER BY rowid DESC LIMIT ?) "
        f"WHERE precipitation < 0 OR temperature_2m < {TEMP_MIN} OR temperature_2m > {TEMP_MAX} "
        "OR (relative_humidity_2m IS NOT NULL AND (relative_humidity_2m < 0 OR relative_humidity_2m > 100)) "
        "OR (pressure_msl IS NOT NULL AND (pressure_msl < 850 OR pressure_msl > 1100))", (SAMPLE,)).fetchone()[0]
    assert bad == 0, f"{bad} historical_hourly rows out of range in the sample"
    dup = db.execute("SELECT COUNT(*) FROM (SELECT district_id, time FROM (SELECT * FROM historical_hourly ORDER BY rowid DESC LIMIT ?) GROUP BY 1, 2 HAVING COUNT(*) > 1)", (SAMPLE,)).fetchone()[0]
    assert dup == 0


def test_reservoir_rows_are_consistent(db):
    rows = db.execute("SELECT code, name, capacity_mcft, current_mcft, storage_pct, source, observed_at, overflow_prob FROM reservoirs").fetchall()
    if not rows:
        pytest.skip("reservoirs empty")
    codes = [r[0] for r in rows]
    assert len(codes) == len(set(codes))
    for code, name, cap, cur, pct, source, observed_at, prob in rows:
        assert name and cap > 0 and cur >= 0, (code, name, cap, cur)
        assert cur <= cap * 1.2, f"{code}: storage {cur} above capacity {cap}"
        if pct is not None:
            assert 0 <= pct <= 115, (code, pct)
        assert source in ("seed", "cmwssb", "kseb", "manual"), (code, source)
        if source in ("cmwssb", "kseb"):
            assert observed_at and len(observed_at) >= 10, f"live row {code} must carry observed_at"
        if prob is not None:
            assert 0 <= prob <= 100


def test_road_risk_samples(db):
    n = db.execute("SELECT COUNT(*) FROM road_risk_samples").fetchone()[0]
    if n == 0:
        pytest.skip("road_risk_samples empty")
    bad = db.execute("SELECT COUNT(*) FROM (SELECT * FROM road_risk_samples ORDER BY id DESC LIMIT ?) "
                     "WHERE label NOT IN (0, 1, 2) OR label_source NOT IN ('sim', 'report') OR segment_id IS NULL", (SAMPLE,)).fetchone()[0]
    assert bad == 0
