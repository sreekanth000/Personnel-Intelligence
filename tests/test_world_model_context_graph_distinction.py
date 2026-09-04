"""
Acceptance Test Suite for Personal World Model vs Context Graph Distinction.

Verifies the strict architectural boundary and division of responsibility:

1. PERSONAL WORLD MODEL
   Answers: "What do we currently know about this person's world?"
   Semantic owner of: Entities, State, Timeline, Goals, Commitments, Situations, Observations.
   Primary API:
   - get_current_world()
   - get_current_state()
   - get_timeline()
   - get_goals()
   - get_situations()

2. CONTEXT GRAPH
   Answers: "How are the relevant things in that world connected?"
   Relational connective substrate for: relationships, temporal links, evidence links, relevance links, traversal.
   Primary API:
   - get_related_entities()
   - get_neighbors()
   - get_context()
   - get_temporal_context()
   - get_supporting_evidence()
   - get_related_goals()
   - get_related_situations()

Acceptance Criteria:
- World Model can operate without Hive.
- World Model can operate without Hermes reasoning.
- Context Graph can be queried independently.
- Context Graph is backed by existing SQLite storage (entity_nodes, entity_edges).
- No graph database is introduced.
- No duplicate memory system is introduced.
- World Model remains the semantic owner.
- Context Graph remains the relational connective substrate.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import unittest
import uuid

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.world.graph import (
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityNode,
)
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import Commitment, PersonalWorldModelSnapshot
from personal_intelligence.storage.db import DatabaseManager


class TestWorldModelContextGraphDistinction(unittest.TestCase):

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.db.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db)
        self.context_graph = ContextGraph(db_manager=self.db)

    def test_world_model_operates_without_hive(self) -> None:
        """Verify PersonalWorldModel operates completely headlessly without Hive UI."""
        # Ingest an observation into the world model
        event = Event(
            event_type="calendar_event",
            source="calendar",
            timestamp=datetime.now(timezone.utc),
            structured_data={"title": "Quarterly Strategy Review"},
            summary="Quarterly Strategy Review",
        )
        self.world_model.record_observation(event)

        # Query semantic snapshot headlessly
        snapshot = self.world_model.get_current_world()
        self.assertIsInstance(snapshot, PersonalWorldModelSnapshot)
        self.assertIsNotNone(snapshot.timestamp)
        self.assertIsNotNone(snapshot.current_state)

    def test_world_model_operates_without_hermes_reasoning(self) -> None:
        """Verify PersonalWorldModel evaluates and maintains state deterministically without LLM calls."""
        # Create a goal directly in the World Model
        self.world_model.create_goal(
            title="Complete Migration",
            description="Separate World Model from Context Graph",
            priority="high",
        )

        # Create a situation in the World Model
        self.world_model.create_situation(
            situation_type="schedule_conflict",
            priority="high",
            summary="Meeting overlaps with deep work block",
        )

        # Verify semantic retrieval methods without LLM reasoning
        goals = self.world_model.get_goals()
        situations = self.world_model.get_situations()
        state = self.world_model.get_current_state()
        timeline = self.world_model.get_timeline(limit=10)

        self.assertGreaterEqual(len(goals), 1)
        self.assertGreaterEqual(len(situations), 1)
        self.assertIsNotNone(state)
        self.assertIsInstance(timeline, list)

    def test_context_graph_can_be_queried_independently(self) -> None:
        """Verify ContextGraph functions as an independent relational connective substrate."""
        cg = ContextGraph(db_manager=self.db)

        # Add nodes
        n1 = EntityNode(name="Project Antigravity", entity_type=CanonicalEntityType.PROJECT.value)
        n2 = EntityNode(name="DeepMind Team", entity_type=CanonicalEntityType.ORGANIZATION.value)
        n3 = EntityNode(name="Q4 Deliverable", entity_type=CanonicalEntityType.GOAL.value)

        cg.add_node(n1)
        cg.add_node(n2)
        cg.add_node(n3)

        # Connect nodes with canonical relationships
        cg.connect(n1.id, n2.id, CanonicalRelationship.ASSOCIATED_WITH)
        cg.connect(n1.id, n3.id, CanonicalRelationship.SUPPORTS)

        # Query direct neighbors (returns (source, relationship, target) triples)
        neighbors = cg.get_neighbors(n1.id)
        connected_names = [target.name if s.id == n1.id else s.name for s, rel, target in neighbors]
        self.assertIn("DeepMind Team", connected_names)
        self.assertIn("Q4 Deliverable", connected_names)

        # Query related entities
        related = cg.get_related_entities(n1.id, relationship=CanonicalRelationship.SUPPORTS)
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0].name, "Q4 Deliverable")

    def test_context_graph_backed_by_existing_sqlite_storage(self) -> None:
        """Verify ContextGraph is backed strictly by SQLite entity_nodes and entity_edges tables."""
        cg = ContextGraph(db_manager=self.db)
        node = EntityNode(name="Test Node", entity_type="person")
        cg.add_node(node)

        # Verify directly in SQLite connection
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, entity_type FROM entity_nodes WHERE id = ?", (node.id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], node.id)
        self.assertEqual(row[1], "Test Node")
        self.assertEqual(row[2], "person")

        # Verify edge in SQLite
        node2 = EntityNode(name="Target Node", entity_type="topic")
        cg.add_node(node2)
        edge = cg.connect(node.id, node2.id, CanonicalRelationship.RELATED_TO)

        cursor.execute("SELECT source_id, target_id, relationship FROM entity_edges WHERE id = ?", (edge.id,))
        edge_row = cursor.fetchone()
        self.assertIsNotNone(edge_row)
        self.assertEqual(edge_row[0], node.id)
        self.assertEqual(edge_row[1], node2.id)
        self.assertEqual(edge_row[2], "related_to")

    def test_no_graph_database_introduced(self) -> None:
        """Verify zero external graph databases (Neo4j, Memgraph, etc.) are imported or configured."""
        import sys
        graph_db_modules = ["neo4j", "memgraph", "networkx", "gremlin_python", "dgraph"]
        for mod in graph_db_modules:
            self.assertNotIn(mod, sys.modules)

        # Verify database is pure SQLite
        self.assertTrue(hasattr(self.db, "get_connection"))
        conn = self.db.get_connection()
        import sqlite3
        self.assertIsInstance(conn, sqlite3.Connection)

    def test_world_model_semantic_owner_api_shape(self) -> None:
        """
        Verify World Model implements the desired semantic API shape:
        - get_current_world()
        - get_current_state()
        - get_timeline()
        - get_goals()
        - get_situations()
        """
        wm = self.world_model

        # 1. get_current_world()
        current_world = wm.get_current_world()
        self.assertIsInstance(current_world, PersonalWorldModelSnapshot)

        # 2. get_current_state()
        state = wm.get_current_state()
        self.assertIsNotNone(state)

        # 3. get_timeline()
        tl = wm.get_timeline(limit=10)
        self.assertIsInstance(tl, list)

        # 4. get_goals()
        goals = wm.get_goals()
        self.assertIsInstance(goals, list)

        # 5. get_situations()
        situations = wm.get_situations()
        self.assertIsInstance(situations, list)

    def test_context_graph_relational_substrate_api_shape(self) -> None:
        """
        Verify Context Graph implements the desired relational connective API shape:
        - get_related_entities()
        - get_neighbors()
        - get_context()
        - get_temporal_context()
        - get_supporting_evidence()
        - get_related_goals()
        - get_related_situations()
        """
        cg = self.context_graph

        # Set up test nodes and edges
        sit_node = EntityNode(id="sit-dist-101", name="Flight Delay Situation", entity_type=CanonicalEntityType.SITUATION.value)
        goal_node = EntityNode(id="goal-dist-102", name="Arrive on Time", entity_type=CanonicalEntityType.GOAL.value)
        obs_node = EntityNode(id="obs-dist-103", name="Airline SMS", entity_type=CanonicalEntityType.OBSERVATION.value)
        person_node = EntityNode(id="person-dist-104", name="Travel Agent", entity_type=CanonicalEntityType.PERSON.value)

        cg.add_node(sit_node)
        cg.add_node(goal_node)
        cg.add_node(obs_node)
        cg.add_node(person_node)

        cg.connect(sit_node.id, goal_node.id, CanonicalRelationship.CONFLICTS_WITH)
        cg.connect(obs_node.id, sit_node.id, CanonicalRelationship.EVIDENCE_FOR)
        cg.connect(sit_node.id, person_node.id, CanonicalRelationship.INVOLVES)

        # 1. get_related_entities()
        related_entities = cg.get_related_entities(sit_node.id)
        self.assertGreaterEqual(len(related_entities), 2)

        # 2. get_neighbors()
        neighbors = cg.get_neighbors(sit_node.id)
        self.assertGreaterEqual(len(neighbors), 3)

        # 3. get_context()
        context = cg.get_context(sit_node.id, depth=1)
        self.assertEqual(context.root_id, sit_node.id)
        self.assertGreaterEqual(len(context.nodes), 3)

        # 4. get_temporal_context()
        temp_context = cg.get_temporal_context(sit_node.id)
        self.assertIn("current", temp_context)
        self.assertIn("historical", temp_context)

        # 5. get_supporting_evidence()
        evidence = cg.get_supporting_evidence(sit_node.id)
        self.assertGreaterEqual(len(evidence), 1)

        # 6. get_related_goals()
        goals = cg.get_related_goals(sit_node.id)
        self.assertGreaterEqual(len(goals), 1)
        self.assertEqual(goals[0]["id"], goal_node.id)

        # 7. get_related_situations()
        sits = cg.get_related_situations(goal_node.id)
        self.assertGreaterEqual(len(sits), 1)
        self.assertEqual(sits[0]["id"], sit_node.id)

    def test_world_model_uses_context_graph_without_exposing_internals(self) -> None:
        """Verify PersonalWorldModel accesses ContextGraph cleanly and exposes high-level abstractions."""
        wm = self.world_model

        # Connect situation and goal via world_model's context_graph
        wm.create_goal(title="Launch v1.0", description="Ship MVP", priority="high")
        active_goals = wm.get_goals()
        self.assertGreaterEqual(len(active_goals), 1)
        goal_id = active_goals[0]["id"]

        wm.create_situation(situation_type="deadline_risk", priority="high", summary="Approaching sprint end")
        active_sits = wm.get_situations()
        self.assertGreaterEqual(len(active_sits), 1)
        sit_id = active_sits[0]["id"]

        # Connect in graph
        wm.context_graph.connect(sit_id, goal_id, CanonicalRelationship.AFFECTS)

        # Query via world model's high level delegation methods
        related_goals = wm.get_related_goals(sit_id)
        self.assertGreaterEqual(len(related_goals), 1)

        # Query neighbors via world model
        neighbors = wm.get_neighbors(sit_id)
        self.assertGreaterEqual(len(neighbors), 1)

    def test_acceptance_a_world_model_returns_current_world_state(self) -> None:
        """ACCEPTANCE TEST A: World Model can return current world state."""
        # Setup observations, goals, situations
        ev = self.world_model.record_observation(
            source="system_metric",
            source_id="metric-001",
            summary="User active on dev machine",
            provenance={"tool": "system_monitor", "host": "dev-01"},
        )
        goal = self.world_model.create_goal(
            title="Maintain Architectural Consistency",
            description="Keep World Model and Context Graph distinct",
            priority="high",
        )
        sit = self.world_model.create_situation(
            situation_type="resource_optimization",
            priority="medium",
            summary="Memory allocation optimal",
        )

        # Retrieve comprehensive current world state
        world_snapshot = self.world_model.get_current_world()
        self.assertIsInstance(world_snapshot, PersonalWorldModelSnapshot)
        self.assertIsNotNone(world_snapshot.timestamp)
        self.assertIsNotNone(world_snapshot.current_state)

        # Retrieve individual semantic dimensions
        state = self.world_model.get_current_state()
        self.assertIsNotNone(state)

        timeline = self.world_model.get_timeline(limit=10)
        self.assertIsInstance(timeline, list)
        self.assertGreaterEqual(len(timeline), 1)

        goals = self.world_model.get_goals()
        self.assertIsInstance(goals, list)
        self.assertTrue(any(g.get("name") == "Maintain Architectural Consistency" or g.get("title") == "Maintain Architectural Consistency" for g in goals))

        situations = self.world_model.get_situations()
        self.assertIsInstance(situations, list)
        self.assertTrue(any(s["type"] == "resource_optimization" for s in situations))

    def test_acceptance_b_context_graph_relationship_traversal(self) -> None:
        """ACCEPTANCE TEST B: Context Graph can perform relationship traversal."""
        cg = self.context_graph

        n_user = cg.upsert_entity(id="usr-1", name="Principal Investigator", entity_type="person")
        n_proj = cg.upsert_entity(id="prj-1", name="Project Antigravity", entity_type="project")
        n_paper = cg.upsert_entity(id="doc-1", name="Architecture Spec v2", entity_type="document")

        cg.connect(n_user.id, n_proj.id, CanonicalRelationship.INVOLVES)
        cg.connect(n_proj.id, n_paper.id, CanonicalRelationship.SUPPORTS)

        # 1-hop traversal
        user_neighbors = cg.get_neighbors(n_user.id)
        self.assertEqual(len(user_neighbors), 1)
        self.assertEqual(user_neighbors[0][1], "involves")
        self.assertEqual(user_neighbors[0][2].id, n_proj.id)

        # 2-hop contextual traversal
        bounded = cg.get_context(n_user.id, depth=2)
        node_ids = {n.id for n in bounded.nodes}
        self.assertIn(n_user.id, node_ids)
        self.assertIn(n_proj.id, node_ids)
        self.assertIn(n_paper.id, node_ids)

        # Formatted traversal prompt
        rendered = bounded.to_reasoning_prompt_context()
        self.assertIn("Principal Investigator", rendered)
        self.assertIn("Project Antigravity", rendered)
        self.assertIn("Architecture Spec v2", rendered)

    def test_acceptance_c_world_model_uses_context_graph_for_contextual_queries(self) -> None:
        """ACCEPTANCE TEST C: World Model can use Context Graph for contextual queries."""
        wm = self.world_model

        goal = wm.create_goal(title="Publish Research", priority="high")
        sit = wm.create_situation(situation_type="submission_deadline", priority="high")

        # Connect via relational substrate
        wm.context_graph.connect(sit.id, goal.id, CanonicalRelationship.AFFECTS)

        # World Model uses Context Graph to discover connected goals
        related_goals = wm.get_related_goals(sit.id)
        self.assertEqual(len(related_goals), 1)
        self.assertEqual(related_goals[0]["id"], goal.id)

        # World Model uses Context Graph to discover connected situations
        related_sits = wm.get_related_situations(goal.id)
        self.assertEqual(len(related_sits), 1)
        self.assertEqual(related_sits[0]["id"], sit.id)

    def test_acceptance_d_context_graph_does_not_become_second_source_of_truth(self) -> None:
        """ACCEPTANCE TEST D: Context Graph does not become a second source of truth."""
        # Verify Context Graph does NOT own goal or situation lifecycles
        self.assertFalse(hasattr(self.context_graph, "create_goal"))
        self.assertFalse(hasattr(self.context_graph, "create_situation"))
        self.assertFalse(hasattr(self.context_graph, "get_timeline"))
        self.assertFalse(hasattr(self.context_graph, "get_current_state"))
        self.assertFalse(hasattr(self.context_graph, "record_observation"))
        self.assertFalse(hasattr(self.context_graph, "record_reasoning_episode"))

        # Context Graph only manages nodes and edges as relational index
        self.assertTrue(hasattr(self.context_graph, "get_node"))
        self.assertTrue(hasattr(self.context_graph, "get_edges"))
        self.assertTrue(hasattr(self.context_graph, "get_neighbors"))

    def test_acceptance_e_no_duplicate_persistence_introduced(self) -> None:
        """ACCEPTANCE TEST E: No duplicate persistence is introduced."""
        # Both share the same unified DatabaseManager
        self.assertIs(self.world_model.context_graph.db_manager, self.world_model.db_manager)

        # Check tables in SQLite
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        # Core unified tables
        self.assertIn("entity_nodes", tables)
        self.assertIn("entity_edges", tables)
        self.assertIn("event_log", tables)
        self.assertIn("goals", tables)
        self.assertIn("situations", tables)

        # Ensure NO duplicate memory or duplicate graph tables exist
        self.assertNotIn("epistemic_facts", tables)
        self.assertNotIn("graph_nodes", tables)
        self.assertNotIn("graph_edges", tables)
        self.assertNotIn("secondary_world_model", tables)

    def test_acceptance_f_no_graph_database_introduced(self) -> None:
        """ACCEPTANCE TEST F: No graph database is introduced."""
        import sys
        for banned in ["neo4j", "memgraph", "networkx", "gremlin_python", "dgraph"]:
            self.assertNotIn(banned, sys.modules)

        # Connection is pure SQLite3
        import sqlite3
        conn = self.db.get_connection()
        self.assertIsInstance(conn, sqlite3.Connection)


if __name__ == "__main__":
    unittest.main()
