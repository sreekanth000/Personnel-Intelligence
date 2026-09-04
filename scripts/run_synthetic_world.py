"""
Single End-to-End Synthetic World Demo Command.

Executes all 15 canonical pipeline stages:
1. reset demo state
2. generate synthetic world
3. ingest all observations
4. construct Personal World Model
5. construct Context Graph
6. construct timeline/state
7. run novelty analysis
8. discover situations
9. calculate evidence strength
10. invoke Hermes reasoning only when eligible
11. validate structured output
12. apply InterventionPolicy
13. persist reasoning episode
14. update learned patterns
15. expose all results to the existing UI

Prints a concise execution summary including:
events ingested
entities created
relationships created
situations discovered
Hermes calls
recommendations
interventions
patterns learned
errors
"""

import argparse
import logging
from pathlib import Path
import sys

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from personal_intelligence.demo.synthetic_hermes import (
    SyntheticHermesMode,
    SyntheticHermesRuntime,
)
from personal_intelligence.demo.synthetic_world import (
    SyntheticWorldDemo,
    SyntheticWorldPipelineSummary,
)
from personal_intelligence.storage.db import DatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Single End-to-End Synthetic World Demo Command"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Observation timeline window in days (default: 30, min: 30)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic PRNG seed for reproducible synthetic generation (default: 42)",
    )
    parser.add_argument(
        "--hermes-mode",
        type=str,
        default="semantic",
        choices=["deterministic", "semantic", "malformed", "incomplete", "contradictory"],
        help="Synthetic Hermes Runtime reasoning mode (default: semantic)",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not reset SQLite database state before running (default: resets to pristine)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Custom SQLite database file path (default: ~/.personal_intelligence/personal_intelligence.db for live UI)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Mode mapping
    mode_map = {
        "deterministic": SyntheticHermesMode.DETERMINISTIC,
        "semantic": SyntheticHermesMode.REALISTIC_SEMANTIC,
        "malformed": SyntheticHermesMode.MALFORMED_JSON,
        "incomplete": SyntheticHermesMode.INCOMPLETE_INVESTIGATION,
        "contradictory": SyntheticHermesMode.CONTRADICTORY_EVIDENCE,
    }
    selected_mode = mode_map[args.hermes_mode]

    # Initialize Database and Runtime
    db_mgr = DatabaseManager(db_path=args.db_path) if args.db_path else None
    runtime = SyntheticHermesRuntime(mode=selected_mode, seed=args.seed)
    demo = SyntheticWorldDemo(db_manager=db_mgr, hermes_runtime=runtime)

    # Execute complete 15-stage end-to-end pipeline
    summary: SyntheticWorldPipelineSummary = demo.run_end_to_end_pipeline(
        days=max(30, args.days),
        seed=args.seed,
        reset_state=not args.no_reset,
        hermes_mode=selected_mode,
    )

    # Print the concise execution summary
    print(summary.to_formatted_summary())


if __name__ == "__main__":
    main()
