"""ML routes — prediction, SHAP explanations, model training."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import District, WeatherCache, HistoricalWeather
from app.services.ml import predict, get_shap_explanations, train_model, get_model_metrics
from app.services.auth import require_admin

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.get("/predict/{district_code}")
async def ml_predict(district_code: str, db: AsyncSession = Depends(get_db)):
    """Get ML-based risk prediction for a district."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    w_result = await db.execute(
        select(WeatherCache).where(WeatherCache.district_id == district.id)
    )
    weather = w_result.scalar_one_or_none()

    weather_data = {}
    if weather:
        weather_data = {
            "temperature": weather.temperature,
            "humidity": weather.humidity,
            "pressure": weather.pressure,
            "wind_speed": weather.wind_speed,
            "cloud_cover": weather.cloud_cover,
            "next_6h_rain": weather.next_6h_rain,
            "peak_intensity": weather.peak_intensity,
        }

    prediction = predict(weather_data)
    prediction["district"] = district.code
    prediction["district_name"] = district.name
    prediction["formula_risk"] = district.risk
    prediction["formula_class"] = district.risk_class

    return prediction


@router.get("/shap/{district_code}")
async def ml_shap(district_code: str, db: AsyncSession = Depends(get_db)):
    """Get SHAP feature attributions for a district's prediction."""
    result = await db.execute(select(District).where(District.code == district_code))
    district = result.scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")

    w_result = await db.execute(
        select(WeatherCache).where(WeatherCache.district_id == district.id)
    )
    weather = w_result.scalar_one_or_none()

    weather_data = {}
    if weather:
        weather_data = {
            "temperature": weather.temperature,
            "humidity": weather.humidity,
            "pressure": weather.pressure,
            "wind_speed": weather.wind_speed,
            "cloud_cover": weather.cloud_cover,
            "next_6h_rain": weather.next_6h_rain,
            "peak_intensity": weather.peak_intensity,
            "humidity_avg": weather.humidity,
            "rainfall_mm": weather.next_6h_rain,
        }

    shap_result = get_shap_explanations(weather_data)
    shap_result["district"] = district.code
    shap_result["district_name"] = district.name

    return shap_result


@router.post("/train")
async def ml_train(
    district_code: str = Query(None, description="Train on specific district, or all if omitted"),
    start_date: str = Query("2023-01-01"),
    end_date: str = Query("2025-12-31"),
    user=None,  # require_admin
    db: AsyncSession = Depends(get_db),
):
    """Train the XGBoost model on historical data."""
    if district_code:
        # Train on one district
        result = await db.execute(select(District).where(District.code == district_code))
        district = result.scalar_one_or_none()
        if district is None:
            raise HTTPException(status_code=404, detail="District not found")

        q = (
            select(HistoricalWeather)
            .where(HistoricalWeather.district_id == district.id)
            .where(HistoricalWeather.date >= start_date)
            .where(HistoricalWeather.date <= end_date)
            .order_by(HistoricalWeather.date)
        )
        result = await db.execute(q)
        rows = result.scalars().all()
    else:
        # Train on all districts
        q = (
            select(HistoricalWeather)
            .where(HistoricalWeather.date >= start_date)
            .where(HistoricalWeather.date <= end_date)
            .order_by(HistoricalWeather.date)
        )
        result = await db.execute(q)
        rows = result.scalars().all()

    metrics = train_model(rows)
    return metrics


@router.get("/metrics")
async def ml_metrics():
    """Get current model training metrics."""
    return get_model_metrics()
