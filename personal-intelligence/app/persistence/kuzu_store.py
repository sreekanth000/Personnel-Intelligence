"""Kuzu graph database initialization and connection management.

Kuzu is the graph persistence layer for the personal world model.
It stores the entity-relationship graph for traversal queries,
context assembly, and reconciliation.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Generator

import kuzu

from app.config.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


class KuzuStore:
    """Manages the Kuzu graph database lifecycle and schema initialization."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        # Kuzu creates the database directory itself; we only ensure the parent exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: kuzu.Database | None = None
        self._conn: kuzu.Connection | None = None
        self._is_closed: bool = False

    def connect(self) -> None:
        """Open a persistent Kuzu database connection and initialize schema."""
        if self._conn is None:
            self._db = kuzu.Database(str(self._db_path))
            self._conn = kuzu.Connection(self._db)
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
        if self._db is not None:
            del self._db
            self._db = None
        self._is_closed = True

    @property
    def connection(self) -> kuzu.Connection:
        """Return the active persistent connection or raise RuntimeError."""
        if self._conn is None or self._is_closed:
            raise RuntimeError("KuzuStore is not connected. Call connect() first.")
        return self._conn

    @contextlib.contextmanager
    def get_connection(self) -> Generator[kuzu.Connection, None, None]:
        """Context manager for acquiring a connection (ephemeral or persistent)."""
        if self._conn is not None and not self._is_closed:
            yield self._conn
            return

        max_retries = 10
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                db = kuzu.Database(str(self._db_path))
                conn = kuzu.Connection(db)
                try:
                    yield conn
                finally:
                    conn.close()
                    del db 
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug("kuzu.lock_retry", attempt=attempt, delay=retry_delay, error=str(e))
                    time.sleep(retry_delay)
                else:
                    raise

    def init_schema(self) -> None:
        """Create core node/relationship tables if they do not already exist."""
        logger.info("kuzu.initializing_schema", path=str(self._db_path))
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    CREATE NODE TABLE IF NOT EXISTS Metadata (
                        key STRING,
                        value STRING,
                        PRIMARY KEY (key)
                    )
                """)

                conn.execute("""
                    CREATE NODE TABLE IF NOT EXISTS Entity (
                        id STRING,
                        type STRING,
                        name STRING,
                        PRIMARY KEY (id)
                    )
                """)

                conn.execute("""
                    CREATE REL TABLE IF NOT EXISTS Edge (
                        FROM Entity TO Entity,
                        predicate STRING,
                        id STRING
                    )
                """)

                # Upsert schema version
                conn.execute("""
                    MERGE (m:Metadata {key: 'schema_version'})
                    SET m.value = '0.1.0'
                """)

            logger.info("kuzu.schema_initialized", schema_version="0.1.0")
        except Exception:
            logger.exception("kuzu.schema_init_failed")
            raise

    def is_healthy(self) -> bool:
        """Return True if the graph database is reachable and schema is initialized."""
        if self._is_closed:
            return False
        try:
            with self.get_connection() as conn:
                result = conn.execute(
                    "MATCH (m:Metadata {key: 'schema_version'}) RETURN m.value"
                )
                if isinstance(result, list):
                    return len(result) > 0
                return result.has_next()
        except Exception:
            logger.exception("kuzu.health_check_failed")
            return False

