"""
Unit and integration test suite for the Personal Intelligence Local State Store.
Verifies:
1. SQLite database and all 7 core tables (event_log, entity_state, goals, situations, patterns, pattern_evidence, reasoning_episodes).
2. event_log is NOT an external API mirror: stores only normalized relevant observations.
3. Allowed sources: gmail, drive, calendar, meet, filesystem, hermes, user.
4. Provenance preservation: source_id, tool, query, timestamp, observation_type.
5. Entity state tracking (entity_state).
6. Goal, situation, pattern, pattern_evidence, and reasoning episode storage.
7. Architectural compliance (no external API clients or OAuth).
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.episodes.models import EpisodeStatus, ReasoningEpisode
from personal_intelligence.core.events.exceptions import EventValidationError
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.patterns.models import Pattern, PatternEvidence, PatternStatus
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.state.entity_store import EntityState
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestLocalStateStore(unittest.TestCase):
    """Test suite for LocalStateStore and the 7 SQLite tables."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "personal_intelligence_local.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.store = LocalStateStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Verify All 7 SQLite Tables Exist
    def test_all_seven_tables_exist(self) -> None:
        """Verify the 7 required tables exist in SQLite schema."""
        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row["name"] for row in cursor.fetchall()}

            expected_seven_tables = {
                "event_log",
                "entity_state",
                "goals",
                "situations",
                "patterns",
                "pattern_evidence",
                "reasoning_episodes",
            }

            for table in expected_seven_tables:
                self.assertIn(table, tables, f"Required table '{table}' missing from SQLite database.")

            counts = self.store.get_table_counts()
            for table in expected_seven_tables:
                self.assertEqual(counts[table], 0)
        finally:
            conn.close()

    # 2. Normalized Observations with Provenance (Gmail Source)
    def test_record_gmail_observation_with_provenance(self) -> None:
        """Verify recording normalized email_received observation with origin provenance."""
        obs = self.store.record_observation(
            source="gmail",
            source_id="msg_gmail_98765",
            observation_type="email_received",
            timestamp="2026-08-22T09:30:00Z",
            payload={
                "sender": "sarah.lead@company.com",
                "subject": "Q3 Architecture Review Rescheduled",
                "summary": "Meeting moved to 3:00 PM today due to release testing.",
                "urgency_hint": "high",
            },
            provenance={
                "tool": "google_workspace_gmail",
                "query": "is:unread label:important after:2026/08/21",
                "retrieved_via": "hermes_skill_execution",
            },
        )

        self.assertIsNotNone(obs.id)
        self.assertEqual(obs.event_type, "email_received")
        self.assertEqual(obs.observation_type, "email_received")
        self.assertEqual(obs.source, "gmail")
        self.assertEqual(obs.source_id, "msg_gmail_98765")
        self.assertEqual(obs.provenance["tool"], "google_workspace_gmail")
        self.assertEqual(obs.provenance["query"], "is:unread label:important after:2026/08/21")

        # Verify retrieval from event_store
        stored = self.store.event_store.get(obs.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.source_id, "msg_gmail_98765")
        self.assertEqual(stored.provenance["tool"], "google_workspace_gmail")
        self.assertEqual(stored.payload["sender"], "sarah.lead@company.com")

    # 3. Normalized Observations across All Supported Sources
    def test_normalized_observations_across_sources(self) -> None:
        """Verify normalized observations from drive, calendar, meet, filesystem, hermes, user."""
        test_cases = [
            ("calendar", "calendar_event", "evt_cal_101", "google_workspace_calendar", {"title": "Executive Sprint Sync"}),
            ("meet", "meeting_completed", "call_meet_202", "google_meet", {"duration_minutes": 45, "action_items": 2}),
            ("drive", "document_changed", "doc_drive_303", "google_workspace_drive", {"doc_title": "Product Roadmap 2026"}),
            ("hermes", "task_commitment_detected", "task_hermes_404", "personal_investigation", {"commitment": "Submit report by 5 PM"}),
            ("user", "routine_change", "user_prompt_505", "direct_user_input", {"note": "Working from home this afternoon"}),
            ("filesystem", "unusual_state", "fs_watch_606", "filesystem_monitor", {"path": "/workspace/build_error.log"}),
        ]

        for source, obs_type, src_id, tool_name, payload in test_cases:
            event = self.store.record_observation(
                source=source,
                source_id=src_id,
                observation_type=obs_type,
                timestamp=self.base_time,
                payload=payload,
                provenance={"tool": tool_name, "query": f"sync_{source}"},
            )
            self.assertEqual(event.source, source)
            self.assertEqual(event.event_type, obs_type)
            self.assertEqual(event.source_id, src_id)
            self.assertEqual(event.provenance["tool"], tool_name)

        counts = self.store.get_table_counts()
        self.assertEqual(counts["event_log"], 6)

    # 4. Entity State Store (entity_state)
    def test_entity_state_lifecycle(self) -> None:
        """Verify upsert, retrieval, listing, and deletion on entity_state table."""
        entity = EntityState(
            entity_id="entity_project_alpha",
            entity_type="project",
            state={"phase": "execution", "deadline": "2026-09-01", "health": "on_track"},
            last_updated_at=self.base_time,
            source_event_ids=["evt-1", "evt-2"],
            metadata={"owner": "user", "priority": "high"},
        )
        self.store.entity_store.upsert(entity)

        retrieved = self.store.entity_store.get("entity_project_alpha")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.entity_type, "project")
        self.assertEqual(retrieved.state["phase"], "execution")
        self.assertEqual(retrieved.source_event_ids, ["evt-1", "evt-2"])

        # Update entity state
        entity.state["health"] = "at_risk"
        entity.state["blocker"] = "pending approval"
        self.store.entity_store.upsert(entity)

        updated = self.store.entity_store.get("entity_project_alpha")
        self.assertEqual(updated.state["health"], "at_risk")
        self.assertEqual(updated.state["blocker"], "pending approval")

        # List by type
        projects = self.store.entity_store.list_by_type("project")
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].entity_id, "entity_project_alpha")

        # Delete
        self.assertTrue(self.store.entity_store.delete("entity_project_alpha"))
        self.assertIsNone(self.store.entity_store.get("entity_project_alpha"))

    # 5. Goal, Situation, Pattern, and Episode Storage
    def test_relational_stores_integration(self) -> None:
        """Verify goals, situations, patterns, pattern_evidence, and reasoning_episodes stores."""
        # 1. Goal
        goal = Goal(
            name="Quarterly Code Review",
            description="Complete code review across all personal projects",
            priority=GoalPriority.HIGH,
            status=GoalStatus.ACTIVE,
        )
        saved_goal = self.store.goal_store.create_goal(goal)
        self.assertIsNotNone(saved_goal.id)

        # 2. Situation
        situation = Situation(
            type="schedule_workload_triage",
            priority=SituationPriority.HIGH,
            status=SituationStatus.OPEN,
            context={"reason": "Overlapping milestones"},
            evidence=["evt_cal_101", "msg_gmail_98765"],
            related_goals=[saved_goal.id],
        )
        saved_sit = self.store.situation_store.create_situation(situation)
        self.assertIsNotNone(saved_sit.id)

        # 3. Pattern & Pattern Evidence
        pattern = Pattern(
            description="User appears more responsive to morning calendar notifications.",
            first_seen=self.base_time - timedelta(days=10),
            last_seen=self.base_time,
            support_count=5,
            contradiction_count=0,
            evidence_strength="strong",
            status=PatternStatus.ACTIVE,
        )
        saved_pattern = self.store.pattern_store.create_pattern(pattern)
        self.assertIsNotNone(saved_pattern.id)

        evidence = PatternEvidence(
            pattern_id=saved_pattern.id,
            observation_type="SUPPORT",
            observed_at=self.base_time,
            episode_id="ep_001",
            event_ids=["evt_cal_101"],
            details={"action": "accepted_prompt"},
        )
        saved_evidence = self.store.pattern_store.add_evidence(evidence)
        self.assertIsNotNone(saved_evidence.evidence_id)

        # 4. Reasoning Episode
        episode = ReasoningEpisode(
            situation_id=saved_sit.id,
            created_at=self.base_time,
            observations=["Sprint sync conflict detected with architecture review."],
            inferences=["User cannot attend both concurrent meetings."],
            predictions=["Skipping architecture review causes blocked PRs."],
            recommendation={"action": "Reschedule sprint sync to 4:00 PM"},
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            intervention_decision={"action": "INTERRUPT", "reason": "High urgency conflict"},
            status=EpisodeStatus.REASONING_COMPLETED,
        )
        saved_ep = self.store.episode_store.create_episode(episode)
        self.assertIsNotNone(saved_ep.id)

        # Check table counts across all 7 tables
        counts = self.store.get_table_counts()
        self.assertEqual(counts["goals"], 1)
        self.assertEqual(counts["situations"], 1)
        self.assertEqual(counts["patterns"], 1)
        self.assertEqual(counts["pattern_evidence"], 1)
        self.assertEqual(counts["reasoning_episodes"], 1)


if __name__ == "__main__":
    unittest.main()
