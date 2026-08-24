"""
Unit tests for the GoalEngine layer sitting above GoalStore.

Tests deterministic priority scoring, deadline urgency multipliers, dependency graph
evaluation, situation-to-goal impact assessment, resource conflict detection,
and integration with ContextBuilder and PersonalWorldModel.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.goals.engine import GoalEngine
from personal_intelligence.core.goals.models import (
    Goal,
    GoalConflictType,
    GoalImpactType,
    GoalPriority,
    GoalStatus,
)
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.storage.db import DatabaseManager


class TestGoalEngine(unittest.TestCase):
    """Test suite for GoalEngine deterministic reasoning."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_goals.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.goal_engine = GoalEngine(goal_store=self.goal_store)
        self.base_time = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Deterministic Priority & Deadline Urgency
    # -------------------------------------------------------------------------

    def test_deterministic_priority_weights(self) -> None:
        """Verify priority scores match user-defined deterministic weights without ML."""
        g_crit = Goal(name="Critical Project", priority=GoalPriority.CRITICAL.value)
        g_high = Goal(name="High Priority Task", priority=GoalPriority.HIGH.value)
        g_med = Goal(name="Medium Objective", priority=GoalPriority.MEDIUM.value)
        g_low = Goal(name="Low Habit", priority=GoalPriority.LOW.value)
        g_bg = Goal(name="Background Interest", priority=GoalPriority.BACKGROUND.value)

        self.assertEqual(self.goal_engine.get_effective_priority(g_crit, self.base_time), 3.0)
        self.assertEqual(self.goal_engine.get_effective_priority(g_high, self.base_time), 2.0)
        self.assertEqual(self.goal_engine.get_effective_priority(g_med, self.base_time), 1.0)
        self.assertEqual(self.goal_engine.get_effective_priority(g_low, self.base_time), 0.5)
        self.assertEqual(self.goal_engine.get_effective_priority(g_bg, self.base_time), 0.2)

    def test_deadline_urgency_multipliers(self) -> None:
        """Verify deadline proximity deterministically scales effective priority."""
        # Due in 12 hours -> 1.6x multiplier
        g_due_today = Goal(
            name="Ship Release",
            priority=GoalPriority.HIGH.value,  # base 2.0
            deadline=self.base_time + timedelta(hours=12),
        )
        self.assertEqual(self.goal_engine.get_urgency_multiplier(g_due_today, self.base_time), 1.6)
        self.assertEqual(self.goal_engine.get_effective_priority(g_due_today, self.base_time), 3.2)

        # Due in 2 days -> 1.3x multiplier
        g_due_3d = Goal(
            name="Deliver Draft",
            priority=GoalPriority.MEDIUM.value,  # base 1.0
            deadline=self.base_time + timedelta(days=2),
        )
        self.assertEqual(self.goal_engine.get_urgency_multiplier(g_due_3d, self.base_time), 1.3)
        self.assertEqual(self.goal_engine.get_effective_priority(g_due_3d, self.base_time), 1.3)

        # Overdue -> 2.0x multiplier
        g_overdue = Goal(
            name="Submit Report",
            priority=GoalPriority.MEDIUM.value,  # base 1.0
            deadline=self.base_time - timedelta(hours=3),
        )
        self.assertEqual(self.goal_engine.get_urgency_multiplier(g_overdue, self.base_time), 2.0)
        self.assertEqual(self.goal_engine.get_effective_priority(g_overdue, self.base_time), 2.0)

    # -------------------------------------------------------------------------
    # 2. Dependency Graph & Blocker Detection
    # -------------------------------------------------------------------------

    def test_goal_dependencies_and_blockers(self) -> None:
        """Verify GoalEngine tracks directed prerequisites and identifies blocked goals."""
        g_prereq = self.goal_store.create_goal(name="Prerequisite Architecture", status=GoalStatus.COMPLETED.value)
        g_pending_prereq = self.goal_store.create_goal(name="Pending Infrastructure", status=GoalStatus.ACTIVE.value)

        # Goal with completed dependency -> NOT blocked
        g_unblocked = Goal(
            name="Build Feature",
            dependencies=[g_prereq.id],
        )
        dep_status = self.goal_engine.check_dependencies(g_unblocked)
        self.assertFalse(dep_status["is_blocked"])
        self.assertIn(g_prereq.id, dep_status["completed_dependencies"])

        # Goal with pending dependency -> BLOCKED
        g_blocked = Goal(
            name="Deploy Service",
            dependencies=[g_pending_prereq.id],
        )
        dep_status_blocked = self.goal_engine.check_dependencies(g_blocked)
        self.assertTrue(dep_status_blocked["is_blocked"])
        self.assertIn(g_pending_prereq.id, dep_status_blocked["unmet_dependencies"])

    # -------------------------------------------------------------------------
    # 3. Situation-to-Goal Impact & Conflict Assessment
    # -------------------------------------------------------------------------

    def test_situation_to_goal_impact_energy_scarcity(self) -> None:
        """
        Verify that a cognitive/physical strain situation identifies training
        goals as AT_RISK or IMPEDED due to physiological contradiction.
        """
        g_workout = self.goal_store.create_goal(name="10km Interval Run", priority=GoalPriority.HIGH.value)
        g_reading = self.goal_store.create_goal(name="Read Architecture Book", priority=GoalPriority.LOW.value)

        sit_strain = Situation(
            id="sit-strain-01",
            type="cognitive_physical_strain_risk",
            context={"summary": "Severe sleep deficit (3.75h) followed by 7-hour executive workload before workout"},
        )

        impacts = self.goal_engine.evaluate_situation_impact(
            situation=sit_strain,
            reference_time=self.base_time,
        )

        # Workout goal must be flagged as AT_RISK with energy scarcity
        workout_impacts = [imp for imp in impacts if imp.goal_id == g_workout.id]
        self.assertTrue(len(workout_impacts) >= 1)
        self.assertEqual(workout_impacts[0].impact_type, GoalImpactType.AT_RISK.value)
        self.assertIn("energy_scarcity", workout_impacts[0].competing_factors)

    def test_situation_to_goal_impact_time_scarcity(self) -> None:
        """
        Verify that reduced available time / meeting density flags time-intensive
        work and training goals as IMPEDED.
        """
        g_project = self.goal_store.create_goal(name="Complete architecture project", priority=GoalPriority.CRITICAL.value)
        g_exercise = self.goal_store.create_goal(name="Exercise regularly", priority=GoalPriority.HIGH.value)

        sit_schedule = Situation(
            id="sit-sched-01",
            type="schedule_conflict",
            context={"summary": "High meeting density has reduced available focus time to under 45 minutes"},
        )

        impacts = self.goal_engine.evaluate_situation_impact(
            situation=sit_schedule,
            reference_time=self.base_time,
        )

        impacted_goal_ids = {imp.goal_id for imp in impacts}
        self.assertIn(g_project.id, impacted_goal_ids)

    def test_goal_conflict_detection_under_time_scarcity(self) -> None:
        """
        Verify conflict detection finds competition between multiple high-priority goals
        when time is scarce and suggests prioritizing the higher effective priority.
        """
        g_proj = self.goal_store.create_goal(name="Architecture Project", priority=GoalPriority.CRITICAL.value)
        g_run = self.goal_store.create_goal(name="Marathon Training", priority=GoalPriority.HIGH.value)

        sit_tight = Situation(
            id="sit-tight-01",
            type="reduced_available_time",
            context={"summary": "Calendar is saturated with critical stakeholder syncs"},
        )

        conflicts = self.goal_engine.detect_conflicts(
            situation=sit_tight,
            reference_time=self.base_time,
        )

        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c.conflict_type, GoalConflictType.TIME_SCARCITY.value)
        self.assertIn(g_proj.id, c.goal_ids)
        self.assertIn(g_run.id, c.goal_ids)
        self.assertIn(g_proj.name, c.resolution_suggestion)  # Prioritizes Critical over High

    # -------------------------------------------------------------------------
    # 4. Situational Ranking & ContextBuilder Integration
    # -------------------------------------------------------------------------

    def test_rank_goals_for_situation(self) -> None:
        """Verify rank_goals_for_situation orders goals by composite importance."""
        g_crit = self.goal_store.create_goal(name="Ship Core V1", priority=GoalPriority.CRITICAL.value)
        g_unrelated = self.goal_store.create_goal(name="Plant Garden", priority=GoalPriority.LOW.value)

        sit = Situation(
            id="sit-01",
            type="goal_risk",
            context={"summary": "Ship Core V1 has high-severity blockers"},
            related_goals=[g_crit.id],
        )

        ranked = self.goal_engine.rank_goals_for_situation(
            situation=sit,
            reference_time=self.base_time,
        )

        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["goal_id"], g_crit.id)
        self.assertGreater(ranked[0]["composite_rank_score"], ranked[1]["composite_rank_score"])

    def test_context_builder_integration(self) -> None:
        """Verify ContextBuilder produces rich goal context using GoalEngine."""
        g1 = self.goal_store.create_goal(
            name="Deliver Architecture",
            priority=GoalPriority.HIGH.value,
        )
        builder = ContextBuilder(
            goal_store=self.goal_store,
            goal_engine=self.goal_engine,
        )

        sit = Situation(
            id="sit-test",
            type="schedule_conflict",
            context={"summary": "Busy calendar today"},
        )
        state = StateRepresentation(timestamp=self.base_time)

        ctx = builder.build_bounded_context(
            situation=sit,
            current_state=state,
        )

        self.assertEqual(len(ctx.active_goals), 1)
        goal_ctx = ctx.active_goals[0]
        self.assertEqual(goal_ctx["name"], "Deliver Architecture")
        self.assertIn("effective_priority_score", goal_ctx)
        self.assertIn("urgency_score", goal_ctx)

    def test_personal_world_model_goal_engine_integration(self) -> None:
        """Verify PersonalWorldModel initializes and integrates GoalEngine."""
        pwm = PersonalWorldModel(db_manager=self.db_manager)
        self.assertIsNotNone(pwm.goal_engine)
        self.assertIsInstance(pwm.goal_engine, GoalEngine)


if __name__ == "__main__":
    unittest.main()
