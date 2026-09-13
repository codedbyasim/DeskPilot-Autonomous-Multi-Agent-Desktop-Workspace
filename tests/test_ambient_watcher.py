"""
Unit tests for DeskPilot Proactive Ambient Watcher Engine.
Verifies background sweeps, clutter detection, cooldown periods,
and human-in-the-loop decision responses.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from backend.agent.ambient_watcher import AmbientWatcher, send_windows_notification


class TestAmbientWatcher(unittest.TestCase):
    def setUp(self):
        # Reset singleton instance for fresh testing
        AmbientWatcher._instance = None
        self.mock_orchestrator = MagicMock()
        self.watcher = AmbientWatcher(orchestrator=self.mock_orchestrator, interval_seconds=10)

    def tearDown(self):
        self.watcher.stop()
        AmbientWatcher._instance = None

    def test_initial_state(self):
        status = self.watcher.get_status()
        self.assertFalse(status["is_running"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["interval_seconds"], 10)
        self.assertEqual(status["pending_decisions_count"], 0)

    def test_toggle(self):
        self.watcher.toggle(False)
        self.assertFalse(self.watcher.enabled)
        self.assertFalse(self.watcher.get_status()["enabled"])

        self.watcher.toggle(True)
        self.assertTrue(self.watcher.enabled)
        self.assertTrue(self.watcher.get_status()["enabled"])

    def test_cooldown_enforcement(self):
        issue_key = "test_clutter"
        self.assertTrue(self.watcher._can_ping(issue_key))

        # Record a ping just now
        self.watcher.last_pings[issue_key] = datetime.now()
        self.assertFalse(self.watcher._can_ping(issue_key))

        # Advance elapsed time beyond cooldown_minutes (15 mins)
        self.watcher.last_pings[issue_key] = datetime.now() - timedelta(minutes=16)
        self.assertTrue(self.watcher._can_ping(issue_key))

    @patch("backend.agent.ambient_watcher.send_windows_notification")
    @patch("pathlib.Path.home")
    def test_check_desktop_clutter_detection(self, mock_home, mock_notify):
        mock_desktop = MagicMock()
        mock_home.return_value = mock_desktop
        mock_desktop.__truediv__.return_value = mock_desktop
        mock_desktop.exists.return_value = True
        mock_desktop.is_dir.return_value = True

        # Simulate 6 loose files (threshold is 5)
        fake_files = []
        for i in range(6):
            f = MagicMock()
            f.is_file.return_value = True
            f.name = f"doc_{i}.txt"
            fake_files.append(f)

        mock_desktop.iterdir.return_value = fake_files

        decision = self.watcher._check_desktop_clutter()
        self.assertIsNotNone(decision)
        self.assertEqual(decision["type"], "desktop_clutter")
        self.assertEqual(decision["severity"], "yellow")
        self.assertEqual(decision["item_count"], 6)
        self.assertIn(decision["id"], self.watcher.pending_decisions)

        # Immediate second check should return None due to cooldown
        decision2 = self.watcher._check_desktop_clutter()
        self.assertIsNone(decision2)

    def test_respond_to_ping_dismiss(self):
        ping_id = "test_ping_123"
        self.watcher.pending_decisions[ping_id] = {
            "id": ping_id,
            "title": "Test Ping",
            "agent_id": "personal_assistant",
            "instruction": "Do something",
        }

        res = self.watcher.respond_to_ping(ping_id, approved=False)
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "dismissed")
        self.assertNotIn(ping_id, self.watcher.pending_decisions)

    @patch("backend.agent.ambient_watcher.send_windows_notification")
    def test_respond_to_ping_approve(self, mock_notify):
        ping_id = "test_ping_456"
        self.watcher.pending_decisions[ping_id] = {
            "id": ping_id,
            "title": "Clean Clutter",
            "agent_id": "personal_assistant",
            "agent_name": "Personal Assistant",
            "action_text": "Organize",
            "instruction": "Organize all loose files on Desktop",
        }

        self.mock_orchestrator.run_task.return_value = {
            "success": True,
            "result": "Organized 6 files into subfolders.",
        }

        res = self.watcher.respond_to_ping(ping_id, approved=True)
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "executing")
        self.assertNotIn(ping_id, self.watcher.pending_decisions)

    def test_respond_to_unknown_ping(self):
        res = self.watcher.respond_to_ping("non_existent_ping", approved=True)
        self.assertFalse(res["success"])
        self.assertIn("not found", res["error"])


if __name__ == "__main__":
    unittest.main()
