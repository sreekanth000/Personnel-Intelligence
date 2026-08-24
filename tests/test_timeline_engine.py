"""
Unit tests for the Personal Intelligence Timeline Engine.
Tests time boundaries, chronological ordering, empty timelines, timezone handling,
large event volumes, surrounding events, and deterministic raw summaries.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
from typing import List
import unittest

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.timeline import Timeline, TimelineEngine
from personal_intelligence.storage.db import DatabaseManager


class TestTimelineEngine(unittest.TestCase):
    """Test suite validating Timeline and TimelineEngine functionality."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_timeline.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.base_time = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_events(self) -> List[Event]:
        """Seeds a set of events across a multi-hour span."""
        events = []
        for i in range(10):
            t = self.base_time + timedelta(minutes=i * 15)  # 0m, 15m, 30m, ... 135m
            evt = Event(
                id=f"evt-{i}",
                event_type="app_activity" if i % 2 == 0 else "location_ping",
                source="laptop" if i < 5 else "phone",
                subject_id="user_alpha" if i < 7 else "user_beta",
                payload={"step": i, "val": i * 10},
                event_time=t,
                confidence=0.8 + (i * 0.02),
            )
            self.event_store.append(evt)
            events.append(evt)
        return events

    # --- 1. Chronological Ordering ---

    def test_chronological_ordering_guarantee(self) -> None:
        """Verify events are returned in strict chronological order regardless of insertion sequence."""
        # Insert events in reverse chronological order
        t3 = self.base_time + timedelta(hours=3)
        t2 = self.base_time + timedelta(hours=2)
        t1 = self.base_time + timedelta(hours=1)

        self.event_store.append(Event(id="e3", event_type="type_c", source="src", payload={"v": 3}, event_time=t3))
        self.event_store.append(Event(id="e2", event_type="type_b", source="src", payload={"v": 2}, event_time=t2))
        self.event_store.append(Event(id="e1", event_type="type_a", source="src", payload={"v": 1}, event_time=t1))

        timeline = self.timeline_engine.get_time_range(start_time=self.base_time, end_time=t3)
        self.assertEqual(len(timeline), 3)
        self.assertEqual([e.id for e in timeline], ["e1", "e2", "e3"])
        self.assertEqual([e.payload["v"] for e in timeline], [1, 2, 3])

    # --- 2. Time Boundaries ---

    def test_time_boundaries_inclusivity(self) -> None:
        """Verify exact start and end boundary matching."""
        t1 = self.base_time
        t2 = self.base_time + timedelta(minutes=30)
        t3 = self.base_time + timedelta(minutes=60)

        self.event_store.append(Event(id="b1", event_type="t", source="s", payload={}, event_time=t1))
        self.event_store.append(Event(id="b2", event_type="t", source="s", payload={}, event_time=t2))
        self.event_store.append(Event(id="b3", event_type="t", source="s", payload={}, event_time=t3))

        # Query bounded exactly from t1 to t2
        tl = self.timeline_engine.get_time_range(start_time=t1, end_time=t2)
        self.assertEqual(len(tl), 2)
        self.assertEqual([e.id for e in tl], ["b1", "b2"])

        # Query bounded strictly within (t1+5m, t3-5m) -> only t2
        tl_mid = self.timeline_engine.get_time_range(
            start_time=t1 + timedelta(minutes=5),
            end_time=t3 - timedelta(minutes=5),
        )
        self.assertEqual(len(tl_mid), 1)
        self.assertEqual(tl_mid[0].id, "b2")

    def test_last_n_minutes_and_hours(self) -> None:
        """Verify relative slicing for minutes and hours."""
        self._seed_events()  # Events at 0m, 15m, 30m, 45m, 60m, 75m, 90m, 105m, 120m, 135m
        ref = self.base_time + timedelta(minutes=135)

        # Last 30 minutes relative to ref (events at 105m, 120m, 135m)
        tl_30m = self.timeline_engine.get_last_n_minutes(30, reference_time=ref)
        self.assertEqual(len(tl_30m), 3)
        self.assertEqual([e.id for e in tl_30m], ["evt-7", "evt-8", "evt-9"])

        # Last 1 hour relative to ref (events at 75m, 90m, 105m, 120m, 135m)
        tl_1h = self.timeline_engine.get_last_n_hours(1, reference_time=ref)
        self.assertEqual(len(tl_1h), 5)
        self.assertEqual([e.id for e in tl_1h], ["evt-5", "evt-6", "evt-7", "evt-8", "evt-9"])

    def test_today_and_yesterday(self) -> None:
        """Verify day-relative queries (today, yesterday)."""
        ref = datetime(2026, 8, 21, 15, 0, 0, tzinfo=timezone.utc)
        yesterday_noon = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
        two_days_ago = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

        self.event_store.append(Event(id="today_evt", event_type="t", source="s", payload={}, event_time=ref))
        self.event_store.append(Event(id="yest_evt", event_type="t", source="s", payload={}, event_time=yesterday_noon))
        self.event_store.append(Event(id="old_evt", event_type="t", source="s", payload={}, event_time=two_days_ago))

        tl_today = self.timeline_engine.get_today(reference_time=ref)
        self.assertEqual(len(tl_today), 1)
        self.assertEqual(tl_today[0].id, "today_evt")

        tl_yest = self.timeline_engine.get_yesterday(reference_time=ref)
        self.assertEqual(len(tl_yest), 1)
        self.assertEqual(tl_yest[0].id, "yest_evt")

        tl_3d = self.timeline_engine.get_last_n_days(3, reference_time=ref)
        self.assertEqual(len(tl_3d), 3)

    # --- 3. Timezone Handling ---

    def test_timezone_conversion_and_cross_offset_queries(self) -> None:
        """Verify queries work seamlessly when events and query windows use different timezone offsets."""
        ist = timezone(timedelta(hours=5, minutes=30))
        pst = timezone(timedelta(hours=-8))

        # Event recorded at 12:00 UTC == 17:30 IST
        t_utc = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
        self.event_store.append(Event(id="evt_tz", event_type="test", source="src", payload={}, event_time=t_utc))

        # Query using IST timestamp range (17:00 IST to 18:00 IST)
        t_ist_start = datetime(2026, 8, 21, 17, 0, 0, tzinfo=ist)
        t_ist_end = datetime(2026, 8, 21, 18, 0, 0, tzinfo=ist)
        tl_ist = self.timeline_engine.get_time_range(start_time=t_ist_start, end_time=t_ist_end)
        self.assertEqual(len(tl_ist), 1)
        self.assertEqual(tl_ist[0].id, "evt_tz")

        # Query using PST timestamp range (03:00 PST to 05:00 PST -> 11:00 UTC to 13:00 UTC)
        t_pst_start = datetime(2026, 8, 21, 3, 0, 0, tzinfo=pst)
        t_pst_end = datetime(2026, 8, 21, 5, 0, 0, tzinfo=pst)
        tl_pst = self.timeline_engine.get_time_range(start_time=t_pst_start, end_time=t_pst_end)
        self.assertEqual(len(tl_pst), 1)
        self.assertEqual(tl_pst[0].id, "evt_tz")

    # --- 4. Empty Timelines ---

    def test_empty_timeline(self) -> None:
        """Verify behavior on empty timeline queries."""
        empty_tl = self.timeline_engine.get_time_range(
            start_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
        self.assertTrue(empty_tl.is_empty)
        self.assertEqual(len(empty_tl), 0)
        self.assertIsNone(empty_tl.first_event)
        self.assertIsNone(empty_tl.last_event)
        self.assertEqual(empty_tl.to_compact_text(), "[Empty Timeline]")

        summary = empty_tl.summarize_raw()
        self.assertEqual(summary["total_events"], 0)
        self.assertEqual(summary["time_span"]["duration_seconds"], 0.0)
        self.assertEqual(summary["event_types"], {})

    # --- 5. Surrounding Events ---

    def test_get_around_event_by_count(self) -> None:
        """Verify retrieving N events before and after a specific anchor event."""
        self._seed_events()  # 10 events: evt-0 through evt-9
        anchor_id = "evt-5"

        tl = self.timeline_engine.get_around_event(
            event_id=anchor_id,
            count_before=2,
            count_after=2,
        )
        # Expected: evt-3, evt-4, evt-5, evt-6, evt-7
        self.assertEqual(len(tl), 5)
        self.assertEqual([e.id for e in tl], ["evt-3", "evt-4", "evt-5", "evt-6", "evt-7"])

    def test_get_around_event_by_time_window(self) -> None:
        """Verify retrieving events within a time delta around an anchor event."""
        self._seed_events()
        anchor_id = "evt-4"  # time = base + 60m

        tl = self.timeline_engine.get_around_event(
            event_id=anchor_id,
            window_before=timedelta(minutes=20),
            window_after=timedelta(minutes=20),
        )
        # Window: [40m, 80m] -> includes evt-3 (45m), evt-4 (60m), evt-5 (75m)
        self.assertEqual(len(tl), 3)
        self.assertEqual([e.id for e in tl], ["evt-3", "evt-4", "evt-5"])

    def test_get_around_nonexistent_event(self) -> None:
        """Verify querying around a nonexistent event returns an empty timeline."""
        tl = self.timeline_engine.get_around_event("nonexistent_id")
        self.assertTrue(tl.is_empty)

    # --- 6. Subject and Type Queries ---

    def test_get_for_subject_and_type(self) -> None:
        """Verify filtering for subject and event_type."""
        self._seed_events()

        tl_subject = self.timeline_engine.get_for_subject("user_alpha")
        self.assertEqual(len(tl_subject), 7)
        for e in tl_subject:
            self.assertEqual(e.subject_id, "user_alpha")

        tl_type = self.timeline_engine.get_for_type("location_ping")
        self.assertEqual(len(tl_type), 5)
        for e in tl_type:
            self.assertEqual(e.event_type, "location_ping")

    # --- 7. Large Event Ranges ---

    def test_large_event_ranges(self) -> None:
        """Verify performance and slicing over 200+ events."""
        bulk_events = []
        for i in range(250):
            t = self.base_time + timedelta(minutes=i * 2)
            evt = Event(
                id=f"bulk-{i}",
                event_type=f"type_{i % 5}",
                source=f"source_{i % 3}",
                subject_id="bulk_user",
                payload={"index": i},
                event_time=t,
            )
            self.event_store.append(evt)
            bulk_events.append(evt)

        # Full range
        tl_all = self.timeline_engine.get_time_range(
            start_time=self.base_time,
            end_time=self.base_time + timedelta(minutes=500),
        )
        self.assertEqual(len(tl_all), 250)

        # Limited range
        tl_limited = self.timeline_engine.get_time_range(
            start_time=self.base_time,
            limit=50,
        )
        self.assertEqual(len(tl_limited), 50)
        self.assertEqual(tl_limited[0].id, "bulk-0")
        self.assertEqual(tl_limited[-1].id, "bulk-49")

    # --- 8. Deterministic summarize_raw() ---

    def test_summarize_raw_deterministic(self) -> None:
        """Verify summarize_raw calculates exact statistical counts without language generation."""
        self._seed_events()
        timeline = self.timeline_engine.get_time_range(
            start_time=self.base_time,
            end_time=self.base_time + timedelta(hours=3),
        )

        summary = timeline.summarize_raw()
        self.assertEqual(summary["total_events"], 10)
        self.assertEqual(summary["time_span"]["duration_seconds"], 135 * 60)
        self.assertIn("app_activity", summary["event_types"])
        self.assertEqual(summary["event_types"]["app_activity"], 5)
        self.assertEqual(summary["event_types"]["location_ping"], 5)
        self.assertEqual(summary["sources"]["laptop"], 5)
        self.assertEqual(summary["sources"]["phone"], 5)
        self.assertEqual(summary["subjects"]["user_alpha"], 7)
        self.assertEqual(summary["subjects"]["user_beta"], 3)
        self.assertGreater(len(summary["hourly_distribution"]), 0)
        self.assertAlmostEqual(summary["confidence_stats"]["min"], 0.80)
        self.assertAlmostEqual(summary["confidence_stats"]["max"], 0.98)

    # --- 9. Compact Representations for Hermes ---

    def test_compact_representations(self) -> None:
        """Verify to_compact_dict and to_compact_text formats."""
        self._seed_events()
        timeline = self.timeline_engine.get_last_n_minutes(30, reference_time=self.base_time + timedelta(minutes=135))

        compact_dict = timeline.to_compact_dict()
        self.assertEqual(compact_dict["total_events"], 3)
        self.assertIn("events", compact_dict)
        self.assertEqual(len(compact_dict["events"]), 3)

        compact_text = timeline.to_compact_text(max_events=2)
        lines = compact_text.splitlines()
        self.assertEqual(len(lines), 3)  # 2 events + "... and 1 more events."
        self.assertIn("... and 1 more events.", lines[2])


if __name__ == "__main__":
    unittest.main()
