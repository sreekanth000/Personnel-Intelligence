"""
Tests for Personal Intelligence Observation Hooks and ObservationManager.

Verifies:
1. Supported Hermes lifecycle and tool hooks (pre_tool_call, post_tool_call, reasoning_outcome).
2. Hook execution does not break normal Hermes behavior even on unexpected/malformed inputs.
3. Selective relevance filtering:
   - Records relevant observations from Gmail, Drive, Calendar, Meet, Filesystem, and Hermes reasoning.
   - Discards transient/irrelevant tool results (ping, echo, empty results, node_modules, temp files).
4. Strict secret scrubbing:
   - Never persists API keys, passwords, bearer tokens, or private keys.
5. Content minimization:
   - Avoids dumping full email bodies or documents, storing concise metadata and summaries with provenance.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.episodes.models import EpisodeStatus, ReasoningEpisode
from personal_intelligence.core.events import EventStore
from personal_intelligence.core.events.observation_manager import ObservationManager

from personal_intelligence.hermes_bridge.plugin.hooks import (
    on_post_tool_call,
    on_pre_tool_call,
    on_reasoning_outcome,
)
from personal_intelligence.storage.db import DatabaseManager


class TestObservationHooks(unittest.TestCase):
    """Test suite verifying Hermes plugin observation hooks and ObservationManager."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_hooks.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.event_store = EventStore(db_manager=self.db_manager)
        self.manager = ObservationManager(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Non-Breaking Safety Guarantees for Normal Hermes Behavior
    # -------------------------------------------------------------------------

    def test_pre_tool_call_hook_approves_cleanly(self) -> None:
        """Verifies pre_tool_call returns approval without blocking or modifying Hermes state."""
        res = on_pre_tool_call("workspace_gmail_search", {"query": "project status"})
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("action"), "approve")

    def test_post_tool_call_handles_malformed_and_exception_inputs_safely(self) -> None:
        """Verifies post_tool_call never raises exceptions on corrupt inputs, None results, or invalid types."""
        # None inputs
        res1 = on_post_tool_call("unknown_tool", {}, None, db_manager=self.db_manager)
        self.assertIsNone(res1)

        # Non-serializable result
        class UnserializableObj:
            pass

        res2 = on_post_tool_call("some_tool", {"arg": "val"}, UnserializableObj(), db_manager=self.db_manager)
        self.assertIsNone(res2)

        # Database manager error simulation
        class BrokenDB:
            def get_connection(self):
                raise RuntimeError("Simulated DB connection failure")

        res3 = on_post_tool_call("gmail_search", {"query": "test"}, {"subject": "Test"}, db_manager=BrokenDB())
        self.assertIsNone(res3)

    # -------------------------------------------------------------------------
    # 2. Selective Relevance Filtering (Do NOT persist every tool result)
    # -------------------------------------------------------------------------

    def test_irrelevant_utility_tools_do_not_create_observations(self) -> None:
        """Verifies transient utilities (ping, echo, health checks) are ignored and not persisted."""
        # Utility tools
        on_post_tool_call("system_ping", {"host": "localhost"}, {"status": "pong"}, db_manager=self.db_manager)
        on_post_tool_call("echo", {"text": "hello world"}, "hello world", db_manager=self.db_manager)
        on_post_tool_call("health_probe", {}, {"healthy": True}, db_manager=self.db_manager)

        # Empty search results
        on_post_tool_call("gmail_search", {"query": "non_existent"}, {"messages": []}, db_manager=self.db_manager)
        on_post_tool_call("drive_search", {"query": "fake_doc"}, [], db_manager=self.db_manager)

        # Noise paths
        on_post_tool_call("read_file", {"path": "/app/node_modules/express/package.json"}, {"name": "express"}, db_manager=self.db_manager)
        on_post_tool_call("read_file", {"path": "/workspace/.git/HEAD"}, "ref: refs/heads/main", db_manager=self.db_manager)

        # Verify nothing was persisted to EventStore
        events = self.event_store.get_recent(limit=50)
        self.assertEqual(len(events), 0, "Irrelevant tool executions should not create observations in EventStore.")

    def test_relevant_gmail_search_creates_normalized_observation(self) -> None:
        """Verifies meaningful email search results create a normalized observation with provenance."""
        email_result = {
            "id": "msg_architect_441",
            "subject": "Architecture Sign-off Required for Friday Milestone",
            "from": "alex@company.com",
            "date": "2026-08-22T14:30:00Z",
            "snippet": "Please review the updated specification before Friday's executive sync.",
        }

        event = on_post_tool_call(
            tool_name="google_workspace_gmail_search",
            tool_args={"query": "subject:Architecture"},
            result=email_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.source, "gmail")
        self.assertEqual(event.source_id, "msg_architect_441")
        self.assertIn("Architecture", event.summary)
        self.assertEqual(event.provenance.get("origin_source"), "gmail")
        self.assertEqual(event.provenance.get("tool_name"), "google_workspace_gmail_search")


    def test_relevant_calendar_event_creates_normalized_observation(self) -> None:
        """Verifies calendar schedule result creates an upcoming milestone observation."""
        calendar_result = {
            "id": "cal_evt_review_01",
            "title": "Quarterly Technical Review",
            "start_time": "2026-08-23T10:00:00Z",
            "end_time": "2026-08-23T11:30:00Z",
            "status": "confirmed",
        }

        event = on_post_tool_call(
            tool_name="google_workspace_calendar_get_event",
            tool_args={"event_id": "cal_evt_review_01"},
            result=calendar_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.source, "calendar")
        self.assertEqual(event.source_id, "cal_evt_review_01")
        self.assertIn("Quarterly Technical Review", event.payload.get("summary", ""))

    def test_relevant_drive_document_creates_normalized_observation(self) -> None:
        """Verifies drive document inspection creates a document_changed observation."""
        drive_result = {
            "file_id": "doc_specs_99",
            "title": "Architecture_V2_Draft.gdoc",
            "modified_time": "2026-08-22T11:00:00Z",
            "snippet": "Approved by senior engineering team.",
        }

        event = on_post_tool_call(
            tool_name="google_workspace_drive_get_file",
            tool_args={"file_id": "doc_specs_99"},
            result=drive_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.source, "drive")
        self.assertEqual(event.source_id, "doc_specs_99")

    def test_relevant_meet_transcript_creates_meeting_decision_observation(self) -> None:
        """Verifies meet transcript analysis creates a meeting_decision observation."""
        meet_result = {
            "id": "meet_sync_101",
            "title": "Architecture Sign-off Call",
            "action_items": ["Alex will update RFC", "Bob will deploy staging"],
            "summary": "Team agreed on hybrid schema architecture.",
        }

        event = on_post_tool_call(
            tool_name="google_meet_get_transcript",
            tool_args={"meeting_id": "meet_sync_101"},
            result=meet_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.source, "meet")
        self.assertEqual(event.event_type, "meeting_decision")

    def test_relevant_filesystem_project_creates_document_observation(self) -> None:
        """Verifies editing/reading project files creates a normalized filesystem observation."""
        file_result = {
            "path": "c:/Users/gopit/Personal Intelligence/architecture_plan.md",
            "snippet": "# System Architecture V2\nCore runtime bridge and observation manager.",
        }

        event = on_post_tool_call(
            tool_name="filesystem_read_file",
            tool_args={"path": "c:/Users/gopit/Personal Intelligence/architecture_plan.md"},
            result=file_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.source, "filesystem")

    def test_high_priority_reasoning_outcome_hook(self) -> None:
        """Verifies high-priority reasoning outcome creates a synthesized observation."""
        episode = ReasoningEpisode(
            episode_id="ep-outcome-777",
            situation_id="sit-urgent-01",
            outcome_evaluation="Severe sleep deficit necessitates rescheduling interval workout.",
            metadata={"urgency": "high", "actionability": "high"},
        )

        event = on_reasoning_outcome(episode, db_manager=self.db_manager)
        self.assertIsNotNone(event)
        self.assertEqual(event.source, "hermes")
        self.assertEqual(event.source_id, "episode_ep-outcome-777")
        self.assertEqual(event.provenance.get("episode_id"), "ep-outcome-777")


    # -------------------------------------------------------------------------
    # 3. Strict Secret Scrubbing (Do NOT store secrets)
    # -------------------------------------------------------------------------

    def test_secrets_and_api_keys_are_redacted_from_observations(self) -> None:
        """Verifies API keys, Bearer tokens, GitHub tokens, and passwords are scrubbed before storage."""
        sensitive_result = {
            "id": "msg_credentials_55",
            "subject": "Deployment Credentials",
            "api_key": "AIzaSyD9876543210abcdefghijklmnopqrs",
            "token": "ghp_1234567890abcdefghijklmnopqrstuv",
            "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID",
            "snippet": "Here is the new API key: api_key='secret_super_pass_12345'",
        }

        event = on_post_tool_call(
            tool_name="gmail_fetch_message",
            tool_args={"id": "msg_credentials_55", "secret_auth": "pass12345678"},
            result=sensitive_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        payload_str = json.dumps(event.payload)

        # Assert no raw secrets remain in stored payload
        self.assertNotIn("AIzaSyD9876543210", payload_str)
        self.assertNotIn("ghp_1234567890", payload_str)
        self.assertNotIn("secret_super_pass_12345", payload_str)
        self.assertNotIn("pass12345678", payload_str)
        self.assertIn("[REDACTED", payload_str)

    # -------------------------------------------------------------------------
    # 4. Content Minimization (Do NOT store complete email/doc content unnecessarily)
    # -------------------------------------------------------------------------

    def test_large_content_is_trimmed_and_summarized_without_bloat(self) -> None:
        """Verifies large 50KB email body is summarized and truncated rather than dumping massive raw text."""
        giant_body = "A" * 50000  # 50KB text
        email_result = {
            "id": "msg_huge_01",
            "subject": "Monthly Newsletter and System Update",
            "body": giant_body,
            "snippet": "Monthly system updates for engineering team.",
        }

        event = on_post_tool_call(
            tool_name="gmail_read_thread",
            tool_args={"id": "msg_huge_01"},
            result=email_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(event)
        payload_str = json.dumps(event.payload)
        # Stored payload must be compact, not 50KB+
        self.assertLess(len(payload_str), 2000)
        self.assertIn("Monthly Newsletter", event.payload.get("summary", ""))

    # -------------------------------------------------------------------------
    # 5. Duplicate Prevention & Provenance Preservation
    # -------------------------------------------------------------------------

    def test_duplicate_observations_are_prevented(self) -> None:
        """Verifies duplicate tool executions with identical data do not create duplicate rows."""
        sample_result = {
            "id": "msg_dup_test_01",
            "subject": "Status Meeting Notes",
            "snippet": "Action items confirmed.",
        }

        # 1. First execution -> persists event
        evt1 = on_post_tool_call(
            tool_name="gmail_search",
            tool_args={"query": "status meeting"},
            result=sample_result,
            db_manager=self.db_manager,
        )
        self.assertIsNotNone(evt1)

        # 2. Re-execution with exact same parameters & result -> deduplicated
        evt2 = on_post_tool_call(
            tool_name="gmail_search",
            tool_args={"query": "status meeting"},
            result=sample_result,
            db_manager=self.db_manager,
        )
        self.assertIsNotNone(evt2)

        # Verify event count in EventStore
        all_events = self.event_store.get_recent(limit=100)
        matching = [e for e in all_events if e.source_id == "msg_dup_test_01"]
        self.assertEqual(len(matching), 1, "Duplicate observation should not create multiple rows in event_log.")

    def test_provenance_is_strictly_preserved(self) -> None:
        """Verifies stored observation retains source, source_id, timestamp, observation_type, summary, structured_data, provenance."""
        doc_result = {
            "file_id": "doc_arch_spec_77",
            "title": "Architecture Specification V2",
            "snippet": "Approved for Q3 roadmap.",
        }

        evt = on_post_tool_call(
            tool_name="google_workspace_drive_get_file",
            tool_args={"file_id": "doc_arch_spec_77"},
            result=doc_result,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(evt)
        self.assertEqual(evt.source, "drive")
        self.assertEqual(evt.source_id, "doc_arch_spec_77")
        self.assertEqual(evt.event_type, "document_changed")
        self.assertIsNotNone(evt.event_time)
        self.assertIn("Architecture Specification V2", evt.payload.get("summary", ""))
        self.assertIn("structured_data", evt.__dict__ if hasattr(evt, "structured_data") else evt.payload)
        self.assertIsNotNone(evt.provenance)
        self.assertEqual(evt.provenance.get("origin_source"), "drive")
        self.assertEqual(evt.provenance.get("tool_name"), "google_workspace_drive_get_file")


if __name__ == "__main__":
    unittest.main()

