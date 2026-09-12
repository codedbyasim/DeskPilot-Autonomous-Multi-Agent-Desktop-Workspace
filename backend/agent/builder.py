"""
DeskPilot — Custom Agent Builder (Section 9)
Uses Amazon Bedrock to draft a specialized custom agent configuration from a plain language description.
Translates technical tool names into plain-language permissions for user confirmation.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.tools import TOOL_REGISTRY
from backend.utils.logger import get_logger
from backend.utils.trust import classify_action
from backend.config.settings import BEDROCK_MODEL_ID

logger = get_logger("agent.builder")

# Human-readable metadata and permission descriptions for all 27 tools
TOOL_METADATA: Dict[str, Dict[str, Any]] = {
    # Web
    "search_web": {
        "title": "Web Search",
        "description": "Search DuckDuckGo and Wikipedia for live web information",
        "category": "Web",
        "tier": "GREEN",
    },
    "read_webpage": {
        "title": "Read Webpage",
        "description": "Fetch and extract clean text and markdown from web URLs",
        "category": "Web",
        "tier": "GREEN",
    },
    "search_and_read": {
        "title": "Comprehensive Research Sweep",
        "description": "Search the web and read top sources automatically",
        "category": "Web",
        "tier": "GREEN",
    },

    # PDF
    "read_pdf": {
        "title": "Read PDF Documents",
        "description": "Extract text, layout, and metadata from PDF files",
        "category": "PDF",
        "tier": "GREEN",
    },
    "extract_pdf_tables": {
        "title": "Extract PDF Tables",
        "description": "Extract tabular data and grids from PDF documents",
        "category": "PDF",
        "tier": "GREEN",
    },
    "extract_pdf_invoice": {
        "title": "Extract PDF Invoices",
        "description": "Extract invoice amounts, line items, and vendor details",
        "category": "PDF",
        "tier": "GREEN",
    },
    "list_pdfs_in_folder": {
        "title": "List PDF Files",
        "description": "Discover all PDF files in any directory or desktop folder",
        "category": "PDF",
        "tier": "GREEN",
    },

    # Word
    "create_word_report": {
        "title": "Create Word Reports (.docx)",
        "description": "Generate professionally styled Word documents with tables and headers",
        "category": "Documents",
        "tier": "GREEN",
    },
    "verify_word_document": {
        "title": "Verify Word Document",
        "description": "Inspect and verify Word document contents, tables, and readability",
        "category": "Documents",
        "tier": "GREEN",
    },

    # Excel
    "create_excel_workbook": {
        "title": "Create Excel Workbooks (.xlsx)",
        "description": "Generate multi-sheet Excel workbooks with formulas and styles",
        "category": "Spreadsheets",
        "tier": "GREEN",
    },
    "read_excel_file": {
        "title": "Read Excel Files",
        "description": "Read sheets, cell values, and data tables from Excel files",
        "category": "Spreadsheets",
        "tier": "GREEN",
    },
    "create_reconciliation_report": {
        "title": "Reconciliation Report",
        "description": "Compare two datasets or bank records and identify discrepancies",
        "category": "Spreadsheets",
        "tier": "GREEN",
    },
    "verify_excel_workbook": {
        "title": "Verify Excel Workbook",
        "description": "Verify formulas, data integrity, and styling in Excel files",
        "category": "Spreadsheets",
        "tier": "GREEN",
    },

    # OS Files
    "list_files": {
        "title": "List Files & Folders",
        "description": "Scan files in specified directories or desktop workspace",
        "category": "Files",
        "tier": "GREEN",
    },
    "verify_file_exists": {
        "title": "Verify File Exists",
        "description": "Check if a file exists and check file size and modified timestamp",
        "category": "Files",
        "tier": "GREEN",
    },
    "move_file": {
        "title": "Move File",
        "description": "Move files to other folders (Requires confirmation)",
        "category": "Files",
        "tier": "YELLOW",
    },
    "rename_file": {
        "title": "Rename File",
        "description": "Rename existing files (Requires confirmation)",
        "category": "Files",
        "tier": "YELLOW",
    },
    "delete_file": {
        "title": "Delete File",
        "description": "Permanently delete files (Requires explicit approval each time)",
        "category": "Files",
        "tier": "RED",
    },
    "create_folder": {
        "title": "Create Folder",
        "description": "Create new subdirectories or organization folders",
        "category": "Files",
        "tier": "GREEN",
    },
    "organize_files": {
        "title": "Organize Files",
        "description": "Automatically categorize and sort loose files into folders (Requires confirmation)",
        "category": "Files",
        "tier": "YELLOW",
    },
    "open_file": {
        "title": "Open File On Desktop",
        "description": "Launch files or reports in default Windows applications",
        "category": "Files",
        "tier": "GREEN",
    },
    "take_screenshot": {
        "title": "Take Screenshot",
        "description": "Capture screen area or desktop for visual verification",
        "category": "Files",
        "tier": "GREEN",
    },
    "get_desktop_path": {
        "title": "Get Desktop Path",
        "description": "Resolve user's Windows Desktop directory path",
        "category": "Files",
        "tier": "GREEN",
    },
    "get_output_directory": {
        "title": "Get Output Directory",
        "description": "Resolve DeskPilot public deliverables directory path",
        "category": "Files",
        "tier": "GREEN",
    },
    "delete_files": {
        "title": "Batch Delete Files (Recycle Bin)",
        "description": "Safely delete multiple files to Windows Recycle Bin in a single approval step",
        "category": "Files",
        "tier": "RED",
    },
    "explain_file_purpose": {
        "title": "Explain File Purpose",
        "description": "Inspect and explain where a file is, what it does, and whether it is safe to delete",
        "category": "Files",
        "tier": "GREEN",
    },
    "scan_and_categorize_files": {
        "title": "Scan & Categorize Files",
        "description": "Inspect and categorize loose files in Desktop or folders with plain-language explanations",
        "category": "Files",
        "tier": "GREEN",
    },
    "open_folder": {
        "title": "Open Folder In Explorer",
        "description": "Open containing folder in Windows File Explorer",
        "category": "Files",
        "tier": "GREEN",
    },
    "get_file_info": {
        "title": "Get File Info",
        "description": "Inspect file size, extension, and modification timestamps",
        "category": "Files",
        "tier": "GREEN",
    },

    # System & Hardware
    "winget_install": {
        "title": "Install Software (Allow-List Only)",
        "description": "Install pre-approved Windows packages via winget (Requires explicit Red-tier approval)",
        "category": "System",
        "tier": "RED",
    },
    "get_storage_status": {
        "title": "System Storage Monitor",
        "description": "Inspect PC drives, free space, and temp cache clutter with low storage alerts",
        "category": "System",
        "tier": "GREEN",
    },
    "clean_temporary_files": {
        "title": "Clean Temporary Files",
        "description": "Clean temporary cache files from user %TEMP% to reclaim gigabytes of storage",
        "category": "System",
        "tier": "YELLOW",
    },
    "get_system_info": {
        "title": "System Diagnostics & Hardware Specs",
        "description": "Inspect CPU, RAM, Battery, OS, Uptime, and network status",
        "category": "System",
        "tier": "GREEN",
    },
    "get_running_processes": {
        "title": "Active Processes Monitor",
        "description": "Identify top memory or CPU-consuming applications and background tasks",
        "category": "System",
        "tier": "GREEN",
    },

    # User Profile & Dynamic Interaction
    "ask_user_form": {
        "title": "Interactive Questionnaire & Clarification Form",
        "description": "Pop up custom runtime forms to onboard users, collect background details, or ask clarification questions",
        "category": "User Context",
        "tier": "GREEN",
    },
    "get_user_profile": {
        "title": "Access User Memory & Profile",
        "description": "Retrieve saved user preferences, health background, and identity facts from local storage",
        "category": "User Context",
        "tier": "GREEN",
    },
    "update_user_profile": {
        "title": "Save User Memory Fact",
        "description": "Store specific facts or preferences learned during conversations into local storage",
        "category": "User Context",
        "tier": "GREEN",
    },
}

BUILDER_PROMPT_TEMPLATE = """You are DeskPilot's Custom Agent Architect.
A user wants to create a new AI desktop assistant with this description:
"{description}"

Available tools in DeskPilot (CHOOSE ONLY FROM THIS EXACT LIST, DO NOT INVENT TOOLS):
{available_tools}

Return a valid JSON object matching this schema:
{{
  "name": "Short, clear agent name (3-5 words max)",
  "description": "1-2 sentence description of what this agent does for the user",
  "icon": "One icon name from: sparkles, search, file-text, book, calculator, briefcase, shield, heart, home, folder, cpu",
  "color": "One color from: green, purple, red, blue, indigo, amber",
  "persona": "Detailed system prompt defining this agent's specialty, tone, workflow, and safety boundaries",
  "allowed_tools": ["only_valid_tool_names_from_the_available_list"]
}}

Rules:
1. ONLY pick tools strictly relevant to the user's requested workflow from the available tools list.
2. If the user doesn't specify tools, use your best judgment to select sensible defaults.
3. NEVER invent tool names outside the provided list.
4. Output ONLY valid JSON, no surrounding commentary.
"""


class AgentBuilder:
    """
    Builds custom agent drafts by calling Amazon Bedrock with a structured prompt,
    or falls back to an intelligent keyword synthesizer if offline or in testing.
    """

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator

    def get_tool_metadata(self, tool_name: str) -> Dict[str, Any]:
        """Returns plain-language permission metadata for a tool."""
        if tool_name in TOOL_METADATA:
            return TOOL_METADATA[tool_name]
        return {
            "title": tool_name.replace("_", " ").title(),
            "description": f"Executes {tool_name}",
            "category": "Other",
            "tier": classify_action(tool_name),
        }

    def draft_agent(self, description: str) -> Dict[str, Any]:
        """
        Drafts a custom agent specification from a natural language prompt.
        Attempts Bedrock LLM generation first; falls back to heuristic drafting if unavailable.
        """
        clean_desc = description.strip()
        if not clean_desc:
            return {"success": False, "error": "Description cannot be empty"}

        logger.info(f"Drafting custom agent for description: '{clean_desc[:60]}...'")

        # Attempt Bedrock Generation
        draft = self._call_bedrock_builder(clean_desc)
        if not draft:
            logger.info("Bedrock draft unavailable or returned empty; using intelligent heuristic synthesizer")
            draft = self._heuristic_draft(clean_desc)

        # Enforce tool whitelist & sanitization
        valid_tools = [t for t in draft.get("allowed_tools", []) if t in TOOL_REGISTRY]
        if not valid_tools:
            valid_tools = ["search_web", "search_and_read"]

        # Deduplicate tools
        valid_tools = list(dict.fromkeys(valid_tools))

        # Generate unique ID slug
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', draft.get("name", "custom").lower()).strip('_')[:20]
        agent_id = f"custom_{slug}_{uuid.uuid4().hex[:6]}"

        final_draft = {
            "id": agent_id,
            "name": draft.get("name", "Custom Assistant"),
            "description": draft.get("description", clean_desc),
            "icon": draft.get("icon", "sparkles"),
            "color": draft.get("color", "indigo"),
            "persona": draft.get("persona", f"You are a specialized assistant for: {clean_desc}"),
            "allowed_tools": valid_tools,
            "category": "custom",
            "created_by": "user",
            "created_at": datetime.now().isoformat(),
            "status": "draft",
        }

        # Build permissions breakdown for confirmation screen
        permissions = []
        for tool in valid_tools:
            meta = self.get_tool_metadata(tool)
            permissions.append({
                "tool": tool,
                "title": meta.get("title", tool),
                "description": meta.get("description", ""),
                "tier": meta.get("tier", "GREEN"),
                "category": meta.get("category", "General"),
            })

        return {
            "success": True,
            "draft": final_draft,
            "permissions": permissions,
        }

    def _call_bedrock_builder(self, description: str) -> Optional[Dict[str, Any]]:
        """Invokes Amazon Bedrock to draft the agent JSON specification."""
        try:
            from backend.agent.orchestrator import AgentOrchestrator
            orch = self.orchestrator or AgentOrchestrator()
            model = orch.get_model()

            available_tools_str = "\n".join(
                f"- {name}: {meta['description']}"
                for name, meta in TOOL_METADATA.items()
            )

            prompt = BUILDER_PROMPT_TEMPLATE.format(
                description=description,
                available_tools=available_tools_str
            )

            from strands import Agent
            agent = Agent(
                model=model,
                system_prompt="You are DeskPilot's Custom Agent Architect. You only output valid JSON."
            )
            response = agent(prompt)
            raw_text = str(response).strip()

            # Parse JSON from response
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return data

        except Exception as e:
            logger.warning(f"Bedrock custom builder call failed: {e}")

        return None

    def _heuristic_draft(self, description: str) -> Dict[str, Any]:
        """Synthesizes a high-quality agent draft using semantic keyword rules."""
        lower = description.lower()
        tools = ["search_web"]
        icon = "sparkles"
        color = "indigo"
        name = description.title()[:35]

        # Domain matching
        if any(k in lower for k in ["pdf", "paper", "reading", "document", "invoice", "receipt"]):
            tools.extend(["read_pdf", "extract_pdf_tables", "list_pdfs_in_folder"])
            icon = "file-text"
            color = "blue"
            if "invoice" in lower or "receipt" in lower:
                tools.append("extract_pdf_invoice")

        if any(k in lower for k in ["word", "report", "doc", "summary", "article"]):
            tools.extend(["create_word_report", "verify_word_document"])
            if icon == "sparkles":
                icon = "book"

        if any(k in lower for k in ["excel", "sheet", "spreadsheet", "data", "finance", "budget", "accounting"]):
            tools.extend(["create_excel_workbook", "read_excel_file", "verify_excel_workbook"])
            icon = "calculator"
            color = "purple"
            if "reconcil" in lower or "discrepanc" in lower:
                tools.append("create_reconciliation_report")

        if any(k in lower for k in ["research", "market", "competitor", "web", "news"]):
            tools.extend(["search_and_read", "read_webpage"])
            if icon == "sparkles":
                icon = "search"

        if any(k in lower for k in ["file", "folder", "desktop", "organize", "clean"]):
            tools.extend(["list_files", "create_folder", "move_file", "rename_file"])
            icon = "folder"
            color = "green"

        if any(k in lower for k in ["delete", "remove", "clean up"]):
            tools.append("delete_file")

        persona = (
            f"You are a specialized custom agent designed for: {description.strip()}.\n"
            f"Your responsibilities: execute tasks methodically, synthesize accurate outputs using your authorized tools, "
            f"and always request human approval for Yellow or Red tier file actions."
        )

        return {
            "name": name,
            "description": description,
            "icon": icon,
            "color": color,
            "persona": persona,
            "allowed_tools": list(dict.fromkeys(tools)),
        }
