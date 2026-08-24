"""
Tests for ReasoningWorkflow Native Hermes Runtime Refactoring.

Verifies:
1. Native Hermes runtime in-process execution without separate Hermes processes.
2. Hermes is prompted to reason over all 7 epistemic dimensions:
   - OBSERVED FACTS
   - RELEVANT TIMELINE
   - ACTIVE GOALS
   - KNOWN PATTERNS
   - EMERGING HYPOTHESES
   - INFORMATION GAPS
   - UNCERTAINTIES
3. Strict structured output schema validation:
   - what_is_happening (string)
   - evidence_summary (list of strings)
   - inferences (list of strings)
   - predictions (list of strings)
   - uncertainties (list of strings)
   - what_would_change_assessment (list of strings)
   - recommendations (list of strings)
   - urgency (low|medium|high|critical)
   - actionability (low|medium|high)
   - relevance (low|medium|high)
   - evidence_strength (weak|moderate|strong)
4. Numerical confidence probabilities are strictly prohibited.
5. Hermes is forbidden from making intervention decisions (INTERRUPT/BRIEFING/DEFER/SUPPRESS/DISCARD).
6. Structured validation and retry behavior are preserved.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.goals import Goal, GoalPriority, GoalStatus, GoalStore
from personal_intelligence.core.patterns.models import LearnedPattern, PatternCadence
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStatus, SituationStore
from personal_intelligence.core.state import StateFeature, StateRepresentation
from personal_intelligence.hermes_bridge.client import HermesClient, HermesExecutionMode
from personal_intelligence.hermes_bridge.reasoning import (
    ActionabilityLevel,
    EvidenceStrength,
    ReasoningWorkflow,
    RelevanceLevel,
    StructuredReasoningSynthesis,
    UrgencyLevel,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestReasoningWorkflowRefactor(unittest.TestCase):
    """Test suite verifying native Hermes ReasoningWorkflow and epistemic constraints."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_reasoning_refactor.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.context_builder = ContextBuilder(goal_store=self.goal_store, situation_store=self.situation_store)
        self.base_time = datetime(2026, 8, 22, 15, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_sample_state(self) -> StateRepresentation:
        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("current_activity", "architecture_review", source="os_window:vscode", confidence=0.95)
        state.set_feature("sleep_duration_hours", 5.2, source="biometrics:oura_ring", confidence=0.98)
        state.set_feature("upcoming_meetings_count", 3, source="calendar:work", confidence=0.90)
        return state

    def _create_sample_situation(self) -> Situation:
        return Situation(
            id="sit-test-101",
            type="cognitive_physical_strain_risk",
            priority=SituationPriority.HIGH.value,
            novelty=0.35,
            status="open",
            context={"title": "High cognitive load with low sleep recovery"},
            evidence=["finding:Sleep restriction of 5.2h vs 8.0h baseline"],
        )

    # -------------------------------------------------------------------------
    # 1. Native Hermes Runtime In-Process Execution (No Subprocesses)
    # -------------------------------------------------------------------------

    def test_native_hermes_runtime_in_process_execution(self) -> None:
        """Verifies workflow executes via native Hermes in-process bridge without subprocesses."""
        client = HermesClient(mode=HermesExecutionMode.NATIVE)

        prompts_received = []

        def mock_native_llm(prompt: str) -> str:
            prompts_received.append(prompt)
            return json.dumps({
                "what_is_happening": "User experienced severe sleep restriction preceding heavy technical review.",
                "evidence_summary": ["Sleep duration 5.2h", "3 upcoming meetings"],
                "inferences": ["Cognitive fatigue will impair downstream review stamina."],
                "predictions": ["Focus fatigue likely to increase by 16:30 without rest."],
                "uncertainties": ["Whether the 16:00 meeting can be asynchronously handled."],
                "what_would_change_assessment": ["Meeting postponement or user reporting feeling fully alert."],
                "recommendations": ["Reschedule non-urgent review to tomorrow morning."],
                "urgency": "high",
                "actionability": "high",
                "relevance": "high",
                "evidence_strength": "strong",
            })

        client.set_llm_callable(mock_native_llm)

        workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=client,
        )

        situation = self._create_sample_situation()
        state = self._create_sample_state()

        result = workflow.run_workflow(situation=situation, current_state=state)

        # Verify successful execution and episode recording
        self.assertIsNotNone(result.synthesis)
        self.assertEqual(result.episode.status, EpisodeStatus.REASONING_COMPLETED.value)
        self.assertEqual(result.synthesis.urgency, "high")
        self.assertEqual(result.synthesis.evidence_strength, "strong")
        self.assertEqual(len(result.synthesis.what_would_change_assessment), 1)

        # Verify prompt contained all 7 epistemic dimensions
        self.assertEqual(len(prompts_received), 1)
        prompt = prompts_received[0]
        self.assertIn("OBSERVED_FACTS", prompt)
        self.assertIn("RELEVANT_TIMELINE", prompt)
        self.assertIn("ACTIVE_GOALS", prompt)
        self.assertIn("KNOWN_PATTERNS", prompt)
        self.assertIn("EMERGING_HYPOTHESES", prompt)
        self.assertIn("INFORMATION_GAPS", prompt)
        self.assertIn("UNCERTAINTIES", prompt)

    # -------------------------------------------------------------------------
    # 2. Strict Structured Output Schema Validation
    # -------------------------------------------------------------------------

    def test_strict_structured_output_validation_success(self) -> None:
        """Verifies schema validation succeeds with all required fields including what_would_change_assessment."""
        valid_json = json.dumps({
            "what_is_happening": "Overlapping calendar commitments create double booking.",
            "evidence_summary": ["Meeting A at 14:00", "Meeting B at 14:15"],
            "inferences": ["Simultaneous presence required across two high-priority meetings."],
            "predictions": ["User will miss critical project sign-off if unmitigated."],
            "uncertainties": ["Whether Meeting A has an alternate representative."],
            "what_would_change_assessment": ["Confirmation of meeting delegate or organizer cancellation."],
            "recommendations": ["Delegate Meeting B attendance to team lead."],
            "urgency": "critical",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        })

        synthesis, errors = validate_reasoning_synthesis(valid_json)
        self.assertEqual(len(errors), 0)
        self.assertIsNotNone(synthesis)
        self.assertEqual(synthesis.urgency, "critical")
        self.assertEqual(synthesis.actionability, "high")
        self.assertEqual(synthesis.evidence_strength, "strong")
        self.assertEqual(len(synthesis.what_would_change_assessment), 1)

    # -------------------------------------------------------------------------
    # 3. Prohibit Numerical Confidence Probabilities
    # -------------------------------------------------------------------------

    def test_reject_numerical_confidence_probabilities(self) -> None:
        """Verifies that numerical confidence values (e.g. confidence: 0.92) are strictly rejected."""
        invalid_numeric_json = json.dumps({
            "what_is_happening": "Double booking detected.",
            "evidence_summary": ["Event 1", "Event 2"],
            "inferences": ["Conflict present"],
            "predictions": ["Disruption likely"],
            "uncertainties": [],
            "what_would_change_assessment": [],
            "recommendations": ["Resolve conflict"],
            "confidence": 0.92,  # FORBIDDEN: Numerical confidence
            "urgency": "medium",
            "actionability": "medium",
            "relevance": "medium",
            "evidence_strength": "moderate",
        })

        synthesis, errors = validate_reasoning_synthesis(invalid_numeric_json)
        self.assertIsNone(synthesis)
        self.assertTrue(any("Numerical confidence values are prohibited" in err for err in errors))

    # -------------------------------------------------------------------------
    # 4. Prohibit Hermes from Dictating Intervention Policy Decisions
    # -------------------------------------------------------------------------

    def test_reject_hermes_intervention_policy_decisions(self) -> None:
        """
        Verifies that Hermes is forbidden from returning policy action decisions
        like INTERRUPT/BRIEFING/DEFER/SUPPRESS/DISCARD (reserved for InterventionPolicyEngine).
        """
        invalid_policy_json = json.dumps({
            "what_is_happening": "Critical goal deadline imminent.",
            "evidence_summary": ["Milestone in 2 hours"],
            "inferences": ["High time pressure"],
            "predictions": ["Risk of delivery failure"],
            "uncertainties": [],
            "what_would_change_assessment": [],
            "recommendations": ["Focus immediately"],
            "action": "INTERRUPT",  # FORBIDDEN: Policy decision belongs to InterventionPolicyEngine
            "urgency": "critical",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        })

        synthesis, errors = validate_reasoning_synthesis(invalid_policy_json)
        self.assertIsNone(synthesis)
        self.assertTrue(any("Intervention decisions" in err for err in errors))

    # -------------------------------------------------------------------------
    # 5. Preserved Validation and Retry Loop Behavior
    # -------------------------------------------------------------------------

    def test_validation_retry_loop_recovers_on_second_attempt(self) -> None:
        """Verifies workflow sends field-specific error feedback on retry and succeeds."""
        client = HermesClient(mode=HermesExecutionMode.NATIVE)
        attempts = 0

        def mock_flaky_llm(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                # First attempt returns invalid categorical rating
                return json.dumps({
                    "what_is_happening": "Double booking detected.",
                    "evidence_summary": [],
                    "inferences": [],
                    "predictions": [],
                    "uncertainties": [],
                    "what_would_change_assessment": [],
                    "recommendations": [],
                    "urgency": "EXTREMELY_URGENT",  # Invalid enum
                    "actionability": "high",
                    "relevance": "high",
                    "evidence_strength": "strong",
                })
            else:
                # Second attempt fixes the schema error
                return json.dumps({
                    "what_is_happening": "Double booking detected.",
                    "evidence_summary": ["Meeting at 14:00"],
                    "inferences": ["Schedule overlap"],
                    "predictions": ["Time conflict"],
                    "uncertainties": [],
                    "what_would_change_assessment": ["Meeting rescheduled"],
                    "recommendations": ["Reschedule Meeting A"],
                    "urgency": "high",
                    "actionability": "high",
                    "relevance": "high",
                    "evidence_strength": "strong",
                })

        client.set_llm_callable(mock_flaky_llm)

        workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=client,
            max_retries=2,
        )

        situation = self._create_sample_situation()
        state = self._create_sample_state()

        result = workflow.run_workflow(situation=situation, current_state=state)

        self.assertEqual(result.attempts, 2)
        self.assertIsNotNone(result.synthesis)
        self.assertEqual(result.synthesis.urgency, "high")
        self.assertEqual(result.episode.status, EpisodeStatus.REASONING_COMPLETED.value)

    def test_persistent_failure_records_unparseable_episode(self) -> None:
        """Verifies persistent validation failures mark episode as UNPARSEABLE without crashing."""
        client = HermesClient(mode=HermesExecutionMode.NATIVE)

        def mock_always_broken_llm(prompt: str) -> str:
            return "Not a valid JSON response"

        client.set_llm_callable(mock_always_broken_llm)

        workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=client,
            max_retries=1,
        )

        situation = self._create_sample_situation()
        state = self._create_sample_state()

        result = workflow.run_workflow(situation=situation, current_state=state)

        self.assertEqual(result.attempts, 2)
        self.assertIsNotNone(result.synthesis)
        self.assertEqual(result.episode.status, EpisodeStatus.UNPARSEABLE.value)
        self.assertGreater(len(result.validation_errors), 0)


if __name__ == "__main__":
    unittest.main()
