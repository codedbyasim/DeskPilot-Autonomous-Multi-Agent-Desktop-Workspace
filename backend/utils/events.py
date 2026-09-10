"""
DeskPilot — Event Dispatcher
Dispatches custom events from Python to the pywebview frontend.
"""

import json
from typing import Any, Optional
from backend.utils.logger import get_logger

logger = get_logger("events")
_active_window = None


def set_active_window(window):
    """Store pywebview window reference."""
    global _active_window
    _active_window = window


def get_active_window():
    return _active_window


_subscribers = []


def register_event_listener(listener_callback):
    """Register a callback that receives (event_name, payload) for SSE broadcasting."""
    if listener_callback not in _subscribers:
        _subscribers.append(listener_callback)


def unregister_event_listener(listener_callback):
    """Unregister an SSE callback."""
    if listener_callback in _subscribers:
        _subscribers.remove(listener_callback)


def emit_event(event_name: str, payload: Any) -> None:
    """
    Safely dispatches a CustomEvent to the webview window:
    window.dispatchEvent(new CustomEvent('event_name', { detail: payload }))
    and to any registered SSE/web listeners.
    """
    # 1. Notify external subscribers (e.g. SSE web server)
    for sub in list(_subscribers):
        try:
            sub(event_name, payload)
        except Exception as e:
            logger.warning(f"Subscriber notification failed: {e}")

    # 2. Dispatch to native pywebview window if active
    if _active_window is None:
        return

    # In headless unit testing where create_app_window was called without webview.start(),
    # _active_window.native is None. Only dispatch when native window handle exists.
    if getattr(_active_window, "native", None) is None:
        return

    try:
        data_json = json.dumps(payload, ensure_ascii=False)
        script = f"window.dispatchEvent(new CustomEvent('{event_name}', {{ detail: {data_json} }}));"
        if hasattr(_active_window, "run_js"):
            _active_window.run_js(script)
        else:
            _active_window.evaluate_js(script)
    except Exception as e:
        logger.warning(f"Failed to emit event '{event_name}' to frontend: {e}")

