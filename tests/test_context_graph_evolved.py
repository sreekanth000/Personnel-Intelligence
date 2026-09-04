"""
Unit & Integration Tests for Context Graph (Prompt 2).

Verifies the 11 Prompt 2 requirements:
1. Entity relationship creation across generic types
2. Relationship provenance preservation
3. Temporal relationships (currently_relevant, historically_relevant, expired_or_stale, future_or_planned)
4. Cross-domain relationships (Person, Organization, Place, Device, Document, Project)
5. Goal relationships discovery (get_related_goals)
6. Situation relationships discovery (get_related_situations)
7. Evidence lookup (get_supporting_evidence)
8. Unrelated entities remaining excluded from bounded context
9. Duplicate relationships prevention
10. Idempotency on repeated edge creation
11. Domain-agnostic architecture (zero domain-specific modules/classes)
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


class TestContextGraphEvolved(unittest.TestCase):
    """Test suite for the SQLite-backed Context Graph."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_context_graph_evolved.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self.local_store)
        self.graph = self.world_model.context_graph
        self.now = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_entity_relationship_creation(self) -> None:
        """Requirement 1: Create entities and generic relationship edges."""
        alice = self.graph.upsert_entity(name="Alice Smith", entity_type=CanonicalEntityType.PERSON.value)
        acme = self.graph.upsert_entity(name="Acme Corp", entity_type=CanonicalEntityType.ORGANIZATION.value)
        proj = self.graph.upsert_entity(name="Project Apollo", entity_type=CanonicalEntityType.PROJECT.value)

        edge1 = self.graph.connect(alice.id, acme.id, CanonicalRelationship.BELONGS_TO.value)
        edge2 = self.graph.connect(alice.id, proj.id, CanonicalRelationship.INVOLVES.value)
        edge3 = self.graph.connect(proj.id, acme.id, CanonicalRelationship.RELATED_TO.value)

        self.assertIsNotNone(edge1.id)
        self.assertEqual(edge1.relationship, CanonicalRelationship.BELONGS_TO.value)
        self.assertEqual(edge2.relationship, CanonicalRelationship.INVOLVES.value)
        self.assertEqual(edge3.relationship, CanonicalRelationship.RELATED_TO.value)

        # Verify edge retrieval
        edges = self.graph.get_edges(node_id=alice.id)
        self.assertEqual(len(edges), 2)

    def test_2_relationship_provenance(self) -> None:
        """Requirement 2: Every derived relationship preserves provenance coordinates."""
        alice = self.graph.upsert_entity(name="Alice", entity_type=CanonicalEntityType.PERSON.value)
        meeting = self.graph.upsert_entity(name="Sprint Planning", entity_type=CanonicalEntityType.MEETING.value)

        prov = {
            "source": "hermes_calendar",
            "source_id": "cal-event-9988",
            "tool": "calendar_list_events",
            "extracted_at": format_iso8601(self.now),
        }

        edge = self.graph.connect(
            source_id=alice.id,
            target_id=meeting.id,
            relationship=CanonicalRelationship.INVOLVES.value,
            epistemic_type="observed",
            provenance=prov,
        )

        # Retrieve and verify provenance is preserved in edge metadata
        retrieved_edges = self.graph.get_edges(node_id=alice.id)
        self.assertEqual(len(retrieved_edges), 1)
        self.assertEqual(retrieved_edges[0].metadata.get("provenance"), prov)
        self.assertEqual(retrieved_edges[0].epistemic_type, "observed")

    def test_3_temporal_relationships(self) -> None:
        """Requirement 3: Distinguish currently_relevant, historically_relevant, expired_or_stale, and future_or_planned."""
        user = self.graph.upsert_entity(name="User", entity_type=CanonicalEntityType.PERSON.value)
        past_gym = self.graph.upsert_entity(name="Old Gym", entity_type=CanonicalEntityType.PLACE.value)
        curr_office = self.graph.upsert_entity(name="Current Office", entity_type=CanonicalEntityType.PLACE.value)
        stale_membership = self.graph.upsert_entity(name="Old Club", entity_type=CanonicalEntityType.ORGANIZATION.value)
        future_retreat = self.graph.upsert_entity(name="Upcoming Retreat", entity_type=CanonicalEntityType.EVENT.value)

        # 1. Historically relevant (ended in the past)
        self.graph.connect(
            user.id, past_gym.id, CanonicalRelationship.OCCURS_AT.value,
            valid_from=self.now - timedelta(days=365),
            valid_to=self.now - timedelta(days=60),
            status="ended",
        )

        # 2. Currently relevant (active now)
        self.graph.connect(
            user.id, curr_office.id, CanonicalRelationship.OCCURS_AT.value,
            valid_from=self.now - timedelta(days=180),
            valid_to=self.now + timedelta(days=180),
            status="active",
        )

        # 3. Expired or stale
        self.graph.connect(
            user.id, stale_membership.id, CanonicalRelationship.BELONGS_TO.value,
            valid_from=self.now - timedelta(days=200),
            status="stale",
        )

        # 4. Future or planned
        self.graph.connect(
            user.id, future_retreat.id, CanonicalRelationship.INVOLVES.value,
            valid_from=self.now + timedelta(days=14),
            status="planned",
        )

        temporal = self.graph.get_temporal_context(entity_id=user.id, as_of=self.now)

        self.assertEqual(len(temporal["currently_relevant"]), 1)
        self.assertEqual(temporal["currently_relevant"][0]["target_id"], curr_office.id)

        self.assertEqual(len(temporal["historically_relevant"]), 1)
        self.assertEqual(temporal["historically_relevant"][0]["target_id"], past_gym.id)

        self.assertEqual(len(temporal["expired_or_stale"]), 1)
        self.assertEqual(temporal["expired_or_stale"][0]["target_id"], stale_membership.id)

        self.assertEqual(len(temporal["future_or_planned"]), 1)
        self.assertEqual(temporal["future_or_planned"][0]["target_id"], future_retreat.id)

    def test_4_cross_domain_relationships(self) -> None:
        """Requirement 4: Cross-domain connections (Person, Device, Document, Project, Place)."""
        person = self.graph.upsert_entity(name="Bob", entity_type=CanonicalEntityType.PERSON.value)
        laptop = self.graph.upsert_entity(name="MacBook Pro", entity_type=CanonicalEntityType.DEVICE.value)
        doc = self.graph.upsert_entity(name="Q3 Roadmap", entity_type=CanonicalEntityType.DOCUMENT.value)
        proj = self.graph.upsert_entity(name="Infrastructure", entity_type=CanonicalEntityType.PROJECT.value)
        office = self.graph.upsert_entity(name="HQ Building", entity_type=CanonicalEntityType.PLACE.value)

        # Connect across domains using generic semantics
        self.graph.connect(person.id, laptop.id, CanonicalRelationship.BELONGS_TO.value)
        self.graph.connect(person.id, doc.id, CanonicalRelationship.AFFECTS.value)
        self.graph.connect(doc.id, proj.id, CanonicalRelationship.RELATED_TO.value)
        self.graph.connect(proj.id, office.id, CanonicalRelationship.OCCURS_AT.value)

        # Verify multi-hop cross-domain traversal
        related = self.graph.get_related_entities(entity_id=person.id, depth=2)
        related_ids = {e.id for e in related}
        self.assertIn(laptop.id, related_ids)
        self.assertIn(doc.id, related_ids)
        self.assertIn(proj.id, related_ids)

    def test_5_goal_relationships(self) -> None:
        """Requirement 5: Discover connected goals through Context Graph."""
        # Create a real goal in GoalStore
        goal = Goal(
            id="goal-fitness-101",
            name="Run Marathon",
            domain="health",
            priority=GoalPriority.HIGH.value,
            status=GoalStatus.ACTIVE.value,
        )
        self.world_model.goal_store.create_goal(goal)

        # Represent as node and connect to an activity entity
        goal_node = self.graph.upsert_entity(id=goal.id, name=goal.name, entity_type=CanonicalEntityType.GOAL.value)
        activity = self.graph.upsert_entity(name="Long Run 15k", entity_type=CanonicalEntityType.ACTIVITY.value)

        self.graph.connect(activity.id, goal_node.id, CanonicalRelationship.SUPPORTS.value)

        # Query related goals from activity
        related_goals = self.graph.get_related_goals(target_id=activity.id)
        self.assertEqual(len(related_goals), 1)
        self.assertEqual(related_goals[0]["id"], "goal-fitness-101")
        self.assertEqual(related_goals[0]["name"], "Run Marathon")

    def test_6_situation_relationships(self) -> None:
        """Requirement 6: Discover active situations linked to an entity."""
        sit = Situation(
            id="sit-deploy-risk",
            type="deployment_blocker",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.OPEN.value,
        )
        self.world_model.situation_store.create(sit)
        sit_node = self.graph.upsert_entity(id=sit.id, name="Deployment Risk", entity_type=CanonicalEntityType.SITUATION.value)

        service = self.graph.upsert_entity(name="Auth Service", entity_type=CanonicalEntityType.PROJECT.value)
        self.graph.connect(sit_node.id, service.id, CanonicalRelationship.AFFECTS.value)

        # Query related situations from service
        situations = self.graph.get_related_situations(entity_id=service.id)
        self.assertEqual(len(situations), 1)
        self.assertEqual(situations[0]["id"], "sit-deploy-risk")
        self.assertEqual(situations[0]["type"], "deployment_blocker")

    def test_7_evidence_lookup(self) -> None:
        """Requirement 7: Supporting evidence lookup resolves originating observations from EventStore."""
        # Record observation in EventStore
        evt = Event(
            id="evt-obs-7788",
            source="github",
            event_type="build_failed",
            payload={"summary": "Pipeline failed on main branch", "exit_code": 1},
            provenance={"tool": "github_actions", "commit": "a1b2c3d"},
            event_time=self.now,
        )
        self.world_model.event_store.append(evt)

        # Create situation with evidence reference
        sit = Situation(
            id="sit-ci-broken",
            type="ci_pipeline_failure",
            priority=SituationPriority.HIGH.value,
            status=SituationStatus.OPEN.value,
            evidence=["event:evt-obs-7788"],
        )
        self.world_model.situation_store.create(sit)

        # Lookup supporting evidence via Context Graph
        evidence = self.graph.get_supporting_evidence(target_id=sit.id)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["id"], "evt-obs-7788")
        self.assertEqual(evidence[0]["source"], "github")
        self.assertEqual(evidence[0]["summary"], "Pipeline failed on main branch")
        self.assertEqual(evidence[0]["provenance"].get("tool"), "github_actions")

    def test_8_unrelated_entities_remaining_excluded(self) -> None:
        """Requirement 8: Unrelated entities remain strictly excluded from bounded context."""
        # Connected cluster
        charlie = self.graph.upsert_entity(name="Charlie", entity_type=CanonicalEntityType.PERSON.value)
        project_x = self.graph.upsert_entity(name="Project X", entity_type=CanonicalEntityType.PROJECT.value)
        self.graph.connect(charlie.id, project_x.id, CanonicalRelationship.INVOLVES.value)

        # Unconnected entity
        stranger = self.graph.upsert_entity(name="Unconnected Stranger", entity_type=CanonicalEntityType.PERSON.value)
        unrelated_proj = self.graph.upsert_entity(name="Secret Unrelated Project", entity_type=CanonicalEntityType.PROJECT.value)

        # Query context for Charlie
        context = self.graph.get_context(target_id=charlie.id, depth=1)
        context_ids = {n.id for n in context.nodes}

        self.assertIn(charlie.id, context_ids)
        self.assertIn(project_x.id, context_ids)
        self.assertNotIn(stranger.id, context_ids)
        self.assertNotIn(unrelated_proj.id, context_ids)

    def test_9_duplicate_relationships(self) -> None:
        """Requirement 9: Prevent duplicate active relationships between the same pair."""
        p1 = self.graph.upsert_entity(name="Alice", entity_type=CanonicalEntityType.PERSON.value)
        p2 = self.graph.upsert_entity(name="Bob", entity_type=CanonicalEntityType.PERSON.value)

        edge_a = self.graph.connect(p1.id, p2.id, CanonicalRelationship.WORKS_WITH.value, weight=1.0)
        edge_b = self.graph.connect(p1.id, p2.id, CanonicalRelationship.WORKS_WITH.value, weight=2.0)

        # Must return the existing edge rather than creating a duplicate
        self.assertEqual(edge_a.id, edge_b.id)
        edges = self.graph.get_edges(node_id=p1.id)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].weight, 2.0)

    def test_10_idempotency(self) -> None:
        """Requirement 10: Repeated edge creation is strictly idempotent."""
        org = self.graph.upsert_entity(name="Acme", entity_type=CanonicalEntityType.ORGANIZATION.value)
        loc = self.graph.upsert_entity(name="New York", entity_type=CanonicalEntityType.PLACE.value)

        e1 = self.graph.connect(org.id, loc.id, CanonicalRelationship.LOCATED_AT.value)
        e2 = self.graph.connect(org.id, loc.id, CanonicalRelationship.LOCATED_AT.value)
        e3 = self.graph.connect(org.id, loc.id, CanonicalRelationship.LOCATED_AT.value)

        self.assertEqual(e1.id, e2.id)
        self.assertEqual(e2.id, e3.id)

        all_edges = self.graph.get_edges(node_id=org.id)
        self.assertEqual(len(all_edges), 1)

    def test_11_no_domain_specific_logic(self) -> None:
        """Requirement 11: Domain-agnostic architecture functions equally across all spheres."""
        # Health, Finance, Travel, Engineering entities all handled through generic substrate
        runner = self.graph.upsert_entity(name="Marathoner", entity_type=CanonicalEntityType.PERSON.value)
        watch = self.graph.upsert_entity(name="Garmin Watch", entity_type=CanonicalEntityType.DEVICE.value)
        account = self.graph.upsert_entity(name="Savings Account", entity_type=CanonicalEntityType.CONCEPT.value)
        flight = self.graph.upsert_entity(name="Flight AA-100", entity_type=CanonicalEntityType.EVENT.value)

        self.graph.connect(runner.id, watch.id, CanonicalRelationship.BELONGS_TO.value)
        self.graph.connect(runner.id, account.id, CanonicalRelationship.RELATED_TO.value)
        self.graph.connect(runner.id, flight.id, CanonicalRelationship.INVOLVES.value)

        rel_entities = self.graph.get_related_entities(entity_id=runner.id)
        rel_ids = {e.id for e in rel_entities}

        self.assertEqual(len(rel_entities), 3)
        self.assertIn(watch.id, rel_ids)
        self.assertIn(account.id, rel_ids)
        self.assertIn(flight.id, rel_ids)


if __name__ == "__main__":
    unittest.main()
