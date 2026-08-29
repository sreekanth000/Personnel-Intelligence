"""
Comprehensive Integration Test Suite for Prompt 6: Live Personal Intelligence Demo & Backend APIs.

Tests:
1. Scenario 1 (Upcoming Travel): Train 21:10, Office state, Weather/Transit investigation, structured 6-field card.
2. Scenario 2 (Unresolved Project Commitment): Gmail + Cal + Drive -> Approaching milestone situation.
3. Scenario 3 (Cross-Domain Novelty): NOVEL_COMBINATION discovery -> Hermes investigation.
4. Scenario 4 (Deep Work): Attention state detection -> Low-urgency recommendation suppression.
5. Scenario 5 (Learned Interaction Preference): Longitudinal empirical pattern promotion.
6. Dispatcher `run_scenario(1..5)` in `DemoScenarioRunner`.
7. DashboardDataService endpoints:
   - `get_mode_payload()` & `set_operating_mode()` (`LIVE`, `DEMO`, `TEST`).
   - `get_reasoning_trace_payload()` (9-stage vertical trace without CoT dump).
   - `get_active_situations_payload()` (6 required card fields).
   - `get_learned_patterns_payload()` (categorized lifecycle grouping).
   - `load_demo_scenario(1..5)`.
"""

import os
import unittest
import tempfile
from datetime import datetime, timezone

from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.demo.scenarios import DemoScenarioRunner
from personal_intelligence.api.server import DashboardDataService


class TestDemoScenariosAndAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_pi_demo.db")
        self.db_manager = DatabaseManager(self.db_path)
        self.demo_runner = DemoScenarioRunner(db_manager=self.db_manager)
        self.data_service = DashboardDataService(db_manager=self.db_manager, is_demo_mode=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scenario_1_upcoming_travel(self):
        """Scenario 1: Train departure 21:10 from Office -> Weather/Transit investigation -> 6 fields."""
        res = self.demo_runner.run_scenario_1_upcoming_travel()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scenario_id"], 1)
        self.assertIn("travel", res["scenario_name"].lower())

        # Check structured situation fields
        self.assertIn("what_happened", res)
        self.assertIn("why_it_matters", res)
        self.assertIn("what_i_suggest", res)
        self.assertIn("evidence", res)
        self.assertIn("uncertainty", res)
        self.assertIn("policy", res)
        self.assertEqual(res["policy"], "INTERRUPT")
        self.assertIn("21:10", res["what_happened"])

    def test_scenario_2_unresolved_project_commitment(self):
        """Scenario 2: Gmail request + Cal review tomorrow + Drive draft unchanged -> Approaching milestone."""
        res = self.demo_runner.run_scenario_2_unresolved_commitment()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scenario_id"], 2)

        self.assertIn("what_happened", res)
        self.assertIn("why_it_matters", res)
        self.assertIn("what_i_suggest", res)
        self.assertIn("policy", res)
        self.assertIn("architecture", res["what_happened"].lower())
        self.assertEqual(res["policy"], "BRIEFING")

    def test_scenario_3_cross_domain_novelty(self):
        """Scenario 3: Cross-domain novelty combination -> NOVEL_COMBINATION situation."""
        res = self.demo_runner.run_scenario_3_cross_domain_novelty()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scenario_id"], 3)

        sit = res["situation"]
        self.assertIn(sit["type"], ("cross_domain_novel_situation", "novel_multi_domain_shift", "novel_situation", "cross_domain_anomaly"))
        self.assertIn("what_happened", res)
        self.assertIn("uncertainty", res)
        self.assertEqual(res["policy"], "BRIEFING")

    def test_scenario_4_deep_work_suppression(self):
        """Scenario 4: Sustained focus -> DEEP_WORK attention state -> low-urgency suppression/deferral."""
        res = self.demo_runner.run_scenario_4_deep_work()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scenario_id"], 4)

        self.assertEqual(res["attention_state"], "DEEP_WORK")
        self.assertIn(res["policy"], ("SUPPRESS", "DEFER", "DISCARD", "BRIEFING"))

    def test_scenario_5_learned_interaction_preference(self):
        """Scenario 5: Longitudinal learning -> 12 reasoning episodes -> Promoted to ACTIVE."""
        res = self.demo_runner.run_scenario_5_learned_interaction_preference()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scenario_id"], 5)
        self.assertGreaterEqual(res["episodes_ingested"], 12)

        patterns = res["patterns"]
        self.assertTrue(len(patterns) > 0)
        # Verify non-causal language invariant
        for p in patterns:
            self.assertNotIn("causes", p.get("description", "").lower())
            self.assertIn("observed association", p.get("description", "").lower())

    def test_demo_runner_dispatcher_1_to_5(self):
        """Test DemoScenarioRunner.run_scenario dispatcher for IDs 1 through 5."""
        for scen_id in range(1, 6):
            res = self.demo_runner.run_scenario(scen_id)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["scenario_id"], scen_id)

    def test_api_mode_endpoints(self):
        """Test GET and POST operating mode payloads (LIVE, DEMO, TEST)."""
        mode_payload = self.data_service.get_mode_payload()
        self.assertIn(mode_payload["mode"], ("LIVE", "DEMO", "TEST"))
        self.assertEqual(set(mode_payload["available_modes"]), {"LIVE", "DEMO", "TEST"})

        # Set to TEST mode
        res = self.data_service.set_operating_mode("TEST")
        self.assertEqual(res["mode"], "TEST")
        self.assertEqual(self.data_service.operating_mode, "TEST")

        # Set to DEMO mode
        res = self.data_service.set_operating_mode("DEMO")
        self.assertEqual(res["mode"], "DEMO")
        self.assertTrue(self.data_service.is_demo_mode)

        # Set to LIVE mode
        res = self.data_service.set_operating_mode("LIVE")
        self.assertEqual(res["mode"], "LIVE")
        self.assertFalse(self.data_service.is_demo_mode)

    def test_api_active_situations_payload(self):
        """Test /api/pi/situations returns all 6 required card fields."""
        self.data_service.load_demo_scenario(1)
        sits = self.data_service.get_active_situations_payload()
        self.assertTrue(len(sits) > 0)
        sit = sits[0]
        self.assertIn("what_happened", sit)
        self.assertIn("why_it_matters", sit)
        self.assertIn("what_i_suggest", sit)
        self.assertIn("evidence", sit)
        self.assertIn("uncertainty", sit)
        self.assertIn("policy", sit)

    def test_api_reasoning_trace_payload(self):
        """Test /api/pi/reasoning_trace returns the 9-stage vertical trace without CoT dump."""
        self.data_service.load_demo_scenario(1)
        sits = self.data_service.get_active_situations_payload()
        sit_id = sits[0]["situation_id"]

        trace_payload = self.data_service.get_reasoning_trace_payload(situation_id=sit_id)
        self.assertEqual(trace_payload["situation_id"], sit_id)
        steps = trace_payload["steps"]
        self.assertEqual(len(steps), 9)

        expected_stages = [
            "Observation",
            "Change Detection",
            "Personal Significance",
            "Situation Detection",
            "Information Gap",
            "Hermes Investigation",
            "Deterministic Evidence",
            "Recommendation",
            "Intervention Policy",
        ]
        for idx, expected in enumerate(expected_stages):
            self.assertEqual(steps[idx]["stage"], expected)
            self.assertTrue(len(steps[idx]["content"]) > 0)
            # Ensure no chain of thought dump
            self.assertNotIn("Let's think step by step", steps[idx]["content"])

    def test_api_learned_patterns_payload(self):
        """Test /api/pi/patterns returns categorized lifecycle groups."""
        self.data_service.load_demo_scenario(5)
        patterns_payload = self.data_service.get_learned_patterns_payload()
        self.assertIn("active", patterns_payload)
        self.assertIn("supported", patterns_payload)
        self.assertIn("emerging", patterns_payload)
        self.assertIn("decaying", patterns_payload)
        self.assertIn("counts", patterns_payload)
        self.assertGreaterEqual(patterns_payload["counts"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
