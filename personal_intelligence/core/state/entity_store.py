"""
Local SQLite Entity State Store for Personal Intelligence.
Tracks multi-dimensional state across entities (e.g. people, topics, projects, devices, activities).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.core.world.graph import validate_and_normalize_entity_type
from personal_intelligence.storage.db import DatabaseManager


@dataclass
class EntityState:
    """Represents the tracked state of a specific entity in Personal Intelligence."""
    entity_id: str
    entity_type: str
    state: Dict[str, Any]
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_event_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.entity_type = validate_and_normalize_entity_type(self.entity_type)
        self.last_updated_at = ensure_timezone_aware(self.last_updated_at, "last_updated_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "state": self.state,
            "last_updated_at": format_iso8601(self.last_updated_at),
            "source_event_ids": self.source_event_ids,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityState":
        return cls(
            entity_id=data["entity_id"],
            entity_type=data["entity_type"],
            state=data.get("state", {}),
            last_updated_at=ensure_timezone_aware(data.get("last_updated_at", datetime.now(timezone.utc)), "last_updated_at"),
            source_event_ids=data.get("source_event_ids", []),
            metadata=data.get("metadata", {}),
        )


class EntityStateStore:
    """
    SQLite-backed store for entity_state table.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _row_to_entity(self, row: sqlite3.Row) -> EntityState:
        state_dict = json.loads(row["state_json"]) if row["state_json"] else {}
        events = json.loads(row["source_event_ids_json"]) if row["source_event_ids_json"] else []
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

        return EntityState(
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            state=state_dict,
            last_updated_at=ensure_timezone_aware(row["last_updated_at"], "last_updated_at"),
            source_event_ids=events,
            metadata=meta,
        )

    def upsert(self, entity: EntityState) -> EntityState:
        """Inserts or updates an entity state record."""
        updated_at_iso = format_iso8601(entity.last_updated_at)
        state_json = json.dumps(entity.state, ensure_ascii=False)
        events_json = json.dumps(entity.source_event_ids)
        meta_json = json.dumps(entity.metadata)

        query = """
            INSERT INTO entity_state (
                entity_id, entity_type, state_json, last_updated_at,
                source_event_ids_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                entity_type = excluded.entity_type,
                state_json = excluded.state_json,
                last_updated_at = excluded.last_updated_at,
                source_event_ids_json = excluded.source_event_ids_json,
                metadata_json = excluded.metadata_json;
        """
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, (
                    entity.entity_id,
                    entity.entity_type,
                    state_json,
                    updated_at_iso,
                    events_json,
                    meta_json,
                ))
            return entity
        finally:
            conn.close()

    def get(self, entity_id: str) -> Optional[EntityState]:
        """Retrieves an entity state by entity_id."""
        query = "SELECT * FROM entity_state WHERE entity_id = ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (entity_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_entity(row)
            return None
        finally:
            conn.close()

    def list(self, entity_type: Optional[str] = None, limit: int = 100) -> List[EntityState]:
        """Lists entity states, optionally filtered by entity_type."""
        if entity_type:
            return self.list_by_type(entity_type, limit=limit)
        query = "SELECT * FROM entity_state ORDER BY last_updated_at DESC LIMIT ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            return [self._row_to_entity(r) for r in rows]
        finally:
            conn.close()

    def list_by_type(self, entity_type: str, limit: int = 100) -> List[EntityState]:
        """Lists entity states for a specific entity type."""
        query = "SELECT * FROM entity_state WHERE entity_type = ? ORDER BY last_updated_at DESC LIMIT ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (entity_type, limit))
            rows = cursor.fetchall()
            return [self._row_to_entity(r) for r in rows]
        finally:
            conn.close()

    def delete(self, entity_id: str) -> bool:
        """Deletes an entity state record."""
        query = "DELETE FROM entity_state WHERE entity_id = ?;"
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(query, (entity_id,))
                return cursor.rowcount > 0
        finally:
            conn.close()

    def count(self) -> int:
        """Counts the total entity state records."""
        query = "SELECT COUNT(*) as cnt FROM entity_state;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            conn.close()
