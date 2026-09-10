"""
DeskPilot — Application Settings & Configuration
Loads environment variables and provides app-wide constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

import sys

# Project root path (handles both source execution and PyInstaller frozen bundle)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    EXE_DIR = Path(sys.executable).parent.resolve()
    PROJECT_ROOT = BASE_DIR
    AGENTS_DIR = EXE_DIR / "agents" if (EXE_DIR / "agents").exists() else BASE_DIR / "agents"
    FRONTEND_DIR = BASE_DIR / "frontend"
    LOGS_DIR = EXE_DIR / "logs"
    CHATS_DIR = EXE_DIR / "chats"
else:
    PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
    EXE_DIR = PROJECT_ROOT
    AGENTS_DIR = PROJECT_ROOT / "agents"
    FRONTEND_DIR = PROJECT_ROOT / "frontend"
    LOGS_DIR = PROJECT_ROOT / "logs"
    CHATS_DIR = PROJECT_ROOT / "chats"

# Load .env file from root or DeskPilot directory
_env_root = PROJECT_ROOT / ".env"
_env_sub = PROJECT_ROOT / "DeskPilot" / ".env"
_env_exe = EXE_DIR / ".env"

if _env_exe.exists():
    load_dotenv(dotenv_path=_env_exe)
elif _env_root.exists():
    load_dotenv(dotenv_path=_env_root)
elif _env_sub.exists():
    load_dotenv(dotenv_path=_env_sub)
else:
    load_dotenv()

# ── AWS / Bedrock ──────────────────────────────────────────────────────────────
BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "") or os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")

# ── Directories ───────────────────────────────────────────────────────────────
AGENTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CHATS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = LOGS_DIR  # Alias for backward compatibility

DEFAULT_OUTPUT_DIR = Path(
    os.getenv("DEFAULT_OUTPUT_DIR", str(Path.home() / "Desktop" / "DeskPilot_Output"))
)
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Research & Web Settings ───────────────────────────────────────────────────
MAX_RESEARCH_SOURCES = int(os.getenv("MAX_RESEARCH_SOURCES", "5"))
MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
REQUEST_TIMEOUT = 30  # seconds for HTTP requests

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── App Identity ──────────────────────────────────────────────────────────────
APP_NAME = "DeskPilot"
APP_VERSION = "2.0.0"
APP_TAGLINE = "Multi-Agent Desktop Assistant"

# ── Trust Tiers ───────────────────────────────────────────────────────────────
GREEN_ACTIONS = {
    "open_browser", "search_web", "read_webpage", "read_pdf",
    "create_word_document", "create_word_report", "create_workbook",
    "create_excel_workbook", "create_reconciliation_report", "read_excel_file",
    "list_files", "verify_file_exists", "create_folder", "read_file",
    "open_file", "take_screenshot", "get_desktop_path", "get_output_directory",
    "extract_pdf_tables", "extract_pdf_invoice", "list_pdfs_in_folder",
    "verify_word_document", "verify_excel_workbook", "search_and_read"
}
YELLOW_ACTIONS = {
    "modify_existing_file", "overwrite_document", "write_spreadsheet",
    "move_file", "rename_file", "organize_files", "write_file"
}
RED_ACTIONS = {
    "delete_file", "send_email", "submit_form", "financial_transaction",
    "bulk_delete", "publish_content", "install_software", "system_execute"
}
GREEN_TIER_ACTIONS = GREEN_ACTIONS
YELLOW_TIER_ACTIONS = YELLOW_ACTIONS
RED_TIER_ACTIONS = RED_ACTIONS

# ── Winget Software Allow-List (PROJECT_BRIEF.md Section 10 & 13) ──────────────
# Only allow installs via winget against this explicit allow-list. Never arbitrary .exe.
WINGET_ALLOWLIST = {
    "Mozilla.Firefox": "Firefox Browser",
    "Google.Chrome": "Google Chrome",
    "Microsoft.VisualStudioCode": "Visual Studio Code",
    "Git.Git": "Git Version Control",
    "7zip.7zip": "7-Zip Compression Utility",
    "Notepad++.Notepad++": "Notepad++ Text Editor",
    "VideoLAN.VLC": "VLC Media Player",
    "Obsidian.Obsidian": "Obsidian Note Taking",
    "SlackTechnologies.Slack": "Slack Desktop",
    "Zoom.Zoom": "Zoom Meetings",
}
