"""
DeskPilot — Trust Tier Classifier & Approval Engine
Classifies every agent action into Green / Yellow / Red autonomy tiers
and manages asynchronous Human-in-the-Loop approval requests across pywebview.
"""

import threading
import uuid
from typing import Optional, Dict
from backend.config.settings import GREEN_ACTIONS, YELLOW_ACTIONS, RED_ACTIONS, WINGET_ALLOWLIST


class TrustTier:
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# Alias for backward compatibility
TrustTierClassifier = TrustTier


def classify_action(tool_name: str, params: Optional[Dict] = None) -> str:
    """
    Returns the trust tier for a given tool/action name.

    GREEN  → executes automatically, no user approval needed
    YELLOW → pauses and asks user for confirmation before executing
    RED    → always requires explicit user approval, never auto-executes
    """
    name = tool_name.lower().strip()

    # Software installation is ALWAYS Red-tier (PROJECT_BRIEF Section 10 & 13)
    if "install" in name or "winget" in name or name == "install_software":
        return TrustTier.RED

    if name in ("run_shell_command", "system_execute"):
        return TrustTier.RED

    if name in GREEN_ACTIONS:
        return TrustTier.GREEN
    if name in YELLOW_ACTIONS:
        return TrustTier.YELLOW
    if name in RED_ACTIONS:
        return TrustTier.RED
    return TrustTier.YELLOW


def tier_display(tier: str) -> str:
    labels = {
        TrustTier.GREEN: "🟢 Auto",
        TrustTier.YELLOW: "🟡 Confirm",
        TrustTier.RED: "🔴 Approval Required",
    }
    return labels.get(tier, "🟡 Confirm")


def needs_approval(tier: str) -> bool:
    return tier in (TrustTier.YELLOW, TrustTier.RED)


# ── Pending Approval Registry for Python ↔ Frontend Bridge ──────────────────
class _PendingRequest:
    def __init__(self, request_id: str, action: str, description: str, tier: str, agent_id: Optional[str] = None):
        self.request_id = request_id
        self.action = action
        self.description = description
        self.tier = tier
        self.agent_id = agent_id
        self.event = threading.Event()
        self.approved = False
        self.approve_all = False


_pending_lock = threading.Lock()
_pending_requests: Dict[str, _PendingRequest] = {}
_approved_actions_cache: set = set()
_external_approval_hook = None


def set_approval_hook(hook):
    """
    Set a hook function: hook(request_id, action, description, tier, agent_id)
    Usually emits an event to the pywebview frontend.
    """
    global _external_approval_hook
    _external_approval_hook = hook


def clear_approval_cache():
    """Clears cached action approvals, e.g., when a new task or chat turn begins."""
    with _pending_lock:
        _approved_actions_cache.clear()


def request_approval(
    action_name: str,
    description: str,
    tier: Optional[str] = None,
    agent_id: Optional[str] = None
) -> bool:
    """
    Checks trust tier. If Yellow or Red, creates a pending request,
    notifies the frontend, and blocks the calling agent thread until the user responds.
    """
    actual_tier = tier or classify_action(action_name)
    if not needs_approval(actual_tier):
        return True

    # Check if this action was already granted 'Approve All' for the active operation
    with _pending_lock:
        if action_name in _approved_actions_cache:
            return True

    request_id = f"req_{uuid.uuid4().hex[:12]}"
    req = _PendingRequest(request_id, action_name, description, actual_tier, agent_id)

    with _pending_lock:
        _pending_requests[request_id] = req

    # Notify frontend via hook with actual_tier
    if _external_approval_hook:
        try:
            _external_approval_hook(request_id, action_name, description, actual_tier, agent_id)
        except Exception:
            pass

    # Wait for user response (timeout after 120s to prevent freezing indefinitely)
    responded = req.event.wait(timeout=120)

    with _pending_lock:
        _pending_requests.pop(request_id, None)

    return req.approved if responded else False


def resolve_approval(request_id: str, approved: bool, approve_all: bool = False) -> bool:
    """
    Called from pywebview/server bridge when user clicks Approve, Approve All, or Deny.
    Unblocks the waiting agent thread.
    """
    with _pending_lock:
        req = _pending_requests.get(request_id)
        if not req:
            return False
        req.approved = approved
        req.approve_all = approve_all
        if approved and approve_all:
            _approved_actions_cache.add(req.action)
        req.event.set()
        return True
