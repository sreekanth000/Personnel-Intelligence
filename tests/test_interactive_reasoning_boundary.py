"""
Acceptance Test Suite for Interactive Reasoning Boundary Consistency.

Verifies:
1. Hive can ask a personal contextual question through PI.
2. PI constructs bounded relevant context (BoundedRelevantPersonalContext).
3. Hermes receives only bounded context, never full database or world model dumps.
4. Hermes cannot directly trigger PI intervention.
5. Proactive and interactive reasoning use compatible context contracts.
6. Non-personal Hermes queries remain unaffected (zero personal context leakage).
"""

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.api.interface import PersonalIntelligenceClient
from personal_intelligence.core.context.models import BoundedRelevantPersonalContext
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.evidence_quality import EvidenceQualityLevel
from personal_intelligence.core.goals.models import Goal
from personal_intelligence.core.policy.models import PolicyAction
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.world.graph import (
    CanonicalEntityType,
    CanonicalRelationship,
    EntityNode,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesClient,
    HermesInvocationRequest,
)
from personal_intelligence.hermes_bridge.plugin.hooks import on_pre_llm_call
from personal_intelligence.hermes_bridge.reasoning import validate_reasoning_synthesis
from personal_intelligence.storage.db import DatabaseManager


class TestInteractiveReasoningBoundary(unittest.TestCase):
    """
    Verifies that interactive inquiries and proactive evaluations share
    the exact same PI intelligence boundary.
    """

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.db.initialize_schema()
        self.client = PersonalIntelligenceClient(db_manager=self.db)
        self.now = datetime(2026, 9, 3, 14, 0, 0, tzinfo=timezone.utc)

        # Populate baseline personal world model
        self.client.record_observation(
            source="calendar",
            source_id="cal_evt_001",
            timestamp=self.now,
            observation_type="meeting_scheduled",
            summary="Strategic Planning with DeepMind Team at 3pm",
            provenance={"tool": "google_calendar", "calendar_id": "primary"},
            entity_refs=["ent_deepmind"],
        )
        self.client.context_graph.upsert_entity(
            id="ent_deepmind",
            name="DeepMind Team",
            entity_type="organization",
        )
        self.client.world_model.create_goal(
            title="Antigravity Release",
            description="Deliver autonomous personal intelligence layer",
            priority="high",
        )

    def test_hive_can_ask_personal_contextual_question_through_pi(self) -> None:
        """
        ACCEPTANCE TEST 1:
        Hive can ask a personal contextual question through PI client API.
        Flow: Hive -> PI Client -> Context Query -> Bounded Context -> Hermes -> Structured Result.
        """
        # Ask personal query
        res = self.client.ask(query="What meetings do I have with DeepMind Team today?")

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_personal"])
        self.assertIn("DeepMind", str(res["answer"]) + str(res["evidence"]))
        self.assertIsInstance(res["evidence"], list)
        self.assertIn("evidence_quality", res)
        self.assertIn("bounded_context", res)
        self.assertIn("episode_id", res)

        # Verify episode recorded in EpisodeStore
        episodes = self.client.episode_store.list_recent(limit=5)
        self.assertTrue(any(e.id == res["episode_id"] for e in episodes))

    def test_pi_constructs_bounded_relevant_context(self) -> None:
        """
        ACCEPTANCE TEST 2:
        PI determines relevant personal context and enforces strict bounding.
        """
        # Add a distant irrelevant entity
        self.client.context_graph.upsert_entity(
            id="ent_unrelated_restaurant",
            name="Unrelated Italian Bistro",
            entity_type="place",
        )

        # Context query for focused inquiry
        ctx = self.client.context_query_engine.query_for_user_query("What is scheduled with DeepMind Team?")
        self.assertIsInstance(ctx, BoundedRelevantPersonalContext)

        # DeepMind Team entity is included
        ent_names = [e["name"] for e in ctx.relevant_entities]
        self.assertIn("DeepMind Team", ent_names)

        # Unrelated restaurant is NOT included
        self.assertNotIn("Unrelated Italian Bistro", ent_names)

        # Timeline has only relevant events
        self.assertTrue(len(ctx.relevant_timeline) <= self.client.context_query_engine.max_timeline_events)

    def test_hermes_receives_only_bounded_context(self) -> None:
        """
        ACCEPTANCE TEST 3:
        Hermes receives only bounded context, never full database or world model dumps.
        """
        # Pre-LLM call guard blocks any full database dump attempts
        unbounded_dump_prompt = "SELECT * FROM entity_nodes; DUMP_ENTIRE_WORLD_MODEL;"
        guard_result = on_pre_llm_call(unbounded_dump_prompt)
        self.assertEqual(guard_result.get("action"), "reject")

        # Legitimate bounded context formatted prompt passes cleanly
        bounded = self.client.context_query_engine.query_for_user_query("What are my priorities?")
        bounded_prompt = self.client.ask_engine._construct_hermes_prompt(
            query="What are my priorities?",
            wm_state=self.client.ask_engine._gather_world_model_state(),
            situations=self.client.situation_store.list_active(),
            goals=self.client.goal_store.list_active(),
            patterns=self.client.pattern_store.list_patterns(limit=5),
            timeline_events=self.client.event_store.query_by_time(limit=5),
        )
        guard_ok = on_pre_llm_call(bounded_prompt)
        self.assertIn(guard_ok.get("action"), ("approve", "allow"))

    def test_hermes_cannot_directly_trigger_pi_intervention(self) -> None:
        """
        ACCEPTANCE TEST 4:
        Hermes cannot directly trigger PI intervention policy or user interruption.
        Interventions in interactive queries are not pushed as background alerts.
        """
        # Injected policy in Hermes response is rejected
        injected = json.dumps({
            "what_is_happening": "User inquired about schedule.",
            "observations_used": ["Meeting at 3pm"],
            "inferences": ["User might be busy"],
            "recommendations": ["Reschedule"],
            "action": "INTERRUPT",  # Unauthorized!
        })
        synthesis, errors = validate_reasoning_synthesis(injected)
        self.assertIsNone(synthesis)
        self.assertTrue(any("Intervention decisions" in err for err in errors))

        # Interactive query execution does not create pending interruptions
        initial_interventions = self.client.get_pending_interventions()
        self.client.ask(query="What is on my schedule?")
        after_interventions = self.client.get_pending_interventions()
        # No unsolicited interruption added
        self.assertEqual(len(initial_interventions), len(after_interventions))

    def test_proactive_and_interactive_reasoning_compatible_context_contracts(self) -> None:
        """
        ACCEPTANCE TEST 5:
        Proactive situational reasoning and interactive inquiries use compatible context contracts.
        """
        # Create a situation for proactive evaluation
        sit = self.client.world_model.create_situation(
            situation_type="meeting_overlap",
            priority="high",
            summary="Schedule collision with DeepMind Team",
            context={"primary_entity_ids": ["ent_deepmind"]},
        )

        # Proactive context query
        proactive_context = self.client.context_query_engine.query_for_situation(sit)
        self.assertIsInstance(proactive_context, BoundedRelevantPersonalContext)

        # Interactive context query
        interactive_context = self.client.context_query_engine.query_for_user_query(
            "Is there any meeting overlap today?"
        )
        self.assertIsInstance(interactive_context, BoundedRelevantPersonalContext)

        # Verify contract compatibility
        p_dict = proactive_context.to_dict()
        i_dict = interactive_context.to_dict()

        for key in ["entities", "events", "relationships", "state", "timeline", "goals", "situations", "evidence_references"]:
            self.assertIn(key, p_dict)
            self.assertIn(key, i_dict)

    def test_non_personal_hermes_queries_remain_unaffected(self) -> None:
        """
        ACCEPTANCE TEST 6:
        Non-personal Hermes queries remain unaffected with zero personal context leakage.
        """
        generic_query = "What is the computational complexity of merge sort?"
        res = self.client.ask(query=generic_query)

        self.assertEqual(res["status"], "success")
        self.assertFalse(res["is_personal"])
        self.assertEqual(res["evidence"], [])
        self.assertEqual(res["sources"], ["Hermes General Knowledge"])

        # Bounded context contains ZERO personal entities or goals
        bounded = res["bounded_context"]
        self.assertEqual(bounded.get("entities", []), [])
        self.assertEqual(bounded.get("goals", []), [])
        self.assertEqual(bounded.get("situations", []), [])


if __name__ == "__main__":
    unittest.main()
