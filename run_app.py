#!/usr/bin/env python3
"""
Personal Intelligence Dashboard & Backend Server Launcher.
Starts the local HTTP server hosting both the web UI and the /api/pi/* REST endpoints.
"""

import os
import sys
from pathlib import Path

# Ensure UTF-8 output encoding for console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from personal_intelligence.api.server import create_dashboard_server

if __name__ == "__main__":
    port = 8080
    host = "127.0.0.1"

    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    server = create_dashboard_server(port=port, host=host)
    print("=" * 70)
    print("  [+] PERSONAL INTELLIGENCE DEMO & LIVE DASHBOARD")
    print("=" * 70)
    print(f"  * Web UI:    http://{host}:{port}/")
    print(f"  * API URL:   http://{host}:{port}/api/pi/overview")
    print(f"  * Live Flow: http://{host}:{port}/api/pi/live/run_flow")
    print("=" * 70)
    print("  Server is running. Press Ctrl+C to terminate.")
    print("=" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()
