"""ML routes — prediction, SHAP explanations, model registry, training."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import District, WeatherCache, HistoricalWeather
from app.services.ml import (predict, predict_all, get_shap_explanations, train_model,
                             get_model_metrics, get_registry, TABULAR_MODELS)

router = APIRouter(prefix="/api/ml", tags=["ml"])


async def _context(district_code: str, db: AsyncSession):
    """District, its cached weather dict, and the last 30 days of daily rain."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    w_result = await db.execute(select(WeatherCache).where(WeatherCache.district_id == district.id))
    weather = w_result.scalar_one_or_none()
    weather_data = {}
    if weather:
        weather_data = {
            "temperature": weather.temperature,
            "humidity": weather.humidity,
            "pressure": weather.pressure,
            "wind_speed": weather.wind_speed,
            "wind_gusts": weather.wind_gusts,
            "cloud_cover": weather.cloud_cover,
            "next_6h_rain": weather.next_6h_rain,
            "peak_intensity": weather.peak_intensity,
            "humidity_avg": weather.humidity,
            "rainfall_mm": weather.next_6h_rain,
        }

    h_result = await db.execute(
        select(HistoricalWeather.rainfall_mm)
        .where(HistoricalWeather.district_id == district.id)
        .order_by(HistoricalWeather.date.desc())
        .limit(30)
    )
    history = [r[0] or 0.0 for r in h_result.all()][::-1]  # oldest .. newest
    return district, weather_data, history


@router.get("/predict/{district_code}")
async def ml_predict(
    district_code: str,
    model: str = Query("ensemble_vote", description=f"One of {TABULAR_MODELS}"),
    db: AsyncSession = Depends(get_db),
):
    """Next-day risk prediction for a district from one tabular model."""
    if model not in TABULAR_MODELS:
        raise HTTPException(status_code=400, detail=f"model must be one of {TABULAR_MODELS}")
    district, weather_data, history = await _context(district_code, db)
    # predict() records the served class with monitoring.record_prediction itself
    prediction = predict(weather_data, history, district.lat, district.lon, model_name=model)
    prediction["district"] = district.code
    prediction["district_name"] = district.name
    prediction["formula_risk"] = district.risk
    prediction["formula_class"] = district.risk_class
    return prediction


@router.get("/predict-all/{district_code}")
async def ml_predict_all(district_code: str, db: AsyncSession = Depends(get_db)):
    """Every tabular model's prediction for the same district, side by side."""
    district, weather_data, history = await _context(district_code, db)
    return {
        "district": district.code,
        "district_name": district.name,
        "predictions": predict_all(weather_data, history, district.lat, district.lon),
    }


@router.get("/shap/{district_code}")
async def ml_shap(district_code: str, db: AsyncSession = Depends(get_db)):
    """SHAP feature attributions for a district's prediction."""
    district, weather_data, history = await _context(district_code, db)
    shap_result = get_shap_explanations(weather_data, history, district.lat, district.lon)
    shap_result["district"] = district.code
    shap_result["district_name"] = district.name
    return shap_result


@router.get("/models")
async def ml_models():
    """Full model registry: every trained model with its held-out metrics."""
    return get_registry()


@router.post("/train")
async def ml_train():
    """Retrain the four tabular models on all historical data (takes a few minutes)."""
    return await run_in_threadpool(train_model)


@router.get("/metrics")
async def ml_metrics():
    """Current model training metrics (legacy shape plus all models)."""
    return get_model_metrics()
