"""
Unit Test Suite for Next-Generation Personal World Model Upgrades.

Verifies:
1. Entity Knowledge Graph & Alias Resolution (`EntityGraphStore`)
2. Bayesian Probabilistic Belief Scoring & Reinforcement
3. Ebbinghaus Memory Salience Decay
4. Counterfactual 'What-If' Scenario Simulation (`WorldModelSimulator`)
5. Hierarchical Goal DAGs (Parent/Sub-goal links)
6. Reversible Observation Retraction & Provenance Lineage
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.world.graph import EntityEdge, EntityGraphStore, EntityNode
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import ProbabilisticFact
from personal_intelligence.core.world.simulator import WorldModelSimulator
from personal_intelligence.storage.db import DatabaseManager


class TestWorldModelUpgrades(unittest.TestCase):
    """Integration & Unit tests for Next-Gen World Model features."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_upgrades.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_entity_graph_store_node_edge_and_alias_resolution(self) -> None:
        graph = self.world_model.graph_store

        # 1. Add User and Goal nodes
        u_node = EntityNode(id="ent-user-1", name="Sreekanth", entity_type="person", aliases=["me", "gopit", "user@company.com"])
        g_node = EntityNode(id="ent-goal-1", name="Marathon Goal", entity_type="goal")
        graph.add_node(u_node)
        graph.add_node(g_node)

        # 2. Alias resolution
        resolved_me = graph.resolve_entity("me")
        self.assertIsNotNone(resolved_me)
        self.assertEqual(resolved_me.id, "ent-user-1")

        resolved_email = graph.resolve_entity("user@company.com")
        self.assertIsNotNone(resolved_email)
        self.assertEqual(resolved_email.name, "Sreekanth")

        # 3. Add Directed Edge
        edge = EntityEdge(source_id="ent-user-1", target_id="ent-goal-1", relationship="has_goal")
        graph.add_edge(edge)

        neighbors = graph.get_neighbors("ent-user-1", depth=1)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0][0].name, "Sreekanth")
        self.assertEqual(neighbors[0][1], "has_goal")
        self.assertEqual(neighbors[0][2].name, "Marathon Goal")

    def test_epistemic_record_creation_and_provenance(self) -> None:
        wm = self.world_model

        # 1. Record explicit OBSERVED fact with origin lineage
        rec1 = wm.record_epistemic_fact(
            subject="User",
            predicate="has_preferred_meeting_time",
            object="Morning 09:00-11:00",
            epistemic_type="observed",
            source="google_calendar",
            source_id="cal-pref-1",
            origin_event_id="evt-obs-101",
            supporting_observation_ids=["evt-obs-101"],
            provenance={"channel": "calendar", "verified": True},
        )
        self.assertEqual(rec1.epistemic_type, "observed")
        self.assertEqual(rec1.status, "active")
        self.assertIn("evt-obs-101", rec1.supporting_observation_ids)

        # 2. Reinforce with second supporting observation
        rec2 = wm.record_epistemic_fact(
            subject="User",
            predicate="has_preferred_meeting_time",
            object="Morning 09:00-11:00",
            epistemic_type="observed",
            source="gmail",
            source_id="msg-pref-2",
            origin_event_id="evt-obs-102",
            supporting_observation_ids=["evt-obs-102"],
        )
        self.assertIn("evt-obs-101", rec2.supporting_observation_ids)
        self.assertIn("evt-obs-102", rec2.supporting_observation_ids)

        # 3. Query epistemic records
        records = wm.get_epistemic_records(epistemic_type="observed")
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[0].subject, "User")


    def test_counterfactual_scenario_simulation(self) -> None:
        wm = self.world_model

        # Define hypothetical flight delay event
        h_flight_delay = Event(
            id="hyp-evt-01",
            source="flight_status",
            event_type="flight_delay",
            payload={"summary": "Flight 304 delayed 4 hours due to alpine weather"},
        )

        sim_res = wm.simulate_counterfactual(
            hypothetical_events=[h_flight_delay],
            scenario_description="Flight Delay What-If Simulation",
        )

        self.assertFalse(sim_res.is_safe)
        self.assertGreater(len(sim_res.predicted_issues), 0)
        self.assertIn("delay", sim_res.schedule_domino_effects[0].lower())

    def test_hierarchical_goal_dag(self) -> None:
        # Create Parent Goal
        parent_g = Goal(
            name="Run Alpine Marathon",
            priority=GoalPriority.HIGH.value,
        )
        self.world_model.goal_store.create_goal(parent_g)

        # Create Sub Goal
        sub_g = Goal(
            name="Weekly 30km Long Run",
            priority=GoalPriority.MEDIUM.value,
            parent_goal_id=parent_g.id,
        )
        self.world_model.goal_store.create_goal(sub_g)

        # Retrieve & verify parent/sub-goal relationship
        retrieved_sub = self.world_model.goal_store.get(sub_g.id)
        self.assertIsNotNone(retrieved_sub)
        self.assertEqual(retrieved_sub.parent_goal_id, parent_g.id)

    def test_cascading_truth_retraction(self) -> None:
        wm = self.world_model

        fact = wm.record_probabilistic_fact(
            subject="Project Apex",
            predicate="deadline",
            object="Friday 17:00",
            initial_confidence=0.9,
            evidence_id="evt-email-false-alarm",
        )
        self.assertEqual(fact.status, "active")

        # Retract observation
        retracted = wm.retract_observation("evt-email-false-alarm")
        self.assertIn(fact.id, retracted)

        # Verify fact status is now retracted in DB
        conn = wm.db_manager.get_connection()
        try:
            row = conn.execute("SELECT * FROM probabilistic_facts WHERE id=?", (fact.id,)).fetchone()
            self.assertEqual(dict(row)["status"], "retracted")
            self.assertEqual(dict(row)["belief_score"], 0.0)
        finally:
            conn.close()

    def test_ebbinghaus_memory_salience_decay(self) -> None:
        wm = self.world_model

        fact = wm.record_probabilistic_fact(
            subject="User",
            predicate="current_temporary_location",
            object="Base Camp Café",
            initial_confidence=0.8,
            evidence_id="evt-loc-01",
        )
        self.assertEqual(fact.salience_score, 1.0)

        # Apply 10 days of temporal decay
        wm.apply_memory_salience_decay(elapsed_days=10.0)

        conn = wm.db_manager.get_connection()
        try:
            row = conn.execute("SELECT * FROM probabilistic_facts WHERE id=?", (fact.id,)).fetchone()
            salience = dict(row)["salience_score"]
            self.assertLess(salience, 1.0)
            self.assertGreater(salience, 0.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
