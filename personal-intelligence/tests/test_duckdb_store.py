"""Tests for DuckDB persistence layer."""

from __future__ import annotations

from app.persistence.duckdb_store import DuckDBStore


class TestDuckDBStore:
    """Test suite for DuckDB connection and schema management."""

    def test_connect_creates_database(self, duckdb_store: DuckDBStore) -> None:
        """Connecting should create the database file and initialize schema."""
        assert duckdb_store.is_healthy()

    def test_schema_version_is_set(self, duckdb_store: DuckDBStore) -> None:
        """Schema version should be stamped in the _metadata table."""
        result = duckdb_store.connection.execute(
            "SELECT value FROM _metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert result is not None
        assert result[0] == "0.1.0"

    def test_health_check_returns_true_when_connected(self, duckdb_store: DuckDBStore) -> None:
        """Health check should return True for a properly initialized store."""
        assert duckdb_store.is_healthy() is True

    def test_health_check_returns_false_when_closed(self, duckdb_store: DuckDBStore) -> None:
        """Health check should return False after closing."""
        duckdb_store.close()
        assert duckdb_store.is_healthy() is False

    def test_close_is_idempotent(self, duckdb_store: DuckDBStore) -> None:
        """Calling close() multiple times should not raise."""
        duckdb_store.close()
        duckdb_store.close()  # Should not raise

    def test_connection_property_raises_when_not_connected(self, tmp_data_dir: None) -> None:
        """Accessing .connection before connect() should raise RuntimeError."""
        from pathlib import Path

        import pytest

        store = DuckDBStore(Path("nonexistent.duckdb"))
        with pytest.raises(RuntimeError, match="not connected"):
            _ = store.connection
