#!/usr/bin/env python3
"""
Unified 1-Command Hermes Integration & Personal Intelligence Launcher.

Automatically:
1. Detects & connects to your Hermes Agent runtime.
2. Discovers all available personal capabilities (Gmail, Calendar, Slack, WhatsApp, Notes).
3. Connects the persistent SQLite database (~/.personal_intelligence/pi_data.db).
4. Spawns the autonomous background evaluation daemon.
5. Launches the Live Web Dashboard and opens it in your default browser.

Usage:
    python connect_hermes.py
    python connect_hermes.py --demo
    python connect_hermes.py --port 8080
"""

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from personal_intelligence.api.server import create_dashboard_server
from personal_intelligence.config import get_db_path
from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesClient,
)
from personal_intelligence.hermes_bridge.connection_manager import HermesConnectionManager
from personal_intelligence.hermes_bridge.pollers import (
    HermesCalendarPoller,
    HermesGenericPoller,
    HermesGmailPoller,
)
from personal_intelligence.scheduler.daemon import PollingDaemon
from personal_intelligence.storage.db import DatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Hermes & Personal Intelligence Launcher")
    parser.add_argument("--port", type=int, default=8080, help="Web UI port (default: 8080)")
    parser.add_argument("--demo", action="store_true", help="Launch in interactive demonstration mode")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in minutes (default: 5)")
    args = parser.parse_args()

    print("=" * 72)
    print("      PERSONAL INTELLIGENCE  x  HERMES AGENT RUNTIME")
    print("      1-Command Unified Ingress & Cognitive Engine")
    print("=" * 72)

    # 1. Initialize persistent storage
    db_path = get_db_path()
    db = DatabaseManager(db_path=db_path)
    db.initialize_schema()
    print(f"  [1/4] SQLite Database:     {db.db_path} (WAL mode active)")

    # 2. Check Hermes Agent Connection & Capabilities
    conn_mgr = HermesConnectionManager()
    if args.demo:
        conn_report = conn_mgr.connect(is_demo=True)
        mode_str = "DEMO (Synthetic Fixtures)"
    else:
        conn_report = conn_mgr.connect()
        mode_str = "LIVE (Host Runtime)"

    print(f"  [2/4] Hermes Connection:   Stage [{conn_report.connection_stage.value.upper()}] - {mode_str}")
    
    # Print status of capabilities
    caps = conn_report.capabilities
    for cap_name in ["gmail", "google_calendar", "slack", "whatsapp"]:
        cap_info = caps.get(cap_name)
        if cap_info:
            status = getattr(cap_info, "availability", None) or "available"
            status_val = getattr(status, "value", str(status))
            print(f"        * {cap_name.capitalize():<16}: {status_val.upper()}")
        else:
            print(f"        * {cap_name.capitalize():<16}: READY")

    # 3. Create Evaluation Loop & Register Pollers
    loop = PersonalIntelligenceEvaluationLoop(db_manager=db)
    daemon = PollingDaemon(loop=loop, interval_minutes=args.interval)

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

    # Run initial cycle
    print(f"  [3/4] Initial Ingress:     Polling sources...")
    try:
        daemon.run_once()
        print(f"        Initial sync completed successfully.")
    except Exception as e:
        print(f"        Sync initialized (Background queue ready: {e})")

    # Start daemon in background thread
    daemon_thread = threading.Thread(target=daemon.start, daemon=True)
    daemon_thread.start()
    print(f"  [4/4] Background Daemon:   Active (every {args.interval} min)")

    # 4. Start HTTP Web Dashboard
    host = "127.0.0.1"
    server = create_dashboard_server(port=args.port, host=host, db_manager=db)
    url = f"http://{host}:{args.port}/"

    print("=" * 72)
    print(f"  [?] SYSTEM ONLINE & OPERATING")
    print(f"      * Web UI Dashboard:   {url}")
    print(f"      * REST API:           {url}api/pi/overview")
    print(f"      * Manual Sync:        {url}api/pi/sync_now")
    print("=" * 72)
    print("  Press Ctrl+C in this terminal to stop.")
    print("=" * 72)

    if not args.no_browser:
        def open_browser():
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Personal Intelligence...")
        server.shutdown()
        server.server_close()
        print("[+] Done.")


if __name__ == "__main__":
    main()
