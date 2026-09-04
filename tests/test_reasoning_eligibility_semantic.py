"""
Acceptance Test Suite for Reasoning Eligibility Gate Semantic Refactoring.

Verifies the conceptual shift from:
  "Does this situation fit a token budget?"
to:
  "Should PI spend reasoning resources on this situation?"

Explicit Acceptance Tests:
1. novel but insignificant -> reject
2. non-novel but significant -> allow
3. significant and uncertain -> allow
4. duplicate recently reasoned situation -> reject/defer
5. stale situation -> reject/defer
6. high-value cross-context situation -> allow
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.significance import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.situations.eligibility import (
    ReasoningBudget,
    ReasoningCostClass,
    ReasoningEligibility,
    ReasoningEligibilityGate,
    ReasoningEligibilityResult,
    ReasoningValueLevel,
)
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus


class TestReasoningEligibilitySemantic(unittest.TestCase):
    """Verifies semantic reasoning resource allocation by ReasoningEligibilityGate."""

    def setUp(self) -> None:
        self.gate = ReasoningEligibilityGate()
        self.now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_1_novel_but_insignificant_rejects_reasoning(self) -> None:
        """
        Acceptance Scenario 1:
        A situation has high statistical novelty (0.92) but is evaluated as NOT_SIGNIFICANT.
        PI must REJECT spending reasoning resources on insignificant noise.
        """
        sit = Situation(
            id="sit-novel-noise",
            type="minor_visual_shift",
            priority=SituationPriority.LOW.value,
            status=SituationStatus.OPEN.value,
            novelty=0.92,
        )
        sig = SignificanceAssessment(
            level=SignificanceLevel.NOT_SIGNIFICANT.value,
            novelty_impact="highly_unusual",
        )

        decision = self.gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=True,
            has_new_events=True,
            as_of=self.now,
        )

        # Conceptual decision
        self.assertFalse(decision.eligible, "Insignificant noise must not be eligible for reasoning")
        self.assertFalse(decision.requires_hermes, "Insignificant noise must not invoke Hermes")
        self.assertEqual(decision.estimated_reasoning_value, ReasoningValueLevel.NEGLIGIBLE.value)
        self.assertEqual(decision.cost_class, ReasoningCostClass.NONE.value)
        self.assertIn("NOT_SIGNIFICANT", decision.reason)

    def test_2_non_novel_but_significant_allows_reasoning(self) -> None:
        """
        Acceptance Scenario 2:
        A situation has zero/low novelty (0.05) because it matches a familiar recurring failure,
        but has CRITICAL/HIGH personal significance.
        Novelty is NOT mandatory; PI must ALLOW spending reasoning resources.
        """
        sit = Situation(
            id="sit-familiar-critical",
            type="goal_risk",
            priority=SituationPriority.CRITICAL.value,
            status=SituationStatus.OPEN.value,
            novelty=0.05,
        )
        sig = SignificanceAssessment(
            level=SignificanceLevel.CRITICAL.value,
            novelty_impact="normal",
        )

        decision = self.gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=True,
            has_new_events=True,
            as_of=self.now,
        )

        # Conceptual decision
        self.assertTrue(decision.eligible, "High significance routine events must be eligible for reasoning")
        self.assertTrue(decision.requires_hermes, "Critical significance must invoke Hermes")
        self.assertEqual(decision.priority, "critical")
        self.assertEqual(decision.estimated_reasoning_value, ReasoningValueLevel.CRITICAL.value)
        self.assertIn(decision.cost_class, (ReasoningCostClass.STANDARD.value, ReasoningCostClass.DEEP_INVESTIGATION.value))

    def test_3_significant_and_uncertain_allows_investigation_and_reasoning(self) -> None:
        """
        Acceptance Scenario 3:
        A situation has HIGH significance and an unresolved information gap / uncertainty.
        PI must ALLOW spending higher investigation & reasoning resources.
        """
        sit = Situation(
            id="sit-uncertain-deadline",
            type="deadline_ambiguity",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.OPEN.value,
            information_required=True,
            investigation_target="Query client repo for merge status",
        )
        sig = SignificanceAssessment(
            level=SignificanceLevel.HIGH.value,
        )

        decision = self.gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=True,
            has_new_events=True,
            uncertainty="high",
            as_of=self.now,
        )

        self.assertTrue(decision.eligible)
        self.assertTrue(decision.requires_hermes)
        self.assertTrue(decision.requires_investigation)
        self.assertTrue(decision.uncertainty_present)
        self.assertEqual(decision.estimated_reasoning_value, ReasoningValueLevel.HIGH.value)
        self.assertEqual(decision.cost_class, ReasoningCostClass.DEEP_INVESTIGATION.value)
        self.assertGreater(decision.budget.max_investigation_rounds, 0)

    def test_4_duplicate_recently_reasoned_situation_rejects_repeated_analysis(self) -> None:
        """
        Acceptance Scenario 4:
        A situation has already been evaluated recently in reasoning history, and no new material
        events have arrived.
        PI must REJECT/DEFER duplicate reasoning to avoid wasteful repeated analysis.
        """
        sit = Situation(
            id="sit-already-reasoned",
            type="budget_review",
            priority=SituationPriority.MEDIUM.value,
            status=SituationStatus.OPEN.value,
            last_evaluated_at=self.now - timedelta(minutes=15),
        )
        sig = SignificanceAssessment(
            level=SignificanceLevel.MEDIUM.value,
        )

        # Mock recent episode history containing this situation
        mock_history = [
            {"situation_id": "sit-already-reasoned", "timestamp": self.now - timedelta(minutes=15)}
        ]

        decision = self.gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=False,
            has_new_events=False,
            is_due_reevaluation=False,
            reasoning_history=mock_history,
            as_of=self.now,
        )

        self.assertFalse(decision.eligible, "Duplicate reasoning must be rejected")
        self.assertFalse(decision.requires_hermes)
        self.assertTrue(decision.is_duplicate)
        self.assertEqual(decision.cost_class, ReasoningCostClass.NONE.value)
        self.assertIn("already evaluated", decision.reason.lower())

    def test_5_stale_situation_rejects_or_defers_reasoning(self) -> None:
        """
        Acceptance Scenario 5:
        A situation has become stale (expired event timestamps without fresh observations).
        PI must REJECT/DEFER spending reasoning resources on stale situations.
        """
        sit = Situation(
            id="sit-stale-conflict",
            type="flight_delay",
            priority=SituationPriority.MEDIUM.value,
            status=SituationStatus.ACTIVE.value,
            created_at=self.now - timedelta(days=10),
            updated_at=self.now - timedelta(days=9),
        )
        sig = SignificanceAssessment(
            level=SignificanceLevel.MEDIUM.value,
        )

        decision = self.gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=False,
            has_new_events=False,
            as_of=self.now,
        )

        self.assertFalse(decision.eligible, "Stale situation must be rejected/deferred from reasoning")
        self.assertFalse(decision.requires_hermes)
        self.assertTrue(decision.is_stale)
        self.assertEqual(decision.cost_class, ReasoningCostClass.NONE.value)
        self.assertIn("stale", decision.reason.lower())

    def test_6_high_value_cross_context_situation_allows_reasoning(self) -> None:
        """
        Acceptance Scenario 6:
        A situation spans disparate personal contexts (e.g. personal medical appointment
        conflicts with critical work executive meeting).
        Reasoning provides high synthesis value; PI must ALLOW reasoning.
        """
        sit = Situation(
            id="sit-cross-context-conflict",
            type="cross_context_conflict",
            priority=SituationPriority.MEDIUM.value,
            status=SituationStatus.OPEN.value,
            context={"is_cross_context": True},
        )
        sig = SignificanceAssessment(
            level=SignificanceLevel.MEDIUM.value,
        )

        decision = self.gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=True,
            has_new_events=True,
            is_cross_context=True,
            as_of=self.now,
        )

        self.assertTrue(decision.eligible, "Cross-context situation must be eligible for reasoning")
        self.assertTrue(decision.requires_hermes)
        self.assertEqual(decision.estimated_reasoning_value, ReasoningValueLevel.HIGH.value)
        self.assertEqual(decision.cost_class, ReasoningCostClass.STANDARD.value)
        self.assertIn("cross-context", decision.reason.lower())

    def test_decision_model_structure(self) -> None:
        """Verifies semantic decision model fields and serialization."""
        sit = Situation(
            id="sit-demo",
            type="goal_risk",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.OPEN.value,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.HIGH.value)
        res = self.gate.evaluate(sit, sig, is_new_situation=True, has_new_events=True)

        # Check semantic fields
        self.assertIsInstance(res.eligible, bool)
        self.assertIsInstance(res.reason, str)
        self.assertIsInstance(res.priority, str)
        self.assertIsInstance(res.estimated_reasoning_value, str)
        self.assertIsInstance(res.cost_class, str)

        # Check serialization
        d = res.to_dict()
        self.assertIn("eligible", d)
        self.assertIn("reason", d)
        self.assertIn("priority", d)
        self.assertIn("estimated_reasoning_value", d)
        self.assertIn("cost_class", d)
        self.assertIn("budget", d)
        self.assertIn("requires_hermes", d)


if __name__ == "__main__":
    unittest.main()
