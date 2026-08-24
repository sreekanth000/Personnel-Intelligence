"""
Timeline Engine providing chronological queries over the event_log source of truth.
"""

from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, List, Optional, Union

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.timeline.models import Timeline


class TimelineEngine:
    """
    Query and slicing engine for building chronological Timeline views from the event_log.
    Preserves strict chronological order and supports relative and boundary queries.
    """

    def __init__(self, event_store: Optional[EventStore] = None) -> None:
        self.event_store = event_store or EventStore()
        self.db_manager = self.event_store.db_manager

    def _resolve_reference_time(self, ref: Optional[datetime] = None) -> datetime:
        """Returns a timezone-aware reference datetime, defaulting to current UTC time."""
        if ref is None:
            return datetime.now(timezone.utc)
        return ensure_timezone_aware(ref, "reference_time")

    def get_time_range(
        self,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        subject_id: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Timeline:
        """
        Retrieves a chronological Timeline for an arbitrary time range and optional filters.
        """
        clauses = []
        params: List[Any] = []

        st_obj = None
        et_obj = None

        if start_time is not None:
            st_obj = ensure_timezone_aware(start_time, "start_time")
            clauses.append("event_time >= ?")
            params.append(format_iso8601(st_obj))

        if end_time is not None:
            et_obj = ensure_timezone_aware(end_time, "end_time")
            clauses.append("event_time <= ?")
            params.append(format_iso8601(et_obj))

        if subject_id is not None:
            clauses.append("subject_id = ?")
            params.append(subject_id)

        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(event_types)

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_stmt = f"LIMIT {int(limit)}" if limit is not None else ""
        query = f"SELECT * FROM event_log {where_stmt} ORDER BY event_time ASC, ingested_at ASC {limit_stmt};"

        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            events = [self.event_store._row_to_event(r) for r in rows]
            return Timeline(
                events=events,
                start_time=st_obj,
                end_time=et_obj,
                query_metadata={
                    "query": "time_range",
                    "subject_id": subject_id,
                    "event_types": event_types,
                    "limit": limit,
                },
            )
        finally:
            conn.close()

    def get_last_n_minutes(
        self,
        minutes: int,
        reference_time: Optional[datetime] = None,
        subject_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Timeline:
        """Retrieves events from the last N minutes relative to reference_time."""
        if minutes < 0:
            raise ValueError(f"minutes must be non-negative, got {minutes}")
        ref = self._resolve_reference_time(reference_time)
        start = ref - timedelta(minutes=minutes)
        timeline = self.get_time_range(start_time=start, end_time=ref, subject_id=subject_id, limit=limit)
        timeline.query_metadata["query"] = f"last_{minutes}_minutes"
        return timeline

    def get_last_n_hours(
        self,
        hours: int,
        reference_time: Optional[datetime] = None,
        subject_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Timeline:
        """Retrieves events from the last N hours relative to reference_time."""
        if hours < 0:
            raise ValueError(f"hours must be non-negative, got {hours}")
        ref = self._resolve_reference_time(reference_time)
        start = ref - timedelta(hours=hours)
        timeline = self.get_time_range(start_time=start, end_time=ref, subject_id=subject_id, limit=limit)
        timeline.query_metadata["query"] = f"last_{hours}_hours"
        return timeline

    def get_today(
        self,
        reference_time: Optional[datetime] = None,
        tz: Optional[timezone] = None,
        subject_id: Optional[str] = None,
    ) -> Timeline:
        """
        Retrieves all events occurring today (from 00:00:00 of the local day to reference_time).
        """
        ref = self._resolve_reference_time(reference_time)
        target_tz = tz or ref.tzinfo or timezone.utc
        local_ref = ref.astimezone(target_tz)
        local_start_of_day = local_ref.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end_of_day = local_ref.replace(hour=23, minute=59, second=59, microsecond=999999)

        timeline = self.get_time_range(start_time=local_start_of_day, end_time=local_end_of_day, subject_id=subject_id)
        timeline.query_metadata["query"] = "today"
        timeline.query_metadata["timezone"] = str(target_tz)
        return timeline

    def get_yesterday(
        self,
        reference_time: Optional[datetime] = None,
        tz: Optional[timezone] = None,
        subject_id: Optional[str] = None,
    ) -> Timeline:
        """
        Retrieves all events occurring yesterday (from 00:00:00 to 23:59:59 of previous calendar day).
        """
        ref = self._resolve_reference_time(reference_time)
        target_tz = tz or ref.tzinfo or timezone.utc
        local_ref = ref.astimezone(target_tz)
        yesterday_date = (local_ref - timedelta(days=1)).date()

        start_yesterday = datetime.combine(yesterday_date, dtime.min).replace(tzinfo=target_tz)
        end_yesterday = datetime.combine(yesterday_date, dtime.max).replace(tzinfo=target_tz)

        timeline = self.get_time_range(start_time=start_yesterday, end_time=end_yesterday, subject_id=subject_id)
        timeline.query_metadata["query"] = "yesterday"
        timeline.query_metadata["timezone"] = str(target_tz)
        return timeline

    def get_last_n_days(
        self,
        days: int,
        reference_time: Optional[datetime] = None,
        subject_id: Optional[str] = None,
    ) -> Timeline:
        """Retrieves events from the last N days (24h * N window)."""
        if days < 0:
            raise ValueError(f"days must be non-negative, got {days}")
        ref = self._resolve_reference_time(reference_time)
        start = ref - timedelta(days=days)
        timeline = self.get_time_range(start_time=start, end_time=ref, subject_id=subject_id)
        timeline.query_metadata["query"] = f"last_{days}_days"
        return timeline

    def get_for_subject(
        self,
        subject_id: str,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
    ) -> Timeline:
        """Retrieves chronological events filtered for a specific subject_id."""
        return self.get_time_range(
            start_time=start_time,
            end_time=end_time,
            subject_id=subject_id,
            limit=limit,
        )

    def get_for_type(
        self,
        event_type: str,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
    ) -> Timeline:
        """Retrieves chronological events filtered for a specific event_type."""
        return self.get_time_range(
            start_time=start_time,
            end_time=end_time,
            event_types=[event_type],
            limit=limit,
        )

    def get_around_event(
        self,
        event_id: str,
        window_before: Optional[timedelta] = None,
        window_after: Optional[timedelta] = None,
        count_before: Optional[int] = None,
        count_after: Optional[int] = None,
    ) -> Timeline:
        """
        Retrieves context events surrounding a specific target event.
        Can query by time window (e.g. +/- 30m) or by discrete event counts (e.g. 5 before, 5 after).
        """
        target_event = self.event_store.get(event_id)
        if target_event is None:
            return Timeline(events=[], query_metadata={"target_event_id": event_id, "found": False})

        target_time_iso = format_iso8601(target_event.event_time)

        # 1. Time-window based queries
        if window_before is not None or window_after is not None:
            w_before = window_before or timedelta(minutes=30)
            w_after = window_after or timedelta(minutes=30)
            st = target_event.event_time - w_before
            et = target_event.event_time + w_after
            timeline = self.get_time_range(start_time=st, end_time=et)
            timeline.query_metadata["target_event_id"] = event_id
            return timeline

        # 2. Count-based surrounding queries (default to 5 before, 5 after if not specified)
        n_before = count_before if count_before is not None else 5
        n_after = count_after if count_after is not None else 5

        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()

            # Preceding events (ORDER BY event_time DESC to get closest ones, then reverse)
            cursor.execute(
                "SELECT * FROM event_log WHERE event_time < ? OR (event_time = ? AND id != ?) ORDER BY event_time DESC, ingested_at DESC LIMIT ?;",
                (target_time_iso, target_time_iso, event_id, n_before),
            )
            preceding_rows = cursor.fetchall()
            preceding_events = [self.event_store._row_to_event(r) for r in reversed(preceding_rows)]

            # Subsequent events
            cursor.execute(
                "SELECT * FROM event_log WHERE event_time > ? OR (event_time = ? AND id != ?) ORDER BY event_time ASC, ingested_at ASC LIMIT ?;",
                (target_time_iso, target_time_iso, event_id, n_after),
            )
            subsequent_rows = cursor.fetchall()
            subsequent_events = [self.event_store._row_to_event(r) for r in subsequent_rows]

            # Merge all including target event
            merged_events = preceding_events + [target_event] + subsequent_events

            return Timeline(
                events=merged_events,
                start_time=merged_events[0].event_time if merged_events else target_event.event_time,
                end_time=merged_events[-1].event_time if merged_events else target_event.event_time,
                query_metadata={
                    "target_event_id": event_id,
                    "count_before": n_before,
                    "count_after": n_after,
                },
            )
        finally:
            conn.close()
