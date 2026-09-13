"""
DeskPilot — Desktop Application Entry Point (pywebview Shell)
Launches the native Windows WebView2 desktop window hosting the local frontend.
"""

import sys
import os
from pathlib import Path

# Ensure project root is on sys.path so script can be run directly as `python backend/app.py`
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import webview

from backend.config.settings import APP_NAME, APP_TAGLINE, APP_VERSION, FRONTEND_DIR
from backend.bridge import DeskPilotBridge
from backend.utils.events import set_active_window
from backend.utils.logger import get_logger

logger = get_logger("app")


def create_app_window(dev: bool = False):
    """
    Initializes the DeskPilot bridge, registers the active window, and returns the window instance.
    """
    logger.info(f"Initializing {APP_NAME} v{APP_VERSION} desktop shell...")

    bridge = DeskPilotBridge()
    index_file = FRONTEND_DIR / "index.html"

    if not index_file.exists():
        logger.error(f"Frontend index.html not found at: {index_file}")
        raise FileNotFoundError(f"Missing frontend at {index_file}")

    window = webview.create_window(
        title=f"{APP_NAME} — {APP_TAGLINE}",
        url=str(index_file.resolve().as_uri()),
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(420, 500),
        background_color="#0F172A",
    )

    set_active_window(window)
    return window


def main():
    is_dev = "--dev" in sys.argv or "-d" in sys.argv
    window = create_app_window(dev=is_dev)
    webview.start(debug=is_dev)


if __name__ == "__main__":
    main()
