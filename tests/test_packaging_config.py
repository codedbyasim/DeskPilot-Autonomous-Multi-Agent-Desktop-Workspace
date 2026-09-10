"""
Unit tests for DeskPilot Packaging Configuration & Submission Assets (Phases 10 & 11).
Validates PyInstaller spec, Inno Setup script, build automation, and documentation.
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class TestPackagingConfig(unittest.TestCase):
    """Verifies all packaging files, installer configurations, and hackathon assets."""

    def test_deskpilot_spec_exists_and_valid(self):
        """deskpilot.spec must exist and contain required PyInstaller directives."""
        spec_path = PROJECT_ROOT / "deskpilot.spec"
        self.assertTrue(spec_path.exists(), "deskpilot.spec must exist at project root")

        content = spec_path.read_text(encoding="utf-8")
        self.assertTrue(
            "'backend', 'app.py'" in content or "backend/app.py" in content.replace("\\", "/"),
            "Entry point must be backend/app.py",
        )
        self.assertIn("frontend", content, "datas must include frontend bundle")
        self.assertIn("agents", content, "datas must include agents bundle")
        self.assertIn("assets", content, "datas must include assets bundle")
        self.assertIn("icon.ico", content, "Icon must be specified as icon.ico")
        self.assertIn("DeskPilot", content, "Application name must be DeskPilot")
        self.assertIn("webview", content, "hiddenimports must include pywebview")
        self.assertIn("strands", content, "hiddenimports must include strands")
        self.assertIn("boto3", content, "hiddenimports must include boto3")

    def test_inno_setup_script_exists_and_valid(self):
        """installer/deskpilot_setup.iss must exist and have correct application metadata."""
        iss_path = PROJECT_ROOT / "installer" / "deskpilot_setup.iss"
        self.assertTrue(iss_path.exists(), "installer/deskpilot_setup.iss must exist")

        content = iss_path.read_text(encoding="utf-8")
        self.assertIn('MyAppName "DeskPilot"', content)
        self.assertIn('MyAppVersion "2.0.0"', content)
        self.assertIn('DeskPilot.exe', content)
        self.assertIn('icon.ico', content)
        self.assertIn('dist\\DeskPilot', content)
        self.assertIn('dist\\installer', content)
        self.assertIn('DeskPilot-Setup-v', content)

    def test_build_scripts_exist(self):
        """scripts/build.ps1 and scripts/build.bat must exist."""
        ps1_path = PROJECT_ROOT / "scripts" / "build.ps1"
        bat_path = PROJECT_ROOT / "scripts" / "build.bat"

        self.assertTrue(ps1_path.exists(), "scripts/build.ps1 must exist")
        self.assertTrue(bat_path.exists(), "scripts/build.bat must exist")

        ps1_content = ps1_path.read_text(encoding="utf-8")
        self.assertIn("deskpilot.spec", ps1_content)
        self.assertIn("DeskPilot.exe", ps1_content)

        bat_content = bat_path.read_text(encoding="utf-8")
        self.assertIn("deskpilot.spec", bat_content)
        self.assertIn("DeskPilot.exe", bat_content)

    def test_assets_integrity(self):
        """assets/icon.ico and assets/logo.png must exist with non-zero size."""
        icon_path = PROJECT_ROOT / "assets" / "icon.ico"
        logo_path = PROJECT_ROOT / "assets" / "logo.png"

        self.assertTrue(icon_path.exists(), "assets/icon.ico must exist")
        self.assertTrue(logo_path.exists(), "assets/logo.png must exist")

        self.assertGreater(icon_path.stat().st_size, 1024, "icon.ico must be larger than 1KB")
        self.assertGreater(logo_path.stat().st_size, 1024, "logo.png must be larger than 1KB")

        # Verify ICO header
        with open(icon_path, "rb") as f:
            header = f.read(4)
            # Standard ICO format header: 0x00 0x00 0x01 0x00
            self.assertEqual(header, b"\x00\x00\x01\x00", "icon.ico must have valid ICO magic bytes")

        # Verify PNG header
        with open(logo_path, "rb") as f:
            header = f.read(8)
            # Standard PNG format header
            self.assertEqual(header, b"\x89PNG\r\n\x1a\n", "logo.png must have valid PNG magic bytes")

    def test_demo_script_structure(self):
        """DEMO_SCRIPT.md must exist and outline the 3-minute hackathon presentation."""
        demo_path = PROJECT_ROOT / "DEMO_SCRIPT.md"
        self.assertTrue(demo_path.exists(), "DEMO_SCRIPT.md must exist")

        content = demo_path.read_text(encoding="utf-8")
        self.assertIn("Act 1", content)
        self.assertIn("Act 2", content)
        self.assertIn("Act 3", content)
        self.assertIn("Act 4", content)
        self.assertIn("Act 5", content)
        self.assertIn("Strands Agents SDK", content)
        self.assertIn("Bedrock", content)
        self.assertIn("Trust Engine", content)
        self.assertIn("Custom Agent Builder", content)

    def test_readme_structure(self):
        """README.md must detail architecture, trust tiers, quickstart, and packaging."""
        readme_path = PROJECT_ROOT / "README.md"
        self.assertTrue(readme_path.exists(), "README.md must exist")

        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("DeskPilot — Multi-Agent Windows Desktop Assistant", content)
        self.assertIn("Strands Agents SDK", content)
        self.assertIn("Amazon Bedrock", content)
        self.assertIn("Trust & Safety Model", content)
        self.assertIn("Custom Agent Builder", content)
        self.assertIn("Packaging & Building the Installer", content)

    def test_settings_frozen_path_support(self):
        """Verify that settings.py resolves directories properly whether frozen or source."""
        from backend.config import settings

        self.assertTrue(settings.PROJECT_ROOT.exists())
        self.assertTrue(settings.AGENTS_DIR.exists())
        self.assertTrue(settings.FRONTEND_DIR.exists())
        self.assertTrue((settings.FRONTEND_DIR / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
