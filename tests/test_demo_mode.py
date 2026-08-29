"""
Unit tests for Personal Intelligence Demo Mode & Scenarios (Prompt 6).

Validates:
1. Exact same engine stack execution
2. Scenario 1: Upcoming travel (Train 21:10, Office state, Weather delay -> INTERRUPT)
3. Scenario 2: Unresolved project commitment (Gmail, Cal, Drive -> BRIEFING)
4. Scenario 3: Cross-domain novelty (NOVEL_COMBINATION -> BRIEFING)
5. Scenario 4: Deep work (195m focus -> SUPPRESS)
6. Scenario 5: Learned interaction preference (Longitudinal patterns -> ACTIVE)
7. Isolated storage guarantees & reset_demo_state
"""

import unittest

from personal_intelligence.demo.scenarios import DemoScenarioRunner


class TestDemoMode(unittest.TestCase):
    """
    Test suite for DemoScenarioRunner across the 5 canonical scenarios.
    """

    def setUp(self) -> None:
        self.runner = DemoScenarioRunner(db_path=":memory:")

    def test_scenario_1_upcoming_travel(self) -> None:
        result = self.runner.run_scenario_1_upcoming_travel()
        self.assertEqual(result["scenario_id"], 1)
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
        self.assertIn("what_happened", result)
        self.assertIn("why_it_matters", result)
        self.assertIn("what_i_suggest", result)

    def test_scenario_2_unresolved_commitment(self) -> None:
        result = self.runner.run_scenario_2_unresolved_commitment()
        self.assertEqual(result["scenario_id"], 2)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertEqual(sit["type"], "unresolved_commitment_risk")
        self.assertEqual(sit["priority"], "high")

        # Verify multi-stream evidence
        ev_list = sit["evidence"]
        self.assertTrue(any("gmail" in str(e) for e in ev_list))
        self.assertTrue(any("cal" in str(e) for e in ev_list))
        self.assertTrue(any("drive" in str(e) for e in ev_list))

        self.assertEqual(result["policy_action"], "BRIEFING")

    def test_scenario_3_cross_domain_novelty(self) -> None:
        result = self.runner.run_scenario_3_cross_domain_novelty()
        self.assertEqual(result["scenario_id"], 3)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertGreaterEqual(sit["novelty"], 0.85)

        self.assertEqual(result["policy_action"], "BRIEFING")
        self.assertIn("uncertainty", result)

    def test_scenario_4_deep_work(self) -> None:
        result = self.runner.run_scenario_4_deep_work()
        self.assertEqual(result["scenario_id"], 4)
        self.assertIn("situation", result)
        sit = result["situation"]
        self.assertEqual(sit["type"], "deep_work_focus_block")
        self.assertIn(result["policy_action"], ("SUPPRESS", "DEFER", "DISCARD"))

    def test_scenario_5_learned_interaction_preference(self) -> None:
        result = self.runner.run_scenario_5_learned_interaction_preference()
        self.assertEqual(result["scenario_id"], 5)
        self.assertIn("pattern", result)
        pat = result["pattern"]
        self.assertEqual(pat["evidence_strength"].upper(), "STRONG")
        self.assertEqual(pat["status"], "ACTIVE")
        self.assertEqual(result["policy_action"], "BRIEFING")

    def test_run_intelligence(self) -> None:
        self.runner.run_scenario_1_upcoming_travel()
        intel_res = self.runner.run_intelligence()
        self.assertEqual(intel_res["status"], "success")
        self.assertGreaterEqual(intel_res["active_situations_count"], 1)

    def test_reset_demo_state(self) -> None:
        self.runner.run_scenario_1_upcoming_travel()
        self.assertGreater(self.runner.event_store.count(), 0)

        self.runner.reset_demo_state()
        self.assertEqual(self.runner.event_store.count(), 0)
        self.assertEqual(len(self.runner.situation_store.list_active()), 0)


if __name__ == "__main__":
    unittest.main()
