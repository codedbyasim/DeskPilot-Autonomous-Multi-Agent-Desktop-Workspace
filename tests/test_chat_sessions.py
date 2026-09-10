"""
Unit tests for DeskPilot Chat Session Manager and Multi-Turn Persistence.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from backend.chat.session_manager import ChatSessionManager


class TestChatSessionManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="deskpilot_chat_test_"))
        self.mgr = ChatSessionManager(storage_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_and_get_session(self):
        session = self.mgr.create_session("personal_assistant", "My Test Chat")
        self.assertTrue(session["id"].startswith("chat_"))
        self.assertEqual(session["agent_id"], "personal_assistant")
        self.assertEqual(session["title"], "My Test Chat")
        self.assertEqual(session["messages"], [])

        loaded = self.mgr.get_session(session["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"], session["id"])
        self.assertEqual(loaded["agent_id"], "personal_assistant")

    def test_add_messages_and_auto_title(self):
        session = self.mgr.create_session("work_agent", "New Conversation")
        
        # User message should auto-title session
        msg1 = self.mgr.add_message(
            session["id"],
            role="user",
            content="Research recent advancements in quantum computing"
        )
        self.assertIsNotNone(msg1)
        self.assertEqual(msg1["role"], "user")

        loaded = self.mgr.get_session(session["id"])
        self.assertEqual(len(loaded["messages"]), 1)
        self.assertTrue(loaded["title"].startswith("Research recent advancements"))

        # Assistant message with tool calls and deliverables
        msg2 = self.mgr.add_message(
            session["id"],
            role="assistant",
            content="Here is the executive summary.",
            tool_calls=["search_and_read", "create_word_report"],
            deliverables=["C:\\DeskPilot_Output\\Quantum_Report.docx"]
        )
        self.assertIsNotNone(msg2)
        self.assertEqual(msg2["role"], "assistant")
        self.assertEqual(len(msg2["tool_calls"]), 2)
        self.assertEqual(len(msg2["deliverables"]), 1)

        loaded2 = self.mgr.get_session(session["id"])
        self.assertEqual(len(loaded2["messages"]), 2)
        self.assertEqual(loaded2["messages"][1]["deliverables"][0], "C:\\DeskPilot_Output\\Quantum_Report.docx")

    def test_list_sessions_sorting(self):
        s1 = self.mgr.create_session("health_agent", "Chat 1")
        s2 = self.mgr.create_session("finance_agent", "Chat 2")

        # Update s1 with a message so it becomes most recent
        self.mgr.add_message(s1["id"], "user", "Hello there")

        sessions = self.mgr.list_sessions()
        self.assertEqual(len(sessions), 2)
        # s1 should be first because it was updated most recently
        self.assertEqual(sessions[0]["id"], s1["id"])
        self.assertEqual(sessions[0]["message_count"], 1)
        self.assertEqual(sessions[0]["last_message"], "Hello there")

    def test_delete_session(self):
        session = self.mgr.create_session("property_agent", "To Delete")
        self.assertTrue(self.mgr.delete_session(session["id"]))
        self.assertIsNone(self.mgr.get_session(session["id"]))
        self.assertFalse(self.mgr.delete_session("non_existent_id"))

    def test_update_title(self):
        session = self.mgr.create_session("personal_assistant", "Old Title")
        self.assertTrue(self.mgr.update_title(session["id"], "Updated Title"))
        loaded = self.mgr.get_session(session["id"])
        self.assertEqual(loaded["title"], "Updated Title")


class TestBridgeChatIntegration(unittest.TestCase):
    def test_bridge_chat_methods(self):
        from backend.bridge import DeskPilotBridge

        bridge = DeskPilotBridge()
        # Create session
        created = bridge.create_chat_session("work_agent", "Test Bridge Chat")
        self.assertIn("id", created)
        session_id = created["id"]

        # Fetch session
        fetched = bridge.get_chat_session(session_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Test Bridge Chat")

        # List sessions
        sessions = bridge.get_chat_sessions()
        self.assertTrue(any(s["id"] == session_id for s in sessions))

        # Delete session
        deleted = bridge.delete_chat_session(session_id)
        self.assertTrue(deleted)
        self.assertIsNone(bridge.get_chat_session(session_id))


if __name__ == "__main__":
    unittest.main()
