"""Offline tests for the hyperlocal engine's data-quality, provenance, cap, district lookup,
NaN feature handling and the shared site cache (no network, temporary SQLite files).

    cd backend
    python -m pytest tests/test_hyperlocal_quality.py -q
"""
import asyncio
import json
import math
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.services import features as F  # noqa: E402
from app.services import ml as M  # noqa: E402
from app.services import site_cache as SC  # noqa: E402
from app.services import hyperlocal as H  # noqa: E402
from app.services.district_lookup import resolve, normalise  # noqa: E402
from app.services.flood_history import lookup as flood_lookup  # noqa: E402


# ── features: missing inputs are NaN and named ────────────────────────────────
def test_live_features_nan_and_imputed_list():
    X, row, imputed = F.build_live_features({"temperature": 29, "humidity": 80, "next_6h_rain": 12.0},
                                            [1, 2, 3], 13.08, 80.27, with_quality=True)
    assert X.shape == (1, len(F.TABULAR_FEATURES))
    assert math.isnan(row["soil_moisture"]) and math.isnan(row["pressure_mean"])
    assert row["rh_mean"] == 80 and row["rain_today"] == 12.0
    assert "soil_moisture" in imputed and "rain_sum_7" in imputed and "rain_today" not in imputed
    assert "rain_sum_3" not in imputed                      # three days of history cover the 3-day window
    assert imputed == [f for f in F.TABULAR_FEATURES if f in imputed]   # feature order, no duplicates


def test_live_features_zero_is_a_value_and_old_shape_kept():
    X, row = F.build_live_features({"rainfall_mm": 0.0, "humidity": 0}, [0] * 30, 13.0, 80.0)
    assert row["rain_today"] == 0.0 and row["rh_mean"] == 0.0
    _, _, imputed = F.build_live_features({"rainfall_mm": 0.0}, [], 13.0, 80.0, with_quality=True)
    assert "rain_today" not in imputed and "rain_sum_3" in imputed and "rain_lag1" in imputed


def test_training_frame_leaves_nan():
    import pandas as pd
    daily = pd.DataFrame({
        "district_id": [1] * 5, "date": [f"2025-01-0{i}" for i in range(1, 6)],
        "rainfall_mm": [0, 3, 12, 0, 60], "temp_max": [30] * 5, "temp_min": [22] * 5,
        "wind_speed_max": [10, None, 12, None, 15], "precipitation_hours": [0, None, 4, 0, 9],
        "lat": [13.0] * 5, "lon": [80.0] * 5})
    df = F.build_training_frame(daily)
    assert df["wind_max"].isna().sum() >= 1 and df["precip_hours"].isna().sum() >= 1
    assert df["rh_mean"].isna().all()           # no hourly table -> NaN, not the old 72.0 constant
    assert list(df["label"]) == [0, 1, 0, 3]


# ── ml: data_quality, cap and the median fallback ─────────────────────────────
def test_apply_cap_only_when_key_inputs_imputed():
    r = M._apply_cap({"prediction": "extreme"}, M.data_quality(["soil_moisture", "cloud_mean"], "nan_passthrough"))
    assert r["prediction"] == "mod" and r["prediction_uncapped"] == "extreme" and "soil_moisture" in r["cap_reason"]
    r2 = M._apply_cap({"prediction": "extreme"}, M.data_quality(["cloud_mean"], "nan_passthrough"))
    assert r2["prediction"] == "extreme" and r2["cap_reason"] is None
    r3 = M._apply_cap({"prediction": "safe"}, M.data_quality(["rain_today"], "nan_passthrough"))
    assert r3["prediction"] == "safe" and r3["cap_reason"]      # below the cap: class kept, reason still given


class _RefusesNaN:
    classes_ = np.array([0, 1, 2, 3])

    def predict_proba(self, X):
        if np.isnan(X).any():
            raise ValueError("Input X contains NaN.")
        return np.array([[0.1, 0.2, 0.3, 0.4]])


def test_predict_proba_median_fallback(monkeypatch):
    monkeypatch.setattr(M, "_medians_cache", {f: 1.0 for f in F.TABULAR_FEATURES})
    X = np.zeros((1, len(F.TABULAR_FEATURES)), dtype=np.float32)
    X[0, 0] = np.nan
    probs, how = M._predict_proba(_RefusesNaN(), X)
    assert how == "median" and probs[3] == 0.4
    probs2, how2 = M._predict_proba(_RefusesNaN(), np.zeros((1, len(F.TABULAR_FEATURES)), dtype=np.float32))
    assert how2 == "none"


def test_predict_response_has_data_quality_and_is_json_safe():
    p = M.predict({"temperature": 29, "humidity": 80, "next_6h_rain": 60.0, "peak_intensity": 30}, [], 13.08, 80.27)
    assert set(p["data_quality"]) >= {"imputed", "imputed_count", "key_inputs_imputed", "imputation"}
    assert p["data_quality"]["key_inputs_imputed"] is True
    assert p["prediction"] in ("safe", "mod") and "cap_reason" in p
    json.dumps(p, allow_nan=False)      # no bare NaN reaches the browser


def test_pickled_models_accept_nan():
    """Every shipped tabular model routes NaN natively; if a retrain breaks this, the median
    fallback in ml._predict_proba takes over (feature_medians.json must then exist)."""
    X = np.zeros((1, len(F.TABULAR_FEATURES)), dtype=np.float32)
    X[0, F.TABULAR_FEATURES.index("soil_moisture")] = np.nan
    any_model = False
    for name in ("xgboost", "random_forest", "gradient_boost"):
        m = M.load_model(name)
        if m is None:
            continue
        any_model = True
        probs, how = M._predict_proba(m, X)
        assert abs(float(probs.sum()) - 1.0) < 1e-4
        assert how in ("nan_passthrough", "median")
    if any_model:
        assert M.MEDIANS_PATH.exists()


# ── district lookup / flood history ───────────────────────────────────────────
@pytest.mark.parametrize("alias,canonical,code", [
    ("Tuticorin", "Thoothukkudi", "594"), ("Thoothukudi", "Thoothukkudi", "594"),
    ("Kanyakumari", "Kanniyakumari", "575"), ("Kanniyakumariumari", "Kanniyakumari", "575"),
    ("Trichy", "Tiruchirappalli", "591"), ("Villupuram", "Viluppuram", "596"),
    ("Nilgiris", "The Nilgiris", "587"), ("Kanchipuram District", "Kancheepuram", "574"),
    ("Tiruvallur", "Thiruvallur", "589"), ("CHENGALPATTU", "Chengalpattu", "730"),
    ("Tenkasi", "Tenkasi", "733"), ("Ranipet", "Ranipet", "731"), ("Kallakurichi", "Kallakurichi", "729"),
    ("Tirupattur", "Tirupathur", "732"), ("Bengaluru Urban", "Bangalore", "525"), ("Guwahati", "Kamrup Metropolitan", "618"),
])
def test_resolve_aliases(alias, canonical, code):
    r = resolve(alias, report=False)
    assert r and r["district"] == canonical and r["lgd_code"] == code


def test_resolve_miss_is_reported(monkeypatch):
    seen = []
    import app.services.district_lookup as DL
    monkeypatch.setattr(DL, "_report_miss", lambda n, s: seen.append((n, s)))
    assert resolve("Atlantis District", "Nowhere") is None
    assert seen == [("Atlantis District", "Nowhere")]
    assert normalise("The Nilgiris District!") == "thenilgiris"


def test_flood_lookup_by_alias_and_parent():
    fl = flood_lookup("Tuticorin", "Tamil Nadu")
    assert fl["district"] == "Thoothukkudi" and fl["district_code"] == "594"
    assert fl["district_match"]["method"] == "lookup" and fl["flood_prone_index"] is not None
    new = flood_lookup("Mayiladuthurai")
    assert new["district_match"]["method"] == "parent" and new["district"] == "Nagapattinam"
    miss = flood_lookup("Atlantis")
    assert miss["district"] is None and miss["district_code"] is None and miss["flood_prone_index"] is None


# ── site cache shared in SQLite ───────────────────────────────────────────────
@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    db = str(tmp_path / "cache_test.db")
    monkeypatch.setattr(SC, "DB_PATH", db)
    monkeypatch.setattr(SC, "LEGACY_DIR", str(tmp_path / "legacy"))
    SC._initialised.discard(db)
    return tmp_path


def test_site_cache_roundtrip_and_legacy_import(tmp_cache):
    os.makedirs(SC.LEGACY_DIR)
    with open(os.path.join(SC.LEGACY_DIR, "13.080_80.281.json"), "w") as f:
        json.dump({"soil": {"t": 1700000000.0, "v": {"texture": "clay", "source": "soilgrids"}}}, f)
    rows = SC.load_site("13.080_80.281")          # first read imports the legacy file
    assert rows["soil"]["v"]["texture"] == "clay" and rows["soil"]["t"] == 1700000000.0
    SC.save_site("13.080_80.281", {"water": (time.time(), {"distance_m": 50, "source": "osm_overpass"}),
                                   "soil": (time.time(), {"texture": "loam", "source": "soilgrids"})})
    rows = SC.load_site("13.080_80.281")
    assert rows["water"]["v"]["distance_m"] == 50 and rows["soil"]["v"]["texture"] == "loam"
    assert SC.load_site("0.000_0.000") == {}
    assert SC.stats()["sites"] == 1


def test_site_cache_lock_is_exclusive_until_expiry(tmp_cache):
    assert SC.acquire_lock("k", "osm", ttl_s=0.4) is True
    assert SC.acquire_lock("k", "osm", ttl_s=0.4) is False      # second worker is refused
    assert SC.lock_held("k", "osm") is True
    time.sleep(0.5)
    assert SC.lock_held("k", "osm") is False                     # expired: can be taken over
    assert SC.acquire_lock("k", "osm", ttl_s=5) is True
    SC.release_lock("k", "osm")
    assert SC.lock_held("k", "osm") is False


def test_hyperlocal_disk_helpers_use_site_cache(tmp_cache):
    H._disk_save("12.800_80.000", {"terrain": (123.0, {"source": "unavailable"})})
    assert H._disk_load("12.800_80.000")["terrain"]["v"]["source"] == "unavailable"


# ── compute_impact: data_quality, cap, provenance, stale reservoirs ───────────
def _geo(terrain_ok=True):
    terr = ({"source": "AWS Terrain Tiles", "elevation_m": 6.0, "slope_deg": 0.4, "slope_deg_regional": 0.5,
             "hand_m": 0.8, "lowness": 0.85, "upstream_area_km2": 2.0, "in_closed_depression": False,
             "depression_depth_m": 0.0, "no_outlet_in_window": False}
            if terrain_ok else {"source": "unavailable", "error": "no tiles"})
    return {"terrain": terr,
            "elevation": {"elevation_m": 6.0, "slope_m_km": 0.5, "lowness": 0.8, "source": "open_meteo_elevation"},
            "water": {"distance_m": 120, "type": "river", "counts": {"river": 1, "waterway": 1, "drain": 0, "water": 0},
                      "source": "osm_overpass"},
            "soil": {"texture": "clay", "infiltration_mm_h": 2.0, "runoff_adj": 0.18, "porosity": 0.5, "source": "soilgrids"},
            "landuse": {"impervious_pct": 70, "green_pct": 20, "wetland_pct": 0, "farmland_pct": 0, "source": "osm_overpass"},
            "infra": {"source": "osm_overpass", "buildings_per_km2": 900, "culverts": 0, "embankments": 1, "railways": 1,
                      "storm_drains": 0, "underpasses": 1, "critical_facilities": 3, "substations": 1, "pumping_stations": 0},
            "coast": {"coast_km": 4.0, "coastal": True, "source": "osm_overpass"},
            "district": {"district": "Chennai", "state": "Tamil Nadu", "source": "nominatim"},
            "flood_history": flood_lookup("Chennai", "Tamil Nadu"),
            "layer_meta": {"terrain": {"fetched_at": time.time() - 100}, "water": {"fetched_at": time.time() - 3600}}}


ANT = {"rain_1d_mm": 10, "rain_3d_mm": 40, "rain_7d_mm": 90, "rain_30d_mm": 200, "saturation_pct": 70,
       "series": [0] * 1000 + [50, 80], "source": "open_meteo_archive", "fetched_at": time.time()}
WX = {"source": "open_meteo_forecast", "provider": "Open-Meteo", "fetched_at": time.time(), "soil_moisture_0_7": 0.38,
      "probability": 70, "humidity": 85, "cape_max_6h": 900, "next_24h_rain": 20, "model_agreement": 0.67}


def _impact(geo, upstream=None, tide=None, mm=150, h=3, wx=WX):
    sc = {"rainfall_mm": mm, "duration_h": h, "pattern": "steady", "lat": 13.08, "lon": 80.27}
    return H.compute_impact(geo, ANT, wx, sc, 7_000_000, ml_score=60, upstream=upstream, tide=tide or {})


def test_impact_keeps_every_existing_key_and_adds_quality_blocks():
    r = _impact(_geo())
    for k in ("primary", "modifiers", "exposure", "categories", "impact", "inundation", "drainage", "factors",
              "data_confidence", "advisories", "data_quality", "provenance", "validation_status", "cap_reason",
              "location", "antecedent", "runoff", "secondary_hazards"):
        assert k in r, k
    assert r["location"]["district_code"] == "568" and r["location"]["district_canonical"] == "Chennai"
    assert r["data_quality"]["key_inputs_imputed"] is False and r["cap_reason"] is None
    assert r["impact"]["class"] == r["impact"]["class_uncapped"]
    assert r["validation_status"]["status"] in ("untested_hypothesis", "calibrated") and r["validation_status"].get("note") is not None
    json.dumps(r, allow_nan=False)


def test_impact_caps_class_when_terrain_missing():
    r = _impact(_geo(terrain_ok=False))
    assert "terrain unavailable" in r["data_quality"]["imputed"] and r["data_quality"]["key_inputs_imputed"]
    assert r["impact"]["class_uncapped"] in ("high", "extreme")
    assert r["impact"]["class"] == "mod" and r["inundation"]["evacuation"] == "Monitor"
    assert r["impact"]["score"] >= 50                      # the number is kept, only the class moves
    assert r["cap_reason"] and "terrain unavailable" in r["cap_reason"]
    assert r["data_quality"]["cap_applied"] is True


def test_impact_flags_soil_moisture_and_forecast_fallback():
    wx = dict(WX, soil_moisture_0_7=None, source="metno", provider="MET Norway", provider_fallback=True)
    r = _impact(_geo(), wx=wx)
    assert "soil moisture missing" in r["data_quality"]["imputed"] and "forecast missing" not in r["data_quality"]["imputed"]
    assert r["data_confidence"]["forecast"] is True and r["data_quality"]["forecast_fallback"] is True
    fc = [p for p in r["provenance"] if p["layer"] == "forecast"][0]
    assert fc["status"] == "fallback" and "MET Norway" in fc["licence"]
    wx2 = dict(WX, source="unavailable", error="timeout")
    r2 = _impact(_geo(), wx=wx2)
    assert "forecast missing" in r2["data_quality"]["imputed"] and r2["data_quality"]["key_inputs_imputed"]


def test_stale_reservoirs_contribute_nothing():
    res = {"name": "Chembarambakkam", "code": "CHEM", "upstream": True, "storage_pct": 98, "overflow_prob": 0.9,
           "distance_km": 8, "source": "cmwssb"}
    fresh = {"reservoirs": [dict(res, stale=False, age_h=3)], "source": "riis_db", "fetched_at": time.time()}
    stale = {"reservoirs": [dict(res, stale=True, age_h=120)], "source": "riis_db", "fetched_at": time.time()}
    none = {"reservoirs": [], "source": "riis_db"}
    r_fresh, r_stale, r_none = (_impact(_geo(), upstream=u, mm=40, h=3) for u in (fresh, stale, none))
    mod = lambda r: [m for m in r["modifiers"]["rows"] if m["name"] == "Upstream & tide"][0]
    assert mod(r_fresh)["multiplier"] > mod(r_stale)["multiplier"]
    assert mod(r_stale)["multiplier"] == mod(r_none)["multiplier"]            # reservoir term is x1.0 when stale
    assert "stale (120 h old), ignored" in mod(r_stale)["source"]
    assert "reservoirs stale" in r_stale["data_quality"]["imputed"] and r_stale["data_quality"]["reservoirs_stale"]
    assert "reservoirs stale" not in r_fresh["data_quality"]["imputed"]
    prov = [p for p in r_stale["provenance"] if p["layer"] == "reservoirs"][0]
    assert prov["status"] == "stale" and prov["licence"] == "public page, scraped"


def test_provenance_lists_every_layer_with_licence_and_age():
    r = _impact(_geo(), tide={"applicable": True, "now_m": 0.3, "max_next_6h_m": 0.5, "source": "open_meteo_marine",
                              "fetched_at": time.time() - 30})
    layers = {p["layer"]: p for p in r["provenance"]}
    for name in ("terrain", "water", "soil", "flood_history", "archive", "forecast", "tide"):
        assert name in layers, name
        assert layers[name]["licence"] and layers[name]["ttl_s"] and "fetched_at" in layers[name]
    assert layers["terrain"]["cache_age_s"] == pytest.approx(100, abs=5)
    assert layers["water"]["licence"].endswith("ODbL") and layers["soil"]["licence"].startswith("ISRIC")
    assert layers["tide"]["cache_age_s"] == pytest.approx(30, abs=5)


def test_validation_status_reads_calibration_file(tmp_path, monkeypatch):
    missing = tmp_path / "calibration.json"
    monkeypatch.setattr(H, "CALIBRATION_PATH", str(missing))
    assert H.validation_status()["status"] == "untested_hypothesis"
    missing.write_text(json.dumps({"computed_at": "2026-10-09T00:00:00Z", "method": "IFI event join",
                                   "n_events": 36, "auc": 0.71, "note": "first pass"}))
    vs = H.validation_status()
    assert vs["status"] == "calibrated" and vs["n_events"] == 36 and vs["auc"] == 0.71


def test_reservoir_freshness_fallbacks():
    class Row:
        source = "seed"; observed_at = None; source_url = None
    f = H._reservoir_freshness(Row())
    assert f["stale"] is True and f["live"] is False and f["age_h"] is None

    class Live:
        source = "cmwssb"; observed_at = time.strftime("%Y-%m-%d"); source_url = "https://cmwssb.tn.gov.in/lake-level"
    g = H._reservoir_freshness(Live())
    assert g["live"] is True and g["stale"] is False and g["age_h"] is not None and g["age_h"] < 48

    class Flagged:
        source = "kseb"; observed_at = "2026-01-01"; stale = False; live = True; age_h = 1.0
    assert H._reservoir_freshness(Flagged())["stale"] is False      # the sync's own flags win


def test_metno_mapping_handles_missing_module(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "app.services.forecast_providers":
            raise ImportError("not landed yet")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert asyncio.run(H._metno_live(13.0, 80.0)) is None
