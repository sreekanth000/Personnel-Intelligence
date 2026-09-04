"""
Test Suite for Qualitative Trade-Off Reasoning (Without MCTS in V1).

Verifies:
1. Complex multi-goal situations produce actionable recommendations via Hermes qualitative reasoning.
2. Hermes reasons qualitatively about trade-offs (e.g., late travel + early presentation + reduced sleep).
3. No MCTS or formal causal simulation invocation occurs in the V1 critical reasoning path.
4. No causal certainty or artificial Pareto weights are generated.
5. Reasoning episodes remain complete with full epistemic provenance and outcome recording.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_strength import EvidenceStrengthCalculator, EvidenceStrengthLevel
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.loop import PersonalIntelligenceLoop
from personal_intelligence.core.policy.engine import InterventionPolicyEngine, decide_intervention
from personal_intelligence.core.policy.models import PolicyAction
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow, StructuredReasoningSynthesis
from personal_intelligence.storage.db import DatabaseManager


class TestQualitativeTradeOffReasoning(unittest.TestCase):
    """Verifies qualitative trade-off reasoning in V1 without MCTS."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_tradeoff.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.context_builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )
        self.evidence_calculator = EvidenceStrengthCalculator()
        self.policy_engine = InterventionPolicyEngine()

        self.mock_hermes = MagicMock(spec=HermesClient)
        self.reasoning_workflow = ReasoningWorkflow(
            hermes_client=self.mock_hermes,
            episode_store=self.episode_store,
        )

        self.base_time = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_multi_goal_tradeoff_produces_recommendation_without_mcts(self) -> None:
        """
        Scenario: Late travel + reduced sleep (3.5h) + high-stakes morning presentation + fitness goal.
        Proves:
        - Hermes produces qualitative trade-off recommendations.
        - No MCTS tree search is invoked.
        - No artificial Pareto utility scores are generated.
        - Full episode provenance is preserved.
        """
        # 1. Setup multi-domain goals
        goal_career = self.goal_store.create_goal(
            name="Deliver Q3 Architecture Keynote",
            description="Present system scalability RFC to Executive Board at 09:00",
            priority=GoalPriority.CRITICAL.value,
        )
        goal_fitness = self.goal_store.create_goal(
            name="Half Marathon Training",
            description="Maintain 35km weekly training mileage",
            priority=GoalPriority.HIGH.value,
        )

        # 2. Ingest multi-domain timeline events
        # Domain A: Travel delay
        self.event_store.append(
            Event(
                id="evt-flight-delay",
                event_type="travel_delay",
                source="airline_telemetry",
                event_time=self.base_time - timedelta(hours=6),
                payload={"flight": "UA210", "delay_minutes": 180, "arrival": "02:30 UTC"},
            )
        )
        # Domain B: Sleep debt
        self.event_store.append(
            Event(
                id="evt-sleep-deficit",
                event_type="biometrics_sleep",
                source="sleep_tracker",
                event_time=self.base_time - timedelta(hours=1),
                payload={"duration_minutes": 210, "deep_sleep_minutes": 25, "sleep_score": 42},
            )
        )
        # Domain C: Calendar commitment
        self.event_store.append(
            Event(
                id="evt-cal-keynote",
                event_type="calendar_event",
                source="google_calendar",
                event_time=self.base_time + timedelta(hours=1),
                payload={"summary": "Q3 Architecture Keynote", "location": "Boardroom A"},
            )
        )

        timeline = self.timeline_engine.get_time_range(end_time=self.base_time + timedelta(hours=2))
        current_state = self.state_engine.compute_current_state(reference_time=self.base_time)

        # 3. Create Multi-Goal Situation Frame
        situation = self.situation_store.create(
            type="travel_fatigue_presentation_conflict",
            priority=SituationPriority.CRITICAL.value,
            evidence=[
                {"source": "airline_telemetry", "statement": "Flight delayed 3h", "origin_event_id": "flight-raw-1"},
                {"source": "sleep_tracker", "statement": "Sleep duration was 3.5h (deficit)", "origin_event_id": "sleep-raw-1"},
                {"source": "google_calendar", "statement": "Keynote at 09:00", "origin_event_id": "cal-raw-1"},
            ],
            related_goals=[goal_career.id, goal_fitness.id],
        )

        # 4. Build bounded context
        bounded_ctx = self.context_builder.build_bounded_context(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=[goal_career, goal_fitness],
        )

        # 5. Mock Hermes qualitative trade-off synthesis
        qualitative_synthesis = {
            "what_is_happening": "Severe sleep debt from travel delay intersects with morning keynote presentation.",
            "evidence_summary": [
                "Flight UA210 delayed 180m, arriving at 02:30",
                "Sleep tracker logged 210m (3.5h) total rest",
                "Q3 Keynote scheduled in 60 minutes",
            ],
            "inferences": [
                "Attempting high-intensity run today poses acute injury risk under severe sleep debt.",
                "Cognitive sharpness for the keynote is top priority; physical training should be deferred.",
            ],
            "predictions": [
                "Maintaining scheduled intense workout would degrade keynote focus and increase injury risk.",
                "Postponing run to tomorrow allows full recovery after the presentation.",
            ],
            "uncertainties": ["Whether the keynote requires on-stage physical energy or seated presentation."],
            "recommendations": [
                "Focus morning routine on presentation preparation and hydration.",
                "Reschedule today's interval run to tomorrow afternoon when recovered.",
            ],
            "urgency": "critical",
            "actionability": "high",
            "relevance": "high",
        }

        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(qualitative_synthesis),
            duration_ms=180,
        )

        # 6. Execute reasoning workflow
        workflow_res = self.reasoning_workflow.run_workflow(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=[goal_career, goal_fitness],
        )

        # Assertions:
        # A. Qualitative synthesis produced successfully
        self.assertIsNotNone(workflow_res.synthesis)
        self.assertEqual(workflow_res.synthesis.urgency, "critical")
        self.assertIn("Reschedule today's interval run", workflow_res.synthesis.recommendations[1])

        # B. Assert NO MCTS or Pareto attributes in synthesis or episode
        self.assertFalse(hasattr(workflow_res.synthesis, "pareto_utility_score"))
        self.assertFalse(hasattr(workflow_res.synthesis, "mcts_tree"))
        self.assertFalse(hasattr(workflow_res.synthesis, "causal_graph"))

        # C. Evidence strength is computed deterministically from independent lineage
        evidence_strength = self.evidence_calculator.calculate(situation.evidence)
        self.assertEqual(evidence_strength, EvidenceStrengthLevel.STRONG)

        # D. Policy engine evaluates deterministic intervention
        policy_decision = decide_intervention(
            urgency=workflow_res.synthesis.urgency,
            actionability=workflow_res.synthesis.actionability,
            evidence_strength=evidence_strength,
            attention_state="available",
        )
        self.assertEqual(policy_decision.action, PolicyAction.INTERRUPT.value)

        # E. Full reasoning episode provenance
        ep = workflow_res.episode
        self.assertIsNotNone(ep)
        self.episode_store.record_user_response(
            episode_id=ep.id,
            response=RecommendationResult.ACCEPTED.value,
            feedback_notes="User agreed and shifted run to tomorrow.",
        )
        updated_ep = self.episode_store.get_episode(ep.id)
        self.assertEqual(updated_ep.user_response["response"], RecommendationResult.ACCEPTED.value)

    def test_v1_world_model_has_no_mcts_dependency(self) -> None:
        """Verifies PersonalWorldModel does not instantiate or depend on MCTS."""
        wm = PersonalWorldModel(db_manager=self.db_manager)

        self.assertFalse(hasattr(wm, "mcts_simulator"))
        self.assertFalse(hasattr(wm, "run_mcts_tree_search"))

        # World model methods remain functional
        snapshot = wm.get_snapshot()
        self.assertIsNotNone(snapshot)


if __name__ == "__main__":
    unittest.main()
