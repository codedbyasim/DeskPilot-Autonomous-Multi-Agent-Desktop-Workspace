"""
DeskPilot — Automated Test Suite for Batch File Organization & Approval Caching
Validates organize_files tool, category categorization, file moves, and trust caching.
"""

import unittest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.tools.file_tools import (
    organize_files,
    _get_file_category,
    CATEGORY_RULES,
)
from backend.tools import TOOL_REGISTRY, get_tools_for_agent
from backend.utils.trust import (
    request_approval,
    resolve_approval,
    clear_approval_cache,
    classify_action,
    TrustTier,
)
from backend.agent.registry import AgentRegistry


class TestOrganizeFiles(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        clear_approval_cache()

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(str(self.temp_dir), ignore_errors=True)
        clear_approval_cache()

    def test_file_categories(self):
        self.assertEqual(_get_file_category("report.docx"), "Documents")
        self.assertEqual(_get_file_category("notes.txt"), "Documents")
        self.assertEqual(_get_file_category("budget.xlsx"), "Spreadsheets")
        self.assertEqual(_get_file_category("data.csv"), "Spreadsheets")
        self.assertEqual(_get_file_category("slides.pptx"), "Presentations")
        self.assertEqual(_get_file_category("manual.pdf"), "PDFs")
        self.assertEqual(_get_file_category("photo.png"), "Images")
        self.assertEqual(_get_file_category("script.py"), "Code")
        self.assertEqual(_get_file_category("archive.zip"), "Archives")
        self.assertEqual(_get_file_category("app.lnk"), "Shortcuts")
        self.assertEqual(_get_file_category("unknown.xyz123"), "Other")

    @patch("backend.tools.file_tools.request_approval", return_value=True)
    def test_organize_files_success(self, mock_approval):
        # Create loose files in test directory
        (self.temp_dir / "report.docx").write_text("dummy doc")
        (self.temp_dir / "budget.xlsx").write_text("dummy sheet")
        (self.temp_dir / "invoice.pdf").write_text("dummy pdf")
        (self.temp_dir / "photo.png").write_text("dummy img")
        (self.temp_dir / "app.lnk").write_text("dummy lnk")
        (self.temp_dir / "desktop.ini").write_text("system")  # Should be skipped

        res = organize_files(str(self.temp_dir))
        self.assertIn("SUCCESS: Organized 5 file(s)", res)
        mock_approval.assert_called_once()

        # Check that files were moved into categorized folders
        self.assertTrue((self.temp_dir / "Documents" / "report.docx").exists())
        self.assertTrue((self.temp_dir / "Spreadsheets" / "budget.xlsx").exists())
        self.assertTrue((self.temp_dir / "PDFs" / "invoice.pdf").exists())
        self.assertTrue((self.temp_dir / "Images" / "photo.png").exists())
        self.assertTrue((self.temp_dir / "Shortcuts" / "app.lnk").exists())
        self.assertTrue((self.temp_dir / "desktop.ini").exists())  # Unmoved

    @patch("backend.tools.file_tools.request_approval", return_value=False)
    def test_organize_files_denied(self, mock_approval):
        (self.temp_dir / "report.docx").write_text("dummy doc")
        res = organize_files(str(self.temp_dir))
        self.assertIn("Cancelled: User denied permission", res)
        # Original file should not have moved
        self.assertTrue((self.temp_dir / "report.docx").exists())

    def test_organize_files_empty(self):
        res = organize_files(str(self.temp_dir))
        self.assertIn("No loose files found", res)

    def test_trust_approval_caching(self):
        # Test Approve All cache
        clear_approval_cache()
        self.assertEqual(classify_action("move_file"), TrustTier.YELLOW)

        # Simulate resolving with approve_all=True
        with patch("backend.utils.trust._external_approval_hook") as mock_hook:
            import threading
            def bg_request():
                return request_approval("move_file", "Move test")

            t = threading.Thread(target=bg_request)
            t.start()
            import time
            time.sleep(0.1)

            # Get pending request ID
            from backend.utils.trust import _pending_requests, _pending_lock
            with _pending_lock:
                req_id = list(_pending_requests.keys())[0]

            resolve_approval(req_id, approved=True, approve_all=True)
            t.join()

            # Now subsequent move_file should auto-approve without calling hook
            mock_hook.reset_mock()
            approved_again = request_approval("move_file", "Move second file")
            self.assertTrue(approved_again)
            mock_hook.assert_not_called()

            # Clear cache
            clear_approval_cache()
            # Now it should require approval again
            t2 = threading.Thread(target=bg_request)
            t2.start()
            time.sleep(0.1)
            mock_hook.assert_called()
            with _pending_lock:
                req_id2 = list(_pending_requests.keys())[0]
            resolve_approval(req_id2, approved=True)
            t2.join()

    def test_tool_registry_and_agents(self):
        self.assertIn("organize_files", TOOL_REGISTRY)
        self.assertIn("organize_desktop", TOOL_REGISTRY)

        reg = AgentRegistry()
        pa = reg.get_agent("personal_assistant")
        self.assertIn("organize_files", pa["allowed_tools"])

        wa = reg.get_agent("work_agent")
        self.assertIn("organize_files", wa["allowed_tools"])


if __name__ == "__main__":
    unittest.main()
