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
    provider = Column(String(16), default="open_meteo")      # open_meteo | met_norway (services/forecast_providers.py)
    provider_fallback = Column(Boolean, default=False)       # True when the last poll came from the fallback provider

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

    # Live telemetry provenance (filled by services/reservoir_live.py; "seed" when no public feed exists)
    source = Column(String(16), default="seed")
    observed_at = Column(String(32), nullable=True)      # ISO date (YYYY-MM-DD) or datetime from the source page
    fetched_at = Column(DateTime, nullable=True)         # when the sync last wrote this row from a live page
    level_ft = Column(Float, nullable=True)
    full_level_ft = Column(Float, nullable=True)
    storage_pct = Column(Float, nullable=True)
    rainfall_mm = Column(Float, nullable=True)
    last_year_mcft = Column(Float, nullable=True)
    alert_level = Column(String(8), nullable=True)       # KSEB blue / orange / red
    remarks = Column(String(200), nullable=True)
    source_url = Column(String(200), nullable=True)

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


# ── Safe Routes: road network, flood status, reports, risk samples ───────────
class RoadSite(Base):
    __tablename__ = "road_sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    radius_m = Column(Float, default=1800.0)
    bbox_json = Column(JSON, default=dict)          # {south, west, north, east}
    fetched_at = Column(DateTime, default=datetime.utcnow)
    n_ways = Column(Integer, default=0)
    n_nodes = Column(Integer, default=0)
    source = Column(String(32), default="osm_overpass")


class RoadSegment(Base):
    __tablename__ = "road_segments"
    __table_args__ = (Index("ix_road_segments_site", "site_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("road_sites.id"), nullable=False)
    osm_way_id = Column(Integer, nullable=False)
    seg_index = Column(Integer, default=0)
    from_node = Column(Integer, nullable=False)
    to_node = Column(Integer, nullable=False)
    name = Column(String(128), default="")
    highway = Column(String(32), default="")
    oneway = Column(Boolean, default=False)
    tunnel = Column(Boolean, default=False)
    bridge = Column(Boolean, default=False)
    layer = Column(Integer, default=0)
    length_m = Column(Float, default=0.0)
    geom_json = Column(JSON, default=list)          # [[lon, lat], ...]
    mid_lat = Column(Float, default=0.0)
    mid_lon = Column(Float, default=0.0)
    elev_m = Column(Float, nullable=True)
    hand_m = Column(Float, nullable=True)           # midpoint elev minus 150 m window minimum (cheap HAND proxy)
    slope_pct = Column(Float, nullable=True)
    dist_water_m = Column(Float, nullable=True)
    impervious_pct = Column(Float, nullable=True)
    culvert_near = Column(Boolean, default=False)


class RoadStatusCache(Base):
    __tablename__ = "road_status_cache"
    __table_args__ = (Index("ix_road_status_site_key", "site_id", "scenario_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("road_sites.id"), nullable=False)
    scenario_key = Column(String(64), nullable=False)   # "rainfall_mm|duration_h|intensity"
    computed_at = Column(DateTime, default=datetime.utcnow)
    status_json = Column(JSON, default=dict)             # segment_id -> {status, max_depth_m, wet_fraction}


class RoadReport(Base):
    __tablename__ = "road_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    status = Column(String(16), nullable=False)          # open | caution | closed
    depth_cm = Column(Float, nullable=True)
    source = Column(String(16), default="user")          # user | admin | sensor
    note = Column(String(300), default="")
    scenario_key = Column(String(64), nullable=True)     # scenario active when filed (for training labels)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class RouteLog(Base):
    __tablename__ = "route_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("road_sites.id"), nullable=True)
    from_lat = Column(Float); from_lon = Column(Float)
    to_lat = Column(Float); to_lon = Column(Float)
    scenario_key = Column(String(64), nullable=True)
    safe_len_m = Column(Float, nullable=True)
    normal_len_m = Column(Float, nullable=True)
    closed_avoided = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class RoadRiskSample(Base):
    __tablename__ = "road_risk_samples"
    __table_args__ = (Index("ix_road_risk_segment", "segment_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=False)
    scenario_key = Column(String(64), nullable=False)
    features_json = Column(JSON, default=dict)
    label = Column(Integer, default=0)                   # 0 open, 1 caution, 2 closed
    label_source = Column(String(16), default="sim")     # sim (physics surrogate) | report (observed)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── System Logs ───────────────────────────────────────────────────────────────
class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), default="info")    # info | warn | error
    source = Column(String(64), default="system") # weather_poll | risk_calc | auth | api
    message = Column(Text, default="")
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
