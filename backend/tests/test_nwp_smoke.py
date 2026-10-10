"""Live NWP smoke test — only with RIIS_LIVE_TESTS=1 (one Open-Meteo request, 3 budget units).

Asks the forecast endpoint for Chennai with models=ecmwf_ifs025,gfs_seamless,icon_seamless
and asserts each returns an hourly precipitation array. The result is persisted to
backend/cache/nwp_smoke.json so GET /api/health/monitoring can show it.

    cd backend
    RIIS_LIVE_TESTS=1 python -m pytest tests/test_nwp_smoke.py -q
"""
import os
import sys
import asyncio

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

LIVE = os.environ.get("RIIS_LIVE_TESTS", "") == "1"


@pytest.mark.skipif(not LIVE, reason="set RIIS_LIVE_TESTS=1 to call Open-Meteo")
def test_three_nwp_models_return_precipitation():
    from app.services.forecast_providers import nwp_smoke, NWP_MODELS
    result = asyncio.run(nwp_smoke())
    assert result["error"] is None, result["error"]
    for m in NWP_MODELS:
        assert result["models"][m]["ok"], f"{m} returned no precipitation array: {result['models'][m]}"
        assert result["models"][m]["n_hours"] >= 24
    assert result["ok"] is True
