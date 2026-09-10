"""
DeskPilot — Phase 1 Foundation Verification Test Suite
Validates the Agent Registry, Bridge contract, Trust Tier classification, and Frontend assets.
"""

import os
import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.registry import AgentRegistry
from backend.bridge import DeskPilotBridge
from backend.utils.trust import TrustTierClassifier, classify_action, resolve_approval
from backend.config.settings import (
    AGENTS_DIR, FRONTEND_DIR, GREEN_TIER_ACTIONS, YELLOW_TIER_ACTIONS, RED_TIER_ACTIONS
)


class TestPhase1Foundation(unittest.TestCase):

    def setUp(self):
        self.registry = AgentRegistry()
        self.bridge = DeskPilotBridge(self.registry)

    # ── 1. Agent Registry Validation ──────────────────────────────────────────

    def test_default_agents_loaded(self):
        """Verifies that all 4 default agents are registered and valid."""
        active_agents = self.registry.get_active_agents()
        agent_ids = [a["agent_id"] for a in active_agents]

        self.assertIn("personal_assistant", agent_ids)
        self.assertIn("finance_agent", agent_ids)
        self.assertIn("health_agent", agent_ids)
        self.assertIn("work_agent", agent_ids)
        self.assertEqual(len(agent_ids), 4)

    def test_agent_schema_conformance(self):
        """Validates that every active agent conforms strictly to the Section 6 JSON schema."""
        required_keys = [
            "id", "name", "description", "icon", "color",
            "persona", "allowed_tools", "category", "created_by",
            "created_at", "status"
        ]
        for agent in self.registry.get_active_agents():
            for key in required_keys:
                self.assertIn(key, agent, f"Agent {agent.get('id')} missing required key '{key}'")
            self.assertTrue(isinstance(agent["allowed_tools"], list))
            self.assertTrue(len(agent["allowed_tools"]) > 0)
            self.assertEqual(agent["category"], "default")

    def test_health_agent_safety_prompt(self):
        """Ensures the Health Agent includes strict no-diagnosis and emergency redirection instructions."""
        health_agent = self.registry.get_agent("health_agent")
        self.assertIsNotNone(health_agent)
        prompt = health_agent["persona"]
        self.assertIn("never generate medical diagnoses", prompt.lower())
        self.assertIn("emergency", prompt.lower())

    def test_template_agents_loaded(self):
        """Verifies that the 3 template agents are loaded into the registry."""
        templates = self.registry.get_template_agents()
        template_ids = [t["id"] for t in templates]

        self.assertIn("property_agent", template_ids)
        self.assertIn("student_agent", template_ids)
        self.assertIn("business_value_agent", template_ids)
        self.assertEqual(len(template_ids), 3)

    def test_category_filtering(self):
        """Verifies category querying in AgentRegistry for default and template categories."""
        default_agents = self.registry.get_agents_by_category("default")
        self.assertEqual(len(default_agents), 4)

        template_agents = self.registry.get_agents_by_category("template")
        self.assertEqual(len(template_agents), 3)

    # ── 2. DeskPilotBridge (Section 11 Contract) ──────────────────────────────

    def test_bridge_get_agents(self):
        """Validates bridge.get_agents returns the active agents list."""
        agents = self.bridge.get_agents()
        self.assertTrue(isinstance(agents, list))
        self.assertEqual(len(agents), 4)

    def test_bridge_get_agent(self):
        """Validates bridge.get_agent for valid and invalid IDs."""
        res_valid = self.bridge.get_agent("personal_assistant")
        self.assertTrue(res_valid["found"])
        self.assertEqual(res_valid["agent"]["name"], "Personal Assistant")

        res_invalid = self.bridge.get_agent("non_existent_agent")
        self.assertFalse(res_invalid["found"])

    def test_bridge_get_template_agents(self):
        """Validates bridge.get_template_agents returns 3 templates."""
        templates = self.bridge.get_template_agents()
        self.assertEqual(len(templates), 3)

    def test_bridge_system_status(self):
        """Validates bridge.get_system_status returns diagnostic info."""
        status = self.bridge.get_system_status()
        self.assertEqual(status["status"], "ready")
        self.assertIn("model_id", status)
        self.assertEqual(status["active_agents_count"], 4)
        self.assertEqual(status["template_agents_count"], 3)

    # ── 3. Trust Tier Classification (Section 10 & 13) ────────────────────────

    def test_green_tier_classification(self):
        """Read-only and file-creation actions must classify as GREEN."""
        self.assertEqual(classify_action("search_and_read"), "GREEN")
        self.assertEqual(classify_action("read_pdf"), "GREEN")
        self.assertEqual(classify_action("create_word_report"), "GREEN")
        self.assertEqual(classify_action("create_excel_workbook"), "GREEN")

    def test_yellow_tier_classification(self):
        """File modification, moving, and renaming must classify as YELLOW."""
        self.assertEqual(classify_action("modify_existing_file"), "YELLOW")
        self.assertEqual(classify_action("move_file"), "YELLOW")
        self.assertEqual(classify_action("rename_file"), "YELLOW")

    def test_red_tier_classification(self):
        """File deletion, software installation, and shell execution must classify as RED."""
        self.assertEqual(classify_action("delete_file"), "RED")
        self.assertEqual(classify_action("install_software"), "RED")
        self.assertEqual(classify_action("winget_install"), "RED")
        self.assertEqual(classify_action("run_shell_command"), "RED")

    # ── 4. Frontend Assets Validation ─────────────────────────────────────────

    def test_frontend_assets_exist(self):
        """Verifies that all required HTML, CSS, JS, and logo files exist."""
        index_html = FRONTEND_DIR / "index.html"
        styles_css = FRONTEND_DIR / "css" / "styles.css"
        bridge_js = FRONTEND_DIR / "js" / "bridge.js"
        app_js = FRONTEND_DIR / "js" / "app.js"
        logo_png = FRONTEND_DIR / "assets" / "logo.png"

        self.assertTrue(index_html.exists(), "frontend/index.html is missing")
        self.assertTrue(styles_css.exists(), "frontend/css/styles.css is missing")
        self.assertTrue(bridge_js.exists(), "frontend/js/bridge.js is missing")
        self.assertTrue(app_js.exists(), "frontend/js/app.js is missing")
        self.assertTrue(logo_png.exists(), "frontend/assets/logo.png is missing")

    def test_frontend_index_dom_ids(self):
        """Verifies that frontend/index.html has all required DOM element IDs."""
        content = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        required_ids = [
            "agents-grid", "sidebar-agents-list", "active-agents-badge",
            "activity-feed", "task-modal", "approval-modal", "templates-modal",
            "task-instruction-input", "btn-submit-task", "btn-confirm-approval"
        ]
        for dom_id in required_ids:
            self.assertIn(f'id="{dom_id}"', content, f"Missing DOM id '{dom_id}' in index.html")

    # ── 5. Desktop Window Shell Validation ────────────────────────────────────

    def test_app_window_creation(self):
        """Verifies that backend.app.create_app_window initializes properly."""
        from backend.app import create_app_window
        from backend.utils.events import set_active_window
        window = create_app_window()
        self.assertIsNotNone(window)
        self.assertIn("DeskPilot", window.title)
        self.assertEqual(window.initial_width, 1280)
        self.assertEqual(window.initial_height, 820)
        set_active_window(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
