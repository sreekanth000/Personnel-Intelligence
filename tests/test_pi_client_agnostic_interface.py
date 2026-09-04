"""
Test Suite for Personal Intelligence Client-Agnostic Capability Interface (Prompt 4).

Proves that:
1. PI exposes clean, versioned, provenance-preserving capabilities.
2. Any external consumer (non-Hive conceptual client) can consume PI without PI knowing the client's identity.
3. Replaceability test: ThirdPartyDesktopClient retrieves state, situations, context, recommendations, and provenance.
4. PI has zero dependencies on client internals.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence import (
    PersonalIntelligenceCapabilityInterface,
    PersonalIntelligenceInterface,
)
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.goals.models import GoalPriority
from personal_intelligence.core.situations.models import SituationPriority
from personal_intelligence.core.world.graph import CanonicalEntityType, CanonicalRelationship
from personal_intelligence.storage.db import DatabaseManager


class ThirdPartyDesktopClient:
    """
    Conceptual Non-Hive Client (e.g. standalone desktop dashboard, terminal app, or AI assistant).
    Consumes Personal Intelligence solely via PersonalIntelligenceCapabilityInterface.
    """

    def __init__(self, pi: PersonalIntelligenceCapabilityInterface) -> None:
        self.pi = pi
        self.cached_world: dict = {}
        self.received_notifications: list = []

    def refresh_dashboard(self) -> dict:
        """Fetches current world model and active situations."""
        world = self.pi.get_current_world()
        situations = self.pi.get_active_situations()
        pending = self.pi.get_pending_interventions()
        self.cached_world = {
            "world": world,
            "situations": situations,
            "pending_interventions": pending,
        }
        return self.cached_world

    def handle_user_query_for_entity(self, entity_id: str) -> dict:
        """Fetches bounded context and timeline for a given entity."""
        ctx = self.pi.get_context_for_entity(entity_id=entity_id, depth=1)
        timeline = self.pi.get_relevant_timeline(entity_id=entity_id)
        return {"context": ctx, "timeline": timeline}

    def user_acknowledged_situation(self, situation_id: str, feedback: str = "Accepted by user") -> dict:
        """Sends user decision to PI without PI knowing who the client is."""
        return self.pi.record_user_response(situation_id=situation_id, action="acknowledge", feedback_notes=feedback)


class TestPersonalIntelligenceClientAgnosticInterface(unittest.TestCase):
    """Verifies PI client-agnostic capabilities and replaceability."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_client_interface.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.pi = PersonalIntelligenceCapabilityInterface(db_manager=self.db_manager)
        self.now = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_world_and_state_capabilities(self) -> None:
        """Capability: get_current_world and get_current_state."""
        # 1. Ingest observation creating a commitment
        self.pi.record_observation(
            source="jira",
            source_id="ENG-404",
            timestamp=self.now,
            observation_type="action_item_detected",
            summary="Prepare Q3 Engineering Infrastructure Roadmap",
            evidence={"due_at": format_iso8601(self.now + timedelta(days=2))},
            provenance={"tool": "jira_sync", "issue": "ENG-404"},
        )

        # 2. Query world snapshot
        world = self.pi.get_current_world(as_of=self.now)
        self.assertEqual(world["interface_version"], "1.0.0")
        self.assertGreaterEqual(len(world["commitments"]), 1)
        self.assertIn("Infrastructure Roadmap", world["commitments"][0]["description"])

        # 3. Query current state
        state = self.pi.get_current_state(reference_time=self.now)
        self.assertIn("features", state)

    def test_2_timeline_and_relevant_timeline_capabilities(self) -> None:
        """Capability: get_timeline and get_relevant_timeline."""
        obs1 = self.pi.record_observation(
            source="calendar",
            source_id="cal-1",
            timestamp=self.now - timedelta(hours=5),
            observation_type="calendar_event",
            summary="Architecture Sync",
            provenance={"tool": "gcal"},
        )
        obs2 = self.pi.record_observation(
            source="slack",
            source_id="slack-1",
            timestamp=self.now - timedelta(hours=1),
            observation_type="message_received",
            summary="Urgent security patch required",
            provenance={"tool": "slack"},
            entity_refs=["sec_team"],
        )

        # Timeline range query
        timeline_res = self.pi.get_timeline(
            start_time=self.now - timedelta(hours=10),
            end_time=self.now,
        )
        self.assertEqual(timeline_res["events_count"], 2)

        # Relevant timeline for specific entity
        entity_timeline = self.pi.get_relevant_timeline(entity_id="sec_team")
        self.assertEqual(len(entity_timeline), 1)
        self.assertEqual(entity_timeline[0]["source"], "slack")

    def test_3_context_and_graph_capabilities(self) -> None:
        """Capability: get_context, get_context_for_entity, get_context_for_situation, get_context_for_goal."""
        # Setup entities and relationships in Context Graph
        p1 = self.pi.context_graph.upsert_entity(name="Marcus Aurelius", entity_type="person")
        proj = self.pi.context_graph.upsert_entity(name="Project Meditations", entity_type="project")
        self.pi.context_graph.connect(p1.id, proj.id, CanonicalRelationship.WORKS_WITH.value)

        # Goal and situation
        goal = self.pi.world_model.create_goal(name="Complete Book Translation", priority=GoalPriority.HIGH.value)
        sit = self.pi.world_model.create_situation(
            type="translation_review",
            priority=SituationPriority.MEDIUM.value,
            context={"project_id": proj.id},
        )
        self.pi.context_graph.connect(sit.id, proj.id, CanonicalRelationship.ABOUT.value)

        # 1. Context for entity
        ctx_entity = self.pi.get_context_for_entity(entity_id=p1.id, depth=1)
        self.assertIn("nodes", ctx_entity)
        self.assertTrue(any(n["id"] == proj.id for n in ctx_entity["nodes"]))

        # 2. Context for situation
        ctx_sit = self.pi.get_context_for_situation(situation_id=sit.id, depth=1)
        self.assertTrue(any(n["id"] == proj.id for n in ctx_sit["nodes"]))

        # 3. Context for goal
        ctx_goal = self.pi.get_context_for_goal(goal_id=goal.id, depth=1)
        self.assertEqual(ctx_goal["center_entity"]["name"], "Complete Book Translation")

    def test_4_situations_and_changes_capabilities(self) -> None:
        """Capability: get_active_situations and get_significant_changes."""
        sit_crit = self.pi.world_model.create_situation(type="service_outage", priority=SituationPriority.CRITICAL.value)
        sit_med = self.pi.world_model.create_situation(type="minor_inbox_overflow", priority=SituationPriority.LOW.value)

        # All active situations
        all_sits = self.pi.get_active_situations()
        self.assertEqual(len(all_sits), 2)

        # Filtered by priority
        crit_sits = self.pi.get_active_situations(priority="critical")
        self.assertEqual(len(crit_sits), 1)
        self.assertEqual(crit_sits[0]["type"], "service_outage")

        # Significant changes
        changes = self.pi.get_significant_changes(window_hours=24)
        self.assertIsInstance(changes, list)

    def test_5_reasoning_and_epistemic_capabilities(self) -> None:
        """Capability: evaluate_situation, get_reasoning_context, and request_reasoning."""
        obs = self.pi.record_observation(
            source="cloudwatch",
            source_id="cw-alert-99",
            timestamp=self.now,
            observation_type="unusual_state",
            summary="High Memory Pressure on Primary DB",
            provenance={"tool": "cloudwatch"},
        )
        sit = self.pi.world_model.create_situation(
            type="database_memory_pressure",
            priority=SituationPriority.HIGH.value,
            evidence=[obs["id"]],
        )

        # 1. Evaluate situation significance & eligibility
        eval_res = self.pi.evaluate_situation(situation_id=sit.id, as_of=self.now)
        self.assertTrue(eval_res["requires_hermes"])
        self.assertEqual(eval_res["significance"]["level"], "high")

        # 2. Get epistemic reasoning context
        context_res = self.pi.get_reasoning_context(situation_id=sit.id, objective="Diagnose DB pressure")
        self.assertIn("situation", context_res)
        self.assertIn("current_state", context_res)
        self.assertIn("observed_facts", context_res)

        # 3. Request reasoning
        reasoning_res = self.pi.request_reasoning(situation_id=sit.id, objective="Investigate memory spike")
        self.assertIn("episode_id", reasoning_res)
        self.assertEqual(reasoning_res["situation_id"], sit.id)

    def test_6_recommendations_and_pending_interventions(self) -> None:
        """Capability: get_recommendations, get_pending_interventions, get_client_event_stream."""
        obs = self.pi.record_observation(
            source="pagerduty",
            source_id="pd-inc-1",
            timestamp=self.now,
            observation_type="incident_triggered",
            summary="Payment Gateway Outage",
            provenance={"tool": "pagerduty"},
        )
        sit = self.pi.world_model.create_situation(
            type="payment_gateway_down",
            priority=SituationPriority.CRITICAL.value,
            evidence=[obs["id"]],
        )

        # Request reasoning to generate recommendation
        self.pi.request_reasoning(situation_id=sit.id)

        # Query pending interventions for client
        interventions = self.pi.get_pending_interventions(limit=10)
        self.assertGreaterEqual(len(interventions), 1)
        first_int = interventions[0]
        self.assertEqual(first_int["situation_type"], "payment_gateway_down")
        self.assertEqual(first_int["policy_action"], "INTERRUPT")
        self.assertGreaterEqual(len(first_int["provenance"]), 1)

        # Query event stream
        events = self.pi.get_client_event_stream(limit=10)
        self.assertIsInstance(events, list)

    def test_7_user_response_and_outcome_recording(self) -> None:
        """Capability: record_user_response and record_outcome."""
        sit = self.pi.world_model.create_situation(type="contract_sla_warning", priority=SituationPriority.HIGH.value)
        reasoning = self.pi.request_reasoning(situation_id=sit.id)
        ep_id = reasoning["episode_id"]

        # 1. Client sends user decision
        resp = self.pi.record_user_response(
            situation_id=sit.id,
            action="acknowledge",
            feedback_notes="User reviewed and will act",
        )
        self.assertEqual(resp["status"], "success")

        # 2. Client records longitudinal outcome
        outcome = self.pi.record_outcome(
            episode_id=ep_id,
            outcome="COMPLETED",
            feedback_notes="SLA breach prevented successfully",
        )
        self.assertEqual(outcome["outcome"], "COMPLETED")

        # Verify episode record
        ep_data = self.pi.get_episode(ep_id)
        self.assertIsNotNone(ep_data)

    def test_8_batch_ingestion_capability(self) -> None:
        """Capability: ingest_batch."""
        batch = [
            {
                "source": "github",
                "source_id": "pr-101",
                "timestamp": self.now,
                "observation_type": "pr_merged",
                "summary": "Merged Auth Service refactor",
                "provenance": {"tool": "github"},
            },
            {
                "source": "whoop",
                "source_id": "whoop-88",
                "timestamp": self.now,
                "observation_type": "sleep_logged",
                "summary": "Recovery score 82%",
                "provenance": {"tool": "whoop"},
            },
        ]
        res = self.pi.ingest_batch(batch)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ingested_count"], 2)

    def test_9_replaceability_test_with_non_hive_client(self) -> None:
        """Replaceability Test: ThirdPartyDesktopClient operates fully without PI knowing its identity."""
        # 1. Ingest observations from external sources
        obs = self.pi.record_observation(
            source="slack",
            source_id="msg-exec-1",
            timestamp=self.now,
            observation_type="task_commitment_detected",
            summary="Send Investor Update by Friday 5 PM",
            evidence={"detected_deadline": format_iso8601(self.now + timedelta(days=2))},
            provenance={"tool": "slack_tool", "channel": "executive-sync"},
        )

        sit = self.pi.world_model.create_situation(
            type="investor_update_due",
            priority=SituationPriority.HIGH.value,
            evidence=[obs["id"]],
        )
        self.pi.request_reasoning(situation_id=sit.id)

        # 2. Non-Hive ThirdPartyDesktopClient consumes PI
        client = ThirdPartyDesktopClient(pi=self.pi)
        dashboard_data = client.refresh_dashboard()

        self.assertIn("world", dashboard_data)
        self.assertIn("situations", dashboard_data)
        self.assertIn("pending_interventions", dashboard_data)

        # Verify client can inspect situation and provenance
        pending = dashboard_data["pending_interventions"]
        self.assertGreaterEqual(len(pending), 1)
        self.assertEqual(pending[0]["situation_type"], "investor_update_due")
        self.assertEqual(pending[0]["provenance"][0]["source"], "slack")
        self.assertEqual(pending[0]["provenance"][0]["provenance"]["channel"], "executive-sync")

        # Client records user acknowledgment
        ack_res = client.user_acknowledged_situation(situation_id=sit.id)
        self.assertEqual(ack_res["status"], "success")


if __name__ == "__main__":
    unittest.main()
