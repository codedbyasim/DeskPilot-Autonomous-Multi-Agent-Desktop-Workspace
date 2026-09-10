"""
DeskPilot — Phase 3 & 6 Verification Test Suite
Validates the Custom Agent Builder (Section 9), plain-language tool metadata,
whitelist enforcement, bridge lifecycle (draft -> confirm -> delete), and frontend view DOM IDs.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.registry import AgentRegistry
from backend.agent.builder import AgentBuilder, TOOL_METADATA
from backend.bridge import DeskPilotBridge
from backend.tools import TOOL_REGISTRY
from backend.config.settings import FRONTEND_DIR, AGENTS_DIR


class TestPhase3BuilderSuite(unittest.TestCase):

    def setUp(self):
        self.registry = AgentRegistry()
        self.builder = AgentBuilder()
        self.bridge = DeskPilotBridge(self.registry)
        self.created_agent_files = []

    def tearDown(self):
        # Clean up any test custom agents created
        for f in self.created_agent_files:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass

    # ── 1. Tool Metadata & Plain-Language Permissions ─────────────────────────

    def test_tool_metadata_completeness(self):
        """Verify TOOL_METADATA has plain-language descriptions for all major tools."""
        major_tools = [
            "search_web", "read_pdf", "extract_pdf_tables",
            "create_word_report", "create_excel_workbook", "list_files",
            "winget_install", "delete_file"
        ]
        for t in major_tools:
            self.assertIn(t, TOOL_METADATA, f"Missing metadata for tool '{t}'")
            meta = TOOL_METADATA[t]
            self.assertIn("title", meta)
            self.assertIn("description", meta)
            self.assertIn("category", meta)
            self.assertIn("tier", meta)

    # ── 2. Heuristic Semantic Drafting ────────────────────────────────────────

    def test_heuristic_draft_pdf_workflow(self):
        """Description with PDF receipts should propose PDF extraction tools."""
        draft = self.builder._heuristic_draft("Extract invoice receipts from PDF files")
        tools = draft.get("allowed_tools", [])
        self.assertIn("read_pdf", tools)
        self.assertIn("extract_pdf_tables", tools)
        self.assertIn("extract_pdf_invoice", tools)

    def test_heuristic_draft_word_reports(self):
        """Description with Word reports should propose Word creation and verification."""
        draft = self.builder._heuristic_draft("Analyze market trends and write Word reports")
        tools = draft.get("allowed_tools", [])
        self.assertIn("create_word_report", tools)
        self.assertIn("verify_word_document", tools)

    def test_heuristic_draft_excel_budgets(self):
        """Description with Excel budgets should propose Excel tools."""
        draft = self.builder._heuristic_draft("Build family budget spreadsheets in Excel")
        tools = draft.get("allowed_tools", [])
        self.assertIn("create_excel_workbook", tools)
        self.assertIn("read_excel_file", tools)

    # ── 3. Draft Sanitization & Whitelist Enforcement ─────────────────────────

    @patch.object(AgentBuilder, "_call_bedrock_builder")
    def test_draft_agent_whitelist_enforcement(self, mock_bedrock):
        """Builder must never grant tools that are not in TOOL_REGISTRY."""
        mock_bedrock.return_value = {
            "name": "Super Assistant",
            "description": "Assistant",
            "icon": "sparkles",
            "color": "indigo",
            "persona": "Test persona",
            "allowed_tools": ["search_web", "fake_unallowed_tool", "read_pdf"]
        }
        res = self.builder.draft_agent("General assistant that can do everything")
        self.assertTrue(res["success"])
        draft = res["draft"]
        for tool in draft["allowed_tools"]:
            self.assertIn(tool, TOOL_REGISTRY, f"Tool '{tool}' is not in TOOL_REGISTRY")
        self.assertNotIn("fake_unallowed_tool", draft["allowed_tools"])

    @patch.object(AgentBuilder, "_call_bedrock_builder")
    def test_draft_agent_schema_conformance(self, mock_bedrock):
        """Draft must produce all Section 6 schema fields with status 'draft'."""
        mock_bedrock.return_value = {
            "name": "Academic Summarizer",
            "description": "Summarizes papers",
            "icon": "book",
            "color": "blue",
            "persona": "Academic persona",
            "allowed_tools": ["read_pdf", "create_word_report"]
        }
        res = self.builder.draft_agent("Academic paper summarizer")
        draft = res["draft"]
        required_keys = [
            "id", "name", "description", "icon", "color",
            "persona", "allowed_tools", "category", "created_by",
            "created_at", "status"
        ]
        for k in required_keys:
            self.assertIn(k, draft, f"Missing key '{k}' in drafted agent")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["category"], "custom")

    # ── 4. Bridge Custom Agent Lifecycle ──────────────────────────────────────

    @patch.object(AgentBuilder, "_call_bedrock_builder")
    def test_bridge_create_and_confirm_custom_agent(self, mock_bedrock):
        """End-to-end draft -> confirm -> save lifecycle in Bridge."""
        mock_bedrock.return_value = {
            "name": "Legal Contract Reviewer",
            "description": "Reviews agreements",
            "icon": "file-text",
            "color": "indigo",
            "persona": "Legal persona",
            "allowed_tools": ["read_pdf", "create_word_report"]
        }
        # 1. Draft
        draft_res = self.bridge.create_agent_draft("Specialized contract analyst for legal agreements")
        self.assertTrue(draft_res["success"])
        draft = draft_res["draft"]
        self.assertTrue(draft["id"].startswith("custom_"))

        # Track file for cleanup
        agent_file = AGENTS_DIR / f"{draft['id']}.json"
        self.created_agent_files.append(agent_file)

        # 2. Confirm & Save
        confirm_res = self.bridge.confirm_create_agent(draft)
        self.assertTrue(confirm_res["success"])
        self.assertTrue(agent_file.exists(), f"Agent file {agent_file} was not written to disk")

        # 3. Verify loaded in registry
        loaded = self.registry.get_agent(draft["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], draft["name"])
        self.assertEqual(loaded["category"], "custom")

        # 4. Delete custom agent
        del_res = self.bridge.delete_custom_agent(draft["id"])
        self.assertTrue(del_res["success"])
        self.assertFalse(agent_file.exists(), "Agent file was not removed after deletion")

    def test_bridge_protect_default_agents_from_deletion(self):
        """Built-in default agents cannot be deleted."""
        res = self.bridge.delete_custom_agent("personal_assistant")
        self.assertFalse(res["success"])
        self.assertIn("Cannot delete default", res["error"])

        # File must still exist
        pa_file = AGENTS_DIR / "personal_assistant.json"
        self.assertTrue(pa_file.exists())

    def test_bridge_get_available_tools_metadata(self):
        """Bridge must return full list of tools with metadata for builder UI."""
        tools_meta = self.bridge.get_available_tools_metadata()
        self.assertTrue(len(tools_meta) >= 20)
        tool_names = [t["name"] for t in tools_meta]
        self.assertIn("create_word_report", tool_names)
        self.assertIn("search_web", tool_names)

    # ── 5. Frontend DOM Conformance ───────────────────────────────────────────

    def test_frontend_views_and_builder_dom_ids(self):
        """Verify frontend/index.html includes all views and builder modal elements."""
        index_html = FRONTEND_DIR / "index.html"
        self.assertTrue(index_html.exists())
        content = index_html.read_text(encoding="utf-8")

        required_ids = [
            # Views
            "view-home", "view-agents", "view-tasks", "view-history", "view-settings",
            # Builder Modal
            "builder-modal", "builder-step-1", "builder-step-2",
            "builder-input-desc", "btn-generate-draft", "builder-draft-name",
            "builder-draft-desc", "builder-draft-persona", "builder-tools-list",
            "btn-builder-confirm", "btn-builder-back",
            # Deliverables
            "task-deliverable-card", "btn-open-deliverable", "deliverable-filename",
            # Catalogs & Audits
            "catalog-agents-grid", "audit-table-body"
        ]

        for dom_id in required_ids:
            self.assertIn(f'id="{dom_id}"', content, f"Missing DOM element id='{dom_id}' in index.html")


if __name__ == "__main__":
    unittest.main(verbosity=2)
