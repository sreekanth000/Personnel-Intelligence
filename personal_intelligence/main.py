"""
Personal Intelligence Autonomous Daemon Entry Point.

Runs the continuous personal intelligence evaluation loop in the background,
polling registered data sources (Gmail, Slack, Calendar, etc.) and updating
the Personal World Model.

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
from personal_intelligence.scheduler.daemon import PollingDaemon
from personal_intelligence.storage.db import DatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Intelligence Background Daemon")
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Polling interval in minutes (default: 5)",
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
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = args.db_path or get_db_path()
    db = DatabaseManager(db_path=db_path)
    db.initialize_schema()

    loop = PersonalIntelligenceEvaluationLoop(db_manager=db)
    daemon = PollingDaemon(loop=loop, interval_minutes=args.interval)

    # Register Hermes-mediated capability pollers (Zero direct SDKs / credentials)
    from personal_intelligence.hermes_bridge.pollers import (
        HermesCalendarPoller,
        HermesGenericPoller,
        HermesGmailPoller,
    )
    daemon.register_source(HermesGmailPoller(hermes_client=loop.hermes_client))
    daemon.register_source(HermesCalendarPoller(hermes_client=loop.hermes_client))
    daemon.register_source(HermesGenericPoller(
        capability_name="slack",
        tool_name="slack_search",
        tool_parameters={"query": "has:link OR from:me OR to:me"},
        event_type="slack_message",
        hermes_client=loop.hermes_client,
    ))
    daemon.register_source(HermesGenericPoller(
        capability_name="whatsapp",
        tool_name="whatsapp_search",
        tool_parameters={"query": "recent"},
        event_type="whatsapp_message",
        hermes_client=loop.hermes_client,
    ))

    print("=" * 70)
    print("  [+] PERSONAL INTELLIGENCE BACKGROUND EVALUATION DAEMON")
    print("=" * 70)
    print(f"  * Database:  {db.db_path}")
    print(f"  * Interval:  {args.interval} minutes")
    print(f"  * Mode:      {'Single Run' if args.once else 'Continuous Daemon'}")
    print("=" * 70)

    if args.once:
        daemon.run_once()
        print("[+] Single cycle complete. Exiting.")
    else:
        daemon.start()


if __name__ == "__main__":
    main()
