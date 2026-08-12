"""DuckDB initialization and connection management.

DuckDB is the structured persistence layer for the personal world model.
It stores entities, relationships, evidence, and claims as relational tables.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Generator

import duckdb

from app.config.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


class DuckDBStore:
    """Manages the DuckDB connection lifecycle and schema initialization."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._is_closed: bool = False

    def connect(self) -> None:
        """Open a persistent DuckDB connection and initialize schema."""
        if self._conn is None:
            self._conn = duckdb.connect(str(self._db_path))
            self._is_closed = False
            self.init_schema()

    def close(self) -> None:
        """Close the persistent connection if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._is_closed = True

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the active persistent connection or raise RuntimeError."""
        if self._conn is None or self._is_closed:
            raise RuntimeError("DuckDBStore is not connected. Call connect() first.")
        return self._conn

    @contextlib.contextmanager
    def get_connection(
        self, read_only: bool = False
    ) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Context manager for acquiring a DuckDB connection with lock-retry logic."""
        max_retries = 10
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                conn = duckdb.connect(str(self._db_path), read_only=read_only)
                try:
                    yield conn
                finally:
                    conn.close()
                return
            except (duckdb.ConnectionException, duckdb.IOException) as e:
                if read_only:
                    # Fallback to standard connection if read_only fails due to existing connection config or file lock
                    try:
                        conn = duckdb.connect(str(self._db_path))
                        try:
                            yield conn
                        finally:
                            conn.close()
                        return
                    except Exception:
                        pass
                if attempt < max_retries - 1:
                    logger.debug("duckdb.lock_retry", attempt=attempt, delay=retry_delay)
                    time.sleep(retry_delay)
                else:
                    raise

    def init_schema(self) -> None:
        """Create core tables if they do not already exist."""
        logger.info("duckdb.initializing_schema", path=str(self._db_path))
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _metadata (
                    key VARCHAR PRIMARY KEY,
                    value VARCHAR NOT NULL,
                    updated_at TIMESTAMP DEFAULT (NOW())
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id VARCHAR PRIMARY KEY,
                    type VARCHAR,
                    data JSON,
                    created_at TIMESTAMP DEFAULT (NOW())
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    id VARCHAR PRIMARY KEY,
                    subject VARCHAR,
                    predicate VARCHAR,
                    object VARCHAR,
                    data JSON,
                    created_at TIMESTAMP DEFAULT (NOW())
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state_changes (
                    id VARCHAR PRIMARY KEY,
                    entity_id VARCHAR,
                    observation_id VARCHAR,
                    data JSON,
                    created_at TIMESTAMP DEFAULT (NOW())
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    id VARCHAR PRIMARY KEY,
                    target_id VARCHAR,
                    target_type VARCHAR,
                    data JSON,
                    created_at TIMESTAMP DEFAULT (NOW())
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    id VARCHAR PRIMARY KEY,
                    subject VARCHAR,
                    predicate VARCHAR,
                    value VARCHAR,
                    status VARCHAR,
                    data JSON,
                    created_at TIMESTAMP DEFAULT (NOW())
                )
            """)

            # Stamp the schema version
            conn.execute("""
                INSERT INTO _metadata (key, value)
                VALUES ('schema_version', '0.1.0')
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = NOW()
            """)
        logger.info("duckdb.schema_initialized", schema_version="0.1.0")

    def is_healthy(self) -> bool:
        """Return True if the database is reachable and schema is initialized."""
        if self._is_closed:
            return False
        try:
            with self.get_connection() as conn:
                result = conn.execute(
                    "SELECT value FROM _metadata WHERE key = 'schema_version'"
                ).fetchone()
                return result is not None
        except Exception:
            logger.exception("duckdb.health_check_failed")
            return False

