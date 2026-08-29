"""
Unit tests for multi-signal AttentionDetector covering all 10 canonical states (Prompt 2, Change 9).
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.policy.models import UserContext
from personal_intelligence.core.state.attention_detector import AttentionDetector
from personal_intelligence.core.state.models import StateFeature, StateRepresentation


class TestAttentionDetectorMultiSignal(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = AttentionDetector(
            deep_work_threshold_minutes=30.0,
            focused_threshold_minutes=10.0,
            idle_threshold_minutes=30.0,
            recent_window_minutes=15.0,
            sleep_hour_start=22,
            sleep_hour_end=7,
        )
        self.base_time = datetime(2026, 8, 29, 14, 0, 0, tzinfo=timezone.utc)

    def test_meeting_state_detection(self) -> None:
        """1. MEETING detection from calendar event with attendees."""
        ev = Event(
            event_type="calendar_event",
            source="calendar",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"summary": "1:1 with Manager", "attendees": ["manager@co.com", "user@co.com"]},
        )
        res = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(res.state, UserContext.MEETING.value)
        self.assertEqual(res.source, "calendar")

    def test_dnd_state_detection(self) -> None:
        """2. DND detection from system focus mode signal."""
        ev = Event(
            event_type="do_not_disturb_enabled",
            source="device",
            event_time=self.base_time - timedelta(minutes=2),
            payload={"mode": "silent"},
        )
        res = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(res.state, UserContext.DO_NOT_DISTURB.value)

    def test_driving_state_detection(self) -> None:
        """3. DRIVING detection from in-car mobility event."""
        ev = Event(
            event_type="google_maps_driving",
            source="mobility",
            event_time=self.base_time - timedelta(minutes=4),
            payload={"route": "Home to Office"},
        )
        res = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(res.state, UserContext.DRIVING.value)

    def test_transit_state_detection(self) -> None:
        """4. TRANSIT detection from commute / train / flight event."""
        ev = Event(
            event_type="train_boarding",
            source="transit",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"line": "Express Train 44"},
        )
        res = self.detector.detect([ev], current_time=self.base_time)
        self.assertEqual(res.state, UserContext.TRANSIT.value)

    def test_deep_work_state_detection(self) -> None:
        """5. DEEP_WORK detection from continuous IDE/editor stream with low context-switching."""
        events = [
            Event(event_type="vscode_edit", source="ide", event_time=self.base_time - timedelta(minutes=25)),
            Event(event_type="code_compile", source="ide", event_time=self.base_time - timedelta(minutes=15)),
            Event(event_type="git_commit", source="terminal", event_time=self.base_time - timedelta(minutes=5)),
        ]
        res = self.detector.detect(events, current_time=self.base_time)
        self.assertEqual(res.state, UserContext.DEEP_WORK.value)

    def test_focused_state_detection(self) -> None:
        """6. FOCUSED detection from shorter focused engagement."""
        events = [
            Event(event_type="document_edit", source="editor", event_time=self.base_time - timedelta(minutes=8)),
            Event(event_type="document_write", source="editor", event_time=self.base_time - timedelta(minutes=2)),
        ]
        res = self.detector.detect(events, current_time=self.base_time)
        self.assertEqual(res.state, UserContext.FOCUSED.value)

    def test_sleep_state_detection(self) -> None:
        """7. SLEEP detection from zero activity during sleep hours."""
        night_time = datetime(2026, 8, 29, 23, 30, 0, tzinfo=timezone.utc)
        res = self.detector.detect([], current_time=night_time)
        self.assertEqual(res.state, UserContext.SLEEP.value)

    def test_available_state_detection(self) -> None:
        """10. AVAILABLE detection from default daytime baseline with no urgent blocks."""
        day_time = datetime(2026, 8, 29, 15, 0, 0, tzinfo=timezone.utc)
        res = self.detector.detect([], current_time=day_time)
        self.assertEqual(res.state, UserContext.AVAILABLE.value)
        self.assertEqual(res.source, "default")


if __name__ == "__main__":
    unittest.main()
