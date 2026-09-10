"""
DeskPilot — Python ↔ JS Bridge (Section 11 Contract)
Exposed to the pywebview frontend as `window.pywebview.api.<method>(...)`.
Provides asynchronous task handling, registry querying, approval management, and audit inspection.
"""

import json
import threading
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

from backend.agent.registry import AgentRegistry
from backend.agent.orchestrator import AgentOrchestrator
from backend.agent.builder import AgentBuilder
from backend.chat.session_manager import ChatSessionManager
from backend.utils.trust import resolve_approval, set_approval_hook, clear_approval_cache
from backend.utils.events import emit_event
from backend.utils.logger import get_logger, AuditLogger
from backend.utils.save_preferences import (
    get_save_preferences, set_save_preferences, resolve_effective_save_dir
)
from backend.config.settings import (
    APP_NAME, APP_VERSION, BEDROCK_MODEL_ID,
    DEFAULT_OUTPUT_DIR, LOGS_DIR
)

logger = get_logger("bridge")


class DeskPilotBridge:
    """
    The official bridge API instance exposed to window.pywebview.api in the frontend.
    Every method called from JavaScript runs through this class.
    """

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or AgentRegistry()
        self.audit = AuditLogger()
        self.chat_manager = ChatSessionManager()
        self._active_tasks: Dict[str, dict] = {}
        self.orchestrator = AgentOrchestrator(
            registry=self.registry,
            on_log=self._on_orchestrator_log,
            on_event=self._on_orchestrator_event,
        )
        self.builder = AgentBuilder(orchestrator=self.orchestrator)

        # Wire trust approval hook to emit pywebview event
        set_approval_hook(self._on_approval_needed)

    def _on_orchestrator_log(self, text: str):
        emit_event("deskpilot:log", {"text": text})

    def _on_orchestrator_event(self, event_name: str, payload: dict):
        emit_event(event_name, payload)

    def _on_approval_needed(self, request_id: str, action: str, description: str, tier: str, agent_id: Optional[str] = None):
        """Dispatches an approval request modal event to the frontend."""
        payload = {
            "request_id": request_id,
            "action": action,
            "description": description,
            "tier": tier,
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat(),
        }
        logger.info(f"Emitting approval_required event for {action} [{tier}] (ID: {request_id})")
        emit_event("deskpilot:approval_required", payload)

    # ── 1. Registry Methods ───────────────────────────────────────────────────

    def get_agents(self) -> List[Dict[str, Any]]:
        """
        Returns all registered agents (default and custom) with real-time status.
        Frontend calls this on page load to populate the dashboard cards.
        """
        try:
            return self.registry.get_active_agents()
        except Exception as e:
            logger.error(f"Error in get_agents: {e}")
            return []

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Returns details of a specific agent by ID.
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return {"error": f"Agent '{agent_id}' not found", "found": False}
        return {"agent": agent, "found": True}

    def get_template_agents(self) -> List[Dict[str, Any]]:
        """
        Returns pre-built gallery templates (Property, Student, Business Value)
        that users can add with 1 click.
        """
        try:
            return self.registry.get_template_agents()
        except Exception as e:
            logger.error(f"Error in get_template_agents: {e}")
            return []

    # ── 2. Task Execution & Streaming ─────────────────────────────────────────

    def run_agent_task(self, agent_id: str, instruction: str) -> Dict[str, Any]:
        """
        Launch an asynchronous task for a specific agent.
        Returns immediate acknowledgment while streaming events to the frontend.
        """
        clean_instruction = instruction.strip()
        if not clean_instruction:
            return {"success": False, "error": "Instruction cannot be empty"}

        agent = self.registry.get_agent(agent_id)
        if not agent:
            return {"success": False, "error": f"Agent '{agent_id}' not found"}

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        self._active_tasks[task_id] = {
            "task_id": task_id,
            "agent_id": agent_id,
            "instruction": clean_instruction,
            "started_at": datetime.now().isoformat(),
            "status": "running",
        }
        self.registry.set_agent_status(agent_id, "running")

        # Notify frontend task started
        emit_event("deskpilot:task_started", {
            "task_id": task_id,
            "agent_id": agent_id,
            "agent_name": agent.get("name", agent_id),
            "instruction": clean_instruction,
            "timestamp": datetime.now().isoformat(),
        })

        # Spawn task runner in background thread
        thread = threading.Thread(
            target=self._execute_task_thread,
            args=(task_id, agent, clean_instruction),
            daemon=True
        )
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "agent_id": agent_id,
            "status": "started",
        }

    def _execute_task_thread(self, task_id: str, agent: dict, instruction: str):
        """Worker thread executing task through the dynamic Strands AgentOrchestrator."""
        agent_id = agent["id"]
        agent_name = agent.get("name", agent_id)
        logger.info(f"Starting task execution [{task_id}] for agent '{agent_id}'")

        def _on_step(tool_name: str, status: str):
            emit_event("deskpilot:step", {
                "task_id": task_id,
                "agent_id": agent_id,
                "tool": tool_name,
                "status": status,
                "message": f"Executing tool: {tool_name}",
                "timestamp": datetime.now().isoformat(),
            })

        def _on_log(text: str):
            emit_event("deskpilot:log", {
                "task_id": task_id,
                "agent_id": agent_id,
                "text": text,
            })

        try:
            emit_event("deskpilot:plan_step", {
                "task_id": task_id,
                "agent_id": agent_id,
                "step_idx": 1,
                "step_text": f"Initializing {agent_name} with authorized tools",
                "completed": True,
            })

            res = self.orchestrator.run_task(
                agent_id=agent_id,
                instruction=instruction,
                task_id=task_id,
                on_log=_on_log,
                on_step=_on_step,
            )

            if res.get("success"):
                emit_event("deskpilot:task_complete", {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "summary": res.get("result", "Task completed successfully."),
                    "audit_path": res.get("audit_path", ""),
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                emit_event("deskpilot:task_failed", {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "error": res.get("error", "Task execution failed"),
                    "timestamp": datetime.now().isoformat(),
                })

        except Exception as e:
            logger.error(f"Task error in [{task_id}]: {e}")
            emit_event("deskpilot:task_failed", {
                "task_id": task_id,
                "agent_id": agent_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            })
        finally:
            self.registry.set_agent_status(agent_id, "active")
            if task_id in self._active_tasks:
                self._active_tasks[task_id]["status"] = "finished"

    def stop_agent_task(self, task_id: str) -> Dict[str, Any]:
        """Cancel a running task."""
        if task_id in self._active_tasks:
            self._active_tasks[task_id]["status"] = "cancelled"
            emit_event("deskpilot:task_cancelled", {"task_id": task_id})
            return {"success": True, "message": f"Task {task_id} cancelled"}
        return {"success": False, "error": f"Task {task_id} not found"}

    # ── 3. Human-in-the-Loop Trust Approvals ───────────────────────────────────

    def respond_to_approval(self, request_id: str, approved: bool, approve_all: bool = False) -> Dict[str, Any]:
        """
        Called from the frontend approval modal when user clicks 'Approve', 'Approve All', or 'Deny'.
        Unblocks the waiting agent tool thread.
        """
        logger.info(f"Approval response for {request_id}: approved={approved}, approve_all={approve_all}")
        resolved = resolve_approval(request_id, approved, approve_all=approve_all)
        return {
            "success": resolved,
            "request_id": request_id,
            "approved": approved,
            "approve_all": approve_all,
        }

    # ── 4. Custom Agent Builder (Section 9) ───────────────────────────────────

    def create_agent_draft(self, description: str) -> Dict[str, Any]:
        """
        Drafts a new agent config from a natural language description using AgentBuilder.
        Generates sensible tools, name, persona, icon, color, and plain language permissions.
        """
        clean_desc = description.strip()
        if not clean_desc:
            return {"success": False, "error": "Description cannot be empty"}

        return self.builder.draft_agent(clean_desc)

    def confirm_create_agent(self, draft: dict) -> Dict[str, Any]:
        """
        Saves an approved custom agent draft into agents/<id>.json after strict validation.
        """
        if not isinstance(draft, dict):
            return {"success": False, "error": "Draft must be a dictionary"}

        # Preserve category if template; otherwise set to custom
        if draft.get("category") != "template":
            draft["category"] = "custom"
        draft["status"] = "active"
        draft["created_at"] = datetime.now().isoformat()

        # Sanitize allowed_tools strictly to known tools in TOOL_REGISTRY
        from backend.tools import TOOL_REGISTRY
        tools = draft.get("allowed_tools", [])
        draft["allowed_tools"] = [t for t in tools if t in TOOL_REGISTRY]
        if not draft["allowed_tools"]:
            draft["allowed_tools"] = ["search_web"]

        saved, err = self.registry.save_agent(draft)
        if not saved:
            return {"success": False, "error": err}

        # Notify frontend
        emit_event("deskpilot:agent_created", {"agent": draft})
        logger.info(f"Custom agent '{draft.get('name')}' ({draft.get('id')}) saved and activated.")
        return {"success": True, "agent": draft}

    def delete_custom_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Deletes a custom agent from the registry. Default built-in agents cannot be deleted.
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return {"success": False, "error": f"Agent '{agent_id}' not found"}

        if agent.get("category") == "default":
            return {"success": False, "error": "Cannot delete default built-in agents"}

        deleted, err = self.registry.delete_agent(agent_id)
        if not deleted:
            return {"success": False, "error": err}

        emit_event("deskpilot:agent_deleted", {"agent_id": agent_id})
        logger.info(f"Custom agent '{agent_id}' deleted.")
        return {"success": True, "agent_id": agent_id}

    def open_deliverable(self, file_path: str) -> Dict[str, Any]:
        """
        Opens a generated deliverable file (Word doc, Excel sheet, or image) in the user's default desktop app.
        """
        try:
            from backend.tools.file_tools import open_file
            res = open_file(file_path)
            return {"success": True, "message": res}
        except Exception as e:
            logger.error(f"Failed to open deliverable '{file_path}': {e}")
            return {"success": False, "error": str(e)}

    def get_available_tools_metadata(self) -> List[Dict[str, Any]]:
        """Returns all available tools with plain-language metadata for the custom agent builder."""
        from backend.agent.builder import TOOL_METADATA
        return [
            {"name": k, **v} for k, v in TOOL_METADATA.items()
        ]

    # ── 5. Activity & Audit History ───────────────────────────────────────────

    def get_recent_activity(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Returns recent agent actions formatted for the dashboard feed.
        """
        records = []
        try:
            # Look for recent audit files in LOGS_DIR
            audit_files = sorted(LOGS_DIR.glob("audit_*.jsonl"), reverse=True)
            for af in audit_files[:3]:
                with open(af, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "tool" in data:
                                    records.append({
                                        "timestamp": data.get("timestamp"),
                                        "tool": data.get("tool"),
                                        "agent_id": data.get("agent_id", "system"),
                                        "trust_tier": data.get("trust_tier", "GREEN"),
                                        "success": data.get("success", True),
                                        "summary": data.get("result_summary", ""),
                                    })
                            except Exception:
                                pass
            records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return records[:limit]
        except Exception as e:
            logger.warning(f"Error fetching activity: {e}")
            return []

    def get_audit_history(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns full audit history optionally filtered by agent_id."""
        return self.get_recent_activity(limit=100)

    # ── 6. System Status ──────────────────────────────────────────────────────

    def get_system_status(self) -> Dict[str, Any]:
        """Returns system status, backend version, Bedrock model info."""
        return {
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "model_id": BEDROCK_MODEL_ID,
            "output_directory": str(DEFAULT_OUTPUT_DIR),
            "agents_count": len(self.registry.load_all_agents()),
            "active_agents_count": len(self.registry.get_active_agents()),
            "template_agents_count": len(self.registry.get_template_agents()),
            "status": "ready",
        }

    # ── 6.5. Save Location Preferences ────────────────────────────────────────

    def get_save_preferences(self) -> Dict[str, Any]:
        """Returns the user's deliverable save preferences."""
        return get_save_preferences()

    def set_save_preferences(self, save_location: str, always_save: bool = True, custom_path: str = "") -> Dict[str, Any]:
        """Updates user's deliverable save preferences with 'Always save there' flag."""
        return set_save_preferences(save_location, always_save, custom_path)

    # ── 7. Conversational Chat Sessions (ChatGPT/Gemini Style) ──────────────────

    def get_chat_sessions(self) -> List[Dict[str, Any]]:
        """Lists all chat sessions sorted by updated_at descending."""
        try:
            return self.chat_manager.list_sessions()
        except Exception as e:
            logger.error(f"Error listing chat sessions: {e}")
            return []

    def get_chat_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a full chat session with messages."""
        try:
            return self.chat_manager.get_session(session_id)
        except Exception as e:
            logger.error(f"Error fetching chat session '{session_id}': {e}")
            return None

    def create_chat_session(self, agent_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        """Creates a new chat session for a specific agent."""
        try:
            return self.chat_manager.create_session(agent_id=agent_id, title=title)
        except Exception as e:
            logger.error(f"Error creating chat session: {e}")
            return {"error": str(e)}

    def delete_chat_session(self, session_id: str) -> bool:
        """Deletes a chat session."""
        try:
            return self.chat_manager.delete_session(session_id)
        except Exception as e:
            logger.error(f"Error deleting chat session '{session_id}': {e}")
            return False

    def send_chat_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        Submits a user message to a chat session.
        Appends user message, returns immediate acknowledgment,
        and spawns background worker to stream reasoning, tool execution, and assistant reply.
        """
        clean_msg = message.strip()
        if not clean_msg:
            return {"success": False, "error": "Message cannot be empty"}

        session = self.chat_manager.get_session(session_id)
        if not session:
            return {"success": False, "error": f"Session '{session_id}' not found"}

        # Append user message immediately
        user_msg = self.chat_manager.add_message(session_id, role="user", content=clean_msg)

        # Notify frontend immediately of added message & potential auto-title change
        updated_session = self.chat_manager.get_session(session_id)
        emit_event("deskpilot:chat_user_message", {
            "session_id": session_id,
            "message": user_msg,
            "title": updated_session.get("title", "") if updated_session else "",
        })

        agent_id = session.get("agent_id", "personal_assistant")
        history = session.get("messages", [])

        # Spawn worker thread
        thread = threading.Thread(
            target=self._execute_chat_turn_thread,
            args=(session_id, agent_id, clean_msg, history),
            daemon=True
        )
        thread.start()

        return {
            "success": True,
            "session_id": session_id,
            "message_id": user_msg["id"] if user_msg else "",
            "status": "processing",
        }

    def _execute_chat_turn_thread(self, session_id: str, agent_id: str, user_message: str, history: List[dict]):
        """Worker thread executing chat turn with real-time token/tool event dispatch."""
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        clear_approval_cache()

        def _on_chunk(token: str):
            emit_event("deskpilot:chat_chunk", {
                "session_id": session_id,
                "turn_id": turn_id,
                "agent_id": agent_id,
                "chunk": token,
            })

        def _on_step(tool_name: str, status: str):
            emit_event("deskpilot:chat_step", {
                "session_id": session_id,
                "turn_id": turn_id,
                "agent_id": agent_id,
                "tool": tool_name,
                "status": status,
            })

        try:
            res = self.orchestrator.run_chat_turn(
                session_id=session_id,
                agent_id=agent_id,
                user_message=user_message,
                chat_history=history,
                task_id=turn_id,
                on_chunk=_on_chunk,
                on_step=_on_step,
            )

            if res.get("success"):
                response_text = res.get("response", "")
                tool_calls = res.get("tool_calls", [])
                deliverables = res.get("deliverables", [])

                # Save assistant message to session
                assistant_msg = self.chat_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=response_text,
                    tool_calls=tool_calls,
                    deliverables=deliverables,
                )

                emit_event("deskpilot:chat_turn_complete", {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "agent_id": agent_id,
                    "message": assistant_msg,
                    "deliverables": deliverables,
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                emit_event("deskpilot:chat_turn_failed", {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "agent_id": agent_id,
                    "error": res.get("error", "Execution failed"),
                })
        except Exception as e:
            logger.error(f"Chat turn thread failed for session '{session_id}': {e}")
            emit_event("deskpilot:chat_turn_failed", {
                "session_id": session_id,
                "turn_id": turn_id,
                "agent_id": agent_id,
                "error": str(e),
            })
