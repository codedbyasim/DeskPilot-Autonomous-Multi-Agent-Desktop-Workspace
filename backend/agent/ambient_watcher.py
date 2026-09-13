"""
DeskPilot — Proactive Ambient Watcher Engine
Runs continuously in the background on a daemon thread.
Periodically sweeps the desktop workspace for clutter, disk bloat, and incoming documents.
Pings the user ONLY when a human decision is required (Yellow/Red tier),
offering 1-click execution while executing Green tier inspections silently.
"""

import os
import sys
import time
import uuid
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable

from backend.utils.events import emit_event
from backend.utils.logger import get_logger

logger = get_logger("agent.ambient")


def send_windows_notification(title: str, message: str) -> bool:
    """
    Sends a native Windows Toast notification if running on Windows.
    Uses PowerShell Windows.UI.Notifications with zero third-party dependencies.
    """
    if sys.platform != "win32":
        return False

    # Sanitize inputs for PowerShell
    clean_title = title.replace('"', '`"').replace("'", "''")
    clean_msg = message.replace('"', '`"').replace("'", "''")

    ps_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $toastXml = [xml]$template.GetXml()
    $textNodes = $toastXml.GetElementsByTagName("text")
    $textNodes.Item(0).AppendChild($toastXml.CreateTextNode("{clean_title}")) > $null
    $textNodes.Item(1).AppendChild($toastXml.CreateTextNode("{clean_msg}")) > $null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($toastXml)
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("DeskPilot")
    $notifier.Show($toast)
    """

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        logger.debug(f"Native Windows notification skipped: {e}")
        return False


class AmbientWatcher:
    """
    Proactive Autonomous Agent Daemon for DeskPilot.
    Runs continuous background cycles inspecting the workspace and system state.
    """

    _instance = None

    @classmethod
    def get_instance(cls, orchestrator=None):
        if cls._instance is None:
            cls._instance = cls(orchestrator=orchestrator)
        elif orchestrator is not None and cls._instance.orchestrator is None:
            cls._instance.orchestrator = orchestrator
        return cls._instance

    def __init__(self, orchestrator=None, interval_seconds: int = 60):
        self.orchestrator = orchestrator
        self.interval_seconds = interval_seconds
        self.enabled = True
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State tracking & cooldowns
        self.last_sweep_time: Optional[str] = None
        self.last_pings: Dict[str, datetime] = {}
        self.cooldown_minutes = 15  # Avoid ping spam for the same issue

        # Pending proactive decisions awaiting user confirmation
        self.pending_decisions: Dict[str, Dict[str, Any]] = {}

        # Configurable thresholds
        self.desktop_clutter_threshold = 5  # Files
        self.temp_junk_threshold_mb = 400   # MB
        self.disk_usage_threshold_pct = 90  # %

    def start(self):
        """Starts the ambient watcher daemon thread."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._thread = threading.Thread(target=self._ambient_loop, daemon=True, name="DeskPilot-AmbientWatcher")
            self._thread.start()
            logger.info("Ambient Watcher Daemon started in background.")

    def stop(self):
        """Stops the ambient watcher daemon."""
        with self._lock:
            self.is_running = False
            logger.info("Ambient Watcher Daemon requested to stop.")

    def toggle(self, enabled: bool) -> bool:
        """Enables or pauses the ambient sweeps."""
        self.enabled = enabled
        logger.info(f"Ambient Watcher enabled state set to: {self.enabled}")
        emit_event("deskpilot:ambient_status", self.get_status())
        return self.enabled

    def get_status(self) -> Dict[str, Any]:
        """Returns the current ambient watcher operational status."""
        return {
            "is_running": self.is_running,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "last_sweep_time": self.last_sweep_time,
            "pending_decisions_count": len(self.pending_decisions),
            "pending_decisions": list(self.pending_decisions.values()),
        }

    def _ambient_loop(self):
        """Continuous background sweep execution loop."""
        # Initial wait of 10 seconds after boot to let app settle
        time.sleep(10)

        while self.is_running:
            if self.enabled:
                try:
                    self.perform_sweep()
                except Exception as e:
                    logger.error(f"Error during ambient sweep: {e}")

            # Sleep in 1-second chunks so stopping is responsive
            for _ in range(self.interval_seconds):
                if not self.is_running:
                    break
                time.sleep(1)

    def perform_sweep(self) -> List[Dict[str, Any]]:
        """
        Executes a single sweep across Desktop, Temp cache, and incoming files.
        Returns a list of generated decision pings (if any).
        """
        self.last_sweep_time = datetime.now().isoformat()
        generated_pings = []

        # 1. Inspect Desktop Clutter (Loose unorganized files)
        clutter_ping = self._check_desktop_clutter()
        if clutter_ping:
            generated_pings.append(clutter_ping)

        # 2. Inspect Temp Cache / Junk Accumulation
        junk_ping = self._check_temporary_junk()
        if junk_ping:
            generated_pings.append(junk_ping)

        # 3. Inspect Incoming PDF Invoices / Receipts
        invoice_ping = self._check_incoming_invoices()
        if invoice_ping:
            generated_pings.append(invoice_ping)

        # Broadcast ambient pulse
        emit_event("deskpilot:ambient_pulse", {
            "timestamp": self.last_sweep_time,
            "pings_count": len(generated_pings),
        })

        return generated_pings

    def _can_ping(self, issue_key: str) -> bool:
        """Enforces a 15-minute cooldown to protect user from interruption spam."""
        if issue_key not in self.last_pings:
            return True
        elapsed = datetime.now() - self.last_pings[issue_key]
        return elapsed > timedelta(minutes=self.cooldown_minutes)

    def _check_desktop_clutter(self) -> Optional[Dict[str, Any]]:
        """Detects if loose files have accumulated on the user's Desktop."""
        desktop_path = Path.home() / "Desktop"
        if not desktop_path.exists() or not desktop_path.is_dir():
            return None

        # Exclude system files and subfolders
        loose_files = []
        ignored = {"desktop.ini", "thumbs.db", ".ds_store"}
        for item in desktop_path.iterdir():
            if item.is_file() and not item.name.startswith(".") and item.name.lower() not in ignored:
                loose_files.append(item.name)

        count = len(loose_files)
        if count >= self.desktop_clutter_threshold:
            issue_key = "desktop_clutter"
            if not self._can_ping(issue_key):
                return None

            ping_id = f"ping_clutter_{uuid.uuid4().hex[:6]}"
            preview = ", ".join(loose_files[:4]) + (f" and {count - 4} more" if count > 4 else "")

            decision = {
                "id": ping_id,
                "type": "desktop_clutter",
                "severity": "yellow",
                "agent_id": "personal_assistant",
                "agent_name": "Personal Assistant",
                "title": "Desktop Organization Suggested",
                "message": f"I noticed {count} loose files on your Desktop ({preview}). Would you like me to organize them into categorized subfolders?",
                "action_text": "Organize Desktop Files",
                "instruction": f"Organize all loose files on the Desktop into categorized folders.",
                "item_count": count,
                "created_at": datetime.now().isoformat(),
            }

            self.pending_decisions[ping_id] = decision
            self.last_pings[issue_key] = datetime.now()
            self._dispatch_proactive_ping(decision)
            return decision

        return None

    def _check_temporary_junk(self) -> Optional[Dict[str, Any]]:
        """Detects if the system temporary cache has ballooned."""
        temp_dir = Path(tempfile.gettempdir())
        if not temp_dir.exists():
            return None

        total_bytes = 0
        file_count = 0
        try:
            for item in temp_dir.glob("tmp*"):
                if item.is_file():
                    total_bytes += item.stat().st_size
                    file_count += 1
                if file_count > 500:  # Cap scan to remain lightweight
                    break
        except Exception:
            pass

        total_mb = round(total_bytes / (1024 * 1024), 1)
        if total_mb >= self.temp_junk_threshold_mb:
            issue_key = "temp_junk"
            if not self._can_ping(issue_key):
                return None

            ping_id = f"ping_junk_{uuid.uuid4().hex[:6]}"
            decision = {
                "id": ping_id,
                "type": "storage_junk",
                "severity": "yellow",
                "agent_id": "personal_assistant",
                "agent_name": "Personal Assistant",
                "title": "Temporary Junk Files Detected",
                "message": f"DeskPilot identified approximately {total_mb} MB of transient temporary cache files. Would you like me to safely clean them to reclaim space?",
                "action_text": "Clean Temporary Files",
                "instruction": "Clean temporary cache files from the system temporary directory.",
                "total_mb": total_mb,
                "created_at": datetime.now().isoformat(),
            }

            self.pending_decisions[ping_id] = decision
            self.last_pings[issue_key] = datetime.now()
            self._dispatch_proactive_ping(decision)
            return decision

        return None

    def _check_incoming_invoices(self) -> Optional[Dict[str, Any]]:
        """Scans for new PDF invoices that might require financial ledger indexing."""
        desktop_path = Path.home() / "Desktop"
        if not desktop_path.exists():
            return None

        invoices = []
        try:
            for item in desktop_path.glob("*.pdf"):
                name_lower = item.name.lower()
                if "invoice" in name_lower or "receipt" in name_lower or "bill" in name_lower:
                    invoices.append(item)
        except Exception:
            pass

        if invoices:
            first_inv = invoices[0]
            issue_key = f"invoice_{first_inv.name}"
            if not self._can_ping(issue_key):
                return None

            ping_id = f"ping_inv_{uuid.uuid4().hex[:6]}"
            decision = {
                "id": ping_id,
                "type": "incoming_invoice",
                "severity": "yellow",
                "agent_id": "finance_agent",
                "agent_name": "Finance Agent",
                "title": "New Financial Invoice Detected",
                "message": f"Found new invoice '{first_inv.name}' on Desktop. Would you like Finance Agent to extract the line items and record them into a structured Excel ledger?",
                "action_text": "Extract & Record Invoice",
                "instruction": f"Extract the invoice data from the file '{first_inv.name}' on Desktop and create a verified financial summary workbook in Excel.",
                "file_path": str(first_inv),
                "created_at": datetime.now().isoformat(),
            }

            self.pending_decisions[ping_id] = decision
            self.last_pings[issue_key] = datetime.now()
            self._dispatch_proactive_ping(decision)
            return decision

        return None

    def _dispatch_proactive_ping(self, decision: Dict[str, Any]):
        """Dispatches proactive event to frontend and native desktop toast."""
        logger.info(f"Dispatching Proactive Ambient Ping: [{decision['id']}] {decision['title']}")

        # 1. Send in-app event to WebView / SSE stream
        emit_event("deskpilot:proactive_ping", decision)

        # 2. Fire native Windows Notification for ambient awareness
        send_windows_notification(
            title=f"DeskPilot: {decision['title']}",
            message=decision['message']
        )

    def respond_to_ping(self, ping_id: str, approved: bool) -> Dict[str, Any]:
        """
        Handles the user's decision on a proactive suggestion.
        If approved, autonomously triggers the agent task via orchestrator.
        """
        if ping_id not in self.pending_decisions:
            return {"success": False, "error": f"Proactive ping '{ping_id}' not found or already closed"}

        decision = self.pending_decisions.pop(ping_id)

        if not approved:
            logger.info(f"User dismissed proactive ping [{ping_id}]: {decision.get('title')}")
            emit_event("deskpilot:proactive_dismissed", {"id": ping_id})
            return {"success": True, "status": "dismissed", "ping_id": ping_id}

        logger.info(f"User APPROVED proactive ping [{ping_id}]. Spawning autonomous task...")
        agent_id = decision.get("agent_id", "personal_assistant")
        instruction = decision.get("instruction", "")

        # Execute autonomously in background thread
        thread = threading.Thread(
            target=self._execute_proactive_action,
            args=(decision, agent_id, instruction),
            daemon=True
        )
        thread.start()

        return {
            "success": True,
            "status": "executing",
            "ping_id": ping_id,
            "agent_id": agent_id,
            "message": f"Autonomous task launched for {decision.get('agent_name', 'Agent')}"
        }

    def _execute_proactive_action(self, decision: Dict[str, Any], agent_id: str, instruction: str):
        """Runs the approved proactive action with real-time logging and toast update."""
        task_id = f"ambient_{uuid.uuid4().hex[:8]}"

        emit_event("deskpilot:task_started", {
            "task_id": task_id,
            "agent_id": agent_id,
            "agent_name": decision.get("agent_name", "Autonomous Agent"),
            "instruction": instruction,
            "started_at": datetime.now().isoformat(),
        })

        if not self.orchestrator:
            from backend.agent.registry import AgentRegistry
            from backend.agent.orchestrator import AgentOrchestrator
            self.orchestrator = AgentOrchestrator(AgentRegistry())

        def _on_step(tool: str, status: str):
            emit_event("deskpilot:step", {
                "task_id": task_id,
                "agent_id": agent_id,
                "tool": tool,
                "status": status,
                "message": f"Ambient Agent executing tool: {tool}",
            })

        def _on_log(text: str):
            emit_event("deskpilot:log", {
                "task_id": task_id,
                "agent_id": agent_id,
                "text": text,
            })

        try:
            res = self.orchestrator.run_task(
                agent_id=agent_id,
                instruction=instruction,
                task_id=task_id,
                on_log=_on_log,
                on_step=_on_step,
            )

            if res.get("success"):
                result_str = res.get("result", "Task completed.")
                summary_snippet = result_str[:200]
                send_windows_notification(
                    title="DeskPilot: Task Completed",
                    message=f"Action '{decision.get('action_text')}' completed successfully."
                )
                emit_event("deskpilot:proactive_complete", {
                    "ping_id": decision.get("id"),
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "result": result_str,
                    "summary": summary_snippet,
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                err = res.get("error", "Failed")
                emit_event("deskpilot:proactive_failed", {
                    "ping_id": decision.get("id"),
                    "task_id": task_id,
                    "error": err,
                })
        except Exception as e:
            logger.error(f"Error executing proactive action [{task_id}]: {e}")
            emit_event("deskpilot:proactive_failed", {
                "ping_id": decision.get("id"),
                "task_id": task_id,
                "error": str(e),
            })
