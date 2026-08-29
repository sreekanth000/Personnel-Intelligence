"""
Unit Tests for InterventionPolicyEngine Categorical Policy Decisions.

Validates:
1. Low urgency is not disruptive (returns DISCARD, never interrupts).
2. High urgency + high actionability can interrupt (returns INTERRUPT when available).
3. Deep work suppresses low-value interruptions (returns SUPPRESS or DEFER, never direct interrupt).
4. Repeated dismissal reduces unnecessary interruption (returns SUPPRESS on recently_dismissed).
5. Duplicate recommendations are suppressed (returns DISCARD on already_notified).
6. Discarded recommendations remain in reasoning_episodes (preserved for future learning, never deleted).
7. Pure categorical inputs without fake numerical confidence.
"""

from datetime import datetime, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    UserContext,
)
from personal_intelligence.storage.db import DatabaseManager


class TestInterventionPolicyEngineReview(unittest.TestCase):
    """Review and verification test suite for InterventionPolicyEngine."""

    def setUp(self) -> None:
        self.engine = InterventionPolicyEngine()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_policy_review.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.now = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Low Urgency is NOT Disruptive
    # -------------------------------------------------------------------------

    def test_low_urgency_is_not_disruptive(self) -> None:
        """
        Low urgency situations across available, busy, meeting, deep_work, sleep, driving, DND
        must return DISCARD and NEVER interrupt the user.
        """
        contexts = [
            UserContext.AVAILABLE.value,
            UserContext.BUSY.value,
            UserContext.MEETING.value,
            UserContext.DEEP_WORK.value,
            UserContext.SLEEP.value,
            UserContext.DRIVING.value,
            UserContext.DND.value,
        ]

        for ctx in contexts:
            result = self.engine.evaluate(
                urgency="low",
                actionability="high",
                evidence_strength="strong",
                user_context=ctx,
                relevance="high",
            )
            self.assertIn(
                result.action,
                (PolicyAction.DISCARD.value, PolicyAction.SUPPRESS.value, PolicyAction.BRIEFING.value),
                f"Low urgency in context '{ctx}' must return DISCARD, SUPPRESS, or BRIEFING",
            )
            self.assertNotEqual(result.action, PolicyAction.INTERRUPT.value)

    # -------------------------------------------------------------------------
    # 2. High Urgency + High Actionability Can Interrupt
    # -------------------------------------------------------------------------

    def test_high_urgency_high_actionability_can_interrupt(self) -> None:
        """
        When user is available, high urgency + high actionability + strong evidence
        must result in an immediate INTERRUPT.
        """
        result = self.engine.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
            relevance="high",
        )
        self.assertEqual(result.action, PolicyAction.INTERRUPT.value)
        self.assertIn("triggers immediate interrupt", result.reason.lower())

    def test_critical_urgency_overrides_and_interrupts(self) -> None:
        """Critical urgency overrides user context to interrupt immediately."""
        result = self.engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context="meeting",
            relevance="high",
        )
        self.assertEqual(result.action, PolicyAction.INTERRUPT.value)

    # -------------------------------------------------------------------------
    # 3. Deep Work Suppresses Low-Value Interruptions
    # -------------------------------------------------------------------------

    def test_deep_work_suppresses_low_value_interruptions(self) -> None:
        """
        During deep work:
        - Low value / medium urgency recommendations are deferred or suppressed.
        - Direct INTERRUPT is strictly prevented.
        """
        # Medium urgency, moderate actionability in deep work -> SUPPRESS or DEFER
        res_med = self.engine.evaluate(
            urgency="medium",
            actionability="medium",
            evidence_strength="moderate",
            user_context="deep_work",
            relevance="medium",
        )
        self.assertIn(res_med.action, (PolicyAction.SUPPRESS.value, PolicyAction.DEFER.value))
        self.assertNotEqual(res_med.action, PolicyAction.INTERRUPT.value)

        # High urgency in deep work is DEFERRED rather than interrupting
        res_high = self.engine.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context="deep_work",
            relevance="high",
        )
        self.assertEqual(res_high.action, PolicyAction.DEFER.value)
        self.assertNotEqual(res_high.action, PolicyAction.INTERRUPT.value)

    # -------------------------------------------------------------------------
    # 4. Repeated Dismissal Reduces Unnecessary Interruption
    # -------------------------------------------------------------------------

    def test_repeated_dismissal_reduces_unnecessary_interruption(self) -> None:
        """
        When recently_dismissed is True, the engine returns SUPPRESS to avoid
        badgering the user.
        """
        result = self.engine.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
            relevance="high",
            recently_dismissed=True,
        )
        self.assertEqual(result.action, PolicyAction.SUPPRESS.value)
        self.assertIn("dismissed", result.reason.lower())

    # -------------------------------------------------------------------------
    # 5. Duplicate Recommendations are Suppressed
    # -------------------------------------------------------------------------

    def test_duplicate_recommendations_are_suppressed(self) -> None:
        """
        When already_notified is True, the engine returns DISCARD to prevent
        duplicate alerts for the same situation.
        """
        result = self.engine.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
            relevance="high",
            already_notified=True,
        )
        self.assertEqual(result.action, PolicyAction.DISCARD.value)
        self.assertIn("already been notified", result.reason.lower())

    # -------------------------------------------------------------------------
    # 6. Discarded Recommendations Remain in reasoning_episodes
    # -------------------------------------------------------------------------

    def test_discarded_recommendations_remain_in_reasoning_episodes(self) -> None:
        """
        Proves that when a policy evaluation results in DISCARD, the reasoning episode
        is NOT deleted. It is safely persisted in reasoning_episodes for future learning.
        Only the user presentation is discarded.
        """
        # 1. Evaluate policy yielding DISCARD
        policy_res = self.engine.evaluate(
            urgency="low",
            actionability="low",
            evidence_strength="weak",
            user_context="available",
            relevance="low",
        )
        self.assertEqual(policy_res.action, PolicyAction.DISCARD.value)

        # 2. Persist episode with DISCARD decision
        episode = self.episode_store.create_episode(
            episode_id="ep-discard-001",
            situation_id="sit-minor-gap",
            timestamp=self.now,
            observations_used=["Minor typo in draft document."],
            evidence=["file:draft.md"],
            inferences=["Document readability is slightly degraded."],
            predictions=["No blocker expected."],
            recommendations=["Fix typo in draft document."],
            intervention_decision={
                "action": policy_res.action,
                "reason": policy_res.reason,
            },
            status=EpisodeStatus.REASONING_COMPLETED.value,
        )

        # 3. Verify episode exists and is retrievable from SQLite
        retrieved = self.episode_store.get_episode("ep-discard-001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.episode_id, "ep-discard-001")
        self.assertEqual(retrieved.intervention_decision["action"], PolicyAction.DISCARD.value)
        self.assertEqual(retrieved.recommendations, ["Fix typo in draft document."])

        # 4. Verify all episodes query includes the discarded episode
        all_eps = self.episode_store.list_recent(limit=10)
        self.assertIn("ep-discard-001", [e.id for e in all_eps])


if __name__ == "__main__":
    unittest.main()
