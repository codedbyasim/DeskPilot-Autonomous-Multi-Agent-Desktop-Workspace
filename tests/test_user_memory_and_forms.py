"""
Unit tests for DeskPilot User Memory, Runtime Dynamic Forms, and Multi-Agent Personalization.
Validates local JSON persistence, form request resolution, tool execution, and prompt injection.
"""

import sys
import json
import unittest
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from backend.utils.user_memory import UserMemoryManager, get_user_memory_context
from backend.utils.form_engine import (
    request_user_form, resolve_user_form, get_pending_form_ids
)
from backend.tools.user_tools import ask_user_form, get_user_profile, update_user_profile
from backend.agent.registry import AgentRegistry
from backend.agent.orchestrator import AgentOrchestrator
from backend.bridge import DeskPilotBridge


class TestUserMemoryAndForms(unittest.TestCase):
    """Tests for UserMemoryManager, FormEngine, UserTools, and Orchestrator integration."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.orchestrator = AgentOrchestrator(self.registry)
        self.bridge = DeskPilotBridge(self.registry)

    # ── 1. User Memory Manager Tests ──────────────────────────────────────────

    def test_save_and_retrieve_profile_data(self):
        """Verify saving and retrieving domain profile details in memory."""
        test_health_data = {
            "age": 30,
            "fitness_goal": "Marathon training",
            "allergies": "Peanuts",
            "daily_activity": "High"
        }
        res = UserMemoryManager.save_profile_data("health_agent", test_health_data)
        self.assertEqual(res.get("age"), 30)
        self.assertEqual(res.get("fitness_goal"), "Marathon training")

        retrieved = UserMemoryManager.get_profile("health")
        self.assertEqual(retrieved.get("allergies"), "Peanuts")
        self.assertTrue(UserMemoryManager.has_profile_data("health"))

    def test_update_single_field(self):
        """Verify updating a single profile fact directly."""
        UserMemoryManager.update_single_field("preferred_name", "Alex", "global")
        prof = UserMemoryManager.get_profile("global")
        self.assertEqual(prof.get("preferred_name"), "Alex")

    def test_formatted_memory_context(self):
        """Verify formatted prompt injection contains known user facts."""
        UserMemoryManager.save_profile_data("finance", {
            "currency": "EUR",
            "monthly_savings_goal": "2000"
        })
        context = get_user_memory_context("finance_agent")
        self.assertIn("USER PROFILE & LOCAL MEMORY CONTEXT", context)
        self.assertIn("Finance", context)
        self.assertIn("EUR", context)

    # ── 2. Form Engine Resolution Tests ───────────────────────────────────────

    def test_form_request_and_resolution(self):
        """Verify request_user_form blocks until resolve_user_form is called."""
        test_fields = [
            {"id": "user_role", "label": "Your Role", "type": "text", "required": True},
            {"id": "team_size", "label": "Team Size", "type": "number", "required": False}
        ]

        result_container = []

        def worker():
            res = request_user_form(
                title="Work Clarification",
                description="Please provide your role details",
                fields=test_fields,
                category="work",
                agent_id="work_agent",
                timeout=10
            )
            result_container.append(res)

        t = threading.Thread(target=worker)
        t.start()

        # Wait briefly for form to register
        import time
        time.sleep(0.2)

        active_ids = get_pending_form_ids()
        self.assertTrue(len(active_ids) > 0)
        form_id = active_ids[0]

        # Resolve from simulated UI
        success = resolve_user_form(form_id, {
            "user_role": "Product Manager",
            "team_size": 12
        }, cancelled=False)
        self.assertTrue(success)

        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertTrue(len(result_container) > 0)
        self.assertIn("Product Manager", result_container[0])
        self.assertIn("SUCCESS", result_container[0])

    def test_form_cancellation_by_user(self):
        """Verify graceful handling when user skips or cancels a form."""
        result_container = []

        def worker():
            res = request_user_form(
                title="Skipped Form",
                description="Testing skip",
                fields=[{"id": "q1", "label": "Question 1", "type": "text"}],
                category="general",
                timeout=10
            )
            result_container.append(res)

        t = threading.Thread(target=worker)
        t.start()

        import time
        time.sleep(0.2)

        active_ids = get_pending_form_ids()
        self.assertTrue(len(active_ids) > 0)
        form_id = active_ids[0]

        # User clicks skip / cancel
        resolve_user_form(form_id, {}, cancelled=True)

        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertTrue(len(result_container) > 0)
        self.assertIn("skipped or closed", result_container[0])

    # ── 3. Tool Functionality Tests ───────────────────────────────────────────

    def test_get_user_profile_tool(self):
        """Verify get_user_profile tool returns clean summary."""
        UserMemoryManager.save_profile_data("health", {"daily_steps_target": "10000"})
        tool_res = get_user_profile("health")
        self.assertIn("10000", tool_res)

    def test_update_user_profile_tool(self):
        """Verify update_user_profile tool saves facts directly."""
        msg = update_user_profile("favorite_editor", "VS Code", "work")
        self.assertIn("SUCCESS", msg)
        prof = UserMemoryManager.get_profile("work")
        self.assertEqual(prof.get("favorite_editor"), "VS Code")

    # ── 4. Bridge Integration Tests ───────────────────────────────────────────

    def test_bridge_submit_user_form(self):
        """Verify bridge method submit_user_form unblocks active requests."""
        result_container = []

        def worker():
            res = request_user_form(
                title="Bridge Test Form",
                description="Testing bridge submission",
                fields=[{"id": "topic", "label": "Topic", "type": "text"}],
                category="general",
                timeout=10
            )
            result_container.append(res)

        t = threading.Thread(target=worker)
        t.start()

        import time
        time.sleep(0.2)

        form_id = get_pending_form_ids()[0]
        bridge_res = self.bridge.submit_user_form(form_id, {"topic": "Agentic AI"}, cancelled=False)
        self.assertTrue(bridge_res.get("success"))

        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertIn("Agentic AI", result_container[0])

    # ── 5. Agent Orchestrator Prompt Injection ────────────────────────────────

    def test_build_agent_prompt_includes_memory_and_form_guardrail(self):
        """Verify build_agent system prompt includes memory context and dynamic form rule."""
        agent = self.orchestrator.build_agent("health_agent")
        self.assertIsNotNone(agent)
        self.assertIn("USER PROFILE & LOCAL MEMORY CONTEXT", agent.system_prompt)
        self.assertIn("DYNAMIC USER ONBOARDING", agent.system_prompt)
        self.assertIn("ask_user_form", agent.tool_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
