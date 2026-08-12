"""Tests for application configuration and settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.config.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path


class TestSettings:
    """Test suite for the Settings configuration class."""

    def test_default_settings_are_valid(self) -> None:
        """Settings should instantiate with safe defaults."""
        settings = Settings()
        assert settings.app_name == "Personal Intelligence"
        assert settings.app_version == "0.1.0"
        assert settings.environment == "development"
        assert settings.debug is False

    def test_environment_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables with PI_ prefix should override defaults."""
        monkeypatch.setenv("PI_ENVIRONMENT", "testing")
        monkeypatch.setenv("PI_DEBUG", "true")
        settings = Settings()
        assert settings.environment == "testing"
        assert settings.debug is True

    def test_data_paths_are_absolute(self) -> None:
        """Data directory paths should be absolute."""
        settings = Settings()
        assert settings.data_dir.is_absolute()
        assert settings.duckdb_path.is_absolute()
        assert settings.kuzu_path.is_absolute()

    def test_custom_paths(self, tmp_path: Path) -> None:
        """Settings should accept custom paths."""
        custom_db = tmp_path / "custom.duckdb"
        settings = Settings(duckdb_path=custom_db)
        assert settings.duckdb_path == custom_db

    def test_invalid_environment_rejected(self) -> None:
        """Invalid environment values should raise a validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(environment="staging")  # type: ignore[arg-type]
