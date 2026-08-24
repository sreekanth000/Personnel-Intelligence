"""
Unit tests for Phase 1: Event Storage Layer.
Covers insertion, duplicate prevention, validation, time queries, type queries, and subject queries.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.events import (
    Event,
    EventStore,
    EventValidationError,
    DuplicateEventError,
    ensure_timezone_aware,
    compute_event_hash,
)
from personal_intelligence.storage.db import DatabaseManager


class TestEventStorageLayer(unittest.TestCase):
    """Test suite validating generic, append-only SQLite event store."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_event_store.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. Event Insertion & Retrieval ---

    def test_event_insertion_and_get(self) -> None:
        """Verify appending an event and retrieving it by ID."""
        payload = {"metric_name": "temp_c", "value": 22.5, "device": "sensor_42"}
        event = Event(
            event_type="sensor_reading",
            source="home_sensor_hub",
            subject_id="sensor_42",
            payload=payload,
            event_time=self.base_time,
            confidence=0.98,
        )

        appended_event = self.event_store.append(event)
        self.assertEqual(appended_event.id, event.id)
        self.assertIsNotNone(appended_event.event_hash)

        retrieved = self.event_store.get(event.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, event.id)
        self.assertEqual(retrieved.event_type, "sensor_reading")
        self.assertEqual(retrieved.source, "home_sensor_hub")
        self.assertEqual(retrieved.subject_id, "sensor_42")
        self.assertEqual(retrieved.payload, payload)
        self.assertEqual(retrieved.confidence, 0.98)
        self.assertEqual(retrieved.event_hash, event.event_hash)
        self.assertEqual(retrieved.event_time, self.base_time)

    def test_get_nonexistent_returns_none(self) -> None:
        """Verify querying a non-existent ID returns None."""
        self.assertIsNone(self.event_store.get("nonexistent_id_123"))
        self.assertIsNone(self.event_store.get(""))

    # --- 2. Duplicate Detection ---

    def test_duplicate_detection_same_instance(self) -> None:
        """Appending the exact same event instance twice raises DuplicateEventError."""
        event = Event(
            event_type="system_ping",
            source="gateway",
            payload={"status": "ok"},
            event_time=self.base_time,
        )
        self.event_store.append(event)

        with self.assertRaises(DuplicateEventError) as ctx:
            self.event_store.append(event)
        self.assertEqual(ctx.exception.event_hash, event.event_hash)

    def test_duplicate_detection_different_id_identical_content(self) -> None:
        """Two distinct Event instances with identical logical content have the same hash and raise DuplicateEventError."""
        event1 = Event(
            id="event-uuid-1",
            event_type="system_ping",
            source="gateway",
            payload={"status": "ok"},
            event_time=self.base_time,
        )
        event2 = Event(
            id="event-uuid-2",
            event_type="system_ping",
            source="gateway",
            payload={"status": "ok"},
            event_time=self.base_time,
        )
        self.assertEqual(event1.event_hash, event2.event_hash)

        self.event_store.append(event1)
        with self.assertRaises(DuplicateEventError) as ctx:
            self.event_store.append(event2)
        self.assertEqual(ctx.exception.event_hash, event1.event_hash)

    # --- 3. Malformed Event Rejection ---

    def test_reject_naive_datetime(self) -> None:
        """Reject naive datetimes lacking explicit timezone."""
        naive_dt = datetime(2026, 8, 21, 12, 0, 0)  # No tzinfo
        with self.assertRaises(EventValidationError):
            Event(
                event_type="test_event",
                source="test_source",
                payload={"k": "v"},
                event_time=naive_dt,
            )

    def test_reject_empty_required_fields(self) -> None:
        """Reject empty or whitespace event_type or source."""
        with self.assertRaises(EventValidationError):
            Event(
                event_type="",
                source="test_source",
                payload={"k": "v"},
                event_time=self.base_time,
            )

        with self.assertRaises(EventValidationError):
            Event(
                event_type="test_event",
                source="   ",
                payload={"k": "v"},
                event_time=self.base_time,
            )

    def test_reject_invalid_confidence(self) -> None:
        """Reject confidence outside [0.0, 1.0] or non-numeric."""
        with self.assertRaises(EventValidationError):
            Event(
                event_type="test_event",
                source="test_source",
                payload={"k": "v"},
                event_time=self.base_time,
                confidence=-0.1,
            )

        with self.assertRaises(EventValidationError):
            Event(
                event_type="test_event",
                source="test_source",
                payload={"k": "v"},
                event_time=self.base_time,
                confidence=1.05,
            )

    def test_reject_invalid_payload(self) -> None:
        """Reject non-dict payload or payload with non-serializable objects."""
        with self.assertRaises(EventValidationError):
            Event(
                event_type="test_event",
                source="test_source",
                payload="not_a_dict",  # type: ignore
                event_time=self.base_time,
            )

        class UnserializableObject:
            pass

        with self.assertRaises(EventValidationError):
            Event(
                event_type="test_event",
                source="test_source",
                payload={"bad": UnserializableObject()},
                event_time=self.base_time,
            )

    def test_reject_append_invalid_type(self) -> None:
        """Reject appending non-Event instances to store."""
        with self.assertRaises(EventValidationError):
            self.event_store.append({"not": "an_event"})  # type: ignore

    # --- 4. Time Queries ---

    def test_query_by_time_range(self) -> None:
        """Verify time window filtering and ordering."""
        # Insert 5 events spaced by 1 hour
        for i in range(5):
            t = self.base_time + timedelta(hours=i)
            self.event_store.append(
                Event(
                    event_type="time_sample",
                    source="timer",
                    payload={"index": i},
                    event_time=t,
                )
            )

        # Query full range
        all_events = self.event_store.query_by_time()
        self.assertEqual(len(all_events), 5)
        self.assertEqual(all_events[0].payload["index"], 0)
        self.assertEqual(all_events[-1].payload["index"], 4)

        # Query bounded window: [T+1h, T+3h]
        start = self.base_time + timedelta(hours=1)
        end = self.base_time + timedelta(hours=3)
        window_events = self.event_store.query_by_time(start_time=start, end_time=end)
        self.assertEqual(len(window_events), 3)
        self.assertEqual([e.payload["index"] for e in window_events], [1, 2, 3])

        # Query descending order
        desc_events = self.event_store.query_by_time(order="desc", limit=2)
        self.assertEqual(len(desc_events), 2)
        self.assertEqual(desc_events[0].payload["index"], 4)
        self.assertEqual(desc_events[1].payload["index"], 3)

    # --- 5. Type Queries ---

    def test_query_by_type(self) -> None:
        """Verify filtering events by type with time bounds."""
        t1 = self.base_time
        t2 = self.base_time + timedelta(minutes=10)

        self.event_store.append(Event(event_type="type_a", source="s1", payload={"id": 1}, event_time=t1))
        self.event_store.append(Event(event_type="type_b", source="s1", payload={"id": 2}, event_time=t1))
        self.event_store.append(Event(event_type="type_a", source="s2", payload={"id": 3}, event_time=t2))

        type_a_events = self.event_store.query_by_type("type_a")
        self.assertEqual(len(type_a_events), 2)
        self.assertEqual([e.payload["id"] for e in type_a_events], [1, 3])

        type_b_events = self.event_store.query_by_type("type_b")
        self.assertEqual(len(type_b_events), 1)
        self.assertEqual(type_b_events[0].payload["id"], 2)

        # Non-matching type
        empty = self.event_store.query_by_type("type_c")
        self.assertEqual(len(empty), 0)

    # --- 6. Subject Queries ---

    def test_query_by_subject(self) -> None:
        """Verify filtering events by subject_id."""
        t1 = self.base_time
        t2 = self.base_time + timedelta(minutes=5)

        self.event_store.append(Event(event_type="interaction", source="ui", subject_id="user_alpha", payload={"act": "click"}, event_time=t1))
        self.event_store.append(Event(event_type="interaction", source="ui", subject_id="user_beta", payload={"act": "scroll"}, event_time=t1))
        self.event_store.append(Event(event_type="status_change", source="service", subject_id="user_alpha", payload={"act": "online"}, event_time=t2))

        alpha_events = self.event_store.query_by_subject("user_alpha")
        self.assertEqual(len(alpha_events), 2)
        self.assertEqual([e.payload["act"] for e in alpha_events], ["click", "online"])

        beta_events = self.event_store.query_by_subject("user_beta")
        self.assertEqual(len(beta_events), 1)
        self.assertEqual(beta_events[0].payload["act"], "scroll")

    # --- 7. Recent and Count Aggregation ---

    def test_recent_and_count(self) -> None:
        """Verify recent items sorting and count aggregation."""
        for i in range(10):
            t = self.base_time + timedelta(minutes=i)
            self.event_store.append(
                Event(
                    event_type="alpha_type" if i % 2 == 0 else "beta_type",
                    source="agent_test",
                    subject_id="subj_1" if i < 5 else "subj_2",
                    payload={"idx": i},
                    event_time=t,
                )
            )

        self.assertEqual(self.event_store.count(), 10)
        self.assertEqual(self.event_store.count(event_type="alpha_type"), 5)
        self.assertEqual(self.event_store.count(subject_id="subj_1"), 5)
        self.assertEqual(self.event_store.count(event_type="alpha_type", subject_id="subj_1"), 3)

        recent_3 = self.event_store.recent(limit=3)
        self.assertEqual(len(recent_3), 3)
        # Most recent first
        self.assertEqual(recent_3[0].payload["idx"], 9)
        self.assertEqual(recent_3[1].payload["idx"], 8)
        self.assertEqual(recent_3[2].payload["idx"], 7)


if __name__ == "__main__":
    unittest.main()
