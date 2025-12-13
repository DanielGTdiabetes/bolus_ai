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


class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)


class SecurityConfig(BaseModel):
    jwt_secret: str = Field(min_length=16)
    jwt_issuer: str = Field(default="bolus-ai")
    access_token_minutes: int = Field(default=15, ge=5, le=120)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    cors_origins: list[str] = Field(default_factory=list)


class DataConfig(BaseModel):
    data_dir: Path = Field(default=Path("backend/data"))

    @field_validator("data_dir", mode="before")
    def _expand_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser()


class Settings(BaseModel):
    nightscout: NightscoutConfig
    server: ServerConfig
    security: SecurityConfig
    data: DataConfig

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

    return env_config


def merge_settings(env_config: dict[str, Any], file_config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged["nightscout"] = {**file_config.get("nightscout", {}), **env_config.get("nightscout", {})}
    merged["server"] = {**file_config.get("server", {}), **env_config.get("server", {})}
    merged["security"] = {**file_config.get("security", {}), **env_config.get("security", {})}
    merged["data"] = {**file_config.get("data", {}), **env_config.get("data", {})}
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
