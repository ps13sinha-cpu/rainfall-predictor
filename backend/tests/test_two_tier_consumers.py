"""Safe Routes and the farmer advisory take their verdicts from the engine's two-tier score."""
from app.services import roads as R
from app.services.farmer import waterlogging_level, hazard_drivers


def test_classify_score_follows_engine_classes():
    seg = {"bridge": False, "tunnel": False, "layer": 0, "culvert_near": False}
    assert R.classify_score(0, seg) == "open"
    assert R.classify_score(24.9, seg) == "open"
    assert R.classify_score(25, seg) == "caution"
    assert R.classify_score(50, seg) == "closed_cars"
    assert R.classify_score(75, seg) == "closed_all"
    assert R.classify_score(99, dict(seg, bridge=True)) == "open"
    assert R.classify_score(16, dict(seg, culvert_near=True)) == "caution"
    under = dict(seg, tunnel=True, layer=-1)
    assert R.classify_score(0, under) == "caution"
    assert R.classify_score(0, under, any_wet_near=True) == "closed_cars"
    assert R.classify_score(80, seg, elevation_term=10) == "caution"          # high ground never closes on rain alone
    assert R.classify_score(80, seg, elevation_term=60) == "closed_all"


def test_segment_hazard_uses_primaries_and_site_modifiers():
    ctx = {"peak_intensity_mm_h": 30.0, "site_severity": 20.0, "product_rest": 1.1, "dp_range": (0.9, 1.2),
           "water_type": "river", "lowness": 0.5}
    low = {"hand_m": 0.2, "elev_m": 4.0, "pit_depth_m": 0.5, "dist_water_m": 150}
    ridge = {"hand_m": 30.0, "elev_m": 120.0, "pit_depth_m": 0.0, "dist_water_m": 5000}
    a = R.segment_hazard(low, ctx, 0.3, 90.0, 3.0)
    b = R.segment_hazard(ridge, ctx, 0.0, 90.0, 3.0)
    assert a["terrain_ok"] and b["terrain_ok"]
    assert a["score"] > b["score"]
    assert set(a["primary"]) == {"Rainfall intensity", "Elevation (relative)", "Distance to water"}
    assert 0.6 <= a["modifier_product"] <= 1.6
    # a deeper simulated pool on the same segment only moves the ponding modifier, never the primaries
    assert a["elevation_term"] > 60 and b["elevation_term"] <= 10
    c = R.segment_hazard(low, ctx, 0.6, 90.0, 3.0)
    assert c["base"] == a["base"] and c["score"] >= a["score"]
    # no DEM on the segment -> flagged so the caller can fall back to depth thresholds
    assert not R.segment_hazard({"dist_water_m": 100}, ctx, 0.0, 90.0, 3.0)["terrain_ok"]


def test_waterlogging_level_and_drivers():
    assert waterlogging_level(10) == "low" and waterlogging_level(25) == "moderate" and waterlogging_level(50) == "high"
    imp = {"primary": {"terms": [{"name": "Rainfall intensity", "score": 60}]},
           "modifiers": {"rows": [{"name": "Drainage", "effect_pct": 12.0}, {"name": "Historical", "effect_pct": -2.0},
                                  {"name": "Model", "effect_pct": 0.0}]}}
    d = hazard_drivers(imp)
    assert d[0] == "Rainfall intensity 60/100" and d[1] == "Drainage +12.0%" and "Model" not in " ".join(d)
