"""
Configurable data retention policy manager for Personal Intelligence.
Allows setting custom retention horizons by event type or default global cutoffs,
pruning aged data cleanly from local SQLite tables.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.storage.db import DatabaseManager


@dataclass
class RetentionPolicy:
    """
    Configurable retention horizon rules in days.
    """
    default_days: int = 180
    rules_by_event_type: Dict[str, int] = field(default_factory=lambda: {
        "location_update": 14,
        "ambient_environment": 7,
        "raw_sensor_telemetry": 7,
        "app_focus": 30,
        "sleep_session": 90,
        "exercise_workout": 180,
        "calendar_event": 365,
    })

    def get_retention_days(self, event_type: str) -> int:
        """Returns the retention window in days for a given event type."""
        return self.rules_by_event_type.get(event_type, self.default_days)

    def get_cutoff(self, event_type: str, as_of: Optional[datetime] = None) -> datetime:
        """Computes the cutoff datetime for an event type."""
        now = ensure_timezone_aware(as_of or datetime.now(timezone.utc), "as_of")
        days = self.get_retention_days(event_type)
        return now - timedelta(days=days)


@dataclass
class RetentionSummary:
    """Summary of data retention enforcement actions."""
    executed_at: datetime
    pruned_by_type: Dict[str, int]
    total_pruned: int
    dry_run: bool


class RetentionManager:
    """
    Executes retention pruning against EventStore and local SQLite tables.
    """

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        db_manager: Optional[DatabaseManager] = None,
        policy: Optional[RetentionPolicy] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.event_store = event_store or EventStore(db_manager=self.db_manager)
        self.policy = policy or RetentionPolicy()

    def enforce_retention(
        self,
        as_of: Optional[datetime] = None,
        dry_run: bool = False,
    ) -> RetentionSummary:
        """
        Enforces retention rules across all known event types in event_log.
        Removes events older than their respective cutoff.
        """
        now = ensure_timezone_aware(as_of or datetime.now(timezone.utc), "as_of")
        conn = self.db_manager.get_connection()
        pruned_counts: Dict[str, int] = {}
        total_pruned = 0

        try:
            cursor = conn.cursor()
            # 1. Fetch all distinct event types
            cursor.execute("SELECT DISTINCT event_type FROM event_log;")
            event_types = [row["event_type"] for row in cursor.fetchall()]

            for et in event_types:
                cutoff = self.policy.get_cutoff(et, as_of=now)
                cutoff_iso = format_iso8601(cutoff)

                if dry_run:
                    cursor.execute(
                        "SELECT COUNT(*) as count FROM event_log WHERE event_type = ? AND event_time < ?;",
                        (et, cutoff_iso),
                    )
                    cnt = cursor.fetchone()["count"]
                else:
                    with conn:
                        cursor.execute(
                            "DELETE FROM event_log WHERE event_type = ? AND event_time < ?;",
                            (et, cutoff_iso),
                        )
                        cnt = cursor.rowcount

                if cnt > 0:
                    pruned_counts[et] = cnt
                    total_pruned += cnt

            return RetentionSummary(
                executed_at=now,
                pruned_by_type=pruned_counts,
                total_pruned=total_pruned,
                dry_run=dry_run,
            )
        finally:
            conn.close()
