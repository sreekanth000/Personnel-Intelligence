"""
Unit and integration tests for Situation Lifecycle Management.
Verifies status transitions (OPEN, MONITORING, RESOLVED, EXPIRED, SUPPRESSED),
identity preservation across re-evaluations (no duplicate creation),
and scheduled future re-evaluation execution with fresh state retrieval and context rebuilding.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.situations.lifecycle import (
    SituationLifecycleManager,
    SituationReevaluationResult,
)
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationResponse,
)
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager


class TestSituationLifecycleManagement(unittest.TestCase):
    """Test suite for Situation Lifecycle Management."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_lifecycle.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.context_builder = ContextBuilder(situation_store=self.situation_store)
        self.lifecycle_manager = SituationLifecycleManager(
            situation_store=self.situation_store,
            context_builder=self.context_builder,
            db_manager=self.db_manager,
        )

        self.mock_hermes = MagicMock(spec=HermesClient)
        self.workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.mock_hermes,
        )

        self.now = datetime(2026, 8, 20, 17, 30, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_five_lifecycle_states(self) -> None:
        """
        Verify all 5 lifecycle states:
        OPEN -> MONITORING -> RESOLVED, and SUPPRESSED, EXPIRED.
        """
        # 1. Initial creation -> OPEN
        sit = self.situation_store.create(
            type="commute_delay",
            priority=SituationPriority.HIGH.value,
            context={"note": "Severe traffic congestion"},
        )
        self.assertEqual(sit.status, SituationStatus.OPEN.value)
        self.assertTrue(sit.is_active())

        # 2. Schedule re-evaluation -> MONITORING
        next_eval_time = self.now + timedelta(hours=1)
        monitored = self.situation_store.schedule_reevaluation(sit.id, next_eval_time)
        self.assertIsNotNone(monitored)
        self.assertEqual(monitored.status, SituationStatus.MONITORING.value)
        self.assertEqual(monitored.next_evaluation_at, next_eval_time)
        self.assertTrue(monitored.is_active())

        # 3. Resolve -> RESOLVED
        resolved = self.situation_store.resolve(sit.id, resolution_notes="Traffic congestion cleared.")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, SituationStatus.RESOLVED.value)
        self.assertIsNone(resolved.next_evaluation_at)
        self.assertFalse(resolved.is_active())
        self.assertEqual(resolved.context["resolution_notes"], "Traffic congestion cleared.")

        # 4. Suppress -> SUPPRESSED
        suppress_until = self.now + timedelta(hours=3)
        sit_to_suppress = self.situation_store.create(type="low_priority_alert")
        suppressed = self.situation_store.suppress(sit_to_suppress.id, suppress_until=suppress_until, reason="DND window")
        self.assertIsNotNone(suppressed)
        self.assertEqual(suppressed.status, SituationStatus.SUPPRESSED.value)
        self.assertFalse(suppressed.is_active())
        self.assertEqual(suppressed.context["suppression_reason"], "DND window")

        # 5. Expire -> EXPIRED
        sit_expiring = self.situation_store.create(
            type="temporary_offer",
            expires_at=self.now - timedelta(minutes=10),
        )
        expired_list = self.situation_store.expire(as_of_time=self.now)
        self.assertEqual(len(expired_list), 1)
        self.assertEqual(expired_list[0].id, sit_expiring.id)
        self.assertEqual(expired_list[0].status, SituationStatus.EXPIRED.value)
        self.assertFalse(expired_list[0].is_active())

    def test_identity_preservation_and_deduplication(self) -> None:
        """
        Verify that recurring candidate evaluations update the existing situation
        rather than creating duplicate records, maintaining identity across evaluations.
        """
        cand1 = Situation(
            type="train_risk",
            priority=SituationPriority.HIGH.value,
            evidence=["event:evt-train-1"],
            context={"delay_mins": 15},
            created_at=self.now,
        )

        # 1. Register candidate 1 -> Creates new situation
        sit1, is_new1 = self.lifecycle_manager.register_or_update(cand1)
        self.assertTrue(is_new1)
        self.assertEqual(sit1.type, "train_risk")
        self.assertEqual(sit1.evidence, ["event:evt-train-1"])

        # 2. Register candidate 2 with fresh evidence -> Updates existing situation
        later_time = self.now + timedelta(minutes=15)
        cand2 = Situation(
            type="train_risk",
            priority=SituationPriority.CRITICAL.value,
            evidence=["event:evt-train-2"],
            context={"delay_mins": 35},
            created_at=later_time,
        )

        sit2, is_new2 = self.lifecycle_manager.register_or_update(cand2)

        # Identity preserved: same ID, no duplicate record created
        self.assertFalse(is_new2)
        self.assertEqual(sit2.id, sit1.id)
        self.assertEqual(sit2.priority, SituationPriority.CRITICAL.value)
        self.assertIn("event:evt-train-1", sit2.evidence)
        self.assertIn("event:evt-train-2", sit2.evidence)
        self.assertEqual(sit2.context["delay_mins"], 35)

        # Verify database table has exactly 1 situation record
        all_situations = self.situation_store.list_active()
        self.assertEqual(len(all_situations), 1)
        self.assertEqual(all_situations[0].id, sit1.id)

    def test_scheduled_future_reevaluation_execution_cycle(self) -> None:
        """
        Verify end-to-end scheduled re-evaluation:
        1. Situation detected at 17:30.
        2. Scheduled next evaluation at 18:30.
        3. At 18:00: No due re-evaluations.
        4. At 18:30: Retrieves fresh state, updates situation, rebuilds context, re-evaluates with Hermes.
        """
        t_detect = datetime(2026, 8, 20, 17, 30, 0, tzinfo=timezone.utc)
        t_next = datetime(2026, 8, 20, 18, 30, 0, tzinfo=timezone.utc)

        # 1. Train risk detected at 17:30
        initial_state = StateRepresentation(timestamp=t_detect)
        initial_state.set_feature("train_status", "delayed_30m", "transit_api", t_detect)

        init_cand = Situation(
            type="train_risk",
            priority=SituationPriority.HIGH.value,
            evidence=["event:evt-transit-1"],
            context={"route": "Line A", "delay": 30},
            created_at=t_detect,
        )

        situation, _ = self.lifecycle_manager.register_or_update(
            candidate_situation=init_cand,
            current_state=initial_state,
            next_evaluation_at=t_next,
        )

        self.assertEqual(situation.status, SituationStatus.MONITORING.value)
        self.assertEqual(situation.next_evaluation_at, t_next)

        # 2. Check at 18:00 (Before scheduled time) -> 0 evaluations due
        t_early = datetime(2026, 8, 20, 18, 0, 0, tzinfo=timezone.utc)
        due_early = self.situation_store.get_due_reevaluations(as_of=t_early)
        self.assertEqual(len(due_early), 0)

        # 3. Check at 18:30 (Scheduled evaluation arrived)
        t_due = datetime(2026, 8, 20, 18, 30, 0, tzinfo=timezone.utc)
        due_list = self.situation_store.get_due_reevaluations(as_of=t_due)
        self.assertEqual(len(due_list), 1)
        self.assertEqual(due_list[0].id, situation.id)

        # Fresh state at 18:30: Train delay resolved, running on time
        fresh_state = StateRepresentation(timestamp=t_due)
        fresh_state.set_feature("train_status", "on_time", "transit_api", t_due)

        fresh_timeline = Timeline([
            Event(id="evt-transit-resolved", event_type="transit_status_update", source="transit_api", event_time=t_due, payload={"status": "on_time"}),
        ])

        # Mock Hermes returning cleared/low urgency assessment
        hermes_payload = {
            "what_is_happening": "Train service delay has cleared and trains are operating normally on time.",
            "evidence_summary": ["Transit API update: train_status is on_time"],
            "inferences": ["Earlier schedule risk is no longer present."],
            "predictions": ["User will board normal scheduled departure."],
            "recommendations": ["No intervention required; continue normal transit."],
            "uncertainties": [],
            "requires_follow_up": False,
            "urgency": "low",
            "actionability": "low",
            "relevance": "low",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_payload),
            duration_ms=320,
        )

        # Execute scheduled re-evaluation
        results = self.lifecycle_manager.process_due_reevaluations(
            current_state=fresh_state,
            timeline=fresh_timeline,
            as_of=t_due,
            reasoning_workflow=self.workflow,
        )

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.situation.id, situation.id)
        self.assertEqual(res.new_status, SituationStatus.RESOLVED.value)
        self.assertTrue(res.status_changed)

        # Verify situation in database is now RESOLVED
        persisted = self.situation_store.get(situation.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, SituationStatus.RESOLVED.value)
        self.assertIsNone(persisted.next_evaluation_at)


if __name__ == "__main__":
    unittest.main()
