"""Gate G0: Config management tests."""

import pytest
from pydantic import ValidationError


class TestConfig:
    def test_config_rejects_placeholder_api_key(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("LLM_GATEWAY_URL", "http://localhost:8001")
        monkeypatch.setenv("LLM_GATEWAY_API_KEY", "change-me")

        from core.config import Settings
        with pytest.raises((ValidationError, ValueError)):
            Settings()

    def test_config_accepts_valid_values(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("LLM_GATEWAY_URL", "http://localhost:8001")
        monkeypatch.setenv("LLM_GATEWAY_API_KEY", "real-key-abc123")

        from core.config import Settings
        s = Settings()
        assert s.llm_gateway_api_key == "real-key-abc123"
        assert s.cost_limit_per_incident == 1.00
        assert s.cost_limit_daily == 20.00

    def test_config_missing_required_field(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
        monkeypatch.delenv("LLM_GATEWAY_API_KEY", raising=False)

        from core.config import Settings
        with pytest.raises((ValidationError, ValueError)):
            Settings()

    def test_production_flag(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("LLM_GATEWAY_URL", "http://localhost:8001")
        monkeypatch.setenv("LLM_GATEWAY_API_KEY", "real-key-abc123")
        monkeypatch.setenv("APP_ENV", "production")

        from core.config import Settings
        s = Settings()
        assert s.is_production is True
