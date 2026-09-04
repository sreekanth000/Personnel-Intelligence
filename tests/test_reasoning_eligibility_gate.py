"""
Unit tests for ReasoningEligibilityGate and ReasoningBudget (Prompt 2, Change 2 & 3).
"""

from datetime import datetime, timezone
import unittest

from personal_intelligence.core.significance import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.situations.eligibility import (
    ReasoningBudget,
    ReasoningBudgetLevel,
    ReasoningEligibility,
    ReasoningEligibilityGate,
)
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus


class TestReasoningEligibilityGate(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = ReasoningEligibilityGate()
        self.base_time = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)

    def test_insignificant_change_produces_no_reasoning(self) -> None:
        """NOT_SIGNIFICANT change produces NO_REASONING with LOW budget."""
        sit = Situation(
            id="sit_routine",
            type="routine_observation",
            priority=SituationPriority.LOW.value,
            status=SituationStatus.OPEN.value,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.NOT_SIGNIFICANT.value)
        result = self.gate.evaluate(sit, sig, is_new_situation=False)

        self.assertFalse(result.eligible)
        self.assertEqual(result.cost_class, "none")
        self.assertEqual(result.estimated_reasoning_value, "negligible")
        self.assertEqual(result.eligibility, ReasoningEligibility.NO_REASONING.value)
        self.assertFalse(result.budget.allow_hermes_call)
        self.assertEqual(result.budget.budget_level, ReasoningBudgetLevel.LOW.value)

    def test_closed_situation_skips_reasoning(self) -> None:
        """Resolved or dismissed situations produce NO_REASONING."""
        sit = Situation(
            id="sit_resolved",
            type="goal_risk",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.RESOLVED.value,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.HIGH.value)
        result = self.gate.evaluate(sit, sig)

        self.assertFalse(result.eligible)
        self.assertEqual(result.cost_class, "none")
        self.assertEqual(result.eligibility, ReasoningEligibility.NO_REASONING.value)
        self.assertFalse(result.budget.allow_hermes_call)

    def test_critical_significance_produces_critical_budget(self) -> None:
        """CRITICAL significance triggers HERMES_REASONING with CRITICAL budget."""
        sit = Situation(
            id="sit_crit",
            type="goal_risk",
            priority=SituationPriority.CRITICAL.value,
            status=SituationStatus.OPEN.value,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.CRITICAL.value)
        result = self.gate.evaluate(sit, sig, is_new_situation=True)

        self.assertTrue(result.eligible)
        self.assertEqual(result.priority, "critical")
        self.assertEqual(result.estimated_reasoning_value, "critical")
        self.assertEqual(result.eligibility, ReasoningEligibility.HERMES_REASONING.value)
        self.assertTrue(result.budget.allow_hermes_call)
        self.assertEqual(result.budget.budget_level, ReasoningBudgetLevel.CRITICAL.value)
        self.assertEqual(result.budget.max_investigation_rounds, 3)

    def test_information_gap_produces_investigation_and_reasoning(self) -> None:
        """High significance situation with information_required triggers HERMES_INVESTIGATION_AND_REASONING."""
        sit = Situation(
            id="sit_gap",
            type="information_gap",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.OPEN.value,
            information_required=True,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.HIGH.value)
        result = self.gate.evaluate(sit, sig, is_new_situation=True)

        self.assertTrue(result.eligible)
        self.assertEqual(result.cost_class, "deep_investigation")
        self.assertEqual(result.eligibility, ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value)
        self.assertTrue(result.requires_investigation)
        self.assertTrue(result.budget.allow_hermes_call)
        self.assertGreater(result.budget.max_investigation_rounds, 0)
        self.assertGreater(result.budget.max_tool_calls, 0)

    def test_medium_significance_standard_reasoning_no_investigation(self) -> None:
        """MEDIUM significance triggers standard HERMES_REASONING without external tool calls."""
        sit = Situation(
            id="sit_med",
            type="conflicting_commitments",
            priority=SituationPriority.MEDIUM.value,
            status=SituationStatus.OPEN.value,
            information_required=False,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.MEDIUM.value)
        result = self.gate.evaluate(sit, sig, is_new_situation=True)

        self.assertTrue(result.eligible)
        self.assertEqual(result.cost_class, "standard")
        self.assertEqual(result.eligibility, ReasoningEligibility.HERMES_REASONING.value)
        self.assertEqual(result.budget.budget_level, ReasoningBudgetLevel.MEDIUM.value)
        self.assertEqual(result.budget.max_investigation_rounds, 0)
        self.assertEqual(result.budget.max_tool_calls, 0)

    def test_low_significance_triggers_local_reasoning(self) -> None:
        """LOW significance triggers LOCAL_REASONING without invoking Hermes."""
        sit = Situation(
            id="sit_low",
            type="prolonged_inactivity_on_priority",
            priority=SituationPriority.LOW.value,
            status=SituationStatus.OPEN.value,
        )
        sig = SignificanceAssessment(level=SignificanceLevel.LOW.value)
        result = self.gate.evaluate(sit, sig, is_new_situation=False, has_new_events=True)

        self.assertTrue(result.eligible)
        self.assertEqual(result.cost_class, "local_only")
        self.assertFalse(result.requires_hermes)
        self.assertEqual(result.eligibility, ReasoningEligibility.LOCAL_REASONING.value)
        self.assertFalse(result.budget.allow_hermes_call)


if __name__ == "__main__":
    unittest.main()
