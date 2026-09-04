"""
Unit & Integration Test Suite for Advanced Cognitive Intelligence Engines.

Verifies:
1. Predictive Processing & Expectation Engine (Free Energy prediction error)
2. Theory of Mind Interpersonal Dynamics (`PersonEntity` & urgency multipliers)
3. Memory Maintenance & Consolidation (Deterministic lifecycle & decay)
4. Multi-Step Causal Monte Carlo Tree Search (MCTS Pareto decision trees)
5. PersonalWorldModel integration
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.person_model import PersonEntity
from personal_intelligence.experimental.predictive import ExpectedState, PredictiveProcessingEngine
from personal_intelligence.storage.db import DatabaseManager


class TestCognitiveIntelligenceEngines(unittest.TestCase):
    """Tests for advanced Cognitive Intelligence Engines."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_cognitive.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_predictive_processing_experimental_isolation_and_v1_decoupling(self) -> None:
        wm = self.world_model

        # 1. Verify V1 PersonalWorldModel does NOT have active predictive engine or evaluate_prediction_error
        self.assertFalse(hasattr(wm, "predictive_engine"))
        self.assertFalse(hasattr(wm, "evaluate_prediction_error"))

        # 2. Verify experimental PredictiveProcessingEngine operates standalone
        pred_engine = PredictiveProcessingEngine(db_manager=self.db_manager)
        exp = pred_engine.get_expected_state()
        self.assertIsNotNone(exp)
        self.assertIn("time_window_key", exp.to_dict())

        # 3. Routine event -> low prediction error
        routine_evt = Event(
            source="calendar",
            event_type="calendar_event",
            payload={"summary": "Daily Engineering Standup Sync"},
        )
        delta_routine = pred_engine.calculate_prediction_error(routine_evt)
        self.assertLess(delta_routine, 0.5)

        # 4. Biometric sleep deficit event -> high prediction error
        strain_evt = Event(
            source="health_tracker",
            event_type="biometric_alert",
            payload={"summary": "Abnormal sleep duration recorded", "duration_minutes": 210},
        )
        delta_strain = pred_engine.calculate_prediction_error(strain_evt)
        self.assertGreaterEqual(delta_strain, 0.5)


    def test_theory_of_mind_person_model_and_urgency(self) -> None:
        wm = self.world_model

        # Upsert Manager Person Profile
        manager = PersonEntity(
            name="Alex Rivera",
            relationship_role="manager",
            email="alex.rivera@company.com",
            priority_sensitivity=0.9,
        )
        wm.person_model_engine.upsert_person(manager)

        # Retrieve & verify
        resolved = wm.person_model_engine.get_person_by_name_or_email("alex.rivera@company.com")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "Alex Rivera")

        # Evaluate urgency multiplier for manager vs unknown collaborator
        urgency_mgr = wm.evaluate_person_urgency("Alex Rivera")
        urgency_unknown = wm.evaluate_person_urgency("Random Contact")

        self.assertGreater(urgency_mgr, urgency_unknown)
        self.assertGreater(urgency_mgr, 1.3)

    def test_memory_maintenance_consolidation(self) -> None:
        wm = self.world_model

        # Record raw observations with valid provenance
        wm.record_observation(
            source="gmail",
            source_id="msg-101",
            timestamp=datetime.now(timezone.utc),
            observation_type="email_received",
            summary="Project Apex Architecture Deliverable Update from Alex Rivera",
            provenance={"tool": "gmail_search", "query": "msg-101"},
        )

        summary = wm.run_memory_maintenance(retention_days=30, salience_decay_days=1.0)
        self.assertIsNotNone(summary)
        self.assertTrue(summary.db_optimized)

        # Verify raw event remains strictly intact and immutable
        events = wm.event_store.get_recent(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_id, "msg-101")
        self.assertEqual(events[0].provenance["tool"], "gmail_search")

    def test_mcts_experimental_isolation_and_v1_decoupling(self) -> None:
        """Verifies MCTS is decoupled from V1 World Model and isolated in experimental/."""
        wm = self.world_model

        # 1. Assert PersonalWorldModel V1 interface does NOT contain MCTS
        self.assertFalse(hasattr(wm, "mcts_simulator"))
        self.assertFalse(hasattr(wm, "run_mcts_tree_search"))

        # 2. Assert MCTS is isolated and operational in personal_intelligence.experimental
        from personal_intelligence.experimental import MCTSWorldSimulator, MCTSOptionNode
        sim = MCTSWorldSimulator()
        tree_res = sim.evaluate_decision_tree(
            situation_id="sit-mcts-001",
            scenario_title="Executive Committee Threat Mitigation Conflict",
        )

        self.assertIsNotNone(tree_res.recommended_option)
        self.assertGreater(len(tree_res.ranked_options), 1)
        self.assertGreater(tree_res.recommended_option.pareto_utility_score, 0.5)
        self.assertTrue(len(tree_res.recommended_option.option_title) > 0)



if __name__ == "__main__":
    unittest.main()
