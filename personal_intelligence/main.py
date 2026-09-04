"""
Personal Intelligence Local Evaluation Daemon Entry Point.

Runs the continuous personal intelligence evaluation loop in the background,
evaluating local state, situations, goals, and intervention policy over
the local SQLite database.

Architectural Notice:
External-world observation acquisition is owned and scheduled exclusively by Hermes
(via Hermes cron/schedules.yaml or HermesObservationScheduler).
Personal Intelligence performs local evaluation and maintenance.

Usage:
    python -m personal_intelligence.main
    python -m personal_intelligence.main --interval 5
    python -m personal_intelligence.main --once
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from personal_intelligence.config import get_db_path
from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
from personal_intelligence.scheduler.daemon import LocalEvaluationDaemon
from personal_intelligence.storage.db import DatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Intelligence Local Evaluation Daemon")
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Evaluation interval in minutes (default: 5)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database file (default: ~/.personal_intelligence/pi_data.db)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single evaluation cycle and exit",
    )
    parser.add_argument(
        "--synthetic-world",
        action="store_true",
        help="Run single end-to-end Synthetic World Demo and print execution summary",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days for synthetic timeline (default: 30)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic seed for synthetic generation (default: 42)",
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
        help="Do not reset database before synthetic world generation",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
    args = parser.parse_args()

    if args.synthetic_world:
        from personal_intelligence.demo.synthetic_hermes import SyntheticHermesMode, SyntheticHermesRuntime
        from personal_intelligence.demo.synthetic_world import SyntheticWorldDemo

        mode_map = {
            "deterministic": SyntheticHermesMode.DETERMINISTIC,
            "semantic": SyntheticHermesMode.REALISTIC_SEMANTIC,
            "malformed": SyntheticHermesMode.MALFORMED_JSON,
            "incomplete": SyntheticHermesMode.INCOMPLETE_INVESTIGATION,
            "contradictory": SyntheticHermesMode.CONTRADICTORY_EVIDENCE,
        }
        selected_mode = mode_map[args.hermes_mode]
        db_path = args.db_path or get_db_path()
        db = DatabaseManager(db_path=db_path)
        runtime = SyntheticHermesRuntime(mode=selected_mode, seed=args.seed)
        demo = SyntheticWorldDemo(db_manager=db, hermes_runtime=runtime)
        summary = demo.run_end_to_end_pipeline(
            days=max(30, args.days),
            seed=args.seed,
            reset_state=not args.no_reset,
            hermes_mode=selected_mode,
        )
        print(summary.to_formatted_summary())
        return

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = args.db_path or get_db_path()
    db = DatabaseManager(db_path=db_path)
    db.initialize_schema()

    loop = PersonalIntelligenceEvaluationLoop(db_manager=db)
    daemon = LocalEvaluationDaemon(loop=loop, interval_minutes=args.interval)

    print("=" * 70)
    print("  [+] PERSONAL INTELLIGENCE LOCAL EVALUATION DAEMON")
    print("=" * 70)
    print(f"  * Database:       {db.db_path}")
    print(f"  * Interval:       {args.interval} minutes")
    print(f"  * Mode:           {'Single Run' if args.once else 'Continuous Daemon'}")
    print("  * Acquisition:    Hermes-owned (External observations via Hermes)")
    print("=" * 70)

    if args.once:
        daemon.run_once()
        print("[+] Single evaluation cycle complete. Exiting.")
    else:
        daemon.start()


if __name__ == "__main__":
    main()
