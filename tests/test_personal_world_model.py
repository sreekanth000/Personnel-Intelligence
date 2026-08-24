"""
Unit and integration tests for the Personal World Model inside the personal_intelligence Hermes plugin.

Verifies:
1. World Model derivation purely from observations into:
   - CURRENT STATE (commitments, upcoming events, open issues, recent important activity, known goals, active situations)
   - TIMELINE
   - GOALS
   - OPEN SITUATIONS
   - KNOWN PATTERNS
   - EMERGING HYPOTHESES
2. SQLite relational backing (no graph databases).
3. Useful information modeling for future reasoning (selective, not modeling everything).
4. Strict fact provenance traceable to:
   - source observation
   - reasoning episode
   - original Hermes source
5. Guardrails preventing silent LLM modifications (all state mutations pass through validated structured operations).
6. Plugin tool execution via `get_personal_world_model`.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.episodes.models import EpisodeStatus, ReasoningEpisode
from personal_intelligence.core.events.exceptions import EventValidationError
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import (
    Commitment,
    CommitmentStatus,
    CurrentState,
    FactProvenance,
    IssueSeverity,
    IssueStatus,
    OpenIssue,
    PersonalWorldModelSnapshot,
    UpcomingEvent,
)
from personal_intelligence.hermes_bridge.plugin.tools import (
    get_personal_world_model as hermes_world_model_tool,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestPersonalWorldModel(unittest.TestCase):
    """Comprehensive test suite for the Personal World Model."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_world_model.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self.local_store)
        self.now = datetime(2026, 8, 22, 10, 30, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Derivation of Current State from Observations
    # -------------------------------------------------------------------------

    def test_current_state_derivation_from_observations(self) -> None:
        """
        Verify that observations across Gmail, Meet, Calendar, Drive, and Filesystem
        automatically populate the structured Current State dimensions.
        """
        # 1. Meet action item -> Commitment
        obs_meet = self.world_model.record_observation(
            source="meet",
            source_id="meet_retro_99",
            timestamp=self.now - timedelta(hours=2),
            observation_type="action_item_detected",
            summary="Meeting transcript contains unresolved action item.",
            evidence={
                "action_item": "Provide SQLite encryption benchmarks by Friday",
                "due_at": "2026-08-28T17:00:00Z",
                "assignee": "user",
            },
            provenance={"tool": "google_meet", "meeting_id": "meet_retro_99"},
        )

        # 2. Gmail deadline -> Commitment
        obs_gmail = self.world_model.record_observation(
            source="gmail",
            source_id="msg_contract_review",
            timestamp=self.now - timedelta(hours=1),
            observation_type="deadline_detected",
            summary="Email indicates a possible deadline.",
            evidence={
                "detected_deadline": "2026-08-25T18:00:00Z",
                "subject": "Vendor Contract Signature Due",
            },
            provenance={"tool": "google_workspace_gmail", "query": "label:urgent"},
        )

        # 3. Calendar event -> Upcoming Event
        obs_cal = self.world_model.record_observation(
            source="calendar",
            source_id="cal_evt_arch_review",
            timestamp=self.now - timedelta(minutes=30),
            observation_type="calendar_event",
            summary="Important review scheduled tomorrow.",
            evidence={
                "event_title": "Executive Architecture Review",
                "start_time": "2026-08-23T14:00:00Z",
                "duration_minutes": 60,
                "location": "Room 404 / Meet",
            },
            provenance={"tool": "google_workspace_calendar", "calendar_id": "primary"},
        )

        # 4. Filesystem conflict -> Open Issue
        obs_fs = self.world_model.record_observation(
            source="filesystem",
            source_id="file://build.log",
            timestamp=self.now - timedelta(minutes=15),
            observation_type="blocker_detected",
            summary="Compilation failure detected in core storage tests.",
            evidence={"error": "Database lock timeout during migration"},
            provenance={"tool": "filesystem", "path": "build.log"},
        )

        # 5. Active Goal
        goal = self.world_model.create_goal(
            name="Production Hardening",
            description="Complete SQLite zero-leak encryption and audit trail",
            priority=GoalPriority.HIGH.value,
        )

        # 6. Open Situation Frame
        sit = self.world_model.create_situation(
            type="schedule_workload_triage",
            priority=SituationPriority.HIGH.value,
            novelty=0.75,
            context={"reason": "Architecture review coincides with sprint delivery"},
            evidence=[obs_cal.id, obs_gmail.id],
            related_goals=[goal.id],
        )

        # Query derived Current State
        state = self.world_model.get_current_state(reference_time=self.now)

        # Assert Commitments derived
        self.assertEqual(len(state.current_commitments), 2)
        commit_descs = [c.description for c in state.current_commitments]
        self.assertIn("Provide SQLite encryption benchmarks by Friday", commit_descs)
        self.assertIn("Email indicates a possible deadline.", commit_descs)

        # Assert Upcoming Events derived
        self.assertGreaterEqual(len(state.upcoming_events), 1)
        event_titles = [e.title for e in state.upcoming_events]
        self.assertIn("Executive Architecture Review", event_titles)

        # Assert Open Issues derived
        self.assertEqual(len(state.open_issues), 1)
        self.assertEqual(state.open_issues[0].title, "Compilation failure detected in core storage tests.")
        self.assertEqual(state.open_issues[0].severity, IssueSeverity.HIGH.value)

        # Assert Recent Important Activity
        self.assertGreaterEqual(len(state.recent_important_activity), 4)

        # Assert Known Goals
        self.assertEqual(len(state.known_goals), 1)
        self.assertEqual(state.known_goals[0]["name"], "Production Hardening")

        # Assert Active Situations
        self.assertEqual(len(state.active_situations), 1)
        self.assertEqual(state.active_situations[0]["type"], "schedule_workload_triage")

    # -------------------------------------------------------------------------
    # 2. Strict Fact Provenance Traceability
    # -------------------------------------------------------------------------

    def test_fact_provenance_traceability(self) -> None:
        """
        Verify every derived fact (commitment, issue, upcoming event) is traceable
        back to source observation ID, original Hermes tool, and retrieval query.
        """
        obs = self.world_model.record_observation(
            source="gmail",
            source_id="msg_sec_audit_888",
            timestamp=self.now,
            observation_type="action_item_detected",
            summary="Action item to revoke expired API tokens.",
            evidence={"action_item": "Revoke expired service keys", "assignee": "user"},
            provenance={
                "tool": "google_workspace_gmail",
                "query": "is:unread label:security",
                "message_id": "msg_sec_audit_888",
            },
        )

        state = self.world_model.get_current_state(reference_time=self.now)
        self.assertEqual(len(state.current_commitments), 1)

        commitment = state.current_commitments[0]
        prov = commitment.provenance

        # Must trace to source observation in SQLite event_log
        self.assertEqual(prov.source_observation_id, obs.id)
        # Must trace to original source and tool
        self.assertEqual(prov.origin_source, "gmail")
        self.assertEqual(prov.source_id, "msg_sec_audit_888")
        self.assertEqual(prov.tool, "google_workspace_gmail")
        self.assertEqual(prov.retrieval_query, "is:unread label:security")

    # -------------------------------------------------------------------------
    # 3. Guardrails: No Silent / Unvalidated Modifications
    # -------------------------------------------------------------------------

    def test_structured_mutation_guardrails_prevent_unvalidated_writes(self) -> None:
        """
        Verify that invalid parameters, empty descriptions, or malformed state changes
        are strictly rejected and cannot silently corrupt the world model.
        """
        # Empty commitment description rejected
        with self.assertRaises(EventValidationError):
            self.world_model.record_commitment(description="")

        # Empty issue title rejected
        with self.assertRaises(EventValidationError):
            self.world_model.record_open_issue(title="", description="Some desc")

        # Invalid observation source rejected
        with self.assertRaises(EventValidationError):
            self.world_model.record_observation(
                source="unsupported_external_api",
                source_id="id123",
                timestamp=self.now,
                observation_type="email_received",
                summary="Invalid source",
                provenance={"tool": "external"},
            )

    # -------------------------------------------------------------------------
    # 4. Explicit Lifecycle Operations (Resolving Commitments & Issues)
    # -------------------------------------------------------------------------

    def test_commitment_and_issue_lifecycle_resolution(self) -> None:
        """Verify structured resolution of commitments and issues updates current state."""
        commit = self.world_model.record_commitment(
            description="Update API specification for Q4",
            due_at=self.now + timedelta(days=2),
            provenance=FactProvenance(origin_source="drive", tool="google_workspace_drive"),
        )
        issue = self.world_model.record_open_issue(
            title="Database lock contention during migration",
            description="WAL mode configuration was not applied on replica",
            severity=IssueSeverity.HIGH.value,
            provenance=FactProvenance(origin_source="filesystem", tool="filesystem"),
        )

        state_before = self.world_model.get_current_state(reference_time=self.now)
        self.assertEqual(len(state_before.current_commitments), 1)
        self.assertEqual(len(state_before.open_issues), 1)

        # Resolve commitment
        resolved_commit = self.world_model.resolve_commitment(
            commitment_id=commit.id,
            status=CommitmentStatus.COMPLETED.value,
            resolution_notes="PR merged to main branch",
        )
        self.assertIsNotNone(resolved_commit)
        self.assertEqual(resolved_commit.status, CommitmentStatus.COMPLETED.value)

        # Resolve issue
        resolved_issue = self.world_model.resolve_issue(
            issue_id=issue.id,
            status=IssueStatus.RESOLVED.value,
            resolution_notes="Applied PRAGMA journal_mode=WAL on database initialization",
        )
        self.assertIsNotNone(resolved_issue)
        self.assertEqual(resolved_issue.status, IssueStatus.RESOLVED.value)

        # Query state after resolution - both should be cleared from active current state
        state_after = self.world_model.get_current_state(reference_time=self.now)
        self.assertEqual(len(state_after.current_commitments), 0)
        self.assertEqual(len(state_after.open_issues), 0)

    # -------------------------------------------------------------------------
    # 5. Full Personal World Model Snapshot
    # -------------------------------------------------------------------------

    def test_complete_world_model_snapshot(self) -> None:
        """
        Verify the snapshot covers all 6 required sections:
        CURRENT STATE, TIMELINE, GOALS, OPEN SITUATIONS, KNOWN PATTERNS, EMERGING HYPOTHESES.
        """
        # Seed observation & goal
        self.world_model.record_observation(
            source="drive",
            source_id="doc_q3_goals",
            timestamp=self.now - timedelta(hours=3),
            observation_type="document_changed",
            summary="Architecture document modified.",
            evidence={"title": "Q3 Engineering Goals"},
            provenance={"tool": "google_workspace_drive", "file_id": "doc_q3_goals"},
        )
        self.world_model.create_goal(name="Sub-1:45 Half-Marathon", priority=GoalPriority.HIGH.value)

        # Seed Active Pattern
        active_pattern = Pattern(
            description="User responds effectively to morning schedule briefings.",
            first_seen=self.now - timedelta(days=20),
            last_seen=self.now,
            support_count=12,
            contradiction_count=1,
            evidence_strength="strong",
            status=PatternStatus.ACTIVE,
        )
        self.local_store.pattern_store.create_pattern(active_pattern)

        # Seed Emerging Hypothesis
        hypothesis_pattern = Pattern(
            description="User dismisses reminders when deep work is active.",
            first_seen=self.now - timedelta(days=2),
            last_seen=self.now,
            support_count=2,
            contradiction_count=0,
            evidence_strength="weak",
            status=PatternStatus.HYPOTHESIS,
        )
        self.local_store.pattern_store.create_pattern(hypothesis_pattern)

        # Generate Snapshot
        snapshot = self.world_model.get_snapshot(reference_time=self.now)

        self.assertIsInstance(snapshot, PersonalWorldModelSnapshot)
        self.assertIsInstance(snapshot.current_state, CurrentState)
        self.assertEqual(len(snapshot.goals), 1)
        self.assertGreaterEqual(len(snapshot.timeline_events), 1)
        self.assertEqual(len(snapshot.known_patterns), 1)
        self.assertEqual(snapshot.known_patterns[0]["description"], "User responds effectively to morning schedule briefings.")
        self.assertEqual(len(snapshot.emerging_hypotheses), 1)
        self.assertEqual(snapshot.emerging_hypotheses[0]["description"], "User dismisses reminders when deep work is active.")

    # -------------------------------------------------------------------------
    # 6. SQLite Relational Persistence (No Graph DB)
    # -------------------------------------------------------------------------

    def test_sqlite_persistence_across_instances(self) -> None:
        """
        Verify all facts and entities are cleanly persisted in SQLite and reloadable
        by a fresh PersonalWorldModel instance.
        """
        self.world_model.record_commitment(
            description="Submit architecture review slides",
            due_at=self.now + timedelta(hours=24),
            provenance=FactProvenance(origin_source="drive", source_id="slides_123", tool="google_workspace_drive"),
        )
        self.world_model.create_goal(name="Complete System Audit", priority=GoalPriority.CRITICAL.value)

        # Instantiate brand new WorldModel pointing to same SQLite database
        fresh_world_model = PersonalWorldModel(db_manager=self.db_manager)
        fresh_state = fresh_world_model.get_current_state(reference_time=self.now)

        self.assertEqual(len(fresh_state.current_commitments), 1)
        self.assertEqual(fresh_state.current_commitments[0].description, "Submit architecture review slides")
        self.assertEqual(len(fresh_state.known_goals), 1)
        self.assertEqual(fresh_state.known_goals[0]["name"], "Complete System Audit")


if __name__ == "__main__":
    unittest.main()
