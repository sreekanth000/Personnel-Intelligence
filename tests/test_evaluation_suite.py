"""
Automated unit and integration test suite for the Comprehensive Evaluation Suite.
Verifies all 12 functional categories and 11 adversarial stress cases.
"""

import unittest

from personal_intelligence.evaluation.benchmark import PersonalIntelligenceEvaluationHarness


class TestComprehensiveEvaluationSuite(unittest.TestCase):
    """
    Automated tests verifying the 12 evaluation categories and 11 adversarial scenarios.
    """

    def setUp(self) -> None:
        self.harness = PersonalIntelligenceEvaluationHarness()

    def tearDown(self) -> None:
        self.harness.close()

    # 1. State Tracking
    def test_category_1_state_tracking(self) -> None:
        metric = self.harness.eval_category_1_state_tracking()
        self.assertTrue(metric.passed, metric.details)

    # 2. Timeline Reasoning
    def test_category_2_timeline_reasoning(self) -> None:
        metric = self.harness.eval_category_2_timeline_reasoning()
        self.assertTrue(metric.passed, metric.details)

    # 3. Known Situation Detection
    def test_category_3_known_situation_detection(self) -> None:
        metric = self.harness.eval_category_3_known_situation_detection()
        self.assertTrue(metric.passed, metric.details)

    # 4. Novel Situation Detection
    def test_category_4_novel_situation_detection(self) -> None:
        metric = self.harness.eval_category_4_novel_situation_detection()
        self.assertTrue(metric.passed, metric.details)

    # 5. Cross-Domain Reasoning
    def test_category_5_cross_domain_reasoning(self) -> None:
        metric = self.harness.eval_category_5_cross_domain_reasoning()
        self.assertTrue(metric.passed, metric.details)

    # 6. Uncertainty Handling
    def test_category_6_uncertainty_handling(self) -> None:
        metric = self.harness.eval_category_6_uncertainty_handling()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    # 7. Hermes Structured Output Reliability
    def test_category_7_hermes_output_reliability(self) -> None:
        metric = self.harness.eval_category_7_hermes_output_reliability()
        self.assertTrue(metric.passed, metric.details)

    # 8. Intervention Decisions
    def test_category_8_intervention_decisions(self) -> None:
        metric = self.harness.eval_category_8_intervention_decisions()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    # 9. Pattern Discovery
    def test_category_9_pattern_discovery(self) -> None:
        metric = self.harness.eval_category_9_pattern_discovery()
        self.assertTrue(metric.passed, metric.details)

    # 10. Pattern Decay
    def test_category_10_pattern_decay(self) -> None:
        metric = self.harness.eval_category_10_pattern_decay()
        self.assertTrue(metric.passed, metric.details)

    # 11. Interaction Learning
    def test_category_11_interaction_learning(self) -> None:
        metric = self.harness.eval_category_11_interaction_learning()
        self.assertTrue(metric.passed, metric.details)

    # 12. Follow-Up Situations
    def test_category_12_follow_up_situations(self) -> None:
        metric = self.harness.eval_category_12_follow_up_situations()
        self.assertTrue(metric.passed, metric.details)

    # -------------------------------------------------------------------------
    # 11 Adversarial Test Cases
    # -------------------------------------------------------------------------

    def test_adv_1_insufficient_evidence(self) -> None:
        metric = self.harness.eval_adv_1_insufficient_evidence()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    def test_adv_2_contradictory_evidence(self) -> None:
        metric = self.harness.eval_adv_2_contradictory_evidence()
        self.assertTrue(metric.passed, metric.details)

    def test_adv_3_duplicated_events(self) -> None:
        metric = self.harness.eval_adv_3_duplicated_events()
        self.assertTrue(metric.passed, metric.details)

    def test_adv_4_stale_patterns(self) -> None:
        metric = self.harness.eval_adv_4_stale_patterns()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    def test_adv_5_misleading_events(self) -> None:
        metric = self.harness.eval_adv_5_misleading_events()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    def test_adv_6_malformed_hermes_output(self) -> None:
        metric = self.harness.eval_adv_6_malformed_hermes_output()
        self.assertTrue(metric.passed, metric.details)

    def test_adv_7_irrelevant_novelty(self) -> None:
        metric = self.harness.eval_adv_7_irrelevant_novelty()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    def test_adv_8_multiple_simultaneous_situations(self) -> None:
        metric = self.harness.eval_adv_8_multiple_simultaneous_situations()
        self.assertTrue(metric.passed, metric.details)

    def test_adv_9_conflicting_goals(self) -> None:
        metric = self.harness.eval_adv_9_conflicting_goals()
        self.assertTrue(metric.passed, metric.details)

    def test_adv_10_user_in_deep_work(self) -> None:
        metric = self.harness.eval_adv_10_user_in_deep_work()
        self.assertTrue(metric.passed, metric.details)
        self.assertTrue(metric.restraint_verified)

    def test_adv_11_repeated_dismissed_recommendations(self) -> None:
        metric = self.harness.eval_adv_11_repeated_dismissed_recommendations()
        self.assertTrue(metric.passed, metric.details)

    # Full Benchmark Run
    def test_run_full_benchmark_harness(self) -> None:
        report = self.harness.run_all_evaluations()
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(report.total_evaluations, 23)
        self.assertEqual(report.correct_restraint_rate, 1.0)
        self.assertEqual(report.useful_detection_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
