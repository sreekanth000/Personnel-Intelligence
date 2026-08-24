"""
Unit tests for Personal Intelligence Demo Mode & Scenarios.

Validates:
1. Exact same engine stack execution
2. Scenario 1: Cross-source forgotten commitment
3. Scenario 2: Travel disruption
4. Scenario 3: Novel situation
5. Isolated storage guarantees & reset_demo_state
"""

import unittest

from personal_intelligence.demo.scenarios import DemoScenarioRunner


class TestDemoMode(unittest.TestCase):
    """
    Test suite for DemoScenarioRunner across the 3 canonical scenarios.
    """

    def setUp(self) -> None:
        self.runner = DemoScenarioRunner(db_path=":memory:")

    def test_scenario_1_forgotten_commitment(self) -> None:
        result = self.runner.run_scenario_1_forgotten_commitment()
        self.assertEqual(result["scenario"], 1)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertEqual(sit["type"], "unfinished_deliverable_risk")
        self.assertEqual(sit["priority"], "high")

        # Verify multi-stream evidence
        ev_list = sit["evidence"]
        self.assertTrue(any("gmail" in str(e) for e in ev_list))
        self.assertTrue(any("cal" in str(e) for e in ev_list))
        self.assertTrue(any("drive" in str(e) for e in ev_list))
        self.assertTrue(any("meet" in str(e) for e in ev_list))

        # Verify recommendation
        self.assertIn("Architecture", result["recommendation"])
        self.assertEqual(result["policy_action"], "BRIEFING")

    def test_scenario_2_travel_disruption(self) -> None:
        result = self.runner.run_scenario_2_travel_disruption()
        self.assertEqual(result["scenario"], 2)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertEqual(sit["type"], "travel_timing_risk")
        self.assertEqual(sit["priority"], "high")

        # Verify evidence
        ev_list = sit["evidence"]
        self.assertTrue(any("cal-train" in str(e) for e in ev_list))
        self.assertTrue(any("weather" in str(e) for e in ev_list))
        self.assertTrue(any("loc" in str(e) for e in ev_list))

        # High urgency with high actionability triggers INTERRUPT
        self.assertEqual(result["policy_action"], "INTERRUPT")

    def test_scenario_3_novel_situation(self) -> None:
        result = self.runner.run_scenario_3_novel_situation()
        self.assertEqual(result["scenario"], 3)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertGreaterEqual(sit["novelty"], 0.90)
        self.assertTrue(sit["context"].get("is_novel"))
        self.assertTrue(sit["context"].get("insufficient_evidence"))

        # Preserved uncertainty in recommendation
        self.assertIn("Unusual", result["recommendation"])
        self.assertEqual(result["policy_action"], "BRIEFING")

    def test_scenario_4_multi_goal_conflict(self) -> None:
        result = self.runner.run_scenario_4_multi_goal_conflict()
        self.assertEqual(result["scenario"], 4)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertEqual(sit["type"], "multi_goal_conflict")
        self.assertEqual(sit["priority"], "high")
        self.assertEqual(result["policy_action"], "INTERRUPT")
        self.assertIn("RFC", result["recommendation"])

    def test_scenario_5_pattern_discovery(self) -> None:
        result = self.runner.run_scenario_5_pattern_discovery()
        self.assertEqual(result["scenario"], 5)
        self.assertIn("pattern", result)
        pat = result["pattern"]
        self.assertEqual(pat["evidence_strength"].upper(), "STRONG")
        self.assertEqual(pat["status"], "ACTIVE")
        self.assertEqual(result["policy_action"], "BRIEFING")

    def test_run_intelligence(self) -> None:
        self.runner.run_scenario_1_forgotten_commitment()
        intel_res = self.runner.run_intelligence()
        self.assertEqual(intel_res["status"], "success")
        self.assertGreaterEqual(intel_res["active_situations_count"], 1)

    def test_reset_demo_state(self) -> None:
        self.runner.run_scenario_1_forgotten_commitment()
        self.assertGreater(self.runner.event_store.count(), 0)

        self.runner.reset_demo_state()
        self.assertEqual(self.runner.event_store.count(), 0)
        self.assertEqual(len(self.runner.situation_store.list_active()), 0)


if __name__ == "__main__":
    unittest.main()

