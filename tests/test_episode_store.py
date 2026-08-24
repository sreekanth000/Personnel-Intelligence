"""
Unit tests for the unified ReasoningEpisode model and EpisodeStore.
Verifies complete reasoning lifecycle (Observation -> Inference -> Prediction ->
Recommendation -> Intervention -> User response -> Outcome) in ONE single SQLite table.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.storage.db import DatabaseManager


class TestEpisodeStore(unittest.TestCase):
    """Test suite for unified single-table reasoning episode store."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_episodes_unified.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.store = EpisodeStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 21, 17, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. Creation & Initial Fields Test ---

    def test_create_episode_all_fields(self) -> None:
        """Verify creating an episode with initial observation, inference, and prediction fields."""
        ep = self.store.create_episode(
            situation_id="sit-work-100",
            created_at=self.base_time,
            context_snapshot={"activity": "deep_work", "duration": 180},
            observations=["Continuous coding for 180m (src=os_window)"],
            inferences=["Upcoming 17:30 sync will conflict with current flow"],
            predictions=["User will likely skip sync if not prompted"],
            hermes_task="Assess meeting conflict and propose agenda note",
            hermes_result={"raw_response": "{\"status\":\"analyzed\"}"},
            recommendation={"action": "prepare_5m_agenda_note"},
            urgency="high",
            actionability="high",
            relevance="high",
            evidence_strength="strong",
            intervention_decision={"delivery_mode": "subtle_notification", "cooldown_minutes": 30},
            status=EpisodeStatus.STARTED.value,
        )

        self.assertIsNotNone(ep.id)
        self.assertEqual(ep.situation_id, "sit-work-100")
        self.assertEqual(len(ep.observations), 1)
        self.assertEqual(len(ep.inferences), 1)
        self.assertEqual(len(ep.predictions), 1)
        self.assertEqual(ep.urgency, "high")
        self.assertEqual(ep.actionability, "high")
        self.assertEqual(ep.relevance, "high")
        self.assertEqual(ep.evidence_strength, "strong")

        # Query back from DB
        fetched = self.store.get_episode(ep.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, ep.id)
        self.assertEqual(fetched.situation_id, "sit-work-100")
        self.assertEqual(fetched.observations, ep.observations)
        self.assertEqual(fetched.inferences, ep.inferences)
        self.assertEqual(fetched.predictions, ep.predictions)
        self.assertEqual(fetched.context_snapshot["activity"], "deep_work")
        self.assertEqual(fetched.recommendation["action"], "prepare_5m_agenda_note")

    # --- 2. Full Reasoning Lifecycle Test ---

    def test_full_reasoning_lifecycle(self) -> None:
        """
        Verify end-to-end reasoning lifecycle progression:
        Observation -> Inference -> Prediction -> Recommendation ->
        Intervention -> User response -> Outcome.
        """
        # Step 1: Create initial episode (Observation -> Inference -> Prediction -> Recommendation -> Intervention)
        ep = self.store.create_episode(
            situation_id="sit-lifecycle-1",
            observations=["Observed schedule conflict at 17:30"],
            inferences=["User has not opened meeting link"],
            predictions=["High chance of delayed attendance"],
            recommendation={"suggested_action": "Send 2-min reminder"},
            intervention_decision={"delivered": True, "channel": "desktop_banner"},
            status=EpisodeStatus.INTERVENTION_DELIVERED.value,
        )
        self.assertEqual(ep.status, EpisodeStatus.INTERVENTION_DELIVERED.value)

        # Step 2: User response arrives
        user_resp = {
            "action_taken": "acknowledged",
            "feedback": "helpful reminder",
            "responded_at": self.base_time.isoformat(),
        }
        updated_resp = self.store.update_response(
            episode_id=ep.id,
            user_response=user_resp,
        )
        self.assertIsNotNone(updated_resp)
        self.assertEqual(updated_resp.status, EpisodeStatus.RESPONSE_RECORDED.value)
        self.assertEqual(updated_resp.user_response["action_taken"], "acknowledged")

        # Step 3: Outcome recorded
        outcome_data = {
            "success": True,
            "meeting_attended_on_time": True,
            "goal_impact": "positive",
        }
        final_ep = self.store.update_outcome(
            episode_id=ep.id,
            outcome=outcome_data,
        )
        self.assertIsNotNone(final_ep)
        self.assertEqual(final_ep.status, EpisodeStatus.OUTCOME_RECORDED.value)
        self.assertTrue(final_ep.outcome["success"])
        self.assertTrue(final_ep.outcome["meeting_attended_on_time"])

    # --- 3. Queries: list_recent and list_by_situation ---

    def test_list_recent_and_list_by_situation(self) -> None:
        """Verify list_recent and list_by_situation query APIs."""
        ep1 = self.store.create_episode(
            situation_id="sit-A",
            created_at=self.base_time - timedelta(hours=2),
            hermes_task="Task A1",
        )
        ep2 = self.store.create_episode(
            situation_id="sit-B",
            created_at=self.base_time - timedelta(hours=1),
            hermes_task="Task B1",
        )
        ep3 = self.store.create_episode(
            situation_id="sit-A",
            created_at=self.base_time,
            hermes_task="Task A2",
        )

        # 1. list_recent
        recent = self.store.list_recent(limit=2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].id, ep3.id)
        self.assertEqual(recent[1].id, ep2.id)

        # 2. list_by_situation
        sit_a_eps = self.store.list_by_situation("sit-A")
        self.assertEqual(len(sit_a_eps), 2)
        self.assertEqual(sit_a_eps[0].id, ep3.id)
        self.assertEqual(sit_a_eps[1].id, ep1.id)

        # Non-existent situation
        empty = self.store.list_by_situation("sit-none")
        self.assertEqual(len(empty), 0)

    # --- 4. Nonexistent Episode Handling ---

    def test_nonexistent_episode_operations(self) -> None:
        """Verify safe handling of operations on nonexistent episode IDs."""
        self.assertIsNone(self.store.get_episode("nonexistent-id"))
        self.assertIsNone(self.store.update_response("nonexistent-id", {"action": "none"}))
        self.assertIsNone(self.store.update_outcome("nonexistent-id", {"success": False}))


if __name__ == "__main__":
    unittest.main()
