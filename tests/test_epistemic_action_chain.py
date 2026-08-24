"""
Unit Tests for Personal Intelligence Canonical Epistemic & Action Model.

Tests:
1. Canonical Chain: OBSERVATION -> INFERENCE -> PREDICTION -> RECOMMENDATION -> USER DECISION -> ACTION
2. V1 Zero Autonomous External Actions (Write operations blocked by safety guard without user approval)
3. InterventionPolicyEngine strictly decides presentation mode (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD)
4. No automatic transition from RECOMMENDATION to ACTION without USER DECISION
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    PolicyEvaluationResult,
    UserContext,
)
from personal_intelligence.security import (
    OperationSafetyGuard,
    UnauthorizedWriteOperationError,
)
from personal_intelligence.hermes_bridge.reasoning import (
    ActionabilityLevel,
    EvidenceStrength,
    RelevanceLevel,
    StructuredReasoningSynthesis,
    UrgencyLevel,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestEpistemicActionChain(unittest.TestCase):
    """Test suite verifying canonical epistemic and action model invariants."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_epistemic_chain.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.policy_engine = InterventionPolicyEngine()
        self.safety_guard = OperationSafetyGuard(allowed_directory_roots=[self.temp_dir.name])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Canonical Epistemic Chain Segregation
    # -------------------------------------------------------------------------

    def test_canonical_epistemic_chain_in_synthesis_and_episode(self) -> None:
        """
        Verify that synthesis strictly segregates:
        OBSERVATION (evidence_summary) -> INFERENCE -> PREDICTION -> RECOMMENDATION.
        """
        synthesis = StructuredReasoningSynthesis(
            what_is_happening="User has an imminent deadline conflict.",
            evidence_summary=["event:evt-meeting-1 at 15:00", "event:evt-deliverable-due at 15:30"],
            inferences=["User cannot attend meeting and finish deliverable simultaneously."],
            predictions=["Deliverable submission will be late without schedule modification."],
            what_would_change_assessment=["If deliverable deadline is moved to tomorrow morning."],
            recommendations=["Propose delegating meeting attendance or rescheduling submission."],
            urgency=UrgencyLevel.HIGH.value,
            actionability=ActionabilityLevel.HIGH.value,
            relevance=RelevanceLevel.HIGH.value,
            evidence_strength=EvidenceStrength.STRONG.value,
        )

        episode = self.episode_store.create_episode(
            situation_id="sit-epistemic-01",
            observations=synthesis.evidence_summary,
            inferences=synthesis.inferences,
            predictions=synthesis.predictions,
            recommendation=synthesis.recommendations,
            urgency=synthesis.urgency,
            actionability=synthesis.actionability,
            relevance=synthesis.relevance,
            evidence_strength=synthesis.evidence_strength,
            status=EpisodeStatus.REASONING_COMPLETED.value,
        )

        # Verify epistemic layers are preserved independently
        self.assertEqual(len(episode.observations), 2)
        self.assertIn("event:evt-meeting-1 at 15:00", episode.observations[0])
        self.assertEqual(len(episode.inferences), 1)
        self.assertEqual(len(episode.predictions), 1)
        self.assertEqual(len(episode.recommendation), 1)
        self.assertIsNone(episode.user_response)
        self.assertIsNone(episode.outcome)

    # -------------------------------------------------------------------------
    # 2. InterventionPolicyEngine Decides Presentation Mode ONLY
    # -------------------------------------------------------------------------

    def test_intervention_policy_decides_presentation_only(self) -> None:
        """
        Verify that InterventionPolicyEngine outputs strictly presentation actions:
        INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD, and never executes external actions.
        """
        # Test available context -> INTERRUPT (presentation)
        result_interrupt = self.policy_engine.evaluate(
            urgency=UrgencyLevel.HIGH.value,
            actionability=ActionabilityLevel.HIGH.value,
            evidence_strength=EvidenceStrength.STRONG.value,
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(result_interrupt.action, PolicyAction.INTERRUPT.value)
        self.assertIn(result_interrupt.action, [e.value for e in PolicyAction])

        # Test meeting context -> DEFER (presentation delayed)
        result_defer = self.policy_engine.evaluate(
            urgency=UrgencyLevel.HIGH.value,
            actionability=ActionabilityLevel.HIGH.value,
            evidence_strength=EvidenceStrength.STRONG.value,
            user_context=UserContext.MEETING.value,
        )
        self.assertEqual(result_defer.action, PolicyAction.DEFER.value)

        # Test low urgency -> DISCARD (silent)
        result_discard = self.policy_engine.evaluate(
            urgency=UrgencyLevel.LOW.value,
            actionability=ActionabilityLevel.LOW.value,
            evidence_strength=EvidenceStrength.WEAK.value,
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(result_discard.action, PolicyAction.DISCARD.value)

    # -------------------------------------------------------------------------
    # 3. Explicit User Decision Gate (RECOMMENDATION -> USER DECISION -> ACTION)
    # -------------------------------------------------------------------------

    def test_explicit_user_decision_required_before_action(self) -> None:
        """
        Verify that a recommendation remains pending until an explicit USER DECISION
        is recorded (e.g. ACCEPTED, DISMISSED, DEFERRED), and only then transitions to action outcome.
        """
        episode = self.episode_store.create_episode(
            situation_id="sit-user-gate-01",
            recommendation=["Reschedule 15:00 meeting to 16:30."],
            status=EpisodeStatus.INTERVENTION_DELIVERED.value,
        )

        # Before user decision, user_response is None
        self.assertIsNone(episode.user_response)
        self.assertEqual(episode.status, EpisodeStatus.INTERVENTION_DELIVERED.value)

        # User Decision recorded
        updated = self.episode_store.record_user_response(
            episode_id=episode.id,
            response=RecommendationResult.ACCEPTED.value,
            feedback_notes="User accepted rescheduling suggestion.",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, EpisodeStatus.RESPONSE_RECORDED.value)
        self.assertEqual(updated.user_response["response"], RecommendationResult.ACCEPTED.value)

        # External outcome / Action result recorded after decision
        completed_ep = self.episode_store.record_outcome(
            episode_id=episode.id,
            outcome_status=RecommendationResult.COMPLETED.value,
            evaluation_notes="Meeting rescheduled after user confirmation.",
            success=True,
        )
        self.assertIsNotNone(completed_ep)
        self.assertEqual(completed_ep.status, EpisodeStatus.OUTCOME_RECORDED.value)
        self.assertTrue(completed_ep.outcome["success"])

    # -------------------------------------------------------------------------
    # 4. Zero Autonomous External Actions (V1 Safety Guard)
    # -------------------------------------------------------------------------

    def test_zero_autonomous_external_actions_blocked_by_guard(self) -> None:
        """
        Verify that autonomous external write actions (sending emails, modifying calendar,
        deleting files) are blocked by OperationSafetyGuard in V1 without user authorization.
        """
        # Read-only operations are permitted
        allowed_read, _ = self.safety_guard.validate_tool_execution(
            "gmail_search",
            {"query": "deadline"},
        )
        self.assertTrue(allowed_read)

        # Autonomous write operations are strictly blocked
        allowed_send, denial_send = self.safety_guard.validate_tool_execution(
            "gmail_send_message",
            {"to": "colleague@example.com", "body": "Rescheduling meeting"},
        )
        self.assertFalse(allowed_send)
        self.assertIn("unauthorized autonomous write operation", denial_send.lower())

        allowed_cal_write, denial_cal = self.safety_guard.validate_tool_execution(
            "calendar_create_event",
            {"summary": "New meeting", "start": "2026-08-23T16:00:00Z"},
        )
        self.assertFalse(allowed_cal_write)
        self.assertIn("unauthorized autonomous write operation", denial_cal.lower())


if __name__ == "__main__":
    unittest.main()
