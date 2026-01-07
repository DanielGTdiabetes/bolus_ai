import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator


class NightscoutConfig(BaseModel):
    base_url: Optional[HttpUrl] = None
    api_secret: Optional[str] = Field(default=None)
    token: Optional[str] = Field(default=None)
    timeout_seconds: int = Field(default=10, ge=1)
    
    # Compression Filter Settings
    filter_compression: bool = Field(default=False)
    filter_drop_mgdl: float = Field(default=15.0)
    filter_rebound_mgdl: float = Field(default=15.0)
    filter_window_min: int = 15
    filter_night_start: int = 23
    filter_night_end: int = 7


class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)


class SecurityConfig(BaseModel):
    jwt_secret: str = Field(min_length=16)
    jwt_issuer: str = Field(default="bolus-ai")
    access_token_minutes: int = Field(default=720, ge=5, le=24 * 60)
    cors_origins: list[str] = Field(default_factory=list)



# Calculate absolute path to backend root (3 levels up from app/core/settings.py)
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

class DataConfig(BaseModel):
    data_dir: Path = Field(default_factory=lambda: BACKEND_ROOT / "data")
    static_dir: Path = Field(default_factory=lambda: BACKEND_ROOT / "app" / "static")

    @field_validator("data_dir", mode="before")
    def _expand_path(cls, v: str | Path) -> Path:
        if v is None:
            return BACKEND_ROOT / "data"
        p = Path(v).expanduser()
        if not p.is_absolute():
            # If relative, try to anchor to backend root if it looks like "data"
            # But the default "backend/data" string from previous config might be an issue if we are ALREADY in backend.
            # Let's trust the absolute logic above for default.
            # If user provides a relative path, assume relative to CWD, which is standard.
            pass
        return p


class VisionConfig(BaseModel):
    provider: str = Field(default="openai") # "openai" or "gemini"
    openai_api_key: Optional[str] = Field(default=None)
    google_api_key: Optional[str] = Field(default=None)
    gemini_model: Optional[str] = Field(default=None)
    openai_model: Optional[str] = Field(default="gpt-4o")
    max_image_mb: int = Field(default=6, ge=1, le=20)
    timeout_seconds: int = Field(default=15, ge=5, le=60)


class DatabaseConfig(BaseModel):
    url: Optional[str] = Field(default=None, validate_default=True)

    @field_validator("url")
    def _validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://")
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://")
        return v

class ComboFollowupConfig(BaseModel):
    enabled: bool = False
    delay_minutes: int = 120
    window_hours: int = 6
    silence_minutes: int = 180
    quiet_hours_start: Optional[str] = "23:00"
    quiet_hours_end: Optional[str] = "07:00"

class PremealConfig(BaseModel):
    enabled: bool = False
    chat_id: Optional[int] = None
    silence_minutes: int = 60
    bg_threshold_mgdl: float = 160.0
    delta_threshold_mgdl: float = 5.0

class BasalConfig(BaseModel):
    enabled: bool = False
    chat_id: Optional[int] = None
    time_local: Optional[str] = None # e.g. "22:00"

class ProactiveGlobalConfig(BaseModel):
    combo_followup: ComboFollowupConfig = Field(default_factory=ComboFollowupConfig)
    premeal: PremealConfig = Field(default_factory=PremealConfig)
    basal: BasalConfig = Field(default_factory=BasalConfig)

class DexcomConfig(BaseModel):
    enabled: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    region: Optional[str] = "ous"

class NightPatternConfig(BaseModel):
    enabled: bool = False
    days: int = 18
    bucket_minutes: int = 15
    horizon_minutes: int = 75
    weight_a: float = 0.30
    weight_b: float = 0.20
    cap_mgdl: float = 25.0
    window_a_start: str = "00:00"
    window_a_end: str = "02:00"
    window_b_start: str = "02:00"
    window_b_end: str = "03:45"
    disable_at: str = "04:00"
    meal_lookback_h: float = 6.0
    bolus_lookback_h: float = 4.0
    iob_max_u: float = 0.3
    slope_max_mgdl_per_min: float = 0.4


class Settings(BaseModel):
    nightscout: NightscoutConfig
    server: ServerConfig
    security: SecurityConfig
    data: DataConfig
    vision: VisionConfig = Field(default_factory=VisionConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    proactive: "ProactiveGlobalConfig" = Field(default_factory=lambda: ProactiveGlobalConfig())
    dexcom: DexcomConfig = Field(default_factory=DexcomConfig)
    night_pattern: NightPatternConfig = Field(default_factory=NightPatternConfig)

    model_config = ConfigDict(arbitrary_types_allowed=True)



DEFAULT_CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config/config.json"))


def _load_file_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON configuration at {path}") from exc


def _load_env() -> dict[str, Any]:
    env_config: dict[str, Any] = {}

    base_url = os.environ.get("NIGHTSCOUT_BASE_URL") or os.environ.get("NIGHTSCOUT_URL")
    if base_url:
        env_config.setdefault("nightscout", {})["base_url"] = base_url

    api_secret = os.environ.get("NIGHTSCOUT_API_SECRET")
    if api_secret:
        env_config.setdefault("nightscout", {})["api_secret"] = api_secret

    token = os.environ.get("NIGHTSCOUT_TOKEN")
    if token:
        env_config.setdefault("nightscout", {})["token"] = token

    host = os.environ.get("SERVER_HOST")
    if host:
        env_config.setdefault("server", {})["host"] = host

    port = os.environ.get("SERVER_PORT")
    if port:
        env_config.setdefault("server", {})["port"] = int(port)

    timeout = os.environ.get("NIGHTSCOUT_TIMEOUT_SECONDS")
    if timeout:
        env_config.setdefault("nightscout", {})["timeout_seconds"] = int(timeout)

    jwt_secret = os.environ.get("JWT_SECRET")
    if jwt_secret:
        env_config.setdefault("security", {})["jwt_secret"] = jwt_secret

    jwt_issuer = os.environ.get("JWT_ISSUER")
    if jwt_issuer:
        env_config.setdefault("security", {})["jwt_issuer"] = jwt_issuer

    cors_origins = os.environ.get("CORS_ORIGINS")
    if cors_origins:
        env_config.setdefault("security", {})["cors_origins"] = [
            origin.strip() for origin in cors_origins.split(",") if origin.strip()
        ]

    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        env_config.setdefault("data", {})["data_dir"] = data_dir

    # Vision env vars
    vision_provider = os.environ.get("VISION_PROVIDER")
    if vision_provider:
        env_config.setdefault("vision", {})["provider"] = vision_provider

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        env_config.setdefault("vision", {})["openai_api_key"] = openai_key

    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        env_config.setdefault("vision", {})["google_api_key"] = google_key
    
    vision_max_mb = os.environ.get("VISION_MAX_IMAGE_MB")
    if vision_max_mb:
        env_config.setdefault("vision", {})["max_image_mb"] = int(vision_max_mb)
        
    vision_timeout = os.environ.get("VISION_TIMEOUT_S")
    if vision_timeout:
        env_config.setdefault("vision", {})["timeout_seconds"] = int(vision_timeout)

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        env_config.setdefault("database", {})["url"] = db_url

    # Dexcom Env
    dex_user = os.environ.get("DEXCOM_USERNAME")
    if dex_user:
        d = env_config.setdefault("dexcom", {})
        d["username"] = dex_user
        d["enabled"] = True
    
    dex_pass = os.environ.get("DEXCOM_PASSWORD")
    if dex_pass:
        env_config.setdefault("dexcom", {})["password"] = dex_pass
        
    dex_region = os.environ.get("DEXCOM_REGION")
    if dex_region:
        env_config.setdefault("dexcom", {})["region"] = dex_region

    night_pattern_enabled = os.environ.get("NIGHT_PATTERN_ENABLED")
    if night_pattern_enabled is not None:
        env_config.setdefault("night_pattern", {})["enabled"] = night_pattern_enabled.lower() == "true"

    night_pattern_days = os.environ.get("NIGHT_PATTERN_DAYS")
    if night_pattern_days:
        env_config.setdefault("night_pattern", {})["days"] = int(night_pattern_days)

    night_pattern_bucket = os.environ.get("NIGHT_PATTERN_BUCKET_MIN")
    if night_pattern_bucket:
        env_config.setdefault("night_pattern", {})["bucket_minutes"] = int(night_pattern_bucket)

    night_pattern_horizon = os.environ.get("NIGHT_PATTERN_HORIZON_MIN")
    if night_pattern_horizon:
        env_config.setdefault("night_pattern", {})["horizon_minutes"] = int(night_pattern_horizon)

    night_pattern_weight_a = os.environ.get("NIGHT_PATTERN_WEIGHT_A")
    if night_pattern_weight_a:
        env_config.setdefault("night_pattern", {})["weight_a"] = float(night_pattern_weight_a)

    night_pattern_weight_b = os.environ.get("NIGHT_PATTERN_WEIGHT_B")
    if night_pattern_weight_b:
        env_config.setdefault("night_pattern", {})["weight_b"] = float(night_pattern_weight_b)

    night_pattern_cap = os.environ.get("NIGHT_PATTERN_CAP_MGDL")
    if night_pattern_cap:
        env_config.setdefault("night_pattern", {})["cap_mgdl"] = float(night_pattern_cap)

    night_pattern_window_a_start = os.environ.get("NIGHT_PATTERN_WINDOW_A_START")
    if night_pattern_window_a_start:
        env_config.setdefault("night_pattern", {})["window_a_start"] = night_pattern_window_a_start

    night_pattern_window_a_end = os.environ.get("NIGHT_PATTERN_WINDOW_A_END")
    if night_pattern_window_a_end:
        env_config.setdefault("night_pattern", {})["window_a_end"] = night_pattern_window_a_end

    night_pattern_window_b_start = os.environ.get("NIGHT_PATTERN_WINDOW_B_START")
    if night_pattern_window_b_start:
        env_config.setdefault("night_pattern", {})["window_b_start"] = night_pattern_window_b_start

    night_pattern_window_b_end = os.environ.get("NIGHT_PATTERN_WINDOW_B_END")
    if night_pattern_window_b_end:
        env_config.setdefault("night_pattern", {})["window_b_end"] = night_pattern_window_b_end

    night_pattern_disable_at = os.environ.get("NIGHT_PATTERN_DISABLE_AT")
    if night_pattern_disable_at:
        env_config.setdefault("night_pattern", {})["disable_at"] = night_pattern_disable_at

    night_pattern_meal_lookback = os.environ.get("NIGHT_PATTERN_MEAL_LOOKBACK_H")
    if night_pattern_meal_lookback:
        env_config.setdefault("night_pattern", {})["meal_lookback_h"] = float(night_pattern_meal_lookback)

    night_pattern_bolus_lookback = os.environ.get("NIGHT_PATTERN_BOLUS_LOOKBACK_H")
    if night_pattern_bolus_lookback:
        env_config.setdefault("night_pattern", {})["bolus_lookback_h"] = float(night_pattern_bolus_lookback)

    night_pattern_iob_max = os.environ.get("NIGHT_PATTERN_IOB_MAX_U")
    if night_pattern_iob_max:
        env_config.setdefault("night_pattern", {})["iob_max_u"] = float(night_pattern_iob_max)

    night_pattern_slope_max = os.environ.get("NIGHT_PATTERN_SLOPE_MAX_MGDL_PER_MIN")
    if night_pattern_slope_max:
        env_config.setdefault("night_pattern", {})["slope_max_mgdl_per_min"] = float(night_pattern_slope_max)

    return env_config


def merge_settings(env_config: dict[str, Any], file_config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged["nightscout"] = {**file_config.get("nightscout", {}), **env_config.get("nightscout", {})}
    merged["server"] = {**file_config.get("server", {}), **env_config.get("server", {})}
    merged["security"] = {**file_config.get("security", {}), **env_config.get("security", {})}
    merged["data"] = {**file_config.get("data", {}), **env_config.get("data", {})}
    merged["vision"] = {**file_config.get("vision", {}), **env_config.get("vision", {})}
    merged["database"] = {**file_config.get("database", {}), **env_config.get("database", {})}
    merged["dexcom"] = {**file_config.get("dexcom", {}), **env_config.get("dexcom", {})}
    merged["night_pattern"] = {**file_config.get("night_pattern", {}), **env_config.get("night_pattern", {})}
    return merged


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_config = _load_env()
    file_config = _load_file_config(DEFAULT_CONFIG_PATH)
    merged = merge_settings(env_config=env_config, file_config=file_config)
    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:  # pragma: no cover
        raise RuntimeError(f"Configuration error: {exc}") from exc


__all__ = ["Settings", "get_settings"]
