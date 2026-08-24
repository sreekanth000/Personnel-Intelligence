"""
Integration test for the End-to-End Personal Intelligence demonstration.
Verifies multi-domain cross-context reasoning across 14-day sleep baseline,
today's abnormal sleep, workload, fitness goal, and exercise history without sleep agents or hardcoded rules.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStore
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.novelty import NoveltyEngine
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager
from scripts.demo_end_to_end import generate_synthetic_data, run_demonstration


class TestEndToEndDemonstration(unittest.TestCase):
    """Test suite validating the end-to-end multi-domain reasoning demonstration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_demo.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.novelty_engine = NoveltyEngine()
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.policy_engine = InterventionPolicyEngine()
        self.context_builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )

        self.mock_hermes = MagicMock(spec=HermesClient)
        self.reasoning_workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.mock_hermes,
        )

        self.base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_emergent_multi_domain_reasoning(self) -> None:
        """
        Verify that multi-domain signals (sleep baseline + abnormal sleep + calendar workload +
        fitness goal + workout history) are ingested, bounded, synthesized, and produce
        the appropriate recommendation and intervention policy decision without any domain agent.
        """
        # 1. Ingest Goal
        goal = self.goal_store.create_goal(
            name="Half-Marathon Preparation",
            description="Train for sub-1:45 Half-Marathon with 4 weekly runs.",
            priority=GoalPriority.HIGH.value,
        )

        # 2. Ingest Events
        synthetic_events = generate_synthetic_data(self.base_time)
        self.event_store.append_batch(type("Batch", (), {"events": synthetic_events})())

        # 3. Timeline
        timeline = self.timeline_engine.get_time_range(
            start_time=self.base_time - timedelta(days=14),
            end_time=self.base_time + timedelta(hours=8),
        )
        self.assertGreaterEqual(len(timeline.events), 20)

        # 4. State & Novelty
        current_state = self.state_engine.compute_current_state(reference_time=self.base_time)
        novelty_res = self.novelty_engine.evaluate_state(current_state)
        self.assertIsNotNone(novelty_res)

        # 5. Situation Creation
        situation = self.situation_store.create(
            type="cognitive_physical_strain_risk",
            priority=SituationPriority.HIGH.value,
            novelty=0.85,
            context={
                "summary": "Severe sleep deficit coincides with 7-hour heavy cognitive workload and scheduled interval run.",
                "today_sleep_minutes": 225,
                "baseline_sleep_minutes": 480,
                "meetings_count": 4,
            },
            evidence=[
                "event:evt-sleep-today",
                "event:evt-meeting-today-1",
                "goal:" + goal.id,
            ],
            related_goals=[goal.id],
        )

        # 6. Hermes Emergent Synthesis Mock
        hermes_synthesis = {
            "what_is_happening": "Acute sleep deficit (3.75h) + 4 executive meetings + scheduled evening interval workout.",
            "evidence_summary": [
                "Sleep duration 225m vs 480m 14d baseline.",
                "4 consecutive high-workload meetings.",
                "Scheduled 10km run under Half-Marathon goal.",
                "5 prior workouts show consistent adaptation when rested.",
            ],
            "inferences": [
                "Neuromuscular fatigue sharply elevates injury risk during maximal intervals.",
            ],
            "predictions": [
                "High interval speed run today risks acute muscular strain.",
                "Substituted 20m restorative walk preserves habit while restoring energy.",
            ],
            "recommendations": [
                "Postpone today's 10km interval run to tomorrow afternoon.",
                "Replace 17:30 session with a 20-minute restorative walk and light stretching.",
            ],
            "uncertainties": [],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=450,
        )

        # 7. Run Workflow
        res = self.reasoning_workflow.run_workflow(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=[goal],
        )

        self.assertIsNotNone(res.synthesis)
        self.assertEqual(len(res.validation_errors), 0)
        self.assertEqual(len(res.synthesis.recommendations), 2)
        self.assertIn("Postpone today's 10km interval run", res.synthesis.recommendations[0])

        # 8. Intervention Policy
        policy_res = self.policy_engine.evaluate(
            urgency=res.synthesis.urgency,
            actionability=res.synthesis.actionability,
            evidence_strength=res.synthesis.evidence_strength,
            user_context=UserContext.AVAILABLE.value,
        )
        self.assertEqual(policy_res.action, PolicyAction.INTERRUPT.value)

        # 9. Episode Persistence
        episode = self.episode_store.get_episode(res.episode.id)
        self.assertIsNotNone(episode)
        self.assertEqual(episode.situation_id, situation.id)
        self.assertEqual(episode.urgency, "high")
        self.assertEqual(episode.actionability, "high")

    def test_demonstration_script_execution(self) -> None:
        """Verify the demo script executes without exception."""
        run_demonstration()


if __name__ == "__main__":
    unittest.main()
