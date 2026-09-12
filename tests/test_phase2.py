"""
DeskPilot — Phase 2 Backend Core Verification Test Suite
Validates tool library whitelisting, winget allow-list enforcement,
dynamic Strands Agent Orchestrator creation, trust tier interception, and bridge wiring.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.registry import AgentRegistry
from backend.agent.orchestrator import AgentOrchestrator
from backend.tools import (
    TOOL_REGISTRY, get_tools_for_agent, list_available_tool_names
)
from backend.tools.system_tools import winget_install
from backend.config.settings import WINGET_ALLOWLIST
from backend.utils.trust import (
    classify_action, request_approval, resolve_approval, set_approval_hook
)
from backend.bridge import DeskPilotBridge


class TestPhase2BackendCore(unittest.TestCase):

    def setUp(self):
        self.registry = AgentRegistry()
        self.orchestrator = AgentOrchestrator(self.registry)
        self.bridge = DeskPilotBridge(self.registry)

    # ── 1. Tool Library & Whitelist Resolver ──────────────────────────────────

    def test_tool_registry_completeness(self):
        """Verify that all core tools from PROJECT_BRIEF are registered."""
        required_tools = [
            "search_web", "read_webpage", "search_and_read",
            "read_pdf", "extract_pdf_tables", "extract_pdf_invoice", "list_pdfs_in_folder",
            "create_word_report", "verify_word_document",
            "create_excel_workbook", "create_reconciliation_report", "verify_excel_workbook", "read_excel_file",
            "list_files", "verify_file_exists", "move_file", "rename_file", "delete_file",
            "create_folder", "open_file", "take_screenshot", "get_desktop_path", "get_output_directory",
            "winget_install"
        ]
        for t in required_tools:
            self.assertIn(t, TOOL_REGISTRY, f"Tool '{t}' missing from TOOL_REGISTRY")

    def test_get_tools_for_agent_personal_assistant(self):
        """Verify personal_assistant only gets its declared allowed tools."""
        pa_def = self.registry.get_agent("personal_assistant")
        tools = get_tools_for_agent(pa_def["allowed_tools"])
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]

        self.assertEqual(len(tools), len(pa_def["allowed_tools"]))
        self.assertIn("list_files", tool_names)
        self.assertIn("create_folder", tool_names)
        self.assertIn("move_file", tool_names)
        self.assertIn("rename_file", tool_names)
        self.assertIn("search_web", tool_names)
        self.assertIn("search_and_read", tool_names)
        self.assertIn("create_word_report", tool_names)
        self.assertIn("delete_file", tool_names)
        self.assertIn("winget_install", tool_names)

        # Ensure dangerous / unallowed tools are NOT included
        self.assertNotIn("hack_system", tool_names)
        self.assertNotIn("fake_tool_xyz", tool_names)

    def test_get_tools_for_agent_health_agent(self):
        """Verify health_agent receives its authorized tools."""
        ha_def = self.registry.get_agent("health_agent")
        tools = get_tools_for_agent(ha_def["allowed_tools"])
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]

        self.assertEqual(len(tools), len(ha_def["allowed_tools"]))
        self.assertIn("search_web", tool_names)
        self.assertIn("read_webpage", tool_names)

        # Must not have destructive tools
        self.assertNotIn("delete_file", tool_names)
        self.assertNotIn("winget_install", tool_names)
        self.assertNotIn("move_file", tool_names)

    def test_unauthorized_tools_ignored(self):
        """Verify unauthorized or invented tool names are strictly excluded."""
        dirty_list = ["search_web", "hack_system", "fake_tool_xyz", "read_pdf"]
        tools = get_tools_for_agent(dirty_list)
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]

        self.assertEqual(len(tools), 2)
        self.assertIn("search_web", tool_names)
        self.assertIn("read_pdf", tool_names)
        self.assertNotIn("hack_system", tool_names)
        self.assertNotIn("fake_tool_xyz", tool_names)

    # ── 2. Winget Allow-List Enforcement (Section 10 & 13) ────────────────────

    def test_winget_unapproved_package_rejected(self):
        """Arbitrary package IDs must be rejected immediately without execution."""
        res = winget_install("Malicious.Software.Exe")
        self.assertIn("REJECTED", res)
        self.assertIn("not in the DeskPilot authorized software allow-list", res)

    def test_winget_approved_package_denied_by_user(self):
        """Approved package triggers RED tier confirmation; if user denies, execution aborts."""
        captured_requests = []

        def mock_approval_hook(req_id, action, desc, tier, agent_id):
            captured_requests.append((req_id, action, tier))
            # User denies approval
            resolve_approval(req_id, False)

        set_approval_hook(mock_approval_hook)

        # Call with approved package in allow-list (mock subprocess to simulate package not already installed)
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = ""
            mock_run.return_value = mock_proc
            res = winget_install("Git.Git")

        self.assertIn("CANCELLED", res)
        self.assertIn("User denied permission", res)
        self.assertTrue(len(captured_requests) > 0)
        self.assertEqual(captured_requests[0][1], "winget_install")
        self.assertEqual(captured_requests[0][2], "RED")

    def test_winget_allowlist_contents(self):
        """Validate that all standard utility package IDs exist in settings.WINGET_ALLOWLIST."""
        self.assertIn("Git.Git", WINGET_ALLOWLIST)
        self.assertIn("Mozilla.Firefox", WINGET_ALLOWLIST)
        self.assertIn("Microsoft.VisualStudioCode", WINGET_ALLOWLIST)
        self.assertIn("7zip.7zip", WINGET_ALLOWLIST)

    # ── 3. Dynamic Agent Orchestrator Factory ─────────────────────────────────

    def test_build_agent_personal_assistant(self):
        """Verify dynamic build_agent produces a valid Strands Agent for personal_assistant."""
        agent = self.orchestrator.build_agent("personal_assistant")
        pa_def = self.registry.get_agent("personal_assistant")
        self.assertIsNotNone(agent)
        self.assertEqual(len(agent.tool_names), len(pa_def["allowed_tools"]))
        self.assertIn("Personal Assistant", agent.system_prompt)
        self.assertIn("GLOBAL OPERATING RULES", agent.system_prompt)

    def test_build_agent_health_safety_prompt(self):
        """Verify health_agent retains strict no-diagnosis and emergency redirection in prompt."""
        agent = self.orchestrator.build_agent("health_agent")
        ha_def = self.registry.get_agent("health_agent")
        self.assertIsNotNone(agent)
        self.assertEqual(len(agent.tool_names), len(ha_def["allowed_tools"]))
        prompt = agent.system_prompt.lower()
        self.assertIn("never generate medical diagnoses", prompt)
        self.assertIn("emergency", prompt)

    def test_build_agent_template(self):
        """Verify template agents (Property Agent) instantiate dynamically from registry."""
        agent = self.orchestrator.build_agent("property_agent")
        self.assertIsNotNone(agent)
        self.assertEqual(len(agent.tool_names), 5)
        self.assertIn("Property Research", agent.system_prompt)

    def test_build_agent_nonexistent_raises(self):
        """Requesting an unregistered agent ID must raise ValueError."""
        with self.assertRaises(ValueError):
            self.orchestrator.build_agent("unknown_ghost_agent")

    # ── 4. Trust Tier Interceptor & Approval Hook ──────────────────────────────

    def test_request_approval_green_tier_auto_approves(self):
        """Green tier actions must auto-approve without waiting for user input."""
        # GREEN action should return True immediately
        approved = request_approval("search_and_read", "Searching web")
        self.assertTrue(approved)

    def test_request_approval_yellow_denial(self):
        """Yellow tier action prompts user; denial returns False."""
        def mock_hook(req_id, action, desc, tier, agent_id):
            resolve_approval(req_id, False)

        set_approval_hook(mock_hook)
        approved = request_approval("move_file", "Move desktop file", agent_id="personal_assistant")
        self.assertFalse(approved)

    def test_request_approval_yellow_grant(self):
        """Yellow tier action prompts user; grant returns True."""
        def mock_hook(req_id, action, desc, tier, agent_id):
            resolve_approval(req_id, True)

        set_approval_hook(mock_hook)
        approved = request_approval("rename_file", "Rename document", agent_id="personal_assistant")
        self.assertTrue(approved)

    # ── 5. Bridge Integration ─────────────────────────────────────────────────

    def test_bridge_has_orchestrator(self):
        """Verify DeskPilotBridge has initialized AgentOrchestrator instance."""
        self.assertIsNotNone(self.bridge.orchestrator)
        self.assertIsInstance(self.bridge.orchestrator, AgentOrchestrator)

    @patch.object(DeskPilotBridge, "_execute_task_thread")
    def test_bridge_run_agent_task_dispatch(self, mock_exec):
        """Verify bridge.run_agent_task returns valid acknowledgment and task_id."""
        res = self.bridge.run_agent_task("personal_assistant", "List files on Desktop")
        self.assertTrue(res["success"])
        self.assertIn("task_id", res)
        self.assertEqual(res["agent_id"], "personal_assistant")
        self.assertEqual(res["status"], "started")
        mock_exec.assert_called_once()

    def test_bridge_run_agent_task_invalid_agent(self):
        """Verify bridge.run_agent_task handles missing agents gracefully."""
        res = self.bridge.run_agent_task("fake_agent_id", "Do something")
        self.assertFalse(res["success"])
        self.assertIn("not found", res["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
