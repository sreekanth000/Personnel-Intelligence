"""
CLI entry point to launch the Personal Intelligence Dashboard UI on localhost.
"""

import argparse
import logging
import os
from pathlib import Path
import sys
import webbrowser

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from personal_intelligence.api.server import create_dashboard_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("personal_intelligence.ui")


def main():
    parser = argparse.ArgumentParser(description="Launch Personal Intelligence Local Browser UI")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind server (default: 8080)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    ui_dir = str(project_root / "ui")
    server = create_dashboard_server(
        port=args.port,
        host=args.host,
        ui_dir=ui_dir,
    )

    url = f"http://{args.host}:{args.port}"
    print("=" * 70)
    print(f"PERSONAL INTELLIGENCE LOCAL BROWSER UI")
    print(f"Server running at: {url}")
    print(f"Bound to: {args.host}:{args.port} (Localhost Only)")
    print("=" * 70)

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Personal Intelligence UI server...")
        server.server_close()


if __name__ == "__main__":
    main()
