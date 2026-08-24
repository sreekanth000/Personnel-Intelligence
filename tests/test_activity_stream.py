"""
Unit tests for Personal Intelligence Live Activity Stream.
"""

import unittest

from personal_intelligence.core.activity.stream import ActivityEvent, ActivityStream


class TestActivityStream(unittest.TestCase):
    """
    Test suite for ActivityStream execution telemetry.
    """

    def setUp(self) -> None:
        self.stream = ActivityStream(max_events=10)
        self.stream.clear()

    def test_emit_valid_lifecycle_events(self) -> None:
        valid_types = [
            "observation_created",
            "state_updated",
            "novelty_detected",
            "situation_created",
            "investigation_started",
            "tool_requested",
            "tool_completed",
            "evidence_added",
            "reasoning_started",
            "reasoning_completed",
            "intervention_decided",
            "pattern_updated",
        ]

        for evt_type in valid_types:
            evt = self.stream.emit(
                event_type=evt_type,
                summary=f"Testing lifecycle stage: {evt_type}",
                source="test_runner",
                status="completed",
            )
            self.assertEqual(evt.type, evt_type)
            self.assertIsNotNone(evt.id)
            self.assertIsNotNone(evt.timestamp)

    def test_bounded_capacity_ring_buffer(self) -> None:
        # Emit 15 events into a max_events=10 buffer
        for i in range(15):
            self.stream.emit(
                event_type="state_updated",
                summary=f"Event {i}",
                source="test",
            )

        events = self.stream.get_recent(limit=50)
        self.assertEqual(len(events), 10)
        self.assertEqual(events[0]["summary"], "Event 5")
        self.assertEqual(events[-1]["summary"], "Event 14")

    def test_get_recent_with_since_id(self) -> None:
        evt1 = self.stream.emit("observation_created", "First", source="gmail")
        evt2 = self.stream.emit("situation_created", "Second", source="engine")
        evt3 = self.stream.emit("reasoning_started", "Third", source="reasoner")

        since_evt1 = self.stream.get_recent(since_id=evt1.id)
        self.assertEqual(len(since_evt1), 2)
        self.assertEqual(since_evt1[0]["id"], evt2.id)
        self.assertEqual(since_evt1[1]["id"], evt3.id)

    def test_zero_credential_exposure(self) -> None:
        evt = self.stream.emit(
            event_type="observation_created",
            summary="Bearer ya29.a0AfH6SM... Sync completed",
            source="gmail",
        )
        self.assertNotIn("Bearer", evt.summary)

    def test_listener_subscription(self) -> None:
        received = []

    def test_event_schema_fields(self) -> None:
        evt = self.stream.emit(
            event_type="situation_created",
            summary="Novel situation detected",
            source="situation_engine",
            status="active",
            situation_id="sit-1234",
        )
        d = evt.to_dict()
        self.assertEqual(d["id"], evt.id)
        self.assertEqual(d["timestamp"], evt.timestamp)
        self.assertEqual(d["type"], "situation_created")
        self.assertEqual(d["situation_id"], "sit-1234")
        self.assertEqual(d["summary"], "Novel situation detected")
        self.assertEqual(d["source"], "situation_engine")
        self.assertEqual(d["status"], "active")

    def test_evaluation_loop_activity_stream_emissions(self) -> None:
        from datetime import datetime, timezone
        from personal_intelligence.core.events.models import Event
        from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
        from personal_intelligence.storage.db import DatabaseManager

        global_stream = ActivityStream.get_instance()
        global_stream.clear()

        db = DatabaseManager(":memory:")
        db.initialize_schema()
        loop = PersonalIntelligenceEvaluationLoop(db_manager=db)

        test_ev = Event(
            event_time=datetime.now(timezone.utc),
            event_type="calendar_event",
            source="calendar",
            payload={"title": "Team Sync Meeting"},
        )

        loop.run_cycle(incoming_events=[test_ev])

        recent = global_stream.get_recent(limit=20)
        self.assertTrue(len(recent) >= 2)
        event_types = [e["type"] for e in recent]
        self.assertIn("observation_created", event_types)
        self.assertIn("state_updated", event_types)


if __name__ == "__main__":
    unittest.main()


