"""
DeskPilot — Local Web Server & REST/SSE API
Allows DeskPilot to run in standard web browsers (Chrome, Edge, Firefox)
with full access to Python agents, Amazon Bedrock, local tools, and file generation.
"""

import sys
import os
import json
import time
import queue
from pathlib import Path
from typing import Generator, Optional

# Ensure project root is on sys.path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS

from backend.bridge import DeskPilotBridge
from backend.config.settings import FRONTEND_DIR, APP_NAME, APP_VERSION
from backend.utils.events import register_event_listener, unregister_event_listener
from backend.utils.logger import get_logger

logger = get_logger("server")

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)

bridge = DeskPilotBridge()

# Active SSE listener queues
_sse_clients = []


def _on_backend_event(event_name: str, payload: dict):
    """Callback hooked into backend.utils.events.emit_event."""
    data = json.dumps({"event": event_name, "detail": payload}, ensure_ascii=False)
    message = f"data: {data}\n\n"
    for q in list(_sse_clients):
        try:
            q.put_nowait(message)
        except Exception:
            pass


register_event_listener(_on_backend_event)


# ── Static File Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(FRONTEND_DIR), filename)


# ── Server-Sent Events (Real-time streaming) ──────────────────────────────────

@app.route("/api/events")
def sse_events():
    client_queue = queue.Queue(maxsize=100)
    _sse_clients.append(client_queue)

    def event_stream() -> Generator[str, None, None]:
        # Send initial connected ping
        yield f"data: {json.dumps({'event': 'deskpilot:connected', 'detail': {'status': 'ready'}})}\n\n"
        try:
            while True:
                try:
                    msg = client_queue.get(timeout=15.0)
                    yield msg
                except queue.Empty:
                    # Heartbeat comment to prevent client timeout
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            if client_queue in _sse_clients:
                _sse_clients.remove(client_queue)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(bridge.get_system_status())


@app.route("/api/agents", methods=["GET"])
def get_agents():
    return jsonify(bridge.get_agents())


@app.route("/api/agent/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    agent = bridge.get_agent(agent_id)
    if agent:
        return jsonify(agent)
    return jsonify({"error": "Agent not found"}), 404


@app.route("/api/templates", methods=["GET"])
def get_templates():
    return jsonify(bridge.get_template_agents())


@app.route("/api/task/run", methods=["POST"])
def run_task():
    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    instruction = data.get("instruction")
    if not agent_id or not instruction:
        return jsonify({"success": False, "error": "Missing agent_id or instruction"}), 400
    res = bridge.run_agent_task(agent_id, instruction)
    return jsonify(res)


@app.route("/api/task/stop", methods=["POST"])
def stop_task():
    data = request.get_json() or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "error": "Missing task_id"}), 400
    res = bridge.stop_agent_task(task_id)
    return jsonify(res)


@app.route("/api/tasks", methods=["GET"])
def get_tasks_route():
    return jsonify(bridge.get_tasks())



@app.route("/api/approval", methods=["POST"])
def respond_approval():
    data = request.get_json() or {}
    request_id = data.get("request_id")
    approved = bool(data.get("approved"))
    approve_all = bool(data.get("approve_all", False))
    if not request_id:
        return jsonify({"success": False, "error": "Missing request_id"}), 400
    res = bridge.respond_to_approval(request_id, approved, approve_all=approve_all)
    return jsonify(res)


@app.route("/api/draft", methods=["POST"])
def create_draft():
    data = request.get_json() or {}
    desc = data.get("description", "")
    res = bridge.create_agent_draft(desc)
    return jsonify(res)


@app.route("/api/agent/create", methods=["POST"])
def confirm_agent():
    data = request.get_json() or {}
    draft = data.get("draft")
    if not draft:
        return jsonify({"success": False, "error": "Missing draft"}), 400
    res = bridge.confirm_create_agent(draft)
    return jsonify(res)


@app.route("/api/agent/<agent_id>", methods=["DELETE"])
def delete_agent(agent_id):
    res = bridge.delete_custom_agent(agent_id)
    return jsonify(res)


@app.route("/api/activity", methods=["GET"])
def get_activity():
    limit = int(request.args.get("limit", 10))
    return jsonify(bridge.get_recent_activity(limit))


@app.route("/api/audit", methods=["GET"])
def get_audit():
    agent_id = request.args.get("agent_id")
    return jsonify(bridge.get_audit_history(agent_id))


@app.route("/api/open_file", methods=["POST"])
def open_file_route():
    data = request.get_json() or {}
    path = data.get("file_path", "")
    res = bridge.open_deliverable(path)
    return jsonify(res)


@app.route("/api/open_folder", methods=["POST"])
def open_folder_route():
    data = request.get_json() or {}
    path = data.get("file_path", "")
    res = bridge.open_file_location(path)
    return jsonify(res)


@app.route("/api/winget/status", methods=["GET"])
def winget_status():
    return jsonify(bridge.check_winget_installed())


@app.route("/api/winget/allowlist", methods=["GET"])
def winget_allowlist():
    return jsonify(bridge.get_winget_allowlist())


@app.route("/api/tools_metadata", methods=["GET"])
def get_tools_metadata():
    return jsonify(bridge.get_available_tools_metadata())


@app.route("/api/system/storage", methods=["GET"])
def get_system_storage_route():
    return jsonify(bridge.get_storage_summary())


@app.route("/api/system/diagnostics", methods=["GET"])
def get_system_diagnostics_route():
    return jsonify(bridge.get_system_diagnostics_summary())


# ── Interactive Dynamic Form & User Profile Endpoints ────────────────────────

@app.route("/api/user/form-submit", methods=["POST"])
def submit_user_form_route():
    data = request.get_json() or {}
    form_id = data.get("form_id", "")
    form_data = data.get("data", {})
    cancelled = bool(data.get("cancelled", False))
    res = bridge.submit_user_form(form_id, form_data, cancelled=cancelled)
    return jsonify(res)


@app.route("/api/user/profile", methods=["GET"])
def get_user_profile_route():
    category = request.args.get("category", "all")
    if category == "all":
        return jsonify(bridge.get_all_user_profiles())
    return jsonify(bridge.get_user_profile(category))




# ── Chat Session Endpoints ────────────────────────────────────────────────────

@app.route("/api/chat/sessions", methods=["GET"])
def list_chat_sessions():
    return jsonify(bridge.get_chat_sessions())


@app.route("/api/chat/session/<session_id>", methods=["GET"])
def get_chat_session(session_id):
    session = bridge.get_chat_session(session_id)
    if session:
        return jsonify(session)
    return jsonify({"error": "Session not found"}), 404


@app.route("/api/chat/session", methods=["POST"])
def create_chat_session():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "personal_assistant")
    title = data.get("title")
    res = bridge.create_chat_session(agent_id, title)
    return jsonify(res)


@app.route("/api/chat/session/<session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    success = bridge.delete_chat_session(session_id)
    return jsonify({"success": success})


@app.route("/api/chat/message", methods=["POST"])
def send_chat_message():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    message = data.get("message")
    if not session_id or not message:
        return jsonify({"success": False, "error": "Missing session_id or message"}), 400
    res = bridge.send_chat_message(session_id, message)
    return jsonify(res)


# ── Save Location Preferences Endpoints ───────────────────────────────────────

@app.route("/api/settings/save-preferences", methods=["GET"])
def get_save_preferences_endpoint():
    return jsonify(bridge.get_save_preferences())


@app.route("/api/settings/save-preferences", methods=["POST"])
def set_save_preferences_endpoint():
    data = request.get_json() or {}
    save_location = data.get("save_location", "Desktop")
    always_save = data.get("always_save", True)
    custom_path = data.get("custom_path", "")
    res = bridge.set_save_preferences(save_location, always_save, custom_path)
    return jsonify(res)


# ── Server Runner ─────────────────────────────────────────────────────────────

def run_server(host: Optional[str] = None, port: Optional[int] = None):
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", 5000))
    logger.info(f"Starting DeskPilot Web API Server at http://{host}:{port}")
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"\n========================================================")
    print(f"🚀 DeskPilot Web Server running at: http://localhost:{port}")
    print(f"   Connecting Amazon Bedrock with Autonomous Desktop Tools")
    print(f"========================================================\n")
    if "--open" in sys.argv:
        webbrowser.open(f"http://localhost:{port}")
    run_server(port=port)
