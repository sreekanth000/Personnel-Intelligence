"""Application settings loaded from environment variables.

Uses pydantic-settings to validate and type-check all configuration.
Defaults are safe for local development.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Immutable, validated application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PI_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Personal Intelligence"
    app_version: str = "0.1.0"
    environment: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Data Paths ---
    data_dir: Path = _PROJECT_ROOT / "data"
    raw_data_dir: Path = _PROJECT_ROOT / "data" / "raw"
    exports_dir: Path = _PROJECT_ROOT / "data" / "exports"
    credentials_dir: Path = _PROJECT_ROOT / "data" / "credentials"

    # --- DuckDB ---
    duckdb_path: Path = _PROJECT_ROOT / "data" / "world_model.duckdb"

    # --- Kuzu ---
    kuzu_path: Path = _PROJECT_ROOT / "data" / "world_model_graph"

    # --- Azure OpenAI / Extraction & Reasoning ---
    azure_ai_endpoint: str = ""
    azure_ai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4.1"
    azure_ai_api_version: str = "2024-12-01-preview"

    # --- Universal LLM Provider Configuration ---
    llm_provider: str = "azure"  # "azure", "openai", "ollama", "groq", "deepseek", "openrouter", "custom"
    llm_model: str = "gpt-4.1"   # Model name or deployment ID
    llm_api_key: str = ""        # API key (fallbacks to provider-specific env vars)
    llm_api_base: str = ""       # Custom Base URL (e.g. http://localhost:11434/v1 for Ollama)
    llm_api_version: str = "2024-12-01-preview"  # Azure API version if applicable


def get_settings() -> Settings:
    """Factory function for settings.  Allows test overrides via env vars."""
    return Settings()
