"""
Unit tests for PersonalSignificanceEngine (Prompt 2, Change 1).
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.novelty.models import NoveltyResult
from personal_intelligence.core.significance import (
    PersonalSignificanceEngine,
    SignificanceAssessment,
    SignificanceLevel,
)
from personal_intelligence.core.world.changes import MeaningfulChange
from personal_intelligence.core.world.models import Commitment, CommitmentStatus


class TestPersonalSignificanceEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PersonalSignificanceEngine(
            imminent_deadline_hours=6.0,
            soon_deadline_hours=24.0,
        )
        self.base_time = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)

    def test_critical_goal_change_is_critical_significance(self) -> None:
        """Change affecting a critical goal produces CRITICAL significance."""
        goal = Goal(name="Launch Production Beta", priority=GoalPriority.CRITICAL.value)
        change = MeaningfulChange(
            what_changed="Deployment pipeline failure for Launch Production Beta",
            why_it_matters="Blocks the critical release milestone",
            evidence=["CI/CD build failed at step 4"],
            what_may_happen_next="Release delayed past deadline",
            uncertainty="Unknown fix effort",
        )
        result = self.engine.evaluate_change(
            change=change,
            active_goals=[goal],
            reference_time=self.base_time,
        )
        self.assertEqual(result.level, SignificanceLevel.CRITICAL.value)
        self.assertEqual(result.goal_relevance, "critical")
        self.assertEqual(result.actionability, "high")

    def test_imminent_commitment_deadline_is_critical(self) -> None:
        """Commitment due in <6h with high actionability produces CRITICAL significance."""
        comm = Commitment(
            description="Send Q3 board deck to CEO",
            status=CommitmentStatus.PENDING.value,
            due_at=self.base_time + timedelta(hours=3),
        )
        change = MeaningfulChange(
            what_changed="Draft board deck remains incomplete",
            why_it_matters="Due in 3 hours",
            evidence=["Doc edit stopped 2 hours ago"],
            what_may_happen_next="Missed commitment to executive",
            uncertainty="None",
            domain="commitment",
        )
        result = self.engine.evaluate_change(
            change=change,
            commitments=[comm],
            reference_time=self.base_time,
        )
        self.assertEqual(result.level, SignificanceLevel.CRITICAL.value)
        self.assertEqual(result.deadline_proximity, "imminent_<6h")

    def test_high_priority_goal_change_is_high_significance(self) -> None:
        """Change affecting a high priority goal produces HIGH significance."""
        goal = Goal(name="Hiring Pipeline Q3", priority=GoalPriority.HIGH.value)
        change = MeaningfulChange(
            what_changed="Lead candidate interview rescheduled for Hiring Pipeline Q3",
            why_it_matters="Extends candidate decision window",
            evidence=["Calendar update from recruiter"],
            what_may_happen_next="Offer timeline shifted by 3 days",
            uncertainty="Candidate availability",
        )
        result = self.engine.evaluate_change(
            change=change,
            active_goals=[goal],
            reference_time=self.base_time,
        )
        self.assertEqual(result.level, SignificanceLevel.HIGH.value)

    def test_novel_combination_escalates_significance(self) -> None:
        """Statistically novel multi-domain feature combination produces HIGH significance."""
        change = MeaningfulChange(
            what_changed="Unfamiliar combination of late flight, night meeting, and low sleep",
            why_it_matters="High fatigue and scheduling risk",
            evidence=["Mobility and calendar conflict"],
            what_may_happen_next="Severe fatigue during morning presentation",
            uncertainty="Flight delay probability",
        )
        novelty = NoveltyResult(
            overall_level="NOVEL_COMBINATION",
            metadata={"score": 0.92, "novelty_type": "cross_domain_co_occurrence"},
        )
        result = self.engine.evaluate_change(
            change=change,
            novelty_result=novelty,
            reference_time=self.base_time,
        )
        self.assertEqual(result.level, SignificanceLevel.HIGH.value)
        self.assertEqual(result.novelty_impact, "novel_combination")

    def test_routine_background_change_is_not_significant(self) -> None:
        """Routine change with no goal or commitment ties produces NOT_SIGNIFICANT."""
        change = MeaningfulChange(
            what_changed="Routine background newsletter received",
            why_it_matters="General industry news",
            evidence=[],
            what_may_happen_next="",
            uncertainty="",
        )
        result = self.engine.evaluate_change(
            change=change,
            active_goals=[],
            reference_time=self.base_time,
        )
        self.assertEqual(result.level, SignificanceLevel.NOT_SIGNIFICANT.value)

    def test_evaluate_situation_directly(self) -> None:
        """Test direct situation significance assessment."""
        res_crit = self.engine.evaluate_situation(
            situation_type="goal_risk",
            situation_priority="critical",
            evidence_count=3,
        )
        self.assertEqual(res_crit.level, SignificanceLevel.CRITICAL.value)

        res_info_gap = self.engine.evaluate_situation(
            situation_type="information_gap",
            situation_priority="medium",
            evidence_count=1,
            has_information_gap=True,
        )
        self.assertEqual(res_info_gap.level, SignificanceLevel.HIGH.value)


if __name__ == "__main__":
    unittest.main()
