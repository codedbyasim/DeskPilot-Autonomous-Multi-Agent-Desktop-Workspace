"""
DeskPilot — Tool Library Registry & Resolver
Provides a central lookup mapping canonical tool names to Strands @tool functions.
Enforces strict tool-whitelisting as required by PROJECT_BRIEF.md Section 7, 8, & 13.
"""

from typing import List, Dict, Callable
from backend.utils.logger import get_logger

# Import tool functions
from backend.tools.web_tools import (
    search_web, read_webpage, search_and_read
)
from backend.tools.pdf_tools import (
    read_pdf, extract_pdf_tables, extract_pdf_invoice, list_pdfs_in_folder
)
from backend.tools.word_tools import (
    create_word_report, verify_word_document
)
from backend.tools.excel_tools import (
    create_excel_workbook, create_reconciliation_report,
    verify_excel_workbook, read_excel_file
)
from backend.tools.file_tools import (
    list_files, verify_file_exists, move_file, rename_file, delete_file,
    create_folder, open_file, take_screenshot, get_desktop_path, get_output_directory,
    read_file, write_file, organize_files
)
from backend.tools.system_tools import (
    winget_install
)

logger = get_logger("tools.registry")

TOOL_REGISTRY: Dict[str, Callable] = {
    # ── Web Research Tools ───────────────────────────────────────────────────
    "search_web": search_web,
    "read_webpage": read_webpage,
    "search_and_read": search_and_read,

    # ── PDF Document Tools ───────────────────────────────────────────────────
    "read_pdf": read_pdf,
    "extract_pdf_tables": extract_pdf_tables,
    "extract_pdf_invoice": extract_pdf_invoice,
    "list_pdfs_in_folder": list_pdfs_in_folder,

    # ── Word Report Generation Tools ─────────────────────────────────────────
    "create_word_report": create_word_report,
    "create_word_document": create_word_report,  # Alias
    "verify_word_document": verify_word_document,

    # ── Excel Workbook Tools ─────────────────────────────────────────────────
    "create_excel_workbook": create_excel_workbook,
    "create_workbook": create_excel_workbook,  # Alias
    "create_reconciliation_report": create_reconciliation_report,
    "verify_excel_workbook": verify_excel_workbook,
    "read_excel_file": read_excel_file,

    # ── File System & Desktop Control Tools ──────────────────────────────────
    "list_files": list_files,
    "verify_file_exists": verify_file_exists,
    "move_file": move_file,
    "rename_file": rename_file,
    "delete_file": delete_file,
    "create_folder": create_folder,
    "organize_files": organize_files,
    "organize_desktop": organize_files,  # Alias
    "organize_folder": organize_files,  # Alias
    "open_file": open_file,
    "take_screenshot": take_screenshot,
    "get_desktop_path": get_desktop_path,
    "get_output_directory": get_output_directory,
    "read_file": read_file,
    "read_text_file": read_file,  # Alias
    "write_file": write_file,
    "create_file": write_file,  # Alias

    # ── System / Software Installation Tools ─────────────────────────────────
    "winget_install": winget_install,
    "install_software": winget_install,  # Alias
}


def get_tools_for_agent(allowed_tools: List[str]) -> List[Callable]:
    """
    Given an agent's declared allowed_tools whitelist from its JSON configuration,
    resolves and returns the exact list of @tool callable functions.

    Hard Rules (Section 13):
    - Never grant a tool not in allowed_tools.
    - Never invent tools.
    - Returns only valid, known functions in the registry.
    """
    resolved_tools = []
    seen_names = set()

    for tool_name in allowed_tools:
        clean_name = tool_name.strip()
        if clean_name in seen_names:
            continue

        if clean_name in TOOL_REGISTRY:
            resolved_tools.append(TOOL_REGISTRY[clean_name])
            seen_names.add(clean_name)
        else:
            logger.warning(f"Tool '{clean_name}' requested by agent config is not in TOOL_REGISTRY; skipped.")

    return resolved_tools


def list_available_tool_names() -> List[str]:
    """Returns sorted list of all unique canonical tool names available for agents."""
    return sorted(list(TOOL_REGISTRY.keys()))
