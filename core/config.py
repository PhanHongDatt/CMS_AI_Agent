from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(str, Enum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = Field(..., description="PostgreSQL connection string")

    # Redis
    redis_url: str = Field(..., description="Redis connection string")

    # LLM Gateway
    llm_gateway_url: str = Field(..., description="Internal LLM Gateway base URL")
    llm_gateway_api_key: str = Field(..., description="LLM Gateway API key")

    # Application
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    # Cost limits (USD)
    cost_limit_per_incident: float = Field(default=1.00, gt=0)
    cost_limit_daily: float = Field(default=20.00, gt=0)

    # Approval timeout
    approval_timeout_seconds: int = Field(default=300, gt=0)

    @field_validator("llm_gateway_api_key")
    @classmethod
    def api_key_not_placeholder(cls, v: str) -> str:
        if v in ("change-me", "placeholder", ""):
            raise ValueError("llm_gateway_api_key must be set to a real value")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
