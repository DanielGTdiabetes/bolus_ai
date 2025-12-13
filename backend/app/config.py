import os
from functools import lru_cache
from pydantic import BaseSettings, AnyUrl, Field, ValidationError


class Settings(BaseSettings):
    jwt_secret: str = Field(..., env="JWT_SECRET")
    jwt_issuer: str = Field("bolus-ai", env="JWT_ISSUER")
    nightscout_url: AnyUrl | None = Field(None, env="NIGHTSCOUT_URL")
    data_dir: str = Field("backend/data", env="DATA_DIR")
    cors_origins: str = Field("*", env="CORS_ORIGINS")

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError("Missing required configuration: JWT_SECRET") from exc
