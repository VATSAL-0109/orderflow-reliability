from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "OrderFlow"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000

    # PostgreSQL Database Pool Configuration
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/orderflow"
    )
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: float = 30.0

    # Downstream Inventory Service Configuration
    INVENTORY_SERVICE_URL: str = "http://localhost:8001"
    INVENTORY_TIMEOUT_SECONDS: float = 5.0


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
