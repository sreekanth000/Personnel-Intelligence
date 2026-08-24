"""
Local-first EventStore for append-only generic event logging and querying.
"""

from datetime import datetime
import json
import sqlite3
from typing import List, Optional, Union

from personal_intelligence.core.events.exceptions import (
    DuplicateEventError,
    EventValidationError,
)
from personal_intelligence.core.events.models import (
    Event,
    EventBatch,
    ensure_timezone_aware,
    format_iso8601,
    serialize_payload,
)
from personal_intelligence.storage.db import DatabaseManager


class EventStore:
    """
    Append-only SQLite event store for generic personal events.
    Contains zero domain-specific assumptions (no health, sleep, travel, etc.).
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """Converts an SQLite row into a validated Event object."""
        try:
            payload = json.loads(row["payload_json"])
        except Exception as e:
            raise EventValidationError(f"Failed to deserialize payload_json for event {row['id']}: {e}")

        source_id = row["source_id"] if "source_id" in row.keys() else None
        provenance_json = row["provenance_json"] if "provenance_json" in row.keys() else None
        provenance = json.loads(provenance_json) if provenance_json else None

        return Event(
            id=row["id"],
            event_time=ensure_timezone_aware(row["event_time"], "event_time"),
            ingested_at=ensure_timezone_aware(row["ingested_at"], "ingested_at"),
            event_type=row["event_type"],
            source=row["source"],
            subject_id=row["subject_id"],
            payload=payload,
            confidence=float(row["confidence"]),
            event_hash=row["event_hash"],
            source_id=source_id,
            provenance=provenance,
        )

    def append(self, event: Event) -> Event:
        """
        Appends an event to the append-only event_log table.
        Enforces validation and raises DuplicateEventError if event_hash already exists.
        """
        if not isinstance(event, Event):
            raise EventValidationError(f"Expected Event instance, got {type(event).__name__}")

        event.validate()

        event_time_iso = format_iso8601(event.event_time)
        ingested_at_iso = format_iso8601(event.ingested_at)
        payload_json = serialize_payload(event.payload)
        provenance_json = json.dumps(event.provenance) if event.provenance is not None else None

        query = """
            INSERT INTO event_log (
                id, event_time, ingested_at, event_type, source,
                subject_id, source_id, provenance_json, payload_json, confidence, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            event.id,
            event_time_iso,
            ingested_at_iso,
            event.event_type,
            event.source,
            event.subject_id,
            event.source_id,
            provenance_json,
            payload_json,
            event.confidence,
            event.event_hash,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return event
        except sqlite3.IntegrityError as e:
            err_msg = str(e)
            if "event_hash" in err_msg or "UNIQUE constraint failed: event_log.event_hash" in err_msg:
                raise DuplicateEventError(event.event_hash)
            elif "id" in err_msg or "UNIQUE constraint failed: event_log.id" in err_msg:
                raise DuplicateEventError(event.id, message=f"Event with id '{event.id}' already exists.")
            raise EventValidationError(f"Database integrity error: {e}")
        finally:
            conn.close()

    def append_batch(self, batch: EventBatch, ignore_duplicates: bool = True) -> List[Event]:
        """
        Appends a batch of events to the event store.
        If ignore_duplicates is True, duplicate events are silently skipped for idempotency.
        """
        inserted: List[Event] = []
        for event in batch.events:
            try:
                self.append(event)
                inserted.append(event)
            except DuplicateEventError:
                if not ignore_duplicates:
                    raise
        return inserted

    def get(self, event_id: str) -> Optional[Event]:
        """Retrieves a single event by its unique ID, or None if not found."""
        if not event_id or not isinstance(event_id, str):
            return None

        query = "SELECT * FROM event_log WHERE id = ? LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (event_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_event(row)
            return None
        finally:
            conn.close()

    def get_by_id(self, event_id: str) -> Optional[Event]:
        """Alias for get(event_id)."""
        return self.get(event_id)

    def get_by_source_id(self, source: str, source_id: str) -> Optional[Event]:
        """Retrieves a single event matching the given source and external source_id."""
        if not source or not source_id:
            return None

        query = "SELECT * FROM event_log WHERE source = ? AND source_id = ? ORDER BY event_time DESC LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (source.strip().lower(), str(source_id).strip()))
            row = cursor.fetchone()
            if row:
                return self._row_to_event(row)
            return None
        finally:
            conn.close()


    def query_by_time(
        self,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        limit: int = 100,
        order: str = "asc",
    ) -> List[Event]:
        """Queries events within a given time range."""
        clauses = []
        params = []

        if start_time is not None:
            st = ensure_timezone_aware(start_time, "start_time")
            clauses.append("event_time >= ?")
            params.append(format_iso8601(st))

        if end_time is not None:
            et = ensure_timezone_aware(end_time, "end_time")
            clauses.append("event_time <= ?")
            params.append(format_iso8601(et))

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        query = f"SELECT * FROM event_log {where_stmt} ORDER BY event_time {order_dir}, ingested_at {order_dir} LIMIT ?;"
        params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def get_recent(self, limit: int = 100) -> List[Event]:
        """Returns the most recent events ordered newest to oldest."""
        return self.query_by_time(limit=limit, order="desc")

    def query_by_type(
        self,
        event_type: str,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        limit: int = 100,
        order: str = "asc",
    ) -> List[Event]:
        """Queries events filtered by event_type and optional time bounds."""
        if not event_type or not isinstance(event_type, str):
            raise EventValidationError("event_type must be a non-empty string.")

        clauses = ["event_type = ?"]
        params = [event_type]

        if start_time is not None:
            st = ensure_timezone_aware(start_time, "start_time")
            clauses.append("event_time >= ?")
            params.append(format_iso8601(st))

        if end_time is not None:
            et = ensure_timezone_aware(end_time, "end_time")
            clauses.append("event_time <= ?")
            params.append(format_iso8601(et))

        where_stmt = f"WHERE {' AND '.join(clauses)}"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        query = f"SELECT * FROM event_log {where_stmt} ORDER BY event_time {order_dir}, ingested_at {order_dir} LIMIT ?;"
        params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def query_by_subject(
        self,
        subject_id: str,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        limit: int = 100,
        order: str = "asc",
    ) -> List[Event]:
        """Queries events filtered by subject_id and optional time bounds."""
        if not isinstance(subject_id, str):
            raise EventValidationError("subject_id must be a string.")

        clauses = ["subject_id = ?"]
        params = [subject_id]

        if start_time is not None:
            st = ensure_timezone_aware(start_time, "start_time")
            clauses.append("event_time >= ?")
            params.append(format_iso8601(st))

        if end_time is not None:
            et = ensure_timezone_aware(end_time, "end_time")
            clauses.append("event_time <= ?")
            params.append(format_iso8601(et))

        where_stmt = f"WHERE {' AND '.join(clauses)}"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        query = f"SELECT * FROM event_log {where_stmt} ORDER BY event_time {order_dir}, ingested_at {order_dir} LIMIT ?;"
        params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def recent(self, limit: int = 50) -> List[Event]:
        """Retrieves the most recently observed events ordered by event_time descending."""
        query = "SELECT * FROM event_log ORDER BY event_time DESC, ingested_at DESC LIMIT ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def count(
        self,
        event_type: Optional[str] = None,
        subject_id: Optional[str] = None,
    ) -> int:
        """Returns the count of events matching optional event_type and subject_id filters."""
        clauses = []
        params = []

        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)

        if subject_id is not None:
            clauses.append("subject_id = ?")
            params.append(subject_id)

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT COUNT(*) as total FROM event_log {where_stmt};"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            return int(row["total"]) if row else 0
        finally:
            conn.close()

    def delete_event(self, event_id: str) -> bool:
        """
        Deletes a single event by its ID.
        Returns True if the event was found and deleted, False otherwise.
        """
        if not event_id:
            return False

        query = "DELETE FROM event_log WHERE id = ?;"
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(query, (event_id,))
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_by_source(self, source: str) -> int:
        """
        Deletes all events originating from a specified source (e.g. 'oura_ring', 'gps_telemetry').
        Returns the count of deleted events.
        """
        if not source:
            return 0

        query = "DELETE FROM event_log WHERE source = ?;"
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(query, (source,))
                return cursor.rowcount
        finally:
            conn.close()

    def delete_by_timerange(
        self,
        start_time: Union[datetime, str],
        end_time: Union[datetime, str],
        source: Optional[str] = None,
    ) -> int:
        """
        Deletes events within a specific time boundary, optionally filtered by source.
        Returns the count of deleted events.
        """
        st = ensure_timezone_aware(start_time, "start_time")
        et = ensure_timezone_aware(end_time, "end_time")

        clauses = ["event_time >= ?", "event_time <= ?"]
        params = [format_iso8601(st), format_iso8601(et)]

        if source:
            clauses.append("source = ?")
            params.append(source)

        query = f"DELETE FROM event_log WHERE {' AND '.join(clauses)};"
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(params))
                return cursor.rowcount
        finally:
            conn.close()
