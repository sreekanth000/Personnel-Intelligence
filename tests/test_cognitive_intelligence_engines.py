"""
Unit & Integration Test Suite for Advanced Cognitive Intelligence Engines.

Verifies:
1. Predictive Processing & Expectation Engine (Free Energy prediction error)
2. Theory of Mind Interpersonal Dynamics (`PersonEntity` & urgency multipliers)
3. Hippocampal Memory Consolidation (Event log schema compaction)
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
from personal_intelligence.core.world.predictive import ExpectedState
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

    def test_predictive_processing_expectation_and_delta(self) -> None:
        wm = self.world_model

        # 1. Retrieve baseline expectation
        exp = wm.predictive_engine.get_expected_state()
        self.assertIsNotNone(exp)
        self.assertIn("time_window_key", exp.to_dict())

        # 2. Routine event -> low prediction error
        routine_evt = Event(
            source="calendar",
            event_type="calendar_event",
            payload={"summary": "Daily Engineering Standup Sync"},
        )
        delta_routine = wm.evaluate_prediction_error(routine_evt)
        self.assertLess(delta_routine, 0.5)

        # 3. Biometric sleep deficit event -> high prediction error
        strain_evt = Event(
            source="health_tracker",
            event_type="biometric_alert",
            payload={"summary": "Abnormal sleep duration recorded", "duration_minutes": 210},
        )
        delta_strain = wm.evaluate_prediction_error(strain_evt)
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

    def test_hippocampal_memory_compaction(self) -> None:
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

        summary = wm.compact_memory_schema(hours_back=24)
        self.assertGreaterEqual(summary.raw_events_scanned, 1)
        self.assertGreaterEqual(summary.nodes_created_or_updated, 1)

    def test_mcts_multi_step_tree_search(self) -> None:
        wm = self.world_model

        tree_res = wm.run_mcts_tree_search(
            situation_id="sit-mcts-001",
            scenario_title="Executive Committee Threat Mitigation Conflict",
        )

        self.assertIsNotNone(tree_res.recommended_option)
        self.assertGreater(len(tree_res.ranked_options), 1)
        self.assertGreater(tree_res.recommended_option.pareto_utility_score, 0.5)
        self.assertTrue(len(tree_res.recommended_option.option_title) > 0)


if __name__ == "__main__":
    unittest.main()
