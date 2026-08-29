"""
Predictive Processing & Expectation Engine (Karl Friston's Free Energy Principle).

Generates top-down expectation states for user location, activity, cognitive load, and schedule,
and computes Prediction Error (delta) against real-time incoming observations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class ExpectedState:
    """Represents expected baseline state projected for a given time window."""
    time_window_key: str  # e.g. 'weekday_morning', 'weekday_evening', 'weekend_afternoon'
    expected_location: str = "Primary Workspace"
    expected_activity: str = "Deep Work"
    expected_cognitive_load: float = 0.5
    confidence: float = 0.8
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_window_key": self.time_window_key,
            "expected_location": self.expected_location,
            "expected_activity": self.expected_activity,
            "expected_cognitive_load": self.expected_cognitive_load,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


class PredictiveProcessingEngine:
    """Calculates top-down expectations and prediction error deltas for incoming observations."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()

    def get_time_window_key(self, dt: datetime) -> str:
        """Returns normalized time window key based on weekday and hour."""
        dt = ensure_timezone_aware(dt, "PredictiveProcessingEngine dt")
        is_weekend = dt.weekday() >= 5
        day_type = "weekend" if is_weekend else "weekday"

        hour = dt.hour
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 22:
            period = "evening"
        else:
            period = "night"

        return f"{day_type}_{period}"

    def get_expected_state(self, dt: Optional[datetime] = None) -> ExpectedState:
        """Retrieves or computes top-down expected state for reference timestamp."""
        now = ensure_timezone_aware(dt or datetime.now(timezone.utc), "get_expected_state")
        window_key = self.get_time_window_key(now)

        conn = self.db_manager.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM predictive_baselines WHERE time_window_key = ?",
                (window_key,),
            ).fetchone()

            if row:
                d = dict(row)
                return ExpectedState(
                    time_window_key=window_key,
                    expected_location=d.get("expected_location", "Primary Workspace"),
                    expected_activity=d.get("expected_activity", "Deep Work"),
                    expected_cognitive_load=float(d.get("expected_cognitive_load", 0.5)),
                    confidence=min(1.0, 0.5 + 0.05 * int(d.get("sample_count", 1))),
                )
            else:
                # Default baseline heuristic
                if "night" in window_key:
                    return ExpectedState(
                        time_window_key=window_key,
                        expected_location="Home",
                        expected_activity="Rest & Sleep",
                        expected_cognitive_load=0.1,
                    )
                elif "evening" in window_key:
                    return ExpectedState(
                        time_window_key=window_key,
                        expected_location="Home / Gym",
                        expected_activity="Personal & Fitness",
                        expected_cognitive_load=0.3,
                    )
                else:
                    return ExpectedState(
                        time_window_key=window_key,
                        expected_location="Primary Workspace",
                        expected_activity="Deep Work & Engineering",
                        expected_cognitive_load=0.7,
                    )
        finally:
            conn.close()

    def calculate_prediction_error(
        self, actual_event: Event, expected: Optional[ExpectedState] = None
    ) -> float:
        """
        Calculates prediction error delta (0.0 to 1.0) between actual observation and expectation.
        High prediction error indicates an anomaly requiring System 2 LLM reasoning.
        """
        event_time = actual_event.event_time or datetime.now(timezone.utc)
        exp = expected or self.get_expected_state(event_time)

        ev_type = actual_event.event_type.lower()
        payload = actual_event.payload if isinstance(actual_event.payload, dict) else {}
        summary = payload.get("summary", "").lower()

        prediction_error = 0.0

        # Biometric recovery anomaly
        if "biometric" in ev_type or "sleep" in ev_type or "sleep" in summary:
            dur = float(payload.get("duration_minutes", 480))
            if dur < 300:
                prediction_error += 0.6  # Severe sleep deficit

        # Security alert or urgent communication
        if "security" in summary or "alert" in summary or "urgent" in summary:
            prediction_error += 0.5

        # Flight delay or travel disruption
        if "delay" in summary or "cancelled" in summary:
            prediction_error += 0.7

        # Meeting compression vs expected quiet time
        if "night" in exp.time_window_key and ("meeting" in ev_type or "meeting" in summary):
            prediction_error += 0.4

        return min(1.0, max(0.0, prediction_error))

    def update_baseline_from_observation(self, actual_event: Event) -> None:
        """Updates predictive baseline counts for continuous learning."""
        event_time = actual_event.event_time or datetime.now(timezone.utc)
        window_key = self.get_time_window_key(event_time)

        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO predictive_baselines (id, time_window_key, expected_location, expected_activity, expected_cognitive_load, sample_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        sample_count = sample_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        f"pred-{window_key}",
                        window_key,
                        "Primary Workspace",
                        actual_event.event_type,
                        0.5,
                        format_iso8601(datetime.now(timezone.utc)),
                    ),
                )
        finally:
            conn.close()
