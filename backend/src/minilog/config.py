from functools import lru_cache

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINILOG_", env_file=".env", extra="ignore")

    app_name: str = "Minilog"
    database_url: str = "sqlite:///./data/minilog.db"
    public_origin: HttpUrl = HttpUrl("http://localhost:8080")
    setup_token: str = Field(default="", min_length=0)
    time_zone: str = "UTC"
    secure_cookies: bool = False
    session_days: int = Field(default=30, ge=1, le=365)
    invitation_hours: int = Field(default=24, ge=1, le=168)
    sync_tombstone_days: int = Field(default=30, ge=7, le=365)
    max_import_bytes: int = Field(default=10_000_000, ge=100_000)
    max_profile_picture_bytes: int = Field(default=8_000_000, ge=100_000)
    max_profile_picture_pixels: int = Field(default=16_000_000, ge=65_536)
    login_attempt_limit: int = Field(default=8, ge=3, le=100)
    login_attempt_window_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator("setup_token")
    @classmethod
    def validate_setup_token(cls, value: str) -> str:
        if value and len(value) < 20:
            raise ValueError("setup token must be at least 20 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


async def get_settings_dependency() -> Settings:
    return get_settings()
