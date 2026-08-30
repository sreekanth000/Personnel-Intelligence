"""
Unit tests for PollingDaemon and background scheduling.
"""

from datetime import datetime, timezone
from typing import List
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
from personal_intelligence.scheduler.daemon import PollingDaemon, SourcePoller
from personal_intelligence.storage.db import DatabaseManager


class MockCustomPoller(SourcePoller):
    name = "mock_poller"

    def __init__(self, events_to_return: List[Event]) -> None:
        self.events_to_return = events_to_return
        self.poll_count = 0

    def poll(self) -> List[Event]:
        self.poll_count += 1
        return self.events_to_return


class FailingPoller(SourcePoller):
    name = "failing_poller"

    def poll(self) -> List[Event]:
        raise RuntimeError("Simulated API failure")


class TestSchedulerDaemon(unittest.TestCase):

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.db.initialize_schema()
        self.loop = PersonalIntelligenceEvaluationLoop(db_manager=self.db)
        self.daemon = PollingDaemon(loop=self.loop, interval_minutes=5)

    def test_register_source_poller(self) -> None:
        poller = MockCustomPoller([])
        self.daemon.register_source(poller)
        self.assertEqual(len(self.daemon.source_pollers), 1)
        self.assertEqual(self.daemon.source_pollers[0].name, "mock_poller")

    def test_collect_events_from_multiple_sources(self) -> None:
        ev1 = Event(
            event_type="test_signal_1",
            source="source_1",
            timestamp=datetime.now(timezone.utc),
            structured_data={"key": "val1"},
        )
        ev2 = Event(
            event_type="test_signal_2",
            source="source_2",
            timestamp=datetime.now(timezone.utc),
            structured_data={"key": "val2"},
        )

        p1 = MockCustomPoller([ev1])
        p2 = MockCustomPoller([ev2])
        self.daemon.register_source(p1)
        self.daemon.register_source(p2)

        collected = self.daemon._collect_events()
        self.assertEqual(len(collected), 2)
        self.assertEqual(p1.poll_count, 1)
        self.assertEqual(p2.poll_count, 1)

    def test_collect_events_handles_failing_poller_gracefully(self) -> None:
        ev1 = Event(
            event_type="good_event",
            source="good_source",
            timestamp=datetime.now(timezone.utc),
            structured_data={"status": "ok"},
        )
        good_poller = MockCustomPoller([ev1])
        failing_poller = FailingPoller()

        self.daemon.register_source(good_poller)
        self.daemon.register_source(failing_poller)

        collected = self.daemon._collect_events()
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0].source, "good_source")

    def test_run_once_executes_cycle_and_stores_events(self) -> None:
        ev = Event(
            event_type="calendar_meeting_scheduled",
            source="calendar",
            timestamp=datetime.now(timezone.utc),
            structured_data={"title": "Team Sync"},
            summary="Team Sync meeting",
        )
        poller = MockCustomPoller([ev])
        self.daemon.register_source(poller)

        self.daemon.run_once()
        stored_count = self.loop.event_store.count()
        self.assertGreaterEqual(stored_count, 1)


if __name__ == "__main__":
    unittest.main()
