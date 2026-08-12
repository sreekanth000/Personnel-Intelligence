"""SQLite Persistence Layer for Gmail Sync State.

Manages persistent synchronization cursors, synced message deduplication indices,
and sync run logs using SQLite (data/gmail_sync_state.db).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config.logging import get_logger

logger = get_logger(__name__)


class SyncState(BaseModel):
    """Data model for SQLite sync state cursor."""

    last_history_id: str | None = Field(default=None, description="Gmail historyId marker.")
    last_sync_timestamp: str | None = Field(default=None, description="ISO timestamp of last sync.")
    total_messages_synced: int = Field(default=0, description="Cumulative count of messages synced.")
    initial_sync_completed: bool = Field(default=False, description="True if initial 10,000 email sync finished.")
    initial_sync_max_limit: int = Field(default=10000, description="Max emails for initial deployment sync.")
    updated_at: str | None = Field(default=None, description="ISO timestamp when cursor was updated.")


class SQLiteSyncStore:
    """SQLite manager for persistent sync state and message deduplication."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent / "data" / "gmail_sync_state.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get an isolated sqlite3 connection with WAL mode enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database tables if they do not exist."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_history_id TEXT,
                    last_sync_timestamp TEXT,
                    total_messages_synced INTEGER DEFAULT 0,
                    initial_sync_completed INTEGER DEFAULT 0,
                    initial_sync_max_limit INTEGER DEFAULT 10000,
                    updated_at TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS synced_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    history_id TEXT,
                    status TEXT DEFAULT 'synced',
                    synced_at TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT,
                    processed_count INTEGER DEFAULT 0,
                    new_observations_count INTEGER DEFAULT 0,
                    duplicate_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    error_message TEXT,
                    started_at TEXT,
                    completed_at TEXT
                )
            """)

            # Ensure row 1 exists in sync_state
            conn.execute("""
                INSERT OR IGNORE INTO sync_state (id, total_messages_synced, initial_sync_completed, initial_sync_max_limit, updated_at)
                VALUES (1, 0, 0, 10000, ?)
            """, (datetime.now(UTC).isoformat(),))

        # Check for legacy JSON cursor and migrate
        self._migrate_legacy_json_cursor()

    def _migrate_legacy_json_cursor(self) -> None:
        """Migrate legacy data/gmail_sync_cursor.json into SQLite if present."""
        json_path = self.db_path.parent / "gmail_sync_cursor.json"
        if not json_path.exists():
            return

        try:
            content = json_path.read_text(encoding="utf-8")
            data = json.loads(content)
            last_history_id = data.get("last_history_id")
            last_sync_timestamp = data.get("last_sync_timestamp")
            total_messages_synced = data.get("total_messages_synced", 0)

            if last_history_id or total_messages_synced > 0:
                with self._get_connection() as conn:
                    conn.execute("""
                        UPDATE sync_state
                        SET last_history_id = COALESCE(?, last_history_id),
                            last_sync_timestamp = COALESCE(?, last_sync_timestamp),
                            total_messages_synced = MAX(total_messages_synced, ?),
                            initial_sync_completed = 1,
                            updated_at = ?
                        WHERE id = 1
                    """, (
                        last_history_id,
                        last_sync_timestamp,
                        total_messages_synced,
                        datetime.now(UTC).isoformat(),
                    ))
                logger.info(
                    "sqlite_sync.legacy_cursor_migrated",
                    history_id=last_history_id,
                    total_synced=total_messages_synced,
                )
        except Exception as e:
            logger.warning("sqlite_sync.migration_failed", error=str(e))

    def get_sync_state(self) -> SyncState:
        """Retrieve current sync state cursor."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
            if not row:
                return SyncState()
            return SyncState(
                last_history_id=row["last_history_id"],
                last_sync_timestamp=row["last_sync_timestamp"],
                total_messages_synced=row["total_messages_synced"] or 0,
                initial_sync_completed=bool(row["initial_sync_completed"]),
                initial_sync_max_limit=row["initial_sync_max_limit"] or 10000,
                updated_at=row["updated_at"],
            )

    def update_sync_state(
        self,
        last_history_id: str | None = None,
        last_sync_timestamp: str | None = None,
        increment_synced_count: int = 0,
        initial_sync_completed: bool | None = None,
    ) -> SyncState:
        """Atomic update of the sync cursor state."""
        now_iso = datetime.now(UTC).isoformat()
        current = self.get_sync_state()

        new_history_id = last_history_id if last_history_id is not None else current.last_history_id
        new_timestamp = last_sync_timestamp if last_sync_timestamp is not None else (current.last_sync_timestamp or now_iso)
        new_total = current.total_messages_synced + increment_synced_count
        new_completed = initial_sync_completed if initial_sync_completed is not None else current.initial_sync_completed

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE sync_state
                SET last_history_id = ?,
                    last_sync_timestamp = ?,
                    total_messages_synced = ?,
                    initial_sync_completed = ?,
                    updated_at = ?
                WHERE id = 1
            """, (
                new_history_id,
                new_timestamp,
                new_total,
                1 if new_completed else 0,
                now_iso,
            ))

        return SyncState(
            last_history_id=new_history_id,
            last_sync_timestamp=new_timestamp,
            total_messages_synced=new_total,
            initial_sync_completed=new_completed,
            initial_sync_max_limit=current.initial_sync_max_limit,
            updated_at=now_iso,
        )

    def is_message_synced(self, message_id: str) -> bool:
        """Check if a message ID has already been recorded in SQLite."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM synced_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            return row is not None

    def record_synced_message(
        self,
        message_id: str,
        thread_id: str | None = None,
        history_id: str | None = None,
        status: str = "synced",
    ) -> None:
        """Record a message ID into synced_messages index."""
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO synced_messages (message_id, thread_id, history_id, status, synced_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    synced_at = EXCLUDED.synced_at
            """, (message_id, thread_id, history_id, status, now_iso))

    def log_sync_run(
        self,
        sync_type: str,
        processed_count: int,
        new_observations_count: int,
        duplicate_count: int,
        status: str = "completed",
        error_message: str | None = None,
        started_at: str | None = None,
    ) -> int:
        """Log a summary of a sync execution run."""
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO sync_runs (
                    sync_type, processed_count, new_observations_count,
                    duplicate_count, status, error_message, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sync_type,
                processed_count,
                new_observations_count,
                duplicate_count,
                status,
                error_message,
                started_at or now_iso,
                now_iso,
            ))
            return cursor.lastrowid or 0
