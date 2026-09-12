"""
DeskPilot — Dynamic Runtime Form Engine
Manages interactive Human-in-the-Loop popup form requests between background agent threads
and the frontend desktop shell. Enables agents to pause execution, request custom onboarding
questionnaires or clarification fields from the user, and resume with structured answers.
"""

import uuid
import threading
from typing import Dict, Any, List, Optional
from backend.utils.events import emit_event
from backend.utils.user_memory import UserMemoryManager
from backend.utils.logger import get_logger

logger = get_logger("utils.form_engine")


class _PendingFormRequest:
    def __init__(
        self,
        form_id: str,
        title: str,
        description: str,
        fields: List[Dict[str, Any]],
        category: str,
        agent_id: Optional[str] = None
    ):
        self.form_id = form_id
        self.title = title
        self.description = description
        self.fields = fields
        self.category = category
        self.agent_id = agent_id
        self.event = threading.Event()
        self.result: Optional[Dict[str, Any]] = None
        self.cancelled = False


_forms_lock = threading.Lock()
_pending_forms: Dict[str, _PendingFormRequest] = {}


def request_user_form(
    title: str,
    description: str,
    fields: List[Dict[str, Any]],
    category: str = "general",
    agent_id: Optional[str] = None,
    timeout: int = 180
) -> str:
    """
    Creates an interactive form request, emits a dynamic form popup event to the frontend,
    and blocks the agent's calling thread until the user submits responses or cancels.

    Args:
        title: Title of the popup dialog (e.g. 'Personal Health Profile', 'Clarification')
        description: Friendly explanation for the user
        fields: List of field dictionaries ({ 'id', 'label', 'type', 'placeholder', 'options', 'required' })
        category: Category key to save answers under in local user memory
        agent_id: Identifier of the requesting agent
        timeout: Maximum seconds to wait (defaults to 180 seconds)

    Returns:
        String summary of the user's responses or cancellation status
    """
    form_id = f"form_{uuid.uuid4().hex[:10]}"

    # Sanitize fields: Ensure each field has required keys
    clean_fields = []
    for idx, f in enumerate(fields):
        if not isinstance(f, dict):
            continue
        field_id = str(f.get("id") or f.get("name") or f"field_{idx}").strip()
        field_label = str(f.get("label") or f.get("question") or field_id.replace("_", " ").title()).strip()
        field_type = str(f.get("type") or "text").lower().strip()
        if field_type not in ("text", "number", "textarea", "select", "radio", "checkbox"):
            field_type = "text"

        options = f.get("options") or []
        if isinstance(options, str):
            options = [opt.strip() for opt in options.split(",") if opt.strip()]

        clean_fields.append({
            "id": field_id,
            "label": field_label,
            "type": field_type,
            "placeholder": str(f.get("placeholder") or ""),
            "options": list(options),
            "required": bool(f.get("required", True)),
            "default": f.get("default", "")
        })

    req = _PendingFormRequest(form_id, title, description, clean_fields, category, agent_id)

    with _forms_lock:
        _pending_forms[form_id] = req

    logger.info(f"[{form_id}] Requesting user form '{title}' with {len(clean_fields)} fields for agent '{agent_id}'")

    # Dispatch event to frontend UI (both pywebview and SSE)
    payload = {
        "form_id": form_id,
        "title": title,
        "description": description,
        "fields": clean_fields,
        "category": category,
        "agent_id": agent_id or ""
    }
    emit_event("deskpilot:form_request", payload)

    # Block waiting for user interaction in modal
    responded = req.event.wait(timeout=timeout)

    with _forms_lock:
        _pending_forms.pop(form_id, None)

    if not responded:
        logger.warning(f"[{form_id}] Form request timed out after {timeout} seconds")
        return (
            "User did not submit the form within the time limit. "
            "Please proceed with best reasonable estimates or general recommendations, "
            "and note that the user can provide details at any time."
        )

    if req.cancelled:
        logger.info(f"[{form_id}] User chose to cancel/skip the form")
        return (
            "The user skipped or closed the questionnaire form. "
            "Proceed with general, safe, and helpful information without insisting on the form again."
        )

    # Process and save submitted data into local memory
    submitted_data = req.result or {}
    logger.info(f"[{form_id}] Received user form submission: {list(submitted_data.keys())}")

    saved_profile = UserMemoryManager.save_profile_data(category, submitted_data)

    # Format a rich summary for the LLM to use
    summary_lines = [
        f"SUCCESS: The user submitted their details through the interactive form ({title}).",
        "The responses have been saved to local memory for future sessions:\n"
    ]
    for k, v in submitted_data.items():
        clean_name = k.replace("_", " ").title()
        summary_lines.append(f"  • {clean_name}: {v}")

    summary_lines.append("\nNow proceed to fulfill the user's initial request using these exact personalized details.")
    return "\n".join(summary_lines)


def resolve_user_form(form_id: str, data: Optional[Dict[str, Any]] = None, cancelled: bool = False) -> bool:
    """
    Called from pywebview bridge or HTTP API when the user clicks 'Submit' or 'Skip/Cancel'.
    Unblocks the waiting agent execution thread.
    """
    with _forms_lock:
        req = _pending_forms.get(form_id)
        if not req:
            logger.warning(f"resolve_user_form: No pending form found with ID '{form_id}'")
            return False

        req.result = data or {}
        req.cancelled = cancelled
        req.event.set()
        return True


def get_pending_form_ids() -> List[str]:
    """Returns all currently active form IDs awaiting user response."""
    with _forms_lock:
        return list(_pending_forms.keys())
