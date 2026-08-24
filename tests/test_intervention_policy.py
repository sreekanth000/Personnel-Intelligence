"""
Unit tests for the Personal Intelligence Intervention Policy Engine.
Verifies pure categorical deterministic evaluation, hard suppression contexts,
critical urgency override, fatigue de-duplication, and user context routing.
"""

import unittest

from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    UserContext,
)


class TestInterventionPolicyEngine(unittest.TestCase):
    """Test suite for deterministic categorical intervention policy."""

    def setUp(self) -> None:
        self.policy = InterventionPolicyEngine()

    # --- 1. CRITICAL Priority Overrides Hard Suppression ---

    def test_critical_urgency_interrupts_across_all_contexts(self) -> None:
        """Verify CRITICAL urgency always produces INTERRUPT, even in hard suppression contexts."""
        contexts = [
            UserContext.AVAILABLE.value,
            UserContext.BUSY.value,
            UserContext.MEETING.value,
            UserContext.DRIVING.value,
            UserContext.SLEEPING.value,
            UserContext.DEEP_WORK.value,
            UserContext.DO_NOT_DISTURB.value,
        ]

        for ctx in contexts:
            result = self.policy.evaluate(
                urgency="critical",
                actionability="high",
                evidence_strength="strong",
                user_context=ctx,
            )
            self.assertEqual(
                result.action,
                PolicyAction.INTERRUPT.value,
                f"Failed for context: {ctx}",
            )
            self.assertIn("Critical urgency", result.reason)

    # --- 2. HIGH + HIGH Actionability + STRONG Evidence ---

    def test_high_actionable_strong_evidence(self) -> None:
        """Verify HIGH urgency + HIGH actionability + STRONG evidence."""
        # 1. Available -> INTERRUPT
        res_avail = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(res_avail.action, PolicyAction.INTERRUPT.value)

        # 2. Busy -> DEFER
        res_busy = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.BUSY.value,
        )
        self.assertEqual(res_busy.action, PolicyAction.DEFER.value)

        # 3. Meeting / Deep Work -> DEFER
        res_meeting = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.MEETING.value,
        )
        self.assertEqual(res_meeting.action, PolicyAction.DEFER.value)

        res_deep = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.DEEP_WORK.value,
        )
        self.assertEqual(res_deep.action, PolicyAction.DEFER.value)

        # 4. Driving / Sleeping / DND -> SUPPRESS
        res_driving = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.DRIVING.value,
        )
        self.assertEqual(res_driving.action, PolicyAction.SUPPRESS.value)

        res_sleeping = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.SLEEPING.value,
        )
        self.assertEqual(res_sleeping.action, PolicyAction.SUPPRESS.value)

    # --- 3. HIGH Urgency with Moderate/Weak Evidence or Actionability ---

    def test_high_urgency_moderate_factors(self) -> None:
        """Verify HIGH urgency routes to BRIEFING if not high actionability + strong evidence."""
        res = self.policy.evaluate(
            urgency="high",
            actionability="medium",
            evidence_strength="moderate",
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(res.action, PolicyAction.BRIEFING.value)

    # --- 4. MEDIUM Urgency Scenarios ---

    def test_medium_urgency_evaluations(self) -> None:
        """Verify MEDIUM urgency generates BRIEFING, DEFER, or DISCARD."""
        # Available + Actionable -> BRIEFING
        res_avail = self.policy.evaluate(
            urgency="medium",
            actionability="high",
            evidence_strength="moderate",
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(res_avail.action, PolicyAction.BRIEFING.value)

        # Available + Low Actionability -> DISCARD
        res_low_act = self.policy.evaluate(
            urgency="medium",
            actionability="low",
            evidence_strength="moderate",
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(res_low_act.action, PolicyAction.DISCARD.value)

        # Busy + Actionable -> DEFER
        res_busy = self.policy.evaluate(
            urgency="medium",
            actionability="high",
            evidence_strength="moderate",
            user_context=UserContext.BUSY.value,
        )
        self.assertEqual(res_busy.action, PolicyAction.DEFER.value)

        # Hard suppressed (meeting) + Actionable -> DEFER
        res_meeting = self.policy.evaluate(
            urgency="medium",
            actionability="medium",
            evidence_strength="moderate",
            user_context=UserContext.MEETING.value,
        )
        self.assertEqual(res_meeting.action, PolicyAction.DEFER.value)

    # --- 5. LOW Urgency Discard ---

    def test_low_urgency_always_discarded(self) -> None:
        """Verify LOW urgency is silently discarded across contexts."""
        for ctx in [UserContext.AVAILABLE.value, UserContext.BUSY.value, UserContext.MEETING.value]:
            res = self.policy.evaluate(
                urgency="low",
                actionability="low",
                evidence_strength="weak",
                user_context=ctx,
            )
            self.assertEqual(res.action, PolicyAction.DISCARD.value)

    # --- 6. Already Notified De-duplication ---

    def test_already_notified_discards_non_critical(self) -> None:
        """Verify already_notified causes non-critical interventions to be DISCARDED."""
        res = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.AVAILABLE.value,
            already_notified=True,
        )
        self.assertEqual(res.action, PolicyAction.DISCARD.value)
        self.assertIn("already been notified", res.reason)

        # But CRITICAL still interrupts
        res_crit = self.policy.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.AVAILABLE.value,
            already_notified=True,
        )
        self.assertEqual(res_crit.action, PolicyAction.INTERRUPT.value)

    # --- 7. Recently Dismissed Suppression ---

    def test_recently_dismissed_suppresses_non_critical(self) -> None:
        """Verify recently_dismissed causes non-critical interventions to be SUPPRESSED."""
        res = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.AVAILABLE.value,
            recently_dismissed=True,
        )
        self.assertEqual(res.action, PolicyAction.SUPPRESS.value)
        self.assertIn("recently dismissed", res.reason)

    # --- 8. Relevance and Situation Freshness ---

    def test_low_relevance_discards_or_briefs(self) -> None:
        """Verify low relevance situations do not interrupt available users."""
        # Available + High urgency + Strong evidence + Low relevance -> BRIEFING (not INTERRUPT)
        res_brief = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            relevance="low",
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(res_brief.action, PolicyAction.BRIEFING.value)

        # Available + Medium urgency + Low relevance -> DISCARD
        res_disc = self.policy.evaluate(
            urgency="medium",
            actionability="medium",
            evidence_strength="moderate",
            relevance="low",
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(res_disc.action, PolicyAction.DISCARD.value)

    def test_stale_or_expired_situation_freshness_discards(self) -> None:
        """Verify stale or expired situations are silently discarded."""
        for freshness in ["stale", "expired"]:
            res = self.policy.evaluate(
                urgency="high",
                actionability="high",
                evidence_strength="strong",
                user_context=UserContext.AVAILABLE.value,
                situation_freshness=freshness,
            )
            self.assertEqual(res.action, PolicyAction.DISCARD.value)
            self.assertIn("temporally fresh", res.reason)

    # --- 9. Context Normalization Aliases ---

    def test_context_normalization_aliases(self) -> None:
        """Verify string aliases for meeting, deep work, sleep, driving, DND."""
        aliases = [
            ("sleep", UserContext.SLEEPING.value),
            ("sleeping", UserContext.SLEEPING.value),
            ("asleep", UserContext.SLEEPING.value),
            ("deep work", UserContext.DEEP_WORK.value),
            ("deep_work", UserContext.DEEP_WORK.value),
            ("focus", UserContext.DEEP_WORK.value),
            ("meeting", UserContext.MEETING.value),
            ("in_meeting", UserContext.MEETING.value),
            ("driving", UserContext.DRIVING.value),
            ("commute", UserContext.DRIVING.value),
            ("dnd", UserContext.DO_NOT_DISTURB.value),
            ("do_not_disturb", UserContext.DO_NOT_DISTURB.value),
            ("do not disturb", UserContext.DO_NOT_DISTURB.value),
        ]
        for raw, expected in aliases:
            normalized = self.policy.normalize_user_context(raw)
            self.assertEqual(normalized, expected, f"Failed for raw alias: {raw}")

    # --- 10. No Numerical Confidence Scores ---

    def test_no_numerical_confidence_scores_in_output(self) -> None:
        """Verify policy output contains strictly categorical reasoning and no fake probability scores."""
        res = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            relevance="high",
            user_context="available",
        )
        d = res.to_dict()
        # Assert no float confidence or probability keys exist
        self.assertNotIn("confidence", d)
        self.assertNotIn("probability", d)
        self.assertNotIn("score", d)
        self.assertIsInstance(d["action"], str)
        self.assertIn(d["action"], [a.value for a in PolicyAction])

    # --- 11. Serialization & Output Formatting ---

    def test_policy_result_serialization(self) -> None:
        """Verify PolicyEvaluationResult dictionary serialization."""
        res = self.policy.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            relevance="high",
            user_context="available",
            situation_freshness="fresh",
        )
        d = res.to_dict()
        self.assertEqual(d["action"], "INTERRUPT")
        self.assertEqual(d["inputs"]["urgency"], "high")
        self.assertEqual(d["inputs"]["relevance"], "high")
        self.assertEqual(d["inputs"]["situation_freshness"], "fresh")
        self.assertIn("timestamp", d)


if __name__ == "__main__":
    unittest.main()

