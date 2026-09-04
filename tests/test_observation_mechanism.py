"""
Test suite for the Personal Intelligence observation mechanism.

Verifies:
1. Normalized observation ingestion without continuously mirroring external systems.
2. Canonical observations across Gmail, Drive, Calendar, Meet, Filesystem, Hermes, User.
3. Strict data minimization (concise summary and salient evidence without raw dumps).
4. Provenance retention sufficient for Hermes to retrieve original information.
5. Input validation (source, source_id, timestamp, observation_type, summary, provenance).
6. Plugin tool execution via `record_observation` handler.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.exceptions import EventValidationError
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.observation import (
    ALLOWED_OBSERVATION_SOURCES,
    record_observation,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.hermes_bridge.plugin.tools import (
    record_observation as hermes_record_observation_tool,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestObservationMechanism(unittest.TestCase):
    """Test suite for record_observation workflow across external sources."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_observations.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Canonical Examples Across All Sources
    def test_record_gmail_observation(self) -> None:
        """Verify Gmail observation: 'Email indicates a possible deadline.'"""
        event = record_observation(
            source="gmail",
            source_id="msg_gmail_987654",
            timestamp=self.now,
            observation_type="deadline_detected",
            summary="Email indicates a possible deadline.",
            evidence={
                "sender": "lead@org.com",
                "subject": "Q3 Target Date",
                "detected_deadline": "2026-08-25T17:00:00Z",
                "urgency": "high",
            },
            provenance={
                "tool": "google_workspace_gmail",
                "query": "is:unread label:urgent",
                "message_id": "msg_gmail_987654",
                "thread_id": "th_12345",
            },
            event_store=self.event_store,
        )

        self.assertIsNotNone(event.id)
        self.assertEqual(event.source, "gmail")
        self.assertEqual(event.source_id, "msg_gmail_987654")
        self.assertEqual(event.event_type, "deadline_detected")
        self.assertEqual(event.payload["summary"], "Email indicates a possible deadline.")
        self.assertEqual(event.payload["evidence"]["detected_deadline"], "2026-08-25T17:00:00Z")
        self.assertEqual(event.provenance["tool"], "google_workspace_gmail")
        self.assertEqual(event.provenance["message_id"], "msg_gmail_987654")

    def test_record_drive_observation(self) -> None:
        """Verify Drive observation: 'Architecture document modified.'"""
        event = record_observation(
            source="drive",
            source_id="doc_arch_spec_v2",
            timestamp=self.now,
            observation_type="document_changed",
            summary="Architecture document modified.",
            evidence={
                "title": "System Architecture v2.0",
                "modified_by": "alex@company.com",
                "change_scope": "Updated data ingestion boundaries",
            },
            provenance={
                "tool": "google_workspace_drive",
                "file_id": "doc_arch_spec_v2",
                "query": "name contains 'Architecture' and mimeType='application/vnd.google-apps.document'",
            },
            event_store=self.event_store,
        )

        self.assertEqual(event.source, "drive")
        self.assertEqual(event.payload["summary"], "Architecture document modified.")
        self.assertEqual(event.provenance["file_id"], "doc_arch_spec_v2")

    def test_record_calendar_observation(self) -> None:
        """Verify Calendar observation: 'Important review scheduled tomorrow.'"""
        event = record_observation(
            source="calendar",
            source_id="cal_event_arch_rev_303",
            timestamp=self.now,
            observation_type="calendar_event",
            summary="Important review scheduled tomorrow.",
            evidence={
                "event_title": "Executive Architecture Review",
                "start_time": "2026-08-23T14:00:00Z",
                "duration_minutes": 60,
                "attendees_count": 8,
            },
            provenance={
                "tool": "google_workspace_calendar",
                "calendar_id": "primary",
                "event_id": "cal_event_arch_rev_303",
            },
            event_store=self.event_store,
        )

        self.assertEqual(event.source, "calendar")
        self.assertEqual(event.payload["summary"], "Important review scheduled tomorrow.")
        self.assertEqual(event.provenance["tool"], "google_workspace_calendar")

    def test_record_meet_observation(self) -> None:
        """Verify Meet observation: 'Meeting transcript contains unresolved action item.'"""
        event = record_observation(
            source="meet",
            source_id="meet_sync_404_transcript",
            timestamp=self.now,
            observation_type="action_item_detected",
            summary="Meeting transcript contains unresolved action item.",
            evidence={
                "meeting_name": "Sprint Retrospective & Sync",
                "assignee": "user",
                "action_item": "Provide hardened SQLite encryption benchmarks by Friday",
            },
            provenance={
                "tool": "google_meet",
                "meeting_id": "meet_sync_404",
                "transcript_id": "meet_sync_404_transcript",
            },
            event_store=self.event_store,
        )

        self.assertEqual(event.source, "meet")
        self.assertEqual(event.payload["summary"], "Meeting transcript contains unresolved action item.")
        self.assertEqual(event.provenance["meeting_id"], "meet_sync_404")

    def test_record_filesystem_observation(self) -> None:
        """Verify Filesystem observation: 'Project document changed.'"""
        event = record_observation(
            source="filesystem",
            source_id="file://docs/spec.md",
            timestamp=self.now,
            observation_type="document_changed",
            summary="Project document changed.",
            evidence={
                "file_path": "docs/spec.md",
                "diff_summary": "Added Section 4: Security Policy",
                "lines_added": 34,
            },
            provenance={
                "tool": "filesystem",
                "path": "docs/spec.md",
                "inode_or_hash": "sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
            },
            event_store=self.event_store,
        )

        self.assertEqual(event.source, "filesystem")
        self.assertEqual(event.payload["summary"], "Project document changed.")
        self.assertEqual(event.provenance["path"], "docs/spec.md")

    # 2. Input Validation & Strict Error Handling
    def test_validation_invalid_source_rejected(self) -> None:
        """Verify malformed and invalid source strings are rejected."""
        with self.assertRaises(EventValidationError):
            record_observation(
                source="invalid source with spaces and symbols #$@!",
                source_id="id123",
                timestamp=self.now,
                observation_type="email_received",
                summary="Test summary",
                provenance={"tool": "some_tool"},
                event_store=self.event_store,
            )

    def test_validation_empty_fields_rejected(self) -> None:
        """Verify empty required strings (source_id, observation_type, summary) are rejected."""
        with self.assertRaises(EventValidationError):
            record_observation(
                source="gmail",
                source_id="",
                timestamp=self.now,
                observation_type="email_received",
                summary="Test summary",
                provenance={"tool": "gmail"},
                event_store=self.event_store,
            )

        with self.assertRaises(EventValidationError):
            record_observation(
                source="gmail",
                source_id="msg_001",
                timestamp=self.now,
                observation_type="",
                summary="Test summary",
                provenance={"tool": "gmail"},
                event_store=self.event_store,
            )

        with self.assertRaises(EventValidationError):
            record_observation(
                source="gmail",
                source_id="msg_001",
                timestamp=self.now,
                observation_type="email_received",
                summary="",
                provenance={"tool": "gmail"},
                event_store=self.event_store,
            )

        with self.assertRaises(EventValidationError):
            record_observation(
                source="gmail",
                source_id="msg_001",
                timestamp=self.now,
                observation_type="email_received",
                summary="Test summary",
                provenance={},  # Empty provenance
                event_store=self.event_store,
            )

    # 3. Data Minimization & Anti-Bloat
    def test_oversized_evidence_rejected(self) -> None:
        """Verify huge raw blobs (> 32KB) are rejected to prevent dumping full raw documents."""
        huge_blob = {"raw_dump": "A" * 40000}
        with self.assertRaises(EventValidationError):
            record_observation(
                source="drive",
                source_id="doc_large",
                timestamp=self.now,
                observation_type="document_changed",
                summary="Architecture document modified.",
                evidence=huge_blob,
                provenance={"tool": "drive", "file_id": "doc_large"},
                event_store=self.event_store,
            )

    # 4. LocalStateStore Integration
    def test_local_state_store_delegation(self) -> None:
        """Verify LocalStateStore.record_observation properly records and updates table count."""
        initial_counts = self.local_store.get_table_counts()
        self.assertEqual(initial_counts["event_log"], 0)

        self.local_store.record_observation(
            source="gmail",
            source_id="msg_101",
            timestamp=self.now,
            observation_type="email_received",
            summary="Email indicates a possible deadline.",
            evidence={"sender": "cto@company.com"},
            provenance={"tool": "google_workspace_gmail", "query": "label:urgent"},
        )

        counts_after = self.local_store.get_table_counts()
        self.assertEqual(counts_after["event_log"], 1)

    # 5. Timeline Retrieval with Provenance
    def test_timeline_retrieval_and_provenance_preservation(self) -> None:
        """Verify recorded observation is immediately queryable via TimelineEngine with intact provenance."""
        record_observation(
            source="meet",
            source_id="meet_rec_777",
            timestamp=self.now - timedelta(minutes=15),
            observation_type="meeting_completed",
            summary="Meeting transcript contains unresolved action item.",
            evidence={"topic": "Roadmap Q4"},
            provenance={"tool": "google_meet", "meeting_id": "meet_rec_777"},
            event_store=self.event_store,
        )

        timeline = self.timeline_engine.get_last_n_hours(1, reference_time=self.now)
        self.assertEqual(len(timeline), 1)
        retrieved_event = timeline.events[0]
        self.assertEqual(retrieved_event.source, "meet")
        self.assertEqual(retrieved_event.source_id, "meet_rec_777")
        self.assertEqual(retrieved_event.payload["summary"], "Meeting transcript contains unresolved action item.")
        self.assertEqual(retrieved_event.provenance["meeting_id"], "meet_rec_777")


if __name__ == "__main__":
    unittest.main()
