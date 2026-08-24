"""
Unit Tests for Multi-Source Ingestion & Cross-Domain Fusion (Gmail + Calendar + Health/Sleep + Voice Notes).
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.fusion.multi_source_engine import MultiSourceFusionEngine
from personal_intelligence.core.query.ask import AskPersonalIntelligenceEngine
from personal_intelligence.hermes_bridge.calendar_adapter import (
    CalendarCapabilityRequest,
    GoogleCalendarCapabilityAdapter,
)
from personal_intelligence.hermes_bridge.voice_notes_adapter import (
    VoiceNotesAdapter,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError
from personal_intelligence.storage.db import DatabaseManager


class TestMultiSourceFusion(unittest.TestCase):
    """Tests for Multi-Source Ingestion and Cross-Domain Fusion Engine."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_fusion.db"
        self.db_manager = DatabaseManager(db_path=str(self.db_path))
        self.db_manager.initialize_schema()

        self.voice_notes_dir = Path(self.tmp_dir.name) / "voice_notes"
        self.voice_adapter = VoiceNotesAdapter(storage_dir=self.voice_notes_dir)
        self.cal_adapter = GoogleCalendarCapabilityAdapter()
        self.fusion_engine = MultiSourceFusionEngine(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_calendar_adapter_read_only(self) -> None:
        req = CalendarCapabilityRequest(time_range_days=7, read_only=True)
        res = self.cal_adapter.execute_query(req)
        self.assertEqual(res.status, "success")
        self.assertGreater(res.total_events, 0)
        self.assertGreater(res.busy_hours_total, 0.0)

        # Ensure write operations are strictly rejected
        with self.assertRaises(UnauthorizedWriteOperationError):
            self.cal_adapter.execute_query(CalendarCapabilityRequest(read_only=False))

    def test_voice_notes_parsing_and_action_extraction(self) -> None:
        raw_text = """# Strategy & Roadmap Review
Attendees: Sarah Connor, John Doe
Discussed the Q3 delivery schedule and local-first architecture.
- [ ] Deliver final vector search benchmarks by Wednesday
- [ ] Schedule follow-up sync with VP of Engineering
Todo: update documentation repository
"""
        note = self.voice_adapter.parse_note_content(raw_text)
        self.assertEqual(note.title, "Strategy & Roadmap Review")
        self.assertIn("Sarah Connor", note.attendees)
        self.assertEqual(len(note.action_items), 3)
        self.assertIn("Deliver final vector search benchmarks by Wednesday", note.action_items[0])

        saved_path = self.voice_adapter.save_note_file(note)
        self.assertTrue(saved_path.exists())

    def test_cross_domain_fatigue_and_schedule_collision(self) -> None:
        now = datetime.now(timezone.utc)

        # 1. Ingest low sleep event (<6 hours)
        self.fusion_engine.event_store.append(Event(
            id="evt-sleep-deficit-01",
            source="sleep",
            event_type="sleep_session",
            event_time=now - timedelta(hours=8),
            payload={"duration_minutes": 300, "efficiency": 0.72},
        ))

        # 2. Ingest heavy calendar schedule (4.5 hours busy)
        self.fusion_engine.event_store.append(Event(
            id="evt-cal-heavy-01",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=2),
            payload={"summary": "Executive Roadmap Session", "duration_minutes": 180},
        ))
        self.fusion_engine.event_store.append(Event(
            id="evt-cal-heavy-02",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=6),
            payload={"summary": "System Architecture Review", "duration_minutes": 90},
        ))

        # Run multi-source fusion analysis
        conflicts = self.fusion_engine.analyze_cross_domain_correlations()
        self.assertTrue(len(conflicts) > 0)
        
        fatigue_conflicts = [c for c in conflicts if c.conflict_type == "fatigue_schedule_collision"]
        self.assertEqual(len(fatigue_conflicts), 1)
        fc = fatigue_conflicts[0]
        self.assertEqual(fc.severity, "high")
        self.assertIn("health_sleep", fc.domains_involved)
        self.assertIn("google_calendar", fc.domains_involved)
        self.assertTrue(any("[Health]" in e for e in fc.supporting_evidence))
        self.assertTrue(any("[Calendar]" in e for e in fc.supporting_evidence))

        # Synthesize situation
        sits = self.fusion_engine.synthesize_fusion_situations()
        self.assertEqual(len(sits), 1)
        self.assertEqual(sits[0].priority, "high")

    def test_dashboard_data_service_multi_source_endpoints(self) -> None:
        ds = DashboardDataService(db_manager=self.db_manager)

        # 1. Sync Calendar
        cal_res = ds.execute_calendar_sync(time_range_days=7)
        self.assertEqual(cal_res["status"], "success")
        self.assertGreater(cal_res["events_synced"], 0)

        # 2. Ingest Voice Note
        vn_res = ds.execute_voice_note_ingest(
            text="- [ ] Finalize Q3 infrastructure budget before Friday meeting",
            title="Budget Planning Call",
        )
        self.assertEqual(vn_res["status"], "success")
        self.assertEqual(vn_res["action_items_derived"], 1)

        # 3. Get Fusion Status
        fusion_status = ds.get_fusion_status()
        self.assertEqual(fusion_status["status"], "success")
        self.assertIn("google_calendar", fusion_status["streams_connected"])
        self.assertIn("voice_notes", fusion_status["streams_connected"])

        # 4. Ask PI about Schedule Conflicts
        ask_res = ds.ask_engine.ask("Do I have any schedule conflicts or capacity strain today?")
        self.assertIsNotNone(ask_res.answer)
        self.assertTrue(len(ask_res.sources) > 0)

        ds.bg_scheduler.stop()


if __name__ == "__main__":
    unittest.main()
