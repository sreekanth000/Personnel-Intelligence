"""
Unit & Integration Tests for Context Graph & Personal World Model Substrate.

Verifies:
1. An observation creates/updates an entity in the graph.
2. Multiple observations connect to the same entity.
3. Relationships persist across time with temporal bounds (valid_from/valid_to).
4. A situation can reference multiple entities.
5. A goal can connect to relevant events and situations.
6. PI can retrieve bounded context around a situation.
7. Retrieved context includes complete provenance.
8. Inferences remain distinguishable from observations (epistemic boundary).
9. Context can cross signal domains without domain-specific code.
10. A new signal type can participate in the graph without creating a new agent.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.world import (
    BoundedContextGraph,
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityNode,
    PersonalWorldModel,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestContextGraphIntelligence(unittest.TestCase):
    """Test suite proving the Context Graph as the central intelligence substrate."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_context_graph.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self.local_store)
        self.context_graph = self.world_model.context_graph
        self.now = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_observation_creates_and_updates_entity(self) -> None:
        """Scenario 1: An observation creates and updates an entity in the Context Graph."""
        obs = self.world_model.record_observation(
            source="jira",
            source_id="PROJ-101",
            timestamp=self.now,
            observation_type="task_updated",
            summary="Sarah updated Project Apollo roadmap",
            evidence={"project": "Project Apollo", "assignee": "Sarah Connor"},
            provenance={"tool": "jira_sync", "issue_key": "PROJ-101"},
            subject_id="user_primary",
        )

        # Verify project and person entities were created
        proj_node = self.context_graph.resolve_entity("Project Apollo")
        self.assertIsNotNone(proj_node)
        self.assertEqual(proj_node.entity_type, CanonicalEntityType.PROJECT.value)

        sarah_node = self.context_graph.resolve_entity("Sarah Connor")
        self.assertIsNotNone(sarah_node)
        self.assertEqual(sarah_node.entity_type, CanonicalEntityType.PERSON.value)

        # Verify observation node exists
        obs_node = self.context_graph.get_node(obs.id)
        self.assertIsNotNone(obs_node)
        self.assertEqual(obs_node.entity_type, CanonicalEntityType.OBSERVATION.value)

    def test_2_multiple_observations_connect_to_same_entity(self) -> None:
        """Scenario 2: Multiple observations across different sources connect to the same entity."""
        # 1. Jira observation mentioning Project Titan
        self.world_model.record_observation(
            source="jira",
            source_id="TITAN-1",
            timestamp=self.now - timedelta(days=2),
            observation_type="task_created",
            summary="Created Project Titan architecture ticket",
            evidence={"project": "Project Titan"},
            provenance={"tool": "jira_tool"},
        )

        # 2. Slack observation mentioning Project Titan
        self.world_model.record_observation(
            source="slack",
            source_id="slack-msg-99",
            timestamp=self.now - timedelta(days=1),
            observation_type="message_received",
            summary="Engineering sync regarding Project Titan launch",
            evidence={"project": "Project Titan"},
            provenance={"tool": "slack_tool"},
        )

        # 3. Calendar observation mentioning Project Titan
        self.world_model.record_observation(
            source="calendar",
            source_id="cal-ev-55",
            timestamp=self.now,
            observation_type="calendar_event",
            summary="Project Titan Executive Review",
            evidence={"project": "Project Titan"},
            provenance={"tool": "gcal_tool"},
        )

        proj_node = self.context_graph.resolve_entity("Project Titan")
        self.assertIsNotNone(proj_node)

        # Check all incoming edges to Project Titan
        edges = self.context_graph.get_edges(node_id=proj_node.id)
        self.assertGreaterEqual(len(edges), 3)

    def test_3_relationships_persist_across_time_with_temporal_validity(self) -> None:
        """Scenario 3: Relationships maintain temporal validity (valid_from, valid_to) and historical queries."""
        emp_start = self.now - timedelta(days=365)
        emp_end = self.now - timedelta(days=30)

        person = self.context_graph.upsert_entity(name="Alice Smith", entity_type=CanonicalEntityType.PERSON.value)
        company = self.context_graph.upsert_entity(name="Acme Corp", entity_type=CanonicalEntityType.ORGANIZATION.value)

        # Active past relationship that ended 30 days ago
        edge = self.context_graph.connect(
            source_id=person.id,
            target_id=company.id,
            relationship=CanonicalRelationship.WORKS_WITH.value,
            valid_from=emp_start,
            valid_to=emp_end,
            status="ended",
        )

        # Query 1: Was Alice working with Acme 60 days ago? (Yes)
        past_query = self.context_graph.what_was_true_at(target_time=self.now - timedelta(days=60), entity_id=person.id)
        self.assertEqual(past_query["active_relationships_count"], 1)

        # Query 2: Is Alice working with Acme now? (No, ended)
        now_query = self.context_graph.what_was_true_at(target_time=self.now, entity_id=person.id)
        self.assertEqual(now_query["active_relationships_count"], 0)

        # Query 3: What changed in the last 45 days? (Edge end detected)
        changes = self.context_graph.what_changed_since(since_time=self.now - timedelta(days=45))
        self.assertGreaterEqual(changes["updated_edges_count"], 1)

    def test_4_situation_references_multiple_entities(self) -> None:
        """Scenario 4: A situation frame connects to multiple people, projects, and observation evidence."""
        # Create entities
        sarah = self.context_graph.upsert_entity(name="Sarah", entity_type=CanonicalEntityType.PERSON.value)
        project = self.context_graph.upsert_entity(name="Migration", entity_type=CanonicalEntityType.PROJECT.value)

        obs = self.world_model.record_observation(
            source="slack",
            source_id="msg-1",
            timestamp=self.now,
            observation_type="deadline_detected",
            summary="Deadline risk for Migration",
            provenance={"tool": "slack"},
        )

        # Create situation
        sit = self.world_model.create_situation(
            type="deadline_pressure",
            priority=SituationPriority.HIGH.value,
            evidence=[obs.id],
            context={"project": project.id, "stakeholder": sarah.id},
        )

        # Link situation explicitly to Sarah and Migration project
        self.context_graph.connect(sit.id, sarah.id, CanonicalRelationship.INVOLVES.value)
        self.context_graph.connect(sit.id, project.id, CanonicalRelationship.AFFECTS.value)

        # Retrieve bounded context around situation
        bounded = self.world_model.get_bounded_context(target_id=sit.id, depth=1)
        entity_ids = {n.id for n in bounded.nodes}

        self.assertIn(sarah.id, entity_ids)
        self.assertIn(project.id, entity_ids)
        self.assertIn(obs.id, entity_ids)

    def test_5_goal_connects_to_events_and_situations(self) -> None:
        """Scenario 5: A user goal links to relevant observations and active situations."""
        goal = self.world_model.create_goal(
            name="Q3 Product Launch",
            description="Deliver core engine features before end of Q3",
            priority=GoalPriority.HIGH.value,
        )

        # Create situation affecting goal
        sit = self.world_model.create_situation(
            type="resource_bottleneck",
            priority=SituationPriority.CRITICAL.value,
            related_goals=[goal.id],
        )

        # Retrieve bounded context for goal
        bounded = self.world_model.get_bounded_context(target_id=goal.id, depth=1)
        self.assertIsNotNone(bounded.center_entity)
        self.assertEqual(bounded.center_entity.name, "Q3 Product Launch")

        # Verify situation is linked
        node_ids = {n.id for n in bounded.nodes}
        self.assertIn(sit.id, node_ids)

    def test_6_bounded_context_retrieval_around_situation(self) -> None:
        """Scenario 6: PI retrieves bounded multi-hop context around a situation without entire graph dump."""
        p1 = self.context_graph.upsert_entity(name="Alex", entity_type="person")
        org1 = self.context_graph.upsert_entity(name="Starlight Labs", entity_type="organization")
        self.context_graph.connect(p1.id, org1.id, CanonicalRelationship.WORKS_WITH.value)

        sit = self.world_model.create_situation(
            type="partner_contract_renewal",
            priority=SituationPriority.MEDIUM.value,
        )
        self.context_graph.connect(sit.id, p1.id, CanonicalRelationship.INVOLVES.value)

        # Depth 1: Sit -> Alex
        ctx_d1 = self.world_model.get_bounded_context(target_id=sit.id, depth=1)
        ids_d1 = {n.id for n in ctx_d1.nodes}
        self.assertIn(p1.id, ids_d1)
        self.assertNotIn(org1.id, ids_d1)  # Starlight Labs is 2 hops away

        # Depth 2: Sit -> Alex -> Starlight Labs
        ctx_d2 = self.world_model.get_bounded_context(target_id=sit.id, depth=2)
        ids_d2 = {n.id for n in ctx_d2.nodes}
        self.assertIn(p1.id, ids_d2)
        self.assertIn(org1.id, ids_d2)

        # Check string summary generation
        summary = ctx_d2.to_reasoning_prompt_context()
        self.assertIn("partner_contract_renewal", summary)
        self.assertIn("Alex", summary)

    def test_7_retrieved_context_includes_provenance(self) -> None:
        """Scenario 7: Every node and relationship in retrieved context carries provenance."""
        obs = self.world_model.record_observation(
            source="whatsapp",
            source_id="wa-msg-777",
            timestamp=self.now,
            observation_type="possible_commitment",
            summary="Agreed to send financial report by tomorrow 10 AM",
            evidence={"time": "10:00", "sender": "Accountant Bob"},
            provenance={"tool": "whatsapp_export", "message_id": "wa-msg-777", "query": "financial report"},
        )

        bounded = self.world_model.get_bounded_context(target_id=obs.id, depth=1)
        self.assertGreaterEqual(len(bounded.provenance_chain), 1)
        first_prov = bounded.provenance_chain[0]
        self.assertEqual(first_prov["tool"], "whatsapp_export")
        self.assertEqual(first_prov["message_id"], "wa-msg-777")

    def test_8_inferences_remain_distinguishable_from_observations(self) -> None:
        """Scenario 8: Context Graph strictly segregates OBSERVED facts from INFERRED relationships."""
        p_user = self.context_graph.upsert_entity(name="User", entity_type="person", id="user_primary")
        p_colleague = self.context_graph.upsert_entity(name="David", entity_type="person")

        # 1. Observed edge (User sent message to David)
        obs_edge = self.context_graph.connect(
            source_id=p_user.id,
            target_id=p_colleague.id,
            relationship=CanonicalRelationship.INVOLVES.value,
            epistemic_type="observed",
        )

        # 2. Inferred edge (PI infers David is User's manager)
        inf_edge = self.context_graph.connect(
            source_id=p_colleague.id,
            target_id=p_user.id,
            relationship=CanonicalRelationship.SUPPORTS.value,
            epistemic_type="inferred",
            metadata={"inference_rule": "frequent_status_updates", "confidence": 0.8},
        )

        # Bounded query with inferred included
        ctx_all = self.world_model.get_bounded_context(target_id=p_user.id, depth=1, include_inferred=True)
        epistemic_types = {e.epistemic_type for e in ctx_all.edges}
        self.assertIn("observed", epistemic_types)
        self.assertIn("inferred", epistemic_types)

        # Bounded query excluding inferred
        ctx_obs_only = self.world_model.get_bounded_context(target_id=p_user.id, depth=1, include_inferred=False)
        epistemic_types_obs = {e.epistemic_type for e in ctx_obs_only.edges}
        self.assertIn("observed", epistemic_types_obs)
        self.assertNotIn("inferred", epistemic_types_obs)

    def test_9_context_can_cross_signal_domains_without_domain_code(self) -> None:
        """Scenario 9: Graph naturally connects biometric, schedule, and messaging domains."""
        # 1. Biometric Observation (Whoop poor sleep)
        obs_health = self.world_model.record_observation(
            source="whoop",
            source_id="whoop-sleep-1",
            timestamp=self.now - timedelta(hours=4),
            observation_type="sleep_logged",
            summary="Recovery 34%, deep sleep deficit",
            evidence={"recovery": 34},
            provenance={"tool": "whoop_tool"},
        )

        # 2. Schedule Observation (Heavy presentation)
        obs_cal = self.world_model.record_observation(
            source="calendar",
            source_id="gcal-pres-2",
            timestamp=self.now + timedelta(hours=2),
            observation_type="calendar_event",
            summary="Executive Board Presentation",
            evidence={"title": "Executive Board Presentation"},
            provenance={"tool": "gcal_tool"},
        )

        # Connect both to User
        self.context_graph.connect(obs_health.id, "user_primary", CanonicalRelationship.AFFECTS.value)
        self.context_graph.connect(obs_cal.id, "user_primary", CanonicalRelationship.INVOLVES.value)

        # Retrieve bounded context around User (cross-domain synthesis)
        user_ctx = self.world_model.get_bounded_context(target_id="user_primary", depth=1)
        node_ids = {n.id for n in user_ctx.nodes}
        self.assertIn(obs_health.id, node_ids)
        self.assertIn(obs_cal.id, node_ids)

    def test_10_new_signal_type_participates_without_new_agent(self) -> None:
        """Scenario 10: Completely novel external signal (e.g. smart car telemetry) participates in graph."""
        novel_obs = self.world_model.record_observation(
            source="connected_car",
            source_id="vin-vehicle-099",
            timestamp=self.now,
            observation_type="low_battery_warning",
            summary="EV battery level 8%, range 18 miles",
            evidence={"battery_level": 8, "range_miles": 18, "location": "Home Garage"},
            provenance={"tool": "vehicle_telemetry", "vin": "VIN0998811"},
            source_type="iot_sensor",
        )

        # Verify car observation is indexed in graph
        car_node = self.context_graph.get_node(novel_obs.id)
        self.assertIsNotNone(car_node)
        self.assertEqual(car_node.metadata["source"], "connected_car")

        # Verify location entity was extracted
        loc_node = self.context_graph.resolve_entity("Home Garage")
        self.assertIsNotNone(loc_node)
        self.assertEqual(loc_node.entity_type, CanonicalEntityType.PLACE.value)


if __name__ == "__main__":
    unittest.main()
