"""Shared pytest fixtures for the Personal Intelligence test suite.

Fixtures provide:
- Isolated temp directories for database files (no test pollution)
- Pre-configured Settings with test overrides
- DuckDB and Kuzu store instances connected to temp paths
- A FastAPI TestClient wired to the full app
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.persistence.duckdb_store import DuckDBStore
from app.persistence.kuzu_store import KuzuStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Return a temporary data directory for a single test."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture()
def test_settings(tmp_data_dir: Path) -> Settings:
    """Return Settings pointing at temporary paths so tests never touch real data."""
    return Settings(
        environment="testing",
        debug=True,
        log_level="DEBUG",
        data_dir=tmp_data_dir,
        raw_data_dir=tmp_data_dir / "raw",
        exports_dir=tmp_data_dir / "exports",
        duckdb_path=tmp_data_dir / "test.duckdb",
        kuzu_path=tmp_data_dir / "test_graph",
    )


@pytest.fixture()
def duckdb_store(test_settings: Settings) -> Iterator[DuckDBStore]:
    """Provide a connected DuckDBStore against a temp database."""
    store = DuckDBStore(test_settings.duckdb_path)
    store.connect()
    yield store
    store.close()


@pytest.fixture()
def kuzu_store(test_settings: Settings) -> Iterator[KuzuStore]:
    """Provide a connected KuzuStore against a temp database."""
    store = KuzuStore(test_settings.kuzu_path)
    store.connect()
    yield store
    store.close()


@pytest.fixture()
def client(
    test_settings: Settings, tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Provide a FastAPI TestClient with all databases pointed at temp paths.

    Uses monkeypatch to override settings so the app lifespan
    initializes against temporary databases.
    """
    monkeypatch.setenv("PI_ENVIRONMENT", "testing")
    monkeypatch.setenv("PI_DEBUG", "true")
    monkeypatch.setenv("PI_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PI_DATA_DIR", str(tmp_data_dir))
    monkeypatch.setenv("PI_RAW_DATA_DIR", str(tmp_data_dir / "raw"))
    monkeypatch.setenv("PI_EXPORTS_DIR", str(tmp_data_dir / "exports"))
    monkeypatch.setenv("PI_DUCKDB_PATH", str(tmp_data_dir / "test.duckdb"))
    monkeypatch.setenv("PI_KUZU_PATH", str(tmp_data_dir / "test_graph"))

    from app.main import create_app

    app = create_app()
    with TestClient(app) as tc:
        yield tc
