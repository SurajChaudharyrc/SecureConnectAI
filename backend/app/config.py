from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field("dev", description="dev | prod")
    app_secret: str = Field(
        "dev-only-secret-change-me-please-this-is-32-chars",
        min_length=32,
    )
    database_url: str = "sqlite:///./secureconnect.db"
    allowed_origin: str = "http://localhost:8000"

    session_ttl_hours: int = Field(24, ge=1, le=24 * 30)
    otp_ttl_minutes: int = Field(10, ge=1, le=60)
    max_upload_bytes: int = Field(8 * 1024 * 1024, ge=64 * 1024)
    deepface_enabled: bool = True
    log_level: str = "INFO"

    # Chat
    chat_broker: str = "memory"  # 'memory' | (future) 'redis'
    chat_max_message_len: int = Field(2000, ge=1, le=10_000)
    chat_send_rate_max: int = Field(5, ge=1)  # max sends per window per connection
    chat_send_rate_window_s: float = Field(2.0, gt=0)
    chat_frame_rate_max: int = Field(30, ge=1)  # max ANY inbound frames per window
    chat_frame_rate_window_s: float = Field(5.0, gt=0)
    chat_max_connections_per_group: int = Field(200, ge=1)
    chat_max_connections_per_user: int = Field(5, ge=1)  # caps the per-socket limiter bypass

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
