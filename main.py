"""
DeskPilot — Root Launch Script
Allows running directly with `python main.py` from project root.
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import threading
import webbrowser
from backend.server import run_server


def _start_background_api():
    try:
        run_server(host="127.0.0.1", port=5000)
    except Exception as e:
        print(f"Background web server error: {e}")


if __name__ == "__main__":
    if "--web" in sys.argv or "--docker" in sys.argv or os.environ.get("DESKPILOT_WEB_MODE"):
        is_docker = "--docker" in sys.argv or os.environ.get("DESKPILOT_DOCKER") or os.environ.get("DOCKER")
        default_host = "0.0.0.0" if is_docker else "127.0.0.1"
        host = os.environ.get("HOST", default_host)
        port = int(os.environ.get("PORT", 5000))
        print("\n========================================================")
        print(f"🚀 Starting DeskPilot in Web Mode at http://{host}:{port}")
        print("   Connecting Amazon Bedrock with Autonomous Multi-Agents")
        print("========================================================\n")
        if "--open" in sys.argv and host in ("127.0.0.1", "localhost"):
            webbrowser.open(f"http://localhost:{port}")
        run_server(host=host, port=port)
    else:
        try:
            from backend.app import main as run_desktop_app
        except ImportError as e:
            print(f"Desktop GUI unavailable: {e}")
            print("Falling back to Web Server mode on port 5000...")
            run_server(host="127.0.0.1", port=5000)
            sys.exit(0)

        # Start local API server in daemon thread so regular browsers can also connect
        srv_thread = threading.Thread(target=_start_background_api, daemon=True)
        srv_thread.start()
        run_desktop_app()


