"""
DeskPilot — Audit Logger
Records every agent action to both console and a JSON-lines audit log file.
"""

import logging
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
import sys

# Ensure UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from backend.config.settings import LOG_DIR, LOG_LEVEL, APP_NAME


def _setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
            datefmt="%H:%M:%S"
        )
        ch.setFormatter(fmt)
        logger.addHandler(ch)

        log_file = LOG_DIR / f"deskpilot_{datetime.now().strftime('%Y%m%d')}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


class AuditLogger:
    """
    Writes every agent tool call + result to a JSON-lines file.
    Gives judges and users full traceability of what the agent actually did.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audit_file = LOG_DIR / f"audit_{self.session_id}.jsonl"
        self._logger = _setup_logger(f"{APP_NAME}.audit")
        self._start_time = time.time()

    def log_action(
        self,
        tool_name: str = "",
        inputs: Optional[dict] = None,
        result: Any = None,
        trust_tier: str = "GREEN",
        success: bool = True,
        error: Optional[str] = None,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        parameters: Optional[dict] = None,
    ) -> None:
        """Record a single tool call to the audit trail."""
        actual_tool = action or tool_name or "unknown"
        actual_inputs = parameters if parameters is not None else (inputs or {})
        if not isinstance(actual_inputs, dict):
            actual_inputs = {"raw": str(actual_inputs)}
        record = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_s": round(time.time() - self._start_time, 2),
            "session_id": self.session_id,
            "agent_id": agent_id,
            "tool": actual_tool,
            "trust_tier": trust_tier,
            "inputs": actual_inputs,
            "result_summary": str(result)[:500] if result else None,
            "success": success,
            "error": error,
        }

        with open(self.audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        status = "✓" if success else "✗"
        self._logger.info(
            f"[{trust_tier}] {status} {agent_id or ''} {actual_tool}({list(actual_inputs.keys())})"
        )

    def log_plan(self, steps: list[str], agent_id: Optional[str] = None) -> None:
        """Record the agent's generated plan."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "agent_id": agent_id,
            "event": "PLAN_GENERATED",
            "steps": steps,
        }
        with open(self.audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._logger.info(f"Plan generated: {len(steps)} steps")

    def log_verification(self, checks: dict[str, bool], agent_id: Optional[str] = None) -> None:
        """Record verification results."""
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "agent_id": agent_id,
            "event": "VERIFICATION",
            "checks": checks,
            "passed": passed,
            "total": total,
        }
        with open(self.audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._logger.info(f"Verification: {passed}/{total} checks passed")

    def get_audit_path(self) -> Path:
        return self.audit_file


def get_logger(name: str) -> logging.Logger:
    return _setup_logger(f"{APP_NAME}.{name}")
