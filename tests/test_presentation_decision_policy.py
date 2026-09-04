"""
Acceptance Test Suite for InterventionPolicyEngine & PresentationDecision API.

Verifies:
1. Hermes cannot force INTERRUPT (forced action injection ignored, critical urgency requires policy evaluation).
2. Weak/unverified evidence cannot bypass policy (defers to avoid premature interruptions).
3. Quiet/focus context is respected (hard suppression and focus contexts defer/suppress interruptions).
4. High significance can produce INTERRUPT when policy permits (high urgency, high actionability, verified evidence, available user context).
5. Low-value situations can be suppressed/discarded.
6. Public API exposes the five meaningful presentation outcomes (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD).
"""

import unittest

from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    PolicyEvaluationResult,
    PresentationAction,
    PresentationDecision,
    UserContext,
    decide_intervention,
    decide_presentation,
)


class TestPresentationDecisionPolicy(unittest.TestCase):
    """Verifies PresentationDecision public model and intervention routing rules."""

    def setUp(self) -> None:
        self.engine = InterventionPolicyEngine()

    def test_public_api_exposes_five_presentation_outcomes(self) -> None:
        """
        ACCEPTANCE TEST 6:
        Public API exposes the five meaningful presentation outcomes via PresentationDecision & PresentationAction.
        """
        actions = [a.value for a in PresentationAction]
        self.assertCountEqual(actions, ["INTERRUPT", "BRIEFING", "DEFER", "SUPPRESS", "DISCARD"])

        # Decide presentation returns PresentationDecision instance
        decision = decide_presentation(urgency="medium", actionability="high", user_context="available")
        self.assertIsInstance(decision, PresentationDecision)
        self.assertIsInstance(decision, PolicyEvaluationResult)
        self.assertIn(decision.action, actions)

        # Dictionary representation contains input fields and action
        dict_rep = decision.to_dict()
        self.assertIn("action", dict_rep)
        self.assertIn("reason", dict_rep)
        self.assertIn("inputs", dict_rep)

    def test_hermes_cannot_force_interrupt(self) -> None:
        """
        ACCEPTANCE TEST 1:
        Hermes cannot dictate or force INTERRUPT.
        Forced action injection in recommendation dictionary is ignored.
        """
        forced_recommendation = {
            "action": "INTERRUPT",  # Unauthorized LLM directive!
            "urgency": "low",
            "actionability": "low",
            "relevance": "low",
        }

        # Policy evaluates objective inputs and returns DISCARD/SUPPRESS, ignoring forced INTERRUPT
        res = self.engine.evaluate_recommendation(
            recommendation=forced_recommendation,
            user_context="available",
        )
        self.assertNotEqual(res.action, PresentationAction.INTERRUPT.value)
        self.assertIn(res.action, (PresentationAction.DISCARD.value, PresentationAction.SUPPRESS.value))

    def test_weak_unverified_evidence_cannot_bypass_policy(self) -> None:
        """
        ACCEPTANCE TEST 2:
        Weak/unverified evidence cannot bypass policy to produce an interruption.
        """
        # Critical urgency with weak evidence quality -> DEFER
        res_crit_weak = decide_presentation(
            urgency="critical",
            actionability="high",
            evidence_quality="weak",
            user_context="available",
        )
        self.assertEqual(res_crit_weak.action, PresentationAction.DEFER.value)

        # High urgency with weak evidence -> DEFER
        res_high_weak = decide_presentation(
            urgency="high",
            actionability="high",
            evidence_quality="weak",
            user_context="available",
        )
        self.assertEqual(res_high_weak.action, PresentationAction.DEFER.value)

    def test_quiet_focus_context_is_respected(self) -> None:
        """
        ACCEPTANCE TEST 3:
        Quiet/focus context is respected (deep_work, meeting, dnd, driving, sleep).
        """
        quiet_contexts = [
            UserContext.MEETING.value,
            UserContext.DEEP_WORK.value,
            UserContext.DRIVING.value,
            UserContext.SLEEPING.value,
            UserContext.DO_NOT_DISTURB.value,
        ]

        for ctx in quiet_contexts:
            res = decide_presentation(
                urgency="high",
                actionability="high",
                evidence_quality="strong",
                user_context=ctx,
            )
            self.assertIn(
                res.action,
                (PresentationAction.DEFER.value, PresentationAction.SUPPRESS.value),
                f"Failed for quiet context: {ctx}",
            )
            self.assertNotEqual(res.action, PresentationAction.INTERRUPT.value)

    def test_high_significance_can_produce_interrupt(self) -> None:
        """
        ACCEPTANCE TEST 4:
        High personal significance produces INTERRUPT when policy conditions permit.
        """
        res = decide_presentation(
            urgency="high",
            actionability="high",
            evidence_quality="strong",
            personal_significance="high",
            user_context="available",
        )
        self.assertEqual(res.action, PresentationAction.INTERRUPT.value)

    def test_low_value_situations_are_suppressed_or_discarded(self) -> None:
        """
        ACCEPTANCE TEST 5:
        Low-value situations (low urgency, low actionability, stale, or already notified)
        are suppressed or discarded.
        """
        # Low urgency + low actionability -> DISCARD
        res_low = decide_presentation(
            urgency="low",
            actionability="low",
            user_context="available",
        )
        self.assertEqual(res_low.action, PresentationAction.DISCARD.value)

        # Stale situation -> DISCARD
        res_stale = decide_presentation(
            urgency="high",
            freshness="stale",
        )
        self.assertEqual(res_stale.action, PresentationAction.DISCARD.value)

        # Recently dismissed situation -> SUPPRESS
        res_dismissed = decide_presentation(
            urgency="high",
            recently_dismissed=True,
        )
        self.assertEqual(res_dismissed.action, PresentationAction.SUPPRESS.value)


if __name__ == "__main__":
    unittest.main()
