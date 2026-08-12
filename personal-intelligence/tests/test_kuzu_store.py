"""Tests for Kuzu graph database persistence layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.persistence.kuzu_store import KuzuStore

if TYPE_CHECKING:
    from pathlib import Path


class TestKuzuStore:
    """Test suite for Kuzu connection and schema management."""

    def test_connect_creates_database(self, kuzu_store: KuzuStore) -> None:
        """Connecting should create the database directory and initialize schema."""
        assert kuzu_store.is_healthy()

    def test_schema_version_is_set(self, kuzu_store: KuzuStore) -> None:
        """Schema version should be stored in the Metadata node."""
        result = kuzu_store.connection.execute(
            "MATCH (m:Metadata {key: 'schema_version'}) RETURN m.value"
        )
        assert result.has_next()
        row = result.get_next()
        assert row[0] == "0.1.0"

    def test_health_check_returns_true_when_connected(self, kuzu_store: KuzuStore) -> None:
        """Health check should return True for a properly initialized store."""
        assert kuzu_store.is_healthy() is True

    def test_health_check_returns_false_when_closed(self, kuzu_store: KuzuStore) -> None:
        """Health check should return False after closing."""
        kuzu_store.close()
        assert kuzu_store.is_healthy() is False

    def test_close_is_idempotent(self, kuzu_store: KuzuStore) -> None:
        """Calling close() multiple times should not raise."""
        kuzu_store.close()
        kuzu_store.close()  # Should not raise

    def test_connection_property_raises_when_not_connected(self, tmp_path: Path) -> None:
        """Accessing .connection before connect() should raise RuntimeError."""
        import pytest

        store = KuzuStore(tmp_path / "nonexistent_kuzu_db")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = store.connection
