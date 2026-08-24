"""
Integration tests for Novel Situation Reasoning.
Verifies end-to-end pipeline:
Statistical Novelty -> NOVEL Situation -> Bounded Context -> Hermes Investigation
-> Structured Reasoning with Epistemic Uncertainty -> Episode Storage -> Intervention Policy.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.novelty import (
    FeatureNoveltyResult,
    NoveltyLevel,
    NoveltyResult,
)
from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    UserContext,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationResponse,
)
from personal_intelligence.hermes_bridge.novelty_orchestrator import (
    NoveltyReasoningOrchestrator,
)
from personal_intelligence.hermes_bridge.reasoning import (
    NovelReasoningSynthesis,
    ReasoningWorkflow,
    validate_novel_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestNovelSituationReasoning(unittest.TestCase):
    """Integration test suite for Novel Situation Reasoning with synthetic novel events."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_novel_reasoning.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.context_builder = ContextBuilder()
        self.mock_hermes_client = MagicMock(spec=HermesClient)
        self.policy_engine = InterventionPolicyEngine()
        self.situation_engine = SituationEngine()

        self.workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.mock_hermes_client,
        )

        self.orchestrator = NoveltyReasoningOrchestrator(
            db_manager=self.db_manager,
            situation_engine=self.situation_engine,
            situation_store=self.situation_store,
            context_builder=self.context_builder,
            reasoning_workflow=self.workflow,
            policy_engine=self.policy_engine,
            episode_store=self.episode_store,
        )

        self.now = datetime(2026, 8, 1, 14, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_novel_situation_end_to_end_reasoning_and_policy(self) -> None:
        """
        Verify complete pipeline for an unfamiliar combination of synthetic events
        with NO predefined situation domain rule:
        NOVEL situation -> Hermes investigation -> Structured synthesis -> Episode store -> Policy evaluation.
        """
        # 1. Create a synthetic novel state (e.g. Unusual event density + routine deviation)
        state = StateRepresentation(timestamp=self.now)
        state.set(StateFeature("event_density", 8.5, "sensor_stream", self.now))
        state.set(StateFeature("routine_deviation", 0.95, "activity_engine", self.now))
        state.set(StateFeature("current_location", "unfamiliar_workspace", "geo", self.now))

        novelty = NoveltyResult(
            overall_level=NoveltyLevel.HIGHLY_UNUSUAL,
            feature_results=[
                FeatureNoveltyResult("event_density", 8.5, 2.0, 3.25, "highly_unusual"),
                FeatureNoveltyResult("routine_deviation", 0.95, 0.1, 4.25, "highly_unusual"),
                FeatureNoveltyResult("current_location", "unfamiliar_workspace", 0.01, None, "unusual"),
            ],
            timestamp=self.now,
        )

        timeline = Timeline([
            Event(event_type="app_switch", source="desktop", event_time=self.now, payload={"app": "new_tool"}),
        ])

        goal = Goal(id="goal-deep-work", name="Deep Work Focus", priority=GoalPriority.HIGH)

        # 2. Mock Hermes exploratory investigation response
        hermes_payload = {
            "what_appears_unusual": "Simultaneous spike in event density and severe routine deviation in unfamiliar location.",
            "possible_interpretations": [
                "User is onboarding a new tool stack in an unfamiliar workspace.",
                "User is troubleshooting an urgent unpredicted incident.",
            ],
            "relevant_goals": ["Deep Work Focus"],
            "possible_risks": ["Severe cognitive fragmentation and loss of deep work focus."],
            "possible_opportunities": ["Rapid skill acquisition on new tooling."],
            "what_is_uncertain": ["Reason for location change", "User intent behind rapid app switching"],
            "additional_observation_needed": True,
            "insufficient_evidence": False,
            "recommendations": ["Observe timeline for 30 minutes without interrupting."],
            "urgency": "low",
            "actionability": "low",
            "relevance": "medium",
            "evidence_strength": "weak",
        }
        self.mock_hermes_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_payload),
            duration_ms=450,
            session_id="mock-session-1",
        )

        # 3. Process novel state through orchestrator
        result = self.orchestrator.process_novel_state(
            novelty_result=novelty,
            current_state=state,
            timeline=timeline,
            goals=[goal],
            user_context=UserContext.AVAILABLE.value,
        )

        # Verify NOVEL Situation Creation
        self.assertIsNotNone(result.situation)
        self.assertIn(result.situation.type, ["unusual_state", "novel_state"])

        # Verify Hermes Structured Novel Synthesis
        synth = result.novel_synthesis
        self.assertIn("Simultaneous spike in event density", synth.what_appears_unusual)
        self.assertEqual(len(synth.possible_interpretations), 2)
        self.assertEqual(len(synth.possible_risks), 1)
        self.assertEqual(len(synth.possible_opportunities), 1)
        self.assertEqual(len(synth.what_is_uncertain), 2)
        self.assertTrue(synth.additional_observation_needed)
        self.assertEqual(synth.urgency, "low")
        self.assertEqual(synth.evidence_strength, "weak")

        # Verify Episode Persistence in SQLite
        episode = self.episode_store.get_episode(result.reasoning_episode.id)
        self.assertIsNotNone(episode)
        self.assertEqual(episode.situation_id, result.situation.id)
        self.assertEqual(episode.status, EpisodeStatus.REASONING_COMPLETED.value)

        # Verify Intervention Policy: Novel != Notify (Low urgency -> DISCARD)
        self.assertEqual(result.policy_evaluation.action, PolicyAction.DISCARD)

    def test_insufficient_evidence_preservation_without_invented_facts(self) -> None:
        """
        Verify that when context is insufficient, Hermes explicitly returns 'insufficient evidence'
        and the system records this epistemic limitation rather than inventing facts.
        """
        state = StateRepresentation(timestamp=self.now)
        state.set(StateFeature("time_of_day", 14.0, "clock", self.now))

        novelty = NoveltyResult(
            overall_level=NoveltyLevel.HIGHLY_UNUSUAL,
            feature_results=[
                FeatureNoveltyResult("time_of_day", 14.0, 3.0, 3.1, "highly_unusual"),
            ],
            timestamp=self.now,
        )

        hermes_insufficient_payload = {
            "what_appears_unusual": "insufficient evidence to explain single statistical outlier.",
            "possible_interpretations": [],
            "relevant_goals": [],
            "possible_risks": [],
            "possible_opportunities": [],
            "what_is_uncertain": ["insufficient evidence: no timeline events recorded in observation window"],
            "additional_observation_needed": True,
            "insufficient_evidence": True,
            "recommendations": [],
            "urgency": "low",
            "actionability": "low",
            "relevance": "low",
            "evidence_strength": "weak",
        }
        self.mock_hermes_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_insufficient_payload),
            duration_ms=300,
        )

        result = self.orchestrator.process_novel_state(
            novelty_result=novelty,
            current_state=state,
            timeline=Timeline([]),
            goals=[],
        )

        # Verify insufficient evidence was captured
        self.assertTrue(result.novel_synthesis.insufficient_evidence)
        self.assertIn("insufficient evidence", result.novel_synthesis.what_appears_unusual.lower())

        # Verify Policy Decision
        self.assertEqual(result.policy_evaluation.action, PolicyAction.DISCARD)


if __name__ == "__main__":
    unittest.main()
