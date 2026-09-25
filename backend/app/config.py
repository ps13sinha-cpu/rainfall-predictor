"""RIIS Backend Configuration — loaded from environment / .env"""
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database — supports both SQLite (dev) and PostgreSQL (prod)
    # Prod: postgresql+asyncpg://user:pass@host:5432/riis
    database_url: str = "sqlite+aiosqlite:///./riis.db"

    # JWT
    secret_key: str = "riis-change-this-in-production-2024"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # External APIs
    openmeteo_base_url: str = "https://api.open-meteo.com/v1"
    openmeteo_archive_url: str = "https://archive-api.open-meteo.com/v1"
    air_quality_url: str = "https://air-quality-api.open-meteo.com/v1"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    rainviewer_url: str = "https://api.rainviewer.com/public/weather-maps.json"
    openweather_api_key: str = ""

    # Polling intervals (seconds)
    weather_poll_interval: int = 300
    district_poll_interval: int = 300

    # Twilio (SMS + WhatsApp)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # Firebase (Push Notifications)
    firebase_credentials_path: str = ""
    fcm_sender_id: str = ""
    fcm_vapid_key: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    environment: str = "development"  # development | production

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
