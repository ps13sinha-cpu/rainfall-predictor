"""SQLAlchemy models for RIIS"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Text, Boolean, DateTime, JSON,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


# ── Users ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False)
    hashed_password = Column(String(256), nullable=False)
    full_name = Column(String(128), default="")
    role = Column(String(20), default="public")  # public | reporter | admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    reports = relationship("CommunityReport", back_populates="author", foreign_keys="CommunityReport.author_id")


# ── Districts ─────────────────────────────────────────────────────────────────
class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    state = Column(String(64), default="")
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    pop = Column(Integer, default=0)

    # Risk (updated by scheduler)
    risk = Column(Integer, default=5)
    rain = Column(Float, default=0.0)
    risk_class = Column(String(10), default="safe")

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    weather_cache = relationship("WeatherCache", back_populates="district", uselist=False)


# ── Weather Cache ─────────────────────────────────────────────────────────────
class WeatherCache(Base):
    __tablename__ = "weather_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(Integer, ForeignKey("districts.id"), unique=True, nullable=False)

    # Current conditions (cached from last API call)
    temperature = Column(Float, default=0.0)
    humidity = Column(Integer, default=0)
    pressure = Column(Float, default=1010.0)
    wind_speed = Column(Float, default=0.0)
    wind_gusts = Column(Float, default=0.0)
    wind_direction = Column(Integer, default=0)
    cloud_cover = Column(Integer, default=0)
    weather_code = Column(Integer, default=0)
    aqi = Column(Integer, default=0)
    aqi_label = Column(String(32), default="Good")
    uv_index = Column(Float, default=0.0)

    # Forecast summary
    next_6h_rain = Column(Float, default=0.0)
    peak_intensity = Column(Float, default=0.0)
    max_probability = Column(Integer, default=0)

    # Raw hourly data (JSON) for timeline
    hourly_data = Column(JSON, default=dict)

    # Air quality
    pm2_5 = Column(Float, default=0.0)
    pm10 = Column(Float, default=0.0)

    # Metadata
    fetched_at = Column(DateTime, default=datetime.utcnow)
    weather_description = Column(String(100), default="")

    district = relationship("District", back_populates="weather_cache")


# ── Reservoirs ────────────────────────────────────────────────────────────────
class Reservoir(Base):
    __tablename__ = "reservoirs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    lat = Column(Float, default=0.0)
    lon = Column(Float, default=0.0)

    capacity_mcft = Column(Float, nullable=False)
    current_mcft = Column(Float, nullable=False)
    inflow_cms = Column(Float, default=0.0)   # m³/s
    outflow_cms = Column(Float, default=0.0)
    overflow_prob = Column(Float, default=0.0)
    risk_class = Column(String(10), default="safe")

    # Baseline values (for scaling by rainfall)
    baseline_inflow = Column(Float, default=0.0)
    baseline_outflow = Column(Float, default=0.0)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Community Reports ─────────────────────────────────────────────────────────
class CommunityReport(Base):
    __tablename__ = "community_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_name = Column(String(128), default="")

    report_type = Column(String(64), nullable=False)   # flood, waterlogging, drainage, road_damage, etc.
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    severity = Column(String(10), default="mod")       # safe | mod | high | extreme

    # Photo/video evidence
    media_url = Column(String(500), default="")
    media_type = Column(String(20), default="")        # image | video

    # Verification
    is_verified = Column(Boolean, default=False)
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verification_note = Column(Text, default="")

    # Community engagement
    upvotes = Column(Integer, default=0)

    # AI classification
    ai_classified = Column(Boolean, default=False)
    ai_class = Column(String(10), default="")          # safe | mod | high | extreme

    status = Column(String(20), default="pending")     # pending | approved | rejected
    created_at = Column(DateTime, default=datetime.utcnow)

    author = relationship("User", foreign_keys=[author_id], back_populates="reports")


# ── Alerts ────────────────────────────────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    severity = Column(String(10), nullable=False)       # safe | mod | high | extreme
    title = Column(String(200), nullable=False)
    body = Column(Text, default="")
    area = Column(String(128), default="General")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    radius_km = Column(Float, default=50.0)

    # Distribution
    channels = Column(JSON, default=lambda: ["web"])    # web | sms | push | whatsapp
    is_broadcast = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


# ── Historical Weather ────────────────────────────────────────────────────────
class HistoricalWeather(Base):
    __tablename__ = "historical_weather"
    __table_args__ = (
        Index("ix_historical_date", "district_id", "date"),
        UniqueConstraint("district_id", "date", name="uq_historical_district_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False)
    date = Column(String(10), nullable=False)   # YYYY-MM-DD

    rainfall_mm = Column(Float, default=0.0)
    temp_max = Column(Float, default=0.0)
    temp_min = Column(Float, default=0.0)
    humidity_avg = Column(Float, default=0.0)
    wind_speed_max = Column(Float, default=0.0)
    precipitation_hours = Column(Integer, default=0)


# ── System Logs ───────────────────────────────────────────────────────────────
class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), default="info")    # info | warn | error
    source = Column(String(64), default="system") # weather_poll | risk_calc | auth | api
    message = Column(Text, default="")
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
