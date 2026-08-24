"""
Unit Tests for ReasoningEpisode as Central Learning and Audit Record.

Validates:
1. Complete capture of 14 dimensions:
   - episode_id
   - situation_id
   - timestamp
   - observations_used
   - evidence
   - inferences
   - predictions
   - recommendations
   - intervention_decision
   - user_response (initially null)
   - outcome (initially null)
   - provenance
   - model/runtime metadata
   - parse status
2. Interaction Pattern Learning consumes reasoning_episodes directly as empirical evidence.
3. No separate RecommendationMemory or ReasoningMemory table exists; reasoning_episodes is unified.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import tempfile
import unittest

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.patterns import (
    LearningEngine,
    PatternEngine,
    PatternStatus,
    PatternStore,
    PatternType,
)
from personal_intelligence.core.policy import PolicyAction, UserContext
from personal_intelligence.storage.db import DatabaseManager


class TestReasoningEpisodesUnifiedRecord(unittest.TestCase):
    """Test suite verifying reasoning_episodes as the central learning/audit record."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_unified_episodes.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.pattern_engine = PatternEngine(pattern_store=self.pattern_store)
        self.now = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. 14 Central Learning & Audit Dimensions
    # -------------------------------------------------------------------------

    def test_complete_14_dimensions_capture_in_episode(self) -> None:
        """
        Verify that ReasoningEpisode captures all 14 central audit/learning record dimensions,
        with user_response and outcome initially null.
        """
        episode = self.episode_store.create_episode(
            episode_id="ep-audit-001",
            situation_id="sit-deliverable-01",
            timestamp=self.now,
            observations_used=[
                "Drive file 'Arch_Doc_V1' not modified in 72 hours",
                "Calendar review scheduled for 15:00 today",
            ],
            evidence=["drive:file_991", "calendar:event_102"],
            inferences=["Deliverable milestone will be missed without documentation review."],
            predictions=["Review session will be blocked or delayed."],
            recommendations=["Prepare architecture document."],
            intervention_decision={
                "action": PolicyAction.BRIEFING.value,
                "reason": "Non-emergency documentation gap queued for morning digest.",
                "user_context": UserContext.AVAILABLE.value,
            },
            user_response=None,  # Initially null
            outcome=None,        # Initially null
            provenance=[
                {"source": "google_workspace_drive", "timestamp": "2026-08-23T08:00:00Z"},
                {"source": "google_workspace_calendar", "timestamp": "2026-08-23T09:00:00Z"},
            ],
            runtime_metadata={
                "model": "hermes-agent-v1",
                "duration_ms": 320,
                "attempts": 1,
            },
            parse_status="valid",
            status=EpisodeStatus.REASONING_COMPLETED.value,
        )

        # 1. episode_id
        self.assertEqual(episode.episode_id, "ep-audit-001")
        self.assertEqual(episode.id, "ep-audit-001")

        # 2. situation_id
        self.assertEqual(episode.situation_id, "sit-deliverable-01")

        # 3. timestamp
        self.assertEqual(episode.timestamp, self.now)
        self.assertEqual(episode.created_at, self.now)

        # 4. observations_used
        self.assertEqual(len(episode.observations_used), 2)
        self.assertIn("Drive file 'Arch_Doc_V1'", episode.observations_used[0])

        # 5. evidence
        self.assertIn("drive:file_991", episode.evidence)

        # 6. inferences
        self.assertEqual(len(episode.inferences), 1)

        # 7. predictions
        self.assertEqual(len(episode.predictions), 1)

        # 8. recommendations
        self.assertEqual(episode.recommendations, ["Prepare architecture document."])

        # 9. intervention_decision
        self.assertEqual(episode.intervention_decision["action"], PolicyAction.BRIEFING.value)

        # 10. user_response (initially null)
        self.assertIsNone(episode.user_response)

        # 11. outcome (initially null)
        self.assertIsNone(episode.outcome)

        # 12. provenance
        self.assertEqual(len(episode.provenance), 2)
        self.assertEqual(episode.provenance[0]["source"], "google_workspace_drive")

        # 13. model/runtime metadata
        self.assertEqual(episode.runtime_metadata["model"], "hermes-agent-v1")
        self.assertEqual(episode.runtime_metadata["duration_ms"], 320)

        # 14. parse status
        self.assertEqual(episode.parse_status, "valid")

        # Verify serialization contains all dimensions
        d = episode.to_dict()
        for key in ["episode_id", "situation_id", "timestamp", "observations_used", "evidence",
                    "inferences", "predictions", "recommendations", "intervention_decision",
                    "user_response", "outcome", "provenance", "runtime_metadata", "parse_status"]:
            self.assertIn(key, d)

    # -------------------------------------------------------------------------
    # 2. Example Lifecycle: Recommendation -> Intervention -> Response -> Outcome
    # -------------------------------------------------------------------------

    def test_example_user_response_and_outcome_lifecycle(self) -> None:
        """
        Tests the exact prompt example:
        Recommendation: "Prepare architecture document."
        Intervention: BRIEFING
        User response: "Done"
        Outcome: Architecture document completed.
        """
        # Step 1: Initial episode with recommendation and BRIEFING intervention
        episode = self.episode_store.create_episode(
            episode_id="ep-arch-doc-1",
            situation_id="sit-arch-01",
            recommendations=["Prepare architecture document."],
            intervention_decision={
                "action": PolicyAction.BRIEFING.value,
                "reason": "Queued for scheduled morning digest.",
            },
            status=EpisodeStatus.INTERVENTION_DELIVERED.value,
        )
        self.assertIsNone(episode.user_response)
        self.assertIsNone(episode.outcome)

        # Step 2: User responds "Done"
        updated_resp = self.episode_store.record_user_response(
            episode_id=episode.id,
            response=RecommendationResult.COMPLETED.value,
            feedback_notes="Done",
        )
        self.assertIsNotNone(updated_resp)
        self.assertEqual(updated_resp.user_response["response"], RecommendationResult.COMPLETED.value)
        self.assertEqual(updated_resp.user_response["feedback_notes"], "Done")

        # Step 3: Longitudinal outcome recorded
        updated_outcome = self.episode_store.record_outcome(
            episode_id=episode.id,
            outcome_status=RecommendationResult.COMPLETED.value,
            evaluation_notes="Architecture document completed.",
            success=True,
        )
        self.assertIsNotNone(updated_outcome)
        self.assertEqual(updated_outcome.outcome["evaluation_notes"], "Architecture document completed.")
        self.assertTrue(updated_outcome.outcome["success"])

    # -------------------------------------------------------------------------
    # 3. Interaction Pattern Learning Consumes Unified reasoning_episodes
    # -------------------------------------------------------------------------

    def test_interaction_pattern_learning_from_unified_episodes(self) -> None:
        """
        Verify that PatternEngine discovers interaction patterns directly from
        reasoning_episodes without any secondary memory table.
        """
        # Ingest 4 longitudinal episodes with user response & outcome records
        eps = []
        for i in range(4):
            ep = self.episode_store.create_episode(
                episode_id=f"ep-learn-{i}",
                situation_id=f"sit-learn-{i}",
                created_at=self.now + timedelta(days=i),
                recommendations=["Review and prepare architecture document before 14:00 signoff."],
                intervention_decision={
                    "action": PolicyAction.BRIEFING.value,
                    "user_context": UserContext.AVAILABLE.value,
                },
                user_response={"response": "COMPLETED", "feedback_notes": "Done"},
                outcome={"outcome_status": "COMPLETED", "evaluation": "Architecture document completed.", "success": True},
                status=EpisodeStatus.OUTCOME_RECORDED.value,
            )
            eps.append(ep)

        # Add 2 generic dismissed episodes
        for i in range(2):
            ep = self.episode_store.create_episode(
                episode_id=f"ep-generic-{i}",
                situation_id=f"sit-gen-{i}",
                created_at=self.now + timedelta(days=i + 5),
                recommendations=["Stay focused and check schedule."],
                intervention_decision={"action": PolicyAction.INTERRUPT.value},
                user_response={"response": "DISMISSED"},
                outcome={"outcome_status": "DISMISSED", "success": False},
                status=EpisodeStatus.OUTCOME_RECORDED.value,
            )
            eps.append(ep)

        # Run PatternEngine discovery
        patterns = self.pattern_engine.discover_interaction_patterns(eps)
        self.assertGreaterEqual(len(patterns), 1)

        pat = patterns[0]
        self.assertEqual(pat.pattern_type, PatternType.INTERACTION_PATTERN)
        self.assertIn("specific contextual recommendations", pat.description)
        # Verify supporting episodes point directly to reasoning_episodes IDs
        self.assertGreater(len(pat.supporting_episodes), 0)

    # -------------------------------------------------------------------------
    # 4. Verification of Unified Single Table (No Duplicate Memory Tables)
    # -------------------------------------------------------------------------

    def test_no_separate_recommendation_or_reasoning_memory_tables(self) -> None:
        """
        Asserts that NO RecommendationMemory or ReasoningMemory tables exist in SQLite.
        reasoning_episodes is the single, unified source of truth.
        """
        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}

            # reasoning_episodes exists
            self.assertIn("reasoning_episodes", tables)

            # Separate memory tables do NOT exist
            self.assertNotIn("recommendation_memory", tables)
            self.assertNotIn("reasoning_memory", tables)
            self.assertNotIn("recommendation_memories", tables)
            self.assertNotIn("reasoning_memories", tables)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
