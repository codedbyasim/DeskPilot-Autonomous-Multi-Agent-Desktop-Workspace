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
    is_cloud_or_headless = (
        "--web" in sys.argv
        or "--docker" in sys.argv
        or bool(os.environ.get("DESKPILOT_WEB_MODE"))
        or bool(os.environ.get("RENDER"))
        or bool(os.environ.get("RAILWAY_ENVIRONMENT"))
        or (bool(os.environ.get("PORT")) and os.environ.get("PORT") != "5000")
        or (sys.platform != "win32" and not os.environ.get("DISPLAY"))
    )

    if is_cloud_or_headless:
        host = os.environ.get("HOST", "0.0.0.0")
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
        except (ImportError, Exception) as e:
            print(f"Desktop GUI unavailable: {e}")
            print("Falling back to Web Server mode on port 5000...")
            run_server(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)))
            sys.exit(0)

        # Start local API server in daemon thread so regular browsers can also connect
        srv_thread = threading.Thread(target=_start_background_api, daemon=True)
        srv_thread.start()
        try:
            run_desktop_app()
        except Exception as e:
            print(f"\n[INFO] Desktop display shell could not start ({e}).")
            print("Web server is already active in background. Keeping server running...")
            try:
                srv_thread.join()
            except KeyboardInterrupt:
                pass



