"""
CLI entry point to execute the Synthetic World Demo.

Exercises the complete, un-truncated Personal Intelligence 19-stage pipeline
with source-backed synthetic observations as if Hermes were supplying them from an external world.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from personal_intelligence.demo.synthetic_world import SyntheticWorldDemo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("personal_intelligence.demo")


def main():
    parser = argparse.ArgumentParser(description="Run Personal Intelligence Synthetic World Demo.")
    parser.add_argument("--fabric", action="store_true", default=True, help="Use SyntheticSourceFabric for multi-day observations")
    parser.add_argument("--days", type=int, default=45, help="Number of timeline days (30-60 days recommended)")
    parser.add_argument("--seed", type=int, default=42, help="PRNG seed for deterministic reproducible observations")
    parser.add_argument("--scenario", type=str, default=None, help="Run a specific latent scenario (e.g., cross_domain_project_risk)")
    parser.add_argument(
        "--hermes-mode",
        type=str,
        default="deterministic",
        choices=["deterministic", "semantic", "malformed", "incomplete", "contradictory"],
        help="Operational mode for Synthetic Hermes Runtime",
    )
    args = parser.parse_args()

    # Map CLI mode string to SyntheticHermesMode
    mode_map = {
        "deterministic": "deterministic",
        "semantic": "realistic_semantic",
        "malformed": "malformed_json",
        "incomplete": "incomplete_investigation",
        "contradictory": "contradictory_evidence",
    }
    selected_mode = mode_map.get(args.hermes_mode, "deterministic")

    from personal_intelligence.demo.synthetic_hermes import SyntheticHermesMode, SyntheticHermesRuntime
    hermes_runtime = SyntheticHermesRuntime(mode=SyntheticHermesMode(selected_mode), seed=args.seed)

    print("=" * 80)
    print("PERSONAL INTELLIGENCE — SYNTHETIC WORLD DEMO")
    if args.scenario:
        print(f"Exercising complete 19-stage pipeline on Latent Scenario: '{args.scenario}' (seed={args.seed}, hermes_mode={args.hermes_mode})")
    else:
        print(f"Exercising complete 19-stage pipeline with Synthetic Source Fabric ({args.days} days, seed={args.seed}, hermes_mode={args.hermes_mode})")
    print("=" * 80)

    demo = SyntheticWorldDemo(hermes_runtime=hermes_runtime)
    if args.scenario:
        result = demo.run_scenario_demo(scenario_id=args.scenario, seed=args.seed)
    elif args.fabric or args.days > 14:
        result = demo.run_fabric_demo(seed=args.seed, days=args.days)
    else:
        result = demo.run_demo(base_time=datetime.now(timezone.utc))



    print("\n--- SYNTHETIC DEMO EXECUTION SUMMARY ---")
    print(f"• Observations Ingested:   {result.observations_ingested}")
    print(f"• Context Graph Nodes:     {result.context_graph_nodes}")
    print(f"• Context Graph Edges:     {result.context_graph_edges}")
    print(f"• Active Situations:       {result.active_situations_count}")
    print(f"• Reasoning Episodes:      {result.episodes_recorded}")
    print(f"• Learned Patterns Count:   {result.learned_patterns_count}")
    print("----------------------------------------")
    
    if result.decisions:
        print("\n--- REASONING & PRESENTATION DECISIONS ---")
        for d in result.decisions[:10]:  # Show top 10 for clean output
            print(f"  Episode ID: {d['episode_id']}")
            print(f"  Situation ID: {d['situation_id']}")
            print(f"  Evidence Quality: {d['evidence_quality']}")
            print(f"  Presentation Decision: {d['presentation_decision']}")
            print("  ---")
        if len(result.decisions) > 10:
            print(f"  ... and {len(result.decisions) - 10} more reasoning decisions recorded.")

    print("\n[SUCCESS] Synthetic World Demo completed successfully across all 19 canonical stages.\n")


if __name__ == "__main__":
    main()

