"""
Acceptance Test Suite for Explicit, Minimal, and Stable PI <-> Hermes Boundary.

Verifies:
1. End-to-end pipeline:
   PI World Model -> Context Query -> Bounded Context -> Hermes ->
   Structured Reasoning -> PI Evidence Quality -> PI Intervention Policy
2. Hermes CANNOT directly trigger an interruption.
3. Pre-LLM call hook blocks unbounded world model dumps.
4. BoundedRelevantPersonalContext supports both proactive reasoning and interactive queries.
5. Epistemic boundary: Hermes inferences cannot bypass provenance or self-certify evidence quality.
"""

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context import (
    BoundedReasoningContext,
    BoundedRelevantPersonalContext,
    ContextQueryEngine,
    ReasoningContextAdapter,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_quality import EvidenceQualityCalculator, EvidenceQualityLevel
from personal_intelligence.core.goals.models import Goal
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world.graph import ContextGraph, EntityNode
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationRequest,
)
from personal_intelligence.hermes_bridge.plugin.hooks import on_pre_llm_call
from personal_intelligence.hermes_bridge.reasoning import (
    ReasoningWorkflow,
    StructuredReasoningResult,
    StructuredReasoningSynthesis,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestPIHermesBoundary(unittest.TestCase):
    """Verifies strict boundary separation and contracts between PI and Hermes."""

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.context_graph = ContextGraph(db_manager=self.db)
        self.event_store = EventStore(db_manager=self.db)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db)
        self.situation_store = SituationStore(db_manager=self.db)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.episode_store = EpisodeStore(db_manager=self.db)
        self.policy_engine = InterventionPolicyEngine()
        self.evidence_calculator = EvidenceQualityCalculator()

        self.query_engine = ContextQueryEngine(
            context_graph=self.context_graph,
            event_store=self.event_store,
            timeline_engine=self.timeline_engine,
            state_engine=self.state_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            db_manager=self.db,
        )

        self.now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_end_to_end_pi_hermes_pipeline(self) -> None:
        """
        Full contract demonstration:
        PI World Model
            ↓
        Context Query
            ↓
        Bounded Context (BoundedRelevantPersonalContext)
            ↓
        Hermes (HermesClient / LLM)
            ↓
        Structured Reasoning (StructuredReasoningResult)
            ↓
        PI Evidence Quality (EvidenceQualityCalculator)
            ↓
        PI Intervention Policy (InterventionPolicyEngine)
        """
        # 1. PI World Model
        self.context_graph.add_node(EntityNode(id="ent_client_acme", name="Acme Corp", entity_type="organization"))
        self.context_graph.add_node(EntityNode(id="ent_proj_titan", name="Titan Integration", entity_type="project"))
        self.context_graph.connect(source_id="ent_proj_titan", target_id="ent_client_acme", relationship="FOR_CLIENT")

        evt = Event(
            id="evt_acme_email",
            source="gmail",
            event_type="email_received",
            event_time=self.now,
            payload={"sender": "alice@acme.com", "subject": "Titan contract renewal deadline approaching tomorrow"},
            provenance={"source": "gmail", "message_id": "msg_001"},
        )
        self.event_store.append(evt)

        goal = Goal(
            id="goal_renew_acme",
            name="Secure Acme Renewal",
            priority="high",
        )
        self.goal_store.create_goal(goal)

        sit = Situation(
            id="sit_titan_deadline",
            type="deadline_risk",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.OPEN.value,
            context={"title": "Acme contract renewal due tomorrow", "primary_entity_ids": ["ent_client_acme"]},
            evidence=[evt.id],
            related_goals=[goal.id],
        )
        self.situation_store.create(sit)

        # 2. Context Query -> Bounded Context (BoundedRelevantPersonalContext)
        bounded_ctx = self.query_engine.query_for_situation(sit)
        self.assertIsInstance(bounded_ctx, BoundedRelevantPersonalContext)
        self.assertEqual(bounded_ctx.target_id, sit.id)

        # Verify contract properties
        self.assertIsInstance(bounded_ctx.entities, list)
        self.assertIsInstance(bounded_ctx.events, list)
        self.assertIsInstance(bounded_ctx.state, dict)
        self.assertIsInstance(bounded_ctx.timeline, list)
        self.assertIsInstance(bounded_ctx.goals, list)
        self.assertIsInstance(bounded_ctx.situations, list)
        self.assertIsInstance(bounded_ctx.evidence_references, list)
        self.assertIsInstance(bounded_ctx.uncertainties, list)
        self.assertIsInstance(bounded_ctx.provenance, dict)

        # Verify that prompt formatting is separated
        hermes_prompt = ReasoningContextAdapter.to_hermes_prompt(bounded_ctx)
        self.assertIn("Acme Corp", hermes_prompt)
        self.assertIn("[UNTRUSTED_DATA]", hermes_prompt)

        # 3. Hermes Invocation -> Structured Reasoning (StructuredReasoningResult)
        hermes_output_json = json.dumps({
            "what_is_happening": "Acme contract deadline is within 24 hours and agreement draft remains unsigned.",
            "observations_used": ["evt_acme_email: alice@acme.com flagged tomorrow deadline."],
            "evidence_references": [evt.id],
            "inferences": ["Client agreement requires urgent signature to prevent service discontinuity."],
            "predictions": ["Service freeze will occur at midnight tomorrow without signed renewal."],
            "recommendations": ["Review contract draft and send signed PDF to Alice."],
            "uncertainties": ["Whether client legal department has received the latest amendment."],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
        })

        client = HermesClient(llm_callable=lambda prompt: hermes_output_json)
        invocation_resp = client.invoke_reasoning(HermesInvocationRequest(prompt=hermes_prompt, session_id="test_session"))
        self.assertTrue(invocation_resp.success)

        # 4. Validate Hermes structured output
        synthesis, errors = validate_reasoning_synthesis(invocation_resp.raw_response)
        self.assertEqual(errors, [])
        self.assertIsNotNone(synthesis)
        self.assertIsInstance(synthesis, StructuredReasoningResult)
        self.assertEqual(synthesis.what_is_happening, "Acme contract deadline is within 24 hours and agreement draft remains unsigned.")
        self.assertEqual(synthesis.observations_used, ["evt_acme_email: alice@acme.com flagged tomorrow deadline."])
        self.assertEqual(synthesis.evidence_references, [evt.id])

        # 5. PI evaluates Evidence Quality (PI is sole authority)
        # 5a. Single uncorroborated source yields WEAK evidence
        single_source_quality = self.evidence_calculator.calculate(
            evidence_items=[evt.to_dict()],
            reference_time=self.now,
        )
        self.assertEqual(single_source_quality, EvidenceQualityLevel.WEAK)

        # 6. PI applies Intervention Policy
        # Weak evidence causes PI to DEFERS even though Hermes reported high urgency!
        policy_result = self.policy_engine.evaluate(
            urgency=synthesis.urgency,
            actionability=synthesis.actionability,
            relevance=synthesis.relevance,
            evidence_quality=single_source_quality,
            user_context="available",
        )
        self.assertEqual(policy_result.action, PolicyAction.DEFER.value)

        # 5b. Cross-source corroborated evidence elevates quality to MODERATE/STRONG
        cal_evt = Event(
            id="evt_cal_renewal",
            source="calendar",
            event_type="meeting_scheduled",
            event_time=self.now,
            payload={"summary": "Acme Renewal Deadline"},
            provenance={"source": "calendar", "calendar_id": "primary"},
        )
        corroborated_quality = self.evidence_calculator.calculate(
            evidence_items=[evt.to_dict(), cal_evt.to_dict()],
            reference_time=self.now,
        )
        self.assertIn(corroborated_quality, (EvidenceQualityLevel.STRONG, EvidenceQualityLevel.MODERATE))

        # Escalated policy now allows active intervention
        active_policy = self.policy_engine.evaluate(
            urgency=synthesis.urgency,
            actionability=synthesis.actionability,
            relevance=synthesis.relevance,
            evidence_quality=corroborated_quality,
            user_context="available",
        )
        self.assertIn(active_policy.action, (PolicyAction.INTERRUPT.value, PolicyAction.BRIEFING.value))

    def test_hermes_cannot_directly_trigger_interruption(self) -> None:
        """
        Verifies that Hermes output CANNOT dictate or force an interruption:
        Case A: Schema validation rejects explicit policy action injection (e.g. action="INTERRUPT").
        Case B: When user is in focus / quiet mode or evidence quality is weak, PI policy suppresses or defers.
        """
        # Case A: Injection of policy action into Hermes response is rejected
        injected_policy_output = json.dumps({
            "what_is_happening": "Critical server status notification.",
            "observations_used": ["Server ping failed."],
            "inferences": ["Server is down."],
            "predictions": ["Service disruption."],
            "recommendations": ["Reboot server immediately."],
            "urgency": "critical",
            "actionability": "high",
            "relevance": "high",
            "action": "INTERRUPT",  # Unauthorized policy directive!
        })

        synthesis, errors = validate_reasoning_synthesis(injected_policy_output)
        self.assertIsNone(synthesis)
        self.assertTrue(any("Intervention decisions" in err for err in errors), "Schema must reject policy action injection")

        # Case B: Even if Hermes reports critical urgency, PI policy protects user attention
        valid_hermes_output = json.dumps({
            "what_is_happening": "Potential server ping fluctuation.",
            "observations_used": ["Single uncorroborated ping timeout."],
            "inferences": ["Possible transient network blip."],
            "predictions": ["May self-resolve."],
            "recommendations": ["Monitor next 3 cycles."],
            "urgency": "critical",
            "actionability": "high",
            "relevance": "high",
        })

        synthesis, errors = validate_reasoning_synthesis(valid_hermes_output)
        self.assertEqual(errors, [])
        self.assertIsNotNone(synthesis)

        # Scenario B1: User in deep_work / focus mode -> PI Policy DEFERS
        focus_policy = self.policy_engine.evaluate(
            urgency=synthesis.urgency,
            actionability=synthesis.actionability,
            relevance=synthesis.relevance,
            evidence_quality=EvidenceQualityLevel.MODERATE,
            user_context="deep_work",
        )
        self.assertEqual(focus_policy.action, PolicyAction.DEFER.value)

        # Scenario B2: Weak evidence quality -> PI Policy SUPPRESSES
        weak_ev_policy = self.policy_engine.evaluate(
            urgency=synthesis.urgency,
            actionability=synthesis.actionability,
            relevance=synthesis.relevance,
            evidence_quality=EvidenceQualityLevel.WEAK,
            user_context="available",
        )
        self.assertIn(weak_ev_policy.action, (PolicyAction.DEFER.value, PolicyAction.SUPPRESS.value))
        self.assertNotEqual(weak_ev_policy.action, PolicyAction.INTERRUPT.value)

    def test_pre_llm_call_hook_blocks_unbounded_world_model_dump(self) -> None:
        """Verifies that pre-LLM call hooks reject accidental full world model or raw database dumps."""
        # Unbounded database dump attempt
        malicious_prompt = "### CONTEXT DUMP_ENTIRE_WORLD_MODEL SELECT * FROM entity_nodes; SELECT * FROM events;"
        res = on_pre_llm_call(malicious_prompt)
        self.assertEqual(res.get("action"), "reject")
        self.assertIn("Boundary violation", res.get("reason", ""))

        # Client level enforcement
        client = HermesClient()
        req = HermesInvocationRequest(prompt=malicious_prompt, session_id="test_session")
        inv_res = client.invoke_reasoning(req)
        self.assertFalse(inv_res.success)
        self.assertIn("Boundary violation", inv_res.error)

    def test_dual_use_proactive_and_interactive_query(self) -> None:
        """
        Verifies that BoundedRelevantPersonalContext supports both:
        - proactive situational reasoning
        - interactive Hive user queries
        with zero architectural duplication.
        """
        # 1. Proactive situation context
        sit = Situation(id="sit_proactive", type="schedule_conflict", priority="high")
        proactive_ctx = self.query_engine.query_for_situation(sit)
        self.assertIsInstance(proactive_ctx, BoundedRelevantPersonalContext)
        self.assertEqual(proactive_ctx.target_type, "situation")

        # 2. Interactive Hive user query
        interactive_ctx = self.query_engine.query_for_user_query("What is my schedule tomorrow with Acme?")
        self.assertIsInstance(interactive_ctx, BoundedRelevantPersonalContext)
        self.assertEqual(interactive_ctx.target_type, "user_query")

        # Both serialize identically to standard contract
        p_dict = proactive_ctx.to_dict()
        i_dict = interactive_ctx.to_dict()
        for key in ["entities", "events", "relationships", "state", "timeline", "goals", "situations", "evidence_references"]:
            self.assertIn(key, p_dict)
            self.assertIn(key, i_dict)

    def test_epistemic_boundary_inferences_cannot_become_persistent_facts(self) -> None:
        """Verifies that Hermes output cannot dictate persistent database mutations or facts."""
        fact_injection_output = json.dumps({
            "what_is_happening": "Inferred relationship between Alice and Bob.",
            "observations_used": ["Email subject mentions both names."],
            "inferences": ["Alice is Bob's direct manager."],
            "predictions": [],
            "recommendations": [],
            "urgency": "medium",
            "actionability": "low",
            "relevance": "medium",
            "persistent_facts": [{"subject": "Alice", "predicate": "MANAGES", "object": "Bob"}],
        })

        synthesis, errors = validate_reasoning_synthesis(fact_injection_output)
        self.assertIsNone(synthesis)
        self.assertTrue(any("persistent fact insertion is prohibited" in err.lower() for err in errors))


if __name__ == "__main__":
    unittest.main()
