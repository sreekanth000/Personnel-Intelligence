"""
Dedicated Test Suite for Hermes Structured Reasoning Output Handling & Bounded Retries.

Tests:
1. valid response
2. malformed JSON
3. missing field
4. invalid enum
5. retry success
6. retry failure (creates UNPARSEABLE_REASONING episode, does not crash SituationEngine, does not trigger intervention, preserves failure)
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
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStore
from personal_intelligence.core.state import StateRepresentation
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import (
    ActionabilityLevel,
    EvidenceStrength,
    ReasoningWorkflow,
    ReasoningWorkflowResult,
    RelevanceLevel,
    StructuredReasoningSynthesis,
    UrgencyLevel,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestReasoningWorkflowStructuredOutput(unittest.TestCase):
    """Test suite for ReasoningWorkflow structured output parsing, validation, retries, and failure handling."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_reasoning_structured.db")
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
        self.base_time = datetime(2026, 8, 23, 11, 0, 0, tzinfo=timezone.utc)
        self.situation = self.situation_store.create_situation(
            situation_type="schedule_conflict",
            priority=SituationPriority.HIGH,
            context={"summary": "Double booked client meeting and board prep"},
            evidence=["event:evt-meeting-1", "event:evt-meeting-2"],
        )
        self.state = StateRepresentation(timestamp=self.base_time)
        self.state.set_feature("current_activity", "meeting_prep", source="calendar")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _sample_valid_payload(self) -> dict:
        return {
            "what_is_happening": "User has overlapping executive roadmap review and client delivery sync.",
            "evidence_summary": ["event:evt-meeting-1 at 14:00", "event:evt-meeting-2 at 14:00"],
            "inferences": ["Simultaneous presence required across conflicting commitments."],
            "predictions": ["One stakeholder group will experience uncommunicated absence without intervention."],
            "uncertainties": ["Whether client meeting organizer allows async status submission."],
            "what_would_change_assessment": ["If user reschedules client delivery sync or delegates attendance."],
            "recommendations": ["Prompt user to delegate client sync to engineering lead."],
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }

    # -------------------------------------------------------------------------
    # 1. Valid Response Test
    # -------------------------------------------------------------------------

    def test_valid_response(self) -> None:
        """Verify that a compliant JSON payload passes schema validation and persists successfully."""
        payload = self._sample_valid_payload()
        self.mock_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=f"```json\n{json.dumps(payload)}\n```",
            duration_ms=250,
            success=True,
        )

        result = self.workflow.run_workflow(
            situation=self.situation,
            current_state=self.state,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.is_unparseable)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.synthesis.what_is_happening, payload["what_is_happening"])
        self.assertEqual(result.synthesis.urgency, "high")
        self.assertEqual(result.synthesis.actionability, "high")
        self.assertEqual(result.synthesis.relevance, "high")
        self.assertEqual(result.synthesis.evidence_strength, "strong")

        # Persisted episode in EpisodeStore
        persisted = self.episode_store.get_episode(result.episode.episode_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, EpisodeStatus.REASONING_COMPLETED)
        self.assertTrue(persisted.outcome_success)

    # -------------------------------------------------------------------------
    # 2. Malformed JSON Test
    # -------------------------------------------------------------------------

    def test_malformed_json_rejected(self) -> None:
        """Verify that malformed JSON strings fail extraction and produce informative errors."""
        malformed_raw = "```json\n{ 'what_is_happening': missing_quotes_and_trailing_comma, }\n```"
        synthesis, errors = validate_reasoning_synthesis(malformed_raw)

        self.assertIsNone(synthesis)
        self.assertGreater(len(errors), 0)
        self.assertIn("JSON Parse Error", errors[0])

    # -------------------------------------------------------------------------
    # 3. Missing Field Test
    # -------------------------------------------------------------------------

    def test_missing_field_rejected(self) -> None:
        """Verify that omitting required schema fields fails validation with field-specific errors."""
        payload = self._sample_valid_payload()
        del payload["what_is_happening"]
        del payload["urgency"]

        synthesis, errors = validate_reasoning_synthesis(json.dumps(payload))

        self.assertIsNone(synthesis)
        self.assertTrue(any("what_is_happening" in err for err in errors))
        self.assertTrue(any("urgency" in err for err in errors))

    # -------------------------------------------------------------------------
    # 4. Invalid Enum Test
    # -------------------------------------------------------------------------

    def test_invalid_enum_rejected(self) -> None:
        """Verify that non-categorical or unrecognized enum strings are rejected."""
        payload = self._sample_valid_payload()
        payload["urgency"] = "emergency"  # Invalid
        payload["actionability"] = "very_high"  # Invalid
        payload["evidence_strength"] = "0.95"  # Numerical probability instead of weak/moderate/strong

        synthesis, errors = validate_reasoning_synthesis(json.dumps(payload))

        self.assertIsNone(synthesis)
        self.assertTrue(any("urgency" in err for err in errors))
        self.assertTrue(any("actionability" in err for err in errors))
        self.assertTrue(any("evidence_strength" in err for err in errors))

    # -------------------------------------------------------------------------
    # 5. Retry Success Test
    # -------------------------------------------------------------------------

    def test_retry_success(self) -> None:
        """
        Verify that on initial validation error, the workflow initiates a bounded retry
        with feedback, succeeding when the model corrects its schema output on attempt 2.
        """
        valid_payload = self._sample_valid_payload()
        self.mock_client.invoke_reasoning.side_effect = [
            HermesInvocationResponse(
                raw_response="Invalid plain text without JSON formatting",
                duration_ms=200,
                success=True,
            ),
            HermesInvocationResponse(
                raw_response=json.dumps(valid_payload),
                duration_ms=300,
                success=True,
            ),
        ]

        result = self.workflow.run_workflow(
            situation=self.situation,
            current_state=self.state,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(self.mock_client.invoke_reasoning.call_count, 2)
        self.assertEqual(result.episode.status, EpisodeStatus.REASONING_COMPLETED)
        self.assertEqual(result.synthesis.what_is_happening, valid_payload["what_is_happening"])

        # Check feedback was passed in retry prompt
        retry_call_args = self.mock_client.invoke_reasoning.call_args_list[1][0][0]
        self.assertIn("SCHEMA VALIDATION ERROR", retry_call_args.prompt)

    # -------------------------------------------------------------------------
    # 6. Retry Failure Test (Zero Crash + UNPARSEABLE_REASONING Status)
    # -------------------------------------------------------------------------

    def test_retry_failure_handling(self) -> None:
        """
        Verify that if all retry attempts fail:
        1. An UNPARSEABLE_REASONING episode is created in EpisodeStore.
        2. SituationEngine / caller does NOT crash.
        3. Intervention is NOT triggered (low urgency/actionability fallback returned).
        4. The failure is NOT silently discarded (raw response & validation errors recorded in metadata).
        """
        self.mock_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response="Unrecoverable invalid output that fails all schema attempts",
            duration_ms=150,
            success=True,
        )

        result = self.workflow.run_workflow(
            situation=self.situation,
            current_state=self.state,
            objective="Evaluate conflict risk",
        )

        # 1. Episode created with UNPARSEABLE_REASONING
        persisted = self.episode_store.get_episode(result.episode.episode_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, EpisodeStatus.UNPARSEABLE_REASONING)
        self.assertFalse(persisted.outcome_success)

        # 2. Did not crash
        self.assertTrue(result.is_unparseable)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 3)  # Initial + 2 retries

        # 3. Does not trigger intervention (urgency and actionability are low)
        self.assertEqual(result.synthesis.urgency, UrgencyLevel.LOW.value)
        self.assertEqual(result.synthesis.actionability, ActionabilityLevel.LOW.value)

        # 4. Failure not silently discarded: raw response and errors stored in metadata
        self.assertEqual(persisted.metadata["raw_response"], "Unrecoverable invalid output that fails all schema attempts")
        self.assertGreater(len(persisted.metadata["validation_errors"]), 0)
        self.assertEqual(persisted.situation_id, self.situation.id)


if __name__ == "__main__":
    unittest.main()
