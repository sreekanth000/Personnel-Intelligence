"""
Comprehensive Personal Intelligence Evaluation Benchmark Runner.
Executes all 12 core functional categories and 11 adversarial stress scenarios.
Outputs structured summary scorecards and detailed per-category metrics.
"""

from pathlib import Path
import sys

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from personal_intelligence.evaluation.benchmark import PersonalIntelligenceEvaluationHarness


def main():
    print("=" * 85)
    print("PERSONAL INTELLIGENCE: COMPREHENSIVE BENCHMARK EVALUATION SUITE")
    print("=" * 85)
    print("Evaluating 12 Functional Categories + 11 Adversarial Stress Cases")
    print("Objective: Maximize Useful Detections, Correct Restraint, Epistemic Integrity, and Learning Quality.")
    print("-" * 85)

    harness = PersonalIntelligenceEvaluationHarness()
    try:
        report = harness.run_all_evaluations()

        print("\n" + "=" * 85)
        print("I. CORE FUNCTIONAL EVALUATION CATEGORIES (12 Categories)")
        print("=" * 85)
        core_metrics = [m for m in report.metrics if not m.is_adversarial]
        for idx, m in enumerate(core_metrics, 1):
            status_str = "[PASS]" if m.passed else "[FAIL]"
            restraint_tag = " (Restraint Verified)" if m.restraint_verified else ""
            print(f"  {status_str} {m.category}: {m.scenario}{restraint_tag}")
            print(f"         Details: {m.details}")

        print("\n" + "=" * 85)
        print("II. ADVERSARIAL STRESS SCENARIOS (11 Stress Cases)")
        print("=" * 85)
        adv_metrics = [m for m in report.metrics if m.is_adversarial]
        for idx, m in enumerate(adv_metrics, 1):
            status_str = "[PASS]" if m.passed else "[FAIL]"
            restraint_tag = " [RESTRAINT VERIFIED]" if m.restraint_verified else ""
            print(f"  {status_str} {m.scenario}{restraint_tag}")
            print(f"         Outcome: {m.details}")

        print("\n" + "=" * 85)
        print("III. SYSTEM BENCHMARK SCORECARD")
        print("=" * 85)
        print(f"  Total Evaluations Run:      {report.total_evaluations}")
        print(f"  Total Passed:               {report.passed_count} / {report.total_evaluations} ({report.passed_count/report.total_evaluations*100:.1f}%)")
        print(f"  Useful Detection Rate:      {report.useful_detection_rate * 100:.1f}%")
        print(f"  Correct Restraint Rate:     {report.correct_restraint_rate * 100:.1f}% (Honest Silence on Weak/Adversarial Signals)")
        print(f"  Epistemic Integrity Rate:   {report.epistemic_integrity_rate * 100:.1f}% (Zero Faux Probabilities / Zero Hallucinated Causality)")
        print(f"  Learning Quality Score:     {report.learning_quality_score * 100:.1f}% (Full Provenance & Non-Causal Associations)")
        print(f"  Idempotency & Consistency:  {report.consistency_rate * 100:.1f}%")
        print("=" * 85)

        if report.failed_count == 0:
            print("\n>>> ALL 23 BENCHMARK EVALUATIONS PASSED UNDER TEST SCENARIOS <<<\n")
        else:
            print(f"\n>>> WARNING: {report.failed_count} EVALUATIONS FAILED <<<\n")
            sys.exit(1)

    finally:
        harness.close()


if __name__ == "__main__":
    main()
