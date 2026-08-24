"""
Unit tests for the hardened Hermes Situational Reasoning Workflow.
Tests strict schema validation, retry loop with field feedback, safe fallbacks,
and UNPARSEABLE audit preservation across all 7 scenarios:
- valid response
- malformed JSON
- missing field
- invalid enum
- wrong data type
- second-attempt success
- permanent failure
"""

from datetime import datetime, timezone
import json
import os
import tempfile
from unittest.mock import MagicMock
import unittest

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.goals import GoalStore
from personal_intelligence.core.situations import Situation, SituationStore
from personal_intelligence.core.state import StateRepresentation
from personal_intelligence.core.timeline import Timeline
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import (
    ActionabilityLevel,
    EvidenceStrength,
    ReasoningWorkflow,
    RelevanceLevel,
    StructuredReasoningSynthesis,
    UrgencyLevel,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestHardenedReasoningWorkflow(unittest.TestCase):
    """Test suite for hardened Hermes reasoning workflow."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_reasoning_hardened.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.context_builder = ContextBuilder(
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )
        self.mock_client = MagicMock(spec=HermesClient)
        self.workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.mock_client,
            max_retries=2,
        )
        self.base_time = datetime(2026, 8, 21, 16, 30, 0, tzinfo=timezone.utc)
        self.situation = Situation(
            id="sit-test-hardened",
            type="prolonged_activity",
            priority="high",
            novelty=0.8,
            context={"activity": "coding", "duration_minutes": 180.0},
            evidence=["event:evt-10"],
        )
        self.state = StateRepresentation(timestamp=self.base_time)
        self.state.set_feature("current_activity", "coding", source="event:evt-10")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _get_valid_json_dict(self) -> dict:
        return {
            "what_is_happening": "User has been engaged in continuous coding for 180 minutes.",
            "evidence_summary": ["event:evt-10", "recent_activity_duration=180.0"],
            "inferences": ["Upcoming meeting may be displaced."],
            "predictions": ["Fatigue will accumulate without a short break."],
            "uncertainties": ["Whether scheduled meeting requires live attendance."],
            "what_would_change_assessment": ["If user concludes coding session before scheduled meeting"],
            "recommendations": ["Prompt user 5 minutes before scheduled 17:00 meeting."],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }

    # --- 1. Valid Response Test ---

    def test_valid_response(self) -> None:
        """Verify valid response passes on attempt 1 without retries."""
        valid_dict = self._get_valid_json_dict()
        self.mock_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=f"```json\n{json.dumps(valid_dict)}\n```",
            tools_executed=[],
            duration_ms=300,
            success=True,
        )

        result = self.workflow.run_workflow(
            situation=self.situation,
            current_state=self.state,
        )

        self.assertEqual(result.attempts, 1)
        self.assertEqual(self.mock_client.invoke_reasoning.call_count, 1)
        self.assertEqual(result.synthesis.what_is_happening, valid_dict["what_is_happening"])
        self.assertEqual(result.episode.status, EpisodeStatus.REASONING_COMPLETED)
        self.assertTrue(result.episode.outcome_success)

    # --- 2. Malformed JSON Test ---

    def test_malformed_json_triggers_retry(self) -> None:
        """Verify malformed JSON is detected by validator and triggers retry."""
        syn, errors = validate_reasoning_synthesis("{ this is not valid json, missing quotes }")
        self.assertIsNone(syn)
        self.assertTrue(any("JSON Parse Error" in err for err in errors))

    # --- 3. Missing Field Test ---

    def test_missing_field_triggers_validation_error(self) -> None:
        """Verify missing required fields (e.g. urgency, what_is_happening) are rejected."""
        incomplete = self._get_valid_json_dict()
        del incomplete["urgency"]
        del incomplete["what_is_happening"]

        syn, errors = validate_reasoning_synthesis(json.dumps(incomplete))
        self.assertIsNone(syn)
        self.assertTrue(any("what_is_happening" in err for err in errors))
        self.assertTrue(any("urgency" in err for err in errors))

    # --- 4. Invalid Enum Test ---

    def test_invalid_enum_triggers_validation_error(self) -> None:
        """Verify invalid categorical strings or numerical probabilities are rejected."""
        invalid = self._get_valid_json_dict()
        invalid["urgency"] = "super_emergency"  # Invalid enum
        invalid["evidence_strength"] = "0.95"   # Numerical probability instead of weak/moderate/strong

        syn, errors = validate_reasoning_synthesis(json.dumps(invalid))
        self.assertIsNone(syn)
        self.assertTrue(any("urgency" in err for err in errors))
        self.assertTrue(any("evidence_strength" in err for err in errors))

    # --- 5. Wrong Data Type Test ---

    def test_wrong_data_type_triggers_validation_error(self) -> None:
        """Verify wrong data types (e.g. string instead of list, int instead of bool) are rejected."""
        wrong_type = self._get_valid_json_dict()
        wrong_type["evidence_summary"] = "single string instead of list"
        wrong_type["requires_follow_up"] = "yes"  # string instead of boolean

        syn, errors = validate_reasoning_synthesis(json.dumps(wrong_type))
        self.assertIsNone(syn)
        self.assertTrue(any("evidence_summary" in err for err in errors))
        self.assertTrue(any("requires_follow_up" in err for err in errors))

    # --- 6. Second Attempt Success Test ---

    def test_second_attempt_success(self) -> None:
        """Verify recovery when 1st attempt fails schema validation and 2nd attempt succeeds."""
        # 1st attempt returns malformed json, 2nd attempt returns valid json
        valid_dict = self._get_valid_json_dict()
        self.mock_client.invoke_reasoning.side_effect = [
            HermesInvocationResponse(
                raw_response="Invalid raw text output",
                duration_ms=200,
                success=True,
            ),
            HermesInvocationResponse(
                raw_response=json.dumps(valid_dict),
                duration_ms=350,
                success=True,
            ),
        ]

        result = self.workflow.run_workflow(
            situation=self.situation,
            current_state=self.state,
        )

        self.assertEqual(result.attempts, 2)
        self.assertEqual(self.mock_client.invoke_reasoning.call_count, 2)
        self.assertEqual(result.episode.status, EpisodeStatus.REASONING_COMPLETED)
        self.assertEqual(result.synthesis.what_is_happening, valid_dict["what_is_happening"])

        # Check that retry prompt contained validation error feedback
        second_call_prompt = self.mock_client.invoke_reasoning.call_args_list[1][0][0].prompt
        self.assertIn("SCHEMA VALIDATION ERROR", second_call_prompt)
        self.assertIn("JSON Parse Error", second_call_prompt)

    # --- 7. Permanent Failure Test (Zero Discard + UNPARSEABLE Status) ---

    def test_permanent_failure_creates_unparseable_episode(self) -> None:
        """
        Verify that persistent schema failure across all retries:
        1. Does NOT raise an exception
        2. Creates a reasoning episode with status = UNPARSEABLE
        3. Preserves raw response, validation errors, situation ID, and task
        4. Returns a safe fallback synthesis
        """
        self.mock_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response="Persistent invalid output that refuses to conform to JSON",
            duration_ms=200,
            success=True,
        )

        result = self.workflow.run_workflow(
            situation=self.situation,
            current_state=self.state,
            objective="Evaluate prolonged activity risks",
        )

        # Max retries reached: 1 initial + 2 retries = 3 total attempts
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.mock_client.invoke_reasoning.call_count, 3)

        # Episode status must be UNPARSEABLE
        persisted = self.episode_store.get_episode(result.episode.episode_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, EpisodeStatus.UNPARSEABLE)
        self.assertFalse(persisted.outcome_success)

        # Preserved details in metadata
        self.assertEqual(persisted.situation_id, "sit-test-hardened")
        self.assertEqual(persisted.metadata["task"], "Evaluate prolonged activity risks")
        self.assertEqual(persisted.metadata["raw_response"], "Persistent invalid output that refuses to conform to JSON")
        self.assertGreater(len(persisted.metadata["validation_errors"]), 0)

        # Safe fallback synthesis returned
        self.assertIsNotNone(result.synthesis)
        self.assertIn("unavailable", result.synthesis.what_is_happening)
        self.assertEqual(result.synthesis.urgency, UrgencyLevel.LOW.value)


if __name__ == "__main__":
    unittest.main()
