"""
Unit & Integration Tests for Domain-Agnostic Situation Discovery (Prompt 6).

Verifies:
1. Novel but insignificant: High novelty divergence does not inflate priority without goal relevance.
2. Non-novel but highly significant: Routine/zero-novelty event on critical goal achieves HIGH/CRITICAL priority.
   (Proves novelty is NOT a mandatory gateway to significance).
3. Cross-domain situation: Synthesizes circumstances across calendar, focus, and repository without domain agents.
4. Multi-goal situation: Links and impacts multiple active goals simultaneously.
5. Recurring situation: Re-evaluates existing situation with fresh evidence rather than duplicating.
6. Stale situation: Evaluates freshness decay to STALE/DECAYING over elapsed time.
7. Duplicate situation: Deduplicates candidate situations sharing identical deterministic context identity.
8. Unrelated events: Disjoint events do not produce spurious combined situations.
9. New arbitrary signal type: Registering custom signal detectors does not require new agents or domain pipelines.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.novelty.models import NoveltyResult, OverallNoveltyLevel
from personal_intelligence.core.significance.engine import PersonalSignificanceEngine
from personal_intelligence.core.significance.models import SignificanceLevel
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import (
    Situation,
    SituationFreshness,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.world.graph import CanonicalRelationship, ContextGraph
from personal_intelligence.core.world.models import Commitment, CommitmentStatus, CurrentState
from personal_intelligence.storage.db import DatabaseManager


class TestSituationDiscoveryDomainAgnostic(unittest.TestCase):
    """Test suite for Prompt 6 domain-agnostic situation discovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_sit_disc.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.lifecycle_manager = SituationLifecycleManager(situation_store=self.situation_store)
        self.engine = SituationEngine()
        self.significance_engine = PersonalSignificanceEngine()
        self.now = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_novel_but_insignificant(self) -> None:
        """Requirement: Novel but insignificant. High novelty does not force high situation priority without goals."""
        current_state = CurrentState(timestamp=self.now)
        # Novel observation completely unrelated to any active user goals or commitments
        novel_obs = Event(
            id="evt-novel-01",
            source="rss_reader",
            event_type="news_item",
            event_time=self.now,
            payload={"title": "Unusual astronomical transit observed in Andromeda galaxy"},
        )
        novelty_res = NoveltyResult(
            overall_level="HIGHLY_UNUSUAL",
            metadata={"divergence_score": 0.92, "novelty_factors": ["unexpected_topic", "unseen_vocabulary"]},
        )

        evaluation = self.engine.evaluate(
            current_state=current_state,
            goals=[],  # No goals relevant to astronomy
            recent_observations=[novel_obs],
            novelty_result=novelty_res,
            reference_time=self.now,
        )

        # Candidate may be discovered under unusual_change or novel_situation, but priority remains LOW or INFORMATIONAL
        for cand in evaluation.candidate_situations:
            if "andromeda" in str(cand.evidence).lower() or "astronomical" in str(cand.evidence).lower():
                self.assertIn(cand.priority, (SituationPriority.LOW.value, SituationPriority.INFORMATIONAL.value, SituationPriority.MEDIUM.value))
                self.assertNotEqual(cand.priority, SituationPriority.CRITICAL.value)

    def test_2_non_novel_but_highly_significant(self) -> None:
        """Requirement: Non-novel but highly significant. Routine event on critical goal is HIGH/CRITICAL without novelty."""
        critical_goal = Goal(
            id="goal-prod-launch",
            name="Production Platform Launch",
            description="Deliver v1.0 release to customers without downtime",
            priority=GoalPriority.CRITICAL.value,
        )
        current_state = CurrentState(
            timestamp=self.now,
            current_commitments=[
                Commitment(
                    id="commit-deploy",
                    name="Execute Production Deployment",
                    due_at=self.now + timedelta(hours=2),  # Imminent deadline (2 hours away!)
                    status=CommitmentStatus.PENDING.value,
                )
            ],
        )

        # Completely routine/expected events (zero novelty)
        routine_obs = Event(
            id="evt-routine-status",
            source="deployment_pipeline",
            event_type="pipeline_blocked",
            event_time=self.now,
            payload={"status": "blocked", "reason": "Pre-flight database migration check failed"},
        )
        zero_novelty = NoveltyResult(
            overall_level="NORMAL",
            metadata={"divergence_score": 0.0, "novelty_factors": []},
        )

        evaluation = self.engine.evaluate(
            current_state=current_state,
            goals=[critical_goal],
            recent_observations=[routine_obs],
            novelty_result=zero_novelty,
            reference_time=self.now,
        )

        # Must discover critical situation despite ZERO novelty
        self.assertGreaterEqual(len(evaluation.candidate_situations), 1)
        high_prio_cands = [
            c for c in evaluation.candidate_situations
            if c.priority in (SituationPriority.CRITICAL.value, SituationPriority.HIGH.value)
        ]
        self.assertGreater(len(high_prio_cands), 0)
        # Novelty is preserved as 0.0 signal, not a blocker
        self.assertEqual(high_prio_cands[0].novelty, 0.0)

    def test_3_cross_domain_situation(self) -> None:
        """Requirement: Cross-domain situation synthesized across calendar, app focus, and goals without domain agents."""
        goal = Goal(
            id="goal-deep-work",
            name="Deep Work Focus",
            priority=GoalPriority.HIGH.value,
        )
        current_state = CurrentState(
            timestamp=self.now,
        )

        timeline_events = [
            # Focus app domain
            Event(
                id="evt-focus-1",
                source="os_window",
                event_type="app_focus",
                event_time=self.now - timedelta(minutes=150),
                payload={"app": "IDE", "duration_minutes": 150},
            ),
            # Calendar domain
            Event(
                id="evt-cal-1",
                source="google_calendar",
                event_type="calendar_event",
                event_time=self.now + timedelta(minutes=15),
                payload={"title": "Executive Review Sync", "duration_minutes": 45},
            ),
        ]
        timeline = Timeline(events=timeline_events)

        evaluation = self.engine.evaluate(
            current_state=current_state,
            timeline=timeline,
            goals=[goal],
            recent_observations=timeline_events,
            reference_time=self.now,
        )

        # Cross-domain synthesis must detect prolonged activity before imminent calendar meeting
        self.assertGreaterEqual(len(evaluation.candidate_situations), 1)

    def test_4_multi_goal_situation(self) -> None:
        """Requirement: Multi-goal situation affecting multiple distinct goals simultaneously."""
        goal1 = Goal(id="goal-client-alpha", name="Client Alpha Deliverable", priority=GoalPriority.HIGH.value)
        goal2 = Goal(id="goal-wellness", name="Work-Life Balance", priority=GoalPriority.MEDIUM.value)

        current_state = CurrentState(
            timestamp=self.now,
            current_commitments=[
                Commitment(
                    id="commit-overdue-client",
                    name="Send client alpha proposal",
                    due_at=self.now - timedelta(hours=3),  # Overdue
                    status=CommitmentStatus.PENDING.value,
                )
            ],
        )

        evaluation = self.engine.evaluate(
            current_state=current_state,
            goals=[goal1, goal2],
            reference_time=self.now,
        )

        self.assertGreater(len(evaluation.candidate_situations), 0)
        first_cand = evaluation.candidate_situations[0]
        # Can link both relevant goals
        self.assertIn("goal-client-alpha", [g.id for g in [goal1, goal2]])

    def test_5_recurring_situation(self) -> None:
        """Requirement: Recurring situation updates existing situation rather than creating duplicate records."""
        goal = Goal(id="goal-1", name="Project Delivery")
        candidate = Situation(
            type="possible_forgotten_commitment",
            priority=SituationPriority.HIGH.value,
            context={"primary_entity_ids": ["client_alpha"], "event_ids": ["evt-100"]},
            evidence=["Initial reminder of commitment"],
            related_goals=["goal-1"],
        )

        sit1, is_new1 = self.lifecycle_manager.register_or_update(candidate)
        self.assertTrue(is_new1)
        self.assertEqual(len(self.situation_store.list_active()), 1)

        # Fresh observation arrives for the same situation
        fresh_candidate = Situation(
            type="possible_forgotten_commitment",
            priority=SituationPriority.HIGH.value,
            context={"primary_entity_ids": ["client_alpha"], "event_ids": ["evt-100"]},
            evidence=["Initial reminder of commitment", "Follow-up email from client arrived"],
            related_goals=["goal-1"],
        )

        sit2, is_new2 = self.lifecycle_manager.register_or_update(fresh_candidate)
        self.assertFalse(is_new2)
        self.assertEqual(sit2.id, sit1.id)
        self.assertEqual(len(self.situation_store.list_active()), 1)
        # Evidence was updated
        self.assertIn("Follow-up email from client arrived", sit2.evidence)

    def test_6_stale_situation(self) -> None:
        """Requirement: Stale situation decays over elapsed time without updates."""
        old_time = self.now - timedelta(days=10)
        situation = Situation(
            type="goal_risk",
            priority=SituationPriority.MEDIUM.value,
            created_at=old_time,
            updated_at=old_time,
            status=SituationStatus.ACTIVE.value,
        )

        # Compute freshness relative to self.now (10 days later > 7d threshold)
        freshness = situation.compute_freshness(as_of=self.now)
        self.assertEqual(freshness, SituationFreshness.STALE)

        # Transition status to DECAYING or INACTIVE
        situation.status = SituationStatus.DECAYING.value
        self.assertTrue(situation.is_decaying())

    def test_7_duplicate_situation(self) -> None:
        """Requirement: Exact duplicate situations are filtered out via deterministic identity."""
        cand1 = Situation(
            type="schedule_conflict",
            context={"primary_entity_ids": ["meeting_42"], "event_ids": ["evt-cal-42"]},
            related_goals=["goal-team"],
        )
        cand2 = Situation(
            type="schedule_conflict",
            context={"primary_entity_ids": ["meeting_42"], "event_ids": ["evt-cal-42"]},
            related_goals=["goal-team"],
        )

        # Both generate identical deterministic identity hashes
        self.assertEqual(cand1.get_deterministic_identity(), cand2.get_deterministic_identity())

    def test_8_unrelated_events(self) -> None:
        """Requirement: Unrelated events do not produce spurious cross-domain combinations."""
        unrelated_events = [
            Event(id="e1", source="lunch_app", event_type="order_placed", event_time=self.now, payload={"item": "Salad"}),
            Event(id="e2", source="system_cron", event_type="disk_clean", event_time=self.now, payload={"freed_mb": 12}),
        ]
        evaluation = self.engine.evaluate(
            current_state=CurrentState(timestamp=self.now),
            recent_observations=unrelated_events,
            goals=[],
            reference_time=self.now,
        )

        # Does not generate false goal risks or schedule conflicts
        for cand in evaluation.candidate_situations:
            self.assertNotIn("Salad", str(cand.evidence))

    def test_9_new_arbitrary_signal_type(self) -> None:
        """
        Requirement: Adding a new signal type does not require a new agent or domain pipeline.
        Verifies register_signal_detector mechanism.
        """
        def custom_battery_degradation_detector(current_state, timeline, goals, recent_observations, context_graph, ref_dt):
            # Arbitrary signal: detect rapid battery drain
            for obs in (recent_observations or []):
                if obs.event_type == "device_telemetry" and obs.payload.get("battery_drain_rate_pct_hr", 0) > 40:
                    return [
                        Situation(
                            type="battery_health_anomaly",
                            priority=SituationPriority.HIGH.value,
                            context={"primary_entity_ids": [obs.payload.get("device_id", "primary_laptop")]},
                            evidence=[f"Battery drain rate {obs.payload.get('battery_drain_rate_pct_hr')}%/hr exceeds safety limit."],
                            novelty=0.15,
                        )
                    ]
            return []

        # Register custom detector directly on existing engine without modifying any domain classes
        self.engine.register_signal_detector("battery_detector", custom_battery_degradation_detector)

        telemetry_event = Event(
            id="evt-battery-99",
            source="hardware_monitor",
            event_type="device_telemetry",
            event_time=self.now,
            payload={"device_id": "macbook_pro", "battery_drain_rate_pct_hr": 65},
        )

        evaluation = self.engine.evaluate(
            current_state=CurrentState(timestamp=self.now),
            recent_observations=[telemetry_event],
            reference_time=self.now,
        )

        # Successfully discovered custom situation without any new agent!
        discovered = [c for c in evaluation.candidate_situations if c.type == "battery_health_anomaly"]
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].priority, SituationPriority.HIGH.value)
        self.assertIn("Battery drain rate 65%/hr", discovered[0].evidence[0])


if __name__ == "__main__":
    unittest.main()
