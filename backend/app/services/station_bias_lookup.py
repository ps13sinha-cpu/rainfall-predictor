"""Per-district ERA5-vs-gauge bias, computed by `python -m app.station_bias` into app/data/station_bias.json.

Served with every impact response so the reader sees how far the reanalysis that trained the models
sits from observed gauges in that district. Districts without gauge coverage get a plain statement.
"""
import os
import json

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "station_bias.json")
_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(PATH) as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _norm(x):
    return "".join(ch for ch in str(x or "").lower() if ch.isalpha())


def station_bias_for(seeded_district: str | None, geocoded_district: str | None = None) -> dict:
    rep = _load()
    ds = rep.get("districts") or {}
    for cand in (seeded_district, geocoded_district):
        if not cand:
            continue
        for name, d in ds.items():
            if _norm(cand) in (_norm(name), _norm(d.get("tndma_name"))):
                return {"status": "measured", "district": name, "window": rep.get("window"),
                        "ratio_era5_over_station": d["ratio_era5_over_station"],
                        "p99_ratio": d["quantile_ratio_era5_over_station"]["p99"],
                        "heavy_day_pod": d["heavy_day"]["pod"], "heavy_day_far": d["heavy_day"]["far"],
                        "pearson_r_daily": d["pearson_r_daily"], "n_days": d["n_days"],
                        "reading": ("the reanalysis that labels every RIIS weather model under-reports the heaviest "
                                    "days here by about " + str(round((1 - d["quantile_ratio_era5_over_station"]["p99"]) * 100))
                                    + "% at the 99th percentile" if d["quantile_ratio_era5_over_station"]["p99"] and
                                    d["quantile_ratio_era5_over_station"]["p99"] < 1 else "reanalysis matches or exceeds gauges at the 99th percentile"),
                        "source": rep.get("station_source")}
    summ = rep.get("summary") or {}
    return {"status": "not_measured", "note": "no gauge network joined for this district",
            "tamil_nadu_median_ratio": summ.get("median_ratio_era5_over_station"),
            "tamil_nadu_median_p99_ratio": summ.get("median_p99_ratio")}
