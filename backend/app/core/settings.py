import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError


class NightscoutConfig(BaseModel):
    base_url: HttpUrl
    api_secret: Optional[str] = Field(default=None)
    token: Optional[str] = Field(default=None)
    timeout_seconds: int = Field(default=10, ge=1)


class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)


class Settings(BaseModel):
    nightscout: NightscoutConfig
    server: ServerConfig


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

    base_url = os.environ.get("NIGHTSCOUT_BASE_URL")
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

    return env_config


def merge_settings(env_config: dict[str, Any], file_config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged["nightscout"] = {**file_config.get("nightscout", {}), **env_config.get("nightscout", {})}
    merged["server"] = {**file_config.get("server", {}), **env_config.get("server", {})}
    return merged


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_config = _load_env()
    file_config = _load_file_config(DEFAULT_CONFIG_PATH)
    merged = merge_settings(env_config=env_config, file_config=file_config)
    try:
        return Settings.parse_obj(merged)
    except ValidationError as exc:  # pragma: no cover - configuration errors during startup
        raise RuntimeError(f"Configuration error: {exc}") from exc


__all__ = ["Settings", "get_settings"]
