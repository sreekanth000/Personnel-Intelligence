"""
Unit tests for AttentionDetector (Blueprint §13, Decision 3).
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.policy.models import UserContext
from personal_intelligence.core.state.attention_detector import AttentionDetector
from personal_intelligence.core.state.models import StateFeature, StateRepresentation


class TestAttentionDetector(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = AttentionDetector(
            deep_work_threshold_minutes=30.0,
            idle_threshold_minutes=30.0,
            recent_window_minutes=15.0,
            sleep_hour_start=22,
            sleep_hour_end=7,
        )
        self.base_time = datetime(2026, 8, 29, 14, 0, 0, tzinfo=timezone.utc)

    def test_default_available_when_no_events(self) -> None:
        """No events during daytime -> AVAILABLE."""
        result = self.detector.detect([], current_time=self.base_time)
        self.assertEqual(result.state, UserContext.AVAILABLE.value)
        self.assertEqual(result.source, "default")

    def test_meeting_detection_from_calendar_event(self) -> None:
        """Active calendar event with multiple attendees -> MEETING."""
        ev = Event(
            event_type="calendar_event",
            source="calendar",
            source_id="cal_123",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"summary": "Sprint Planning", "attendees": ["alice@co.com", "bob@co.com"]},
        )
        result = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(result.state, UserContext.MEETING.value)
        self.assertEqual(result.source, "calendar")
        self.assertIn("Sprint Planning", result.reason)

    def test_dnd_signal_detection(self) -> None:
        """Explicit DND event -> DO_NOT_DISTURB."""
        ev = Event(
            event_type="focus_mode_enabled",
            source="device",
            source_id="dev_1",
            event_time=self.base_time - timedelta(minutes=2),
            payload={"mode": "dnd"},
        )
        result = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(result.state, UserContext.DO_NOT_DISTURB.value)
        self.assertEqual(result.source, "device_signal")

    def test_dnd_from_state_feature(self) -> None:
        """DND state feature in StateRepresentation -> DO_NOT_DISTURB."""
        state = StateRepresentation()
        state.add_feature(StateFeature(name="dnd_mode", value="enabled", source="system"))
        result = self.detector.detect([], current_state=state, current_time=self.base_time)
        self.assertEqual(result.state, UserContext.DO_NOT_DISTURB.value)
        self.assertEqual(result.source, "state_feature")

    def test_deep_work_detection(self) -> None:
        """Continuous focused editor events spanning > 15m -> DEEP_WORK."""
        events = [
            Event(
                event_type="vscode_edit",
                source="ide",
                source_id="ide_1",
                event_time=self.base_time - timedelta(minutes=25),
                payload={"file": "main.py"},
            ),
            Event(
                event_type="editor_activity",
                source="ide",
                source_id="ide_2",
                event_time=self.base_time - timedelta(minutes=10),
                payload={"file": "test.py"},
            ),
            Event(
                event_type="terminal_command",
                source="terminal",
                source_id="term_1",
                event_time=self.base_time - timedelta(minutes=2),
                payload={"cmd": "pytest"},
            ),
        ]
        result = self.detector.detect(events, current_time=self.base_time)
        self.assertEqual(result.state, UserContext.DEEP_WORK.value)
        self.assertEqual(result.source, "device_activity")

    def test_transit_detection(self) -> None:
        """Driving / transit signal -> DRIVING."""
        ev = Event(
            event_type="uber_trip_started",
            source="mobility",
            source_id="uber_1",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"destination": "Airport"},
        )
        result = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(result.state, UserContext.DRIVING.value)
        self.assertEqual(result.source, "mobility")

    def test_sleep_detection_during_sleep_hours(self) -> None:
        """No events during 23:00 -> SLEEP."""
        night_time = datetime(2026, 8, 29, 23, 30, 0, tzinfo=timezone.utc)
        result = self.detector.detect([], current_time=night_time)
        self.assertEqual(result.state, UserContext.SLEEP.value)
        self.assertEqual(result.source, "time_heuristic")

    def test_busy_detection_from_generic_recent_events(self) -> None:
        """Recent generic event (e.g. document_read) -> BUSY."""
        ev = Event(
            event_type="document_opened",
            source="drive",
            source_id="doc_1",
            event_time=self.base_time - timedelta(minutes=3),
            payload={"doc": "Q3 Planning"},
        )
        result = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(result.state, UserContext.BUSY.value)
        self.assertEqual(result.source, "event_density")


if __name__ == "__main__":
    unittest.main()
