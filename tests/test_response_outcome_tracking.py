"""
Unit tests for user response and longitudinal outcome tracking.
Verifies complete reasoning chain retention:
Situation -> Reasoning -> Recommendation -> Intervention -> User response -> Outcome
across all 7 recommendation result states:
ACCEPTED, DISMISSED, IGNORED, DEFERRED, COMPLETED, PARTIALLY_COMPLETED, UNKNOWN.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    OutcomeRecord,
    ReasoningEpisode,
    RecommendationResult,
    UserResponseRecord,
)
from personal_intelligence.storage.db import DatabaseManager


class TestResponseOutcomeTracking(unittest.TestCase):
    """Test suite for user response and longitudinal outcome tracking."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_tracking.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.store = EpisodeStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. All 7 Recommendation Result States ---

    def test_all_recommendation_result_states_user_responses(self) -> None:
        """Verify that user responses can be recorded for all 7 standard result states."""
        states = [
            RecommendationResult.ACCEPTED,
            RecommendationResult.DISMISSED,
            RecommendationResult.IGNORED,
            RecommendationResult.DEFERRED,
            RecommendationResult.COMPLETED,
            RecommendationResult.PARTIALLY_COMPLETED,
            RecommendationResult.UNKNOWN,
        ]

        for state in states:
            ep = self.store.create_episode(
                situation_id="sit-test-states",
                hermes_task=f"Test state {state.value}",
            )
            updated = self.store.record_user_response(
                episode_id=ep.id,
                response=state,
                feedback_notes=f"User marked as {state.value}",
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, EpisodeStatus.RESPONSE_RECORDED.value)
            self.assertEqual(updated.user_response["response"], state.value)
            
            # Verify parsed UserResponseRecord
            rec = updated.get_user_response_record()
            self.assertIsNotNone(rec)
            self.assertEqual(rec.response, state.value)
            self.assertEqual(rec.feedback_notes, f"User marked as {state.value}")

    def test_all_recommendation_result_states_outcomes(self) -> None:
        """Verify that longitudinal outcomes can be recorded for all 7 standard result states."""
        states = [
            RecommendationResult.ACCEPTED,
            RecommendationResult.DISMISSED,
            RecommendationResult.IGNORED,
            RecommendationResult.DEFERRED,
            RecommendationResult.COMPLETED,
            RecommendationResult.PARTIALLY_COMPLETED,
            RecommendationResult.UNKNOWN,
        ]

        for state in states:
            ep = self.store.create_episode(
                situation_id="sit-test-outcomes",
                hermes_task=f"Test outcome {state.value}",
            )
            updated = self.store.record_outcome(
                episode_id=ep.id,
                outcome_status=state,
                evaluation_notes=f"Longitudinal outcome observed as {state.value}",
                success=(state in (RecommendationResult.COMPLETED, RecommendationResult.ACCEPTED)),
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, EpisodeStatus.OUTCOME_RECORDED.value)
            self.assertEqual(updated.outcome["outcome_status"], state.value)
            
            # Verify parsed OutcomeRecord
            out_rec = updated.get_outcome_record()
            self.assertIsNotNone(out_rec)
            self.assertEqual(out_rec.outcome_status, state.value)
            self.assertEqual(out_rec.evaluation_notes, f"Longitudinal outcome observed as {state.value}")

    # --- 2. Complete Reasoning Chain Retention ---

    def test_complete_reasoning_chain_retention(self) -> None:
        """
        Verify that an episode retains the complete end-to-end reasoning chain:
        situation -> reasoning -> recommendation -> intervention decision -> user response -> outcome.
        """
        # 1. Situation + Reasoning + Recommendation + Intervention Decision
        ep = self.store.create_episode(
            situation_id="sit-workload-200",
            created_at=self.base_time,
            context_snapshot={"active_project": "AI Assistant", "focus_duration_mins": 195},
            observations=["Prolonged continuous work without rest: 195 minutes"],
            inferences=["Risk of cognitive fatigue and decreased task efficiency"],
            predictions=["Error rate in code edits likely to increase over next 60m"],
            hermes_task="Assess fatigue risk and formulate gentle break recommendation",
            hermes_result={"model": "hermes-reasoning-v1", "reasoning_steps": ["analyze_timeline", "check_goals"]},
            recommendation={"action": "take_10m_walk", "rationale": "restore cognitive freshness"},
            urgency="medium",
            actionability="high",
            relevance="high",
            evidence_strength="strong",
            intervention_decision={"action": "BRIEFING", "channel": "desktop_tray", "delivery_time": self.base_time.isoformat()},
            status=EpisodeStatus.INTERVENTION_DELIVERED.value,
        )

        # 2. Record User Response
        resp_time = self.base_time + timedelta(minutes=5)
        ep_with_response = self.store.record_user_response(
            episode_id=ep.id,
            response=RecommendationResult.ACCEPTED,
            feedback_notes="Stepped away for coffee and stretch",
            timestamp=resp_time,
            metadata={"device": "workstation", "latency_seconds": 300},
        )
        self.assertIsNotNone(ep_with_response)
        self.assertEqual(ep_with_response.status, EpisodeStatus.RESPONSE_RECORDED.value)

        # 3. Record Longitudinal Outcome (e.g. 2 hours later)
        eval_time = self.base_time + timedelta(hours=2)
        final_ep = self.store.record_outcome(
            episode_id=ep.id,
            outcome_status=RecommendationResult.COMPLETED,
            evaluation_notes="User resumed with normal commit frequency; fatigue averted",
            success=True,
            observed_at=eval_time,
            impact_metrics={"break_duration_mins": 12, "resumed_productivity": "normal"},
            evidence_event_ids=["evt-break-start", "evt-break-end", "evt-commit-12"],
        )
        self.assertIsNotNone(final_ep)
        self.assertEqual(final_ep.status, EpisodeStatus.OUTCOME_RECORDED.value)

        # 4. Assert Complete Chain Integrity from SQLite
        persisted = self.store.get_episode(ep.id)
        self.assertIsNotNone(persisted)

        # Check Situation
        self.assertEqual(persisted.situation_id, "sit-workload-200")
        self.assertEqual(persisted.context_snapshot["active_project"], "AI Assistant")

        # Check Reasoning
        self.assertEqual(persisted.observations, ["Prolonged continuous work without rest: 195 minutes"])
        self.assertEqual(persisted.inferences, ["Risk of cognitive fatigue and decreased task efficiency"])
        self.assertEqual(persisted.predictions, ["Error rate in code edits likely to increase over next 60m"])
        self.assertEqual(persisted.urgency, "medium")
        self.assertEqual(persisted.evidence_strength, "strong")

        # Check Recommendation
        self.assertEqual(persisted.recommendation["action"], "take_10m_walk")

        # Check Intervention Decision
        self.assertEqual(persisted.intervention_decision["action"], "BRIEFING")

        # Check User Response
        user_rec = persisted.get_user_response_record()
        self.assertIsNotNone(user_rec)
        self.assertEqual(user_rec.response, "ACCEPTED")
        self.assertEqual(user_rec.feedback_notes, "Stepped away for coffee and stretch")
        self.assertEqual(user_rec.metadata["latency_seconds"], 300)

        # Check Outcome
        out_rec = persisted.get_outcome_record()
        self.assertIsNotNone(out_rec)
        self.assertEqual(out_rec.outcome_status, "COMPLETED")
        self.assertTrue(out_rec.success)
        self.assertEqual(out_rec.impact_metrics["break_duration_mins"], 12)
        self.assertEqual(len(out_rec.evidence_event_ids), 3)

    # --- 3. Validation & Error Handling ---

    def test_invalid_response_status_rejected(self) -> None:
        """Verify invalid user response strings raise ValueError."""
        ep = self.store.create_episode(situation_id="sit-val-1")
        with self.assertRaises(ValueError):
            self.store.record_user_response(
                episode_id=ep.id,
                response="INVALID_RESPONSE_STATUS",
            )

    def test_invalid_outcome_status_rejected(self) -> None:
        """Verify invalid outcome status strings raise ValueError."""
        ep = self.store.create_episode(situation_id="sit-val-2")
        with self.assertRaises(ValueError):
            self.store.record_outcome(
                episode_id=ep.id,
                outcome_status="INVALID_OUTCOME_STATUS",
            )

    def test_nonexistent_episode_returns_none(self) -> None:
        """Verify operations on nonexistent episode IDs return None."""
        self.assertIsNone(self.store.record_user_response("nonexistent-ep", RecommendationResult.ACCEPTED))
        self.assertIsNone(self.store.record_outcome("nonexistent-ep", RecommendationResult.COMPLETED))


if __name__ == "__main__":
    unittest.main()
