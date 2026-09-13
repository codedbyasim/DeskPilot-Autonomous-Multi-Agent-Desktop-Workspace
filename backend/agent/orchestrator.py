"""
DeskPilot — Dynamic Multi-Agent Orchestrator
Uses the Strands Agents SDK and Amazon Bedrock to dynamically instantiate and run
any agent from the registry (default, template, or custom) with strict tool-whitelisting.
"""

import os
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, Dict, Any, List

from strands import Agent
from strands.models import BedrockModel

from backend.config.settings import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_DEFAULT_REGION, BEDROCK_MODEL_ID, BEDROCK_API_KEY
)
from backend.agent.registry import AgentRegistry
from backend.tools import get_tools_for_agent, TOOL_REGISTRY
from backend.utils.logger import AuditLogger, get_logger
from backend.utils.trust import set_approval_hook
from backend.utils.user_memory import get_user_memory_context

logger = get_logger("agent.orchestrator")

# Standard core guidelines combined with every agent's custom persona
CORE_GUARDRAILS = """
GLOBAL OPERATING RULES (MANDATORY):
1. STRICT DATA REQUIREMENT (NO FABRICATION): You MUST NEVER hallucinate or fabricate data (e.g., budgets, real estate listings, financial totals, reports). If the user asks you to generate a data-driven deliverable, you MUST verify that you have been provided with real raw data (either via a file using your tools or explicit text in the chat). If you do not have the real data, YOU MUST STOP IMMEDIATELY and output a message asking the user to provide the raw data (e.g., 'Please provide the raw data file or upload the document'). Do NOT use placeholder or sample figures under any circumstances.
2. TOOL WHITELIST: You may only use tools explicitly authorized in your current configuration. Never claim capabilities outside this set.
3. NO TOOL CALL LOOPS: If a tool call fails or returns an error, DO NOT call it repeatedly in a loop. Stop, explain the error to the user, and offer alternatives.
4. CHAT FIRST vs FILE GENERATION DIRECTIVE (CRITICAL):
   - DO NOT automatically generate or create physical files (.xlsx, .docx, .pdf, .csv, etc.) on the user's desktop unless the user EXPLICITLY commands you to generate, create, export, save, or write a file (e.g. 'create an excel file', 'generate an excel sheet', 'save as word document', 'export report to excel', 'download file').
   - When the user asks a question, requests help, asks to make/plan/calculate a budget, seeks advice, or chats (e.g. 'help to make monthly budget', 'how can I save money', 'what is my budget', 'plan my diet', 'explain this'):
     * ALWAYS RESPOND DIRECTLY IN THE CHAT WINDOW with a comprehensive, well-structured Markdown response (including clear markdown tables | Col 1 | Col 2 |, bullet points, and calculations).
     * DO NOT create an Excel or Word file on the user's desktop unless explicitly requested!
     * At the end of your chat answer, you may politely offer: 'Would you like me to export this into an Excel spreadsheet or Word report for you?'
   - When the user DOES explicitly request an Excel workbook (create_excel_workbook):
     * Respect the user's preferred currency (e.g. PKR, EUR, GBP, INR, USD). Do NOT hardcode dollar signs ($) when the user uses PKR or other currencies.
     * Pass 'headers' as a clean list of column names, e.g. ["Category", "Amount (PKR)"] or ["Category", "Amount"].
     * Pass 'rows' as a 2D list of rows, e.g. [["Salary", 5000], ["Rent", 1500]].
     * Pass amounts as numbers (e.g. 5000, 1500.50), not crammed text strings or zeros.
     * After creation, call verify_excel_workbook on the returned file path.
   - When the user DOES explicitly request a Word document (create_word_report):
     * Structure content with Markdown headers (# Title, ## Section), bullet points (- item), and Markdown tables (| Col 1 | Col 2 |).
     * After creation, call verify_word_document on the returned file path.
5. ACTION & EXECUTION DIRECTIVE (SYSTEM TOOLS ONLY):
   - When the user asks to organize, move, clean up, categorize, or manage desktop files or install software (e.g. "organize desktop files into categorized folders", "you move all this files", "move all desktop files into specific folder", "take permission for me", "clean up desktop", "install app"):
     * ALWAYS ACTUALLY EXECUTE the relevant authorized tool (`organize_files`, `move_file`, `winget_install`, etc.).
     * NEVER respond with text instructions telling the user to manually move files, drag and drop in File Explorer, or configure Windows UAC/administrator permissions.
     * DeskPilot's built-in Human-in-the-Loop trust framework automatically prompts the user with an interactive confirmation modal dialog when you invoke the tool! Invoking the tool IS how permission is requested.
     * When organizing desktop files or sorting loose files into folders, invoke `organize_files` directly.
6. RESEARCH QUALITY: When performing web research, synthesize key findings into structured markdown tables (| Col 1 | Col 2 |) with source URLs.
7. DYNAMIC USER ONBOARDING & INTERACTIVE CLARIFICATION FORMS:
   - When communicating with the user, if you lack vital domain background or onboarding information (for example: Health Agent needs age, wellness goals, and allergies; Finance Agent needs preferred currency, numeric monthly income, and numeric expenses; Work Agent needs job role and team standards; Personal Assistant needs user name and daily priorities), AND these are not already recorded in the USER PROFILE & LOCAL MEMORY CONTEXT:
     * On your first query, YOU MUST invoke the `ask_user_form` tool!
     * When asking for budget details, ALWAYS prompt for NUMERIC amounts (e.g. Monthly Income Amount, Fixed Expenses Amount, Savings Target) and preferred currency so you have real numbers to work with.
     * If the user provided text descriptions like 'pocket money' or 'lunch', DO NOT assume 0; ask the user politely in chat for the numerical amounts.
     * Decide the appropriate question fields dynamically based on your persona and what you genuinely need to know.
     * DeskPilot will immediately display a modern popup form dialog on the user's screen.
     * The user's submitted answers are automatically stored in local storage (`user_profiles.json`) so you remember them permanently.
   - Ambiguity & Confusion: Whenever instructions are ambiguous, confusing, or missing necessary choices (e.g. date ranges, report formats, file destinations), DO NOT guess — invoke `ask_user_form` to prompt the user directly with custom question fields.
8. DOCUMENT READING & EDITING DIRECTIVE:
   - When the user asks to read, inspect, understand, or edit existing Word documents (.docx), PDFs (.pdf), or spreadsheets (.xlsx) and provides a file path or filename (e.g. 'TB_Lab_Report.docx', 'Desktop/Report.docx', 'ledger.xlsx', 'invoice.pdf'):
     * NEVER require the user to provide a full absolute path if they provide a filename or relative path. Use the document tools directly; they automatically resolve the file across Desktop, Documents, workspace, and outputs.
     * ALWAYS read and understand the file first using `read_word_document`, `read_pdf`, `extract_pdf_tables`, or `read_excel_file`.
     * When editing:
       - For Word documents (.docx): invoke `edit_word_document` with targeted `replacements` (e.g. {'Old Text': 'New Text'}), section updates, or appended markdown content.
       - For PDFs (.pdf): invoke `edit_pdf_document` with requested modifications. DeskPilot extracts the content, applies edits, and compiles a clean, editable Word (.docx) or PDF deliverable.
       - For Spreadsheets (.xlsx): invoke `edit_excel_file` with cell updates and/or appended rows.
     * Verify the modified file and present the deliverable so the user can open it with one click.
"""


class AgentOrchestrator:
    """
    Orchestrates dynamic agent execution with Amazon Bedrock and Strands Agents SDK.
    Loads agent configurations from AgentRegistry, resolves authorized tools,
    and streams events to callbacks and the frontend.
    """

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ):
        self.registry = registry or AgentRegistry()
        self.audit = AuditLogger()
        self.on_log = on_log
        self.on_event = on_event
        self._active_agents: Dict[str, Agent] = {}
        self._lock = threading.Lock()

    def get_model(self) -> BedrockModel:
        """
        Initializes and returns the BedrockModel instance.
        """
        try:
            if BEDROCK_API_KEY:
                logger.info(f"Connecting to Bedrock via API key (Model: {BEDROCK_MODEL_ID})")
                return BedrockModel(
                    api_key=BEDROCK_API_KEY,
                    model_id=BEDROCK_MODEL_ID,
                    streaming=False,
                )
            else:
                logger.info(f"Connecting to Bedrock via AWS session (Region: {AWS_DEFAULT_REGION}, Model: {BEDROCK_MODEL_ID})")
                import boto3
                session = boto3.Session(
                    aws_access_key_id=AWS_ACCESS_KEY_ID or None,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
                    region_name=AWS_DEFAULT_REGION,
                )
                return BedrockModel(
                    boto_session=session,
                    model_id=BEDROCK_MODEL_ID,
                    streaming=False,
                )
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock model: {e}")
            raise

    def build_agent(
        self,
        agent_id: str,
        streaming_callback: Optional[Callable] = None,
    ) -> Agent:
        """
        Dynamically constructs a Strands Agent instance for the requested agent_id:
        1. Loads agent definition from AgentRegistry.
        2. Filters tools to only those declared in allowed_tools (whitelist enforcement).
        3. Constructs composite system prompt (persona + core guardrails).
        4. Initializes Strands Agent with BedrockModel.
        """
        agent_def = self.registry.get_agent(agent_id)
        if not agent_def:
            raise ValueError(f"Agent '{agent_id}' not found in registry")

        allowed_tool_names = agent_def.get("allowed_tools", [])
        tools = get_tools_for_agent(allowed_tool_names)

        # Composite system prompt: persona + user local memory + global operating guardrails
        persona = agent_def.get("persona", "")
        memory_context = get_user_memory_context(agent_id)
        system_prompt = f"{persona.strip()}\n\n{memory_context.strip()}\n\n{CORE_GUARDRAILS.strip()}"

        model = self.get_model()

        logger.info(
            f"Building dynamic agent '{agent_def.get('name')}' ({agent_id}) "
            f"with {len(tools)} authorized tools: {allowed_tool_names}"
        )

        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            callback_handler=streaming_callback,
        )
        return agent

    def _create_callback_handler(
        self,
        task_id: str,
        agent_id: str,
        on_log: Optional[Callable[[str], None]] = None,
        on_step: Optional[Callable[[str, str], None]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Callable:
        """
        Creates a Strands streaming callback handler that parses kwargs and emits
        clean events for text chunks, reasoning, and tool execution status.
        Tool logs are NOT injected into text chunks.
        """
        def _callback(**kwargs):
            # 1. Streaming text data (content chunk)
            data = kwargs.get("data", "")
            if data:
                if on_chunk:
                    on_chunk(data)
                elif on_log:
                    on_log(data)

            # 2. Reasoning text (thinking block)
            reasoning = kwargs.get("reasoningText", "")
            if reasoning:
                thinking_block = f"<thinking>\n{reasoning}\n</thinking>\n"
                if on_chunk:
                    on_chunk(thinking_block)
                elif on_log:
                    on_log(thinking_block)

            # 3. Tool use start event
            event = kwargs.get("event", {})
            tool_use = (event.get("contentBlockStart", {})
                             .get("start", {})
                             .get("toolUse"))
            if tool_use:
                tool_name = tool_use.get("name", "unknown")
                tool_args = tool_use.get("input", {})
                logger.info(f"[{task_id}] Tool use: {tool_name} (args: {tool_args})")
                if on_log:
                    on_log(f"Executing tool: {tool_name}")
                if on_step:
                    on_step(tool_name, "executing")

                self.audit.log_action(
                    action=tool_name,
                    parameters=tool_args if isinstance(tool_args, dict) else {},
                    result=None,
                    agent_id=agent_id,
                )

                if self.on_event:
                    self.on_event("deskpilot:step", {
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "tool": tool_name,
                        "message": f"Executing tool: {tool_name}",
                        "timestamp": datetime.now().isoformat(),
                    })

            # 4. Tool result event
            tool_result = kwargs.get("tool_result", {})
            if tool_result:
                content = str(tool_result.get("content", ""))
                summary = content[:200]
                if on_log:
                    on_log(f"Tool result: {summary}")
                if on_step:
                    on_step("tool_result", "complete")

                self.audit.log_action(
                    action="tool_result",
                    parameters={},
                    result=summary,
                    success=True,
                    agent_id=agent_id,
                )

        return _callback

    def run_task(
        self,
        agent_id: str,
        instruction: str,
        task_id: Optional[str] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_step: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a task instruction using the specified agent.
        Streams real-time events, manages status in the registry, and logs to audit history.
        """
        task_id = task_id or f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clean_instruction = instruction.strip()

        agent_def = self.registry.get_agent(agent_id)
        if not agent_def:
            return {"success": False, "error": f"Agent '{agent_id}' not found"}

        self.registry.set_agent_status(agent_id, "running")
        logger.info(f"Starting execution of task [{task_id}] for '{agent_id}': {clean_instruction[:60]}...")

        merged_on_log = on_log or self.on_log
        cb = self._create_callback_handler(task_id, agent_id, merged_on_log, on_step)

        try:
            agent = self.build_agent(agent_id, streaming_callback=cb)
            response = agent(clean_instruction)
            result_str = str(response)

            logger.info(f"Task [{task_id}] for agent '{agent_id}' completed successfully.")
            return {
                "success": True,
                "task_id": task_id,
                "agent_id": agent_id,
                "result": result_str,
                "audit_path": str(self.audit.get_audit_path()),
            }

        except Exception as e:
            error_msg = f"Task execution failed: {str(e)}"
            logger.error(f"Error executing task [{task_id}] on '{agent_id}': {e}")
            if merged_on_log:
                merged_on_log(f"\n❌ {error_msg}")
            return {
                "success": False,
                "task_id": task_id,
                "agent_id": agent_id,
                "error": error_msg,
            }
        finally:
            self.registry.set_agent_status(agent_id, "active")

    def run_chat_turn(
        self,
        session_id: str,
        agent_id: str,
        user_message: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        task_id: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_step: Optional[Callable[[str, str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a single conversational turn in a multi-turn chat session.
        Preserves conversation context and captures tool calls and deliverables.
        """
        import re
        task_id = task_id or f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clean_message = user_message.strip()
        history = chat_history or []

        agent_def = self.registry.get_agent(agent_id)
        if not agent_def:
            return {"success": False, "error": f"Agent '{agent_id}' not found"}

        self.registry.set_agent_status(agent_id, "running")
        logger.info(f"Starting chat turn [{task_id}] session '{session_id}' on agent '{agent_id}'")

        tools_executed = []
        deliverables_found = []

        def _step_wrapper(tool_name: str, status: str):
            if tool_name not in tools_executed:
                tools_executed.append(tool_name)
            if on_step:
                on_step(tool_name, status)

        cb = self._create_callback_handler(
            task_id=task_id,
            agent_id=agent_id,
            on_log=on_log,
            on_step=_step_wrapper,
            on_chunk=on_chunk,
        )

        # Build context prompt incorporating prior turns if available
        tool_directive = (
            "CRITICAL CHAT DIRECTIVE:\n"
            "1. CHAT RESPONSE FIRST: If the user is asking for assistance, budgeting, planning, advice, or questions (e.g. 'help to make monthly budget'), answer directly in the chat with structured markdown tables and helpful advice. DO NOT call `create_excel_workbook` or `create_word_report` unless the user explicitly requested a file or document to be created/saved/exported!\n"
            "2. DESKTOP SYSTEM ACTIONS: If the user explicitly asks to organize desktop files, move files, or install software, execute the authorized tool (`organize_files`, `move_file`, `winget_install`).\n"
            "3. CURRENCY & NUMERICAL ACCURACY: Use the user's preferred currency from memory (e.g. PKR, EUR, USD, INR). Never show dollar signs ($) when the user specified another currency. If numeric amounts are missing (e.g., user wrote 'pocket money' or 'lunch'), ask the user in chat for the numerical amounts rather than assuming 0."
        )
        if history:
            prompt_turns = ["CONVERSATION HISTORY:"]
            for h in history[-6:]:
                role = "User" if h.get("role") == "user" else f"{agent_def.get('name', 'Assistant')}"
                prompt_turns.append(f"{role}: {h.get('content', '')}")
            prompt_turns.append(f"CURRENT REQUEST:\nUser: {clean_message}\n\n{tool_directive}")
            full_prompt = "\n".join(prompt_turns)
        else:
            full_prompt = f"User Request: {clean_message}\n\n{tool_directive}"

        try:
            agent = self.build_agent(agent_id, streaming_callback=cb)
            response = agent(full_prompt)
            result_str = str(response)

            # Detect any deliverables in result text
            matches = re.findall(r'([a-zA-Z]:[^\s\r\n"\']+\.(?:docx|xlsx|pdf|png|csv))', result_str)
            for m in matches:
                clean_path = m.strip()
                if clean_path not in deliverables_found and Path(clean_path).exists():
                    deliverables_found.append(clean_path)

            logger.info(f"Chat turn [{task_id}] session '{session_id}' completed successfully.")
            return {
                "success": True,
                "task_id": task_id,
                "session_id": session_id,
                "agent_id": agent_id,
                "response": result_str,
                "tool_calls": tools_executed,
                "deliverables": deliverables_found,
            }

        except Exception as e:
            error_msg = f"Chat turn execution failed: {str(e)}"
            logger.error(f"Error in chat turn [{task_id}] session '{session_id}': {e}")
            return {
                "success": False,
                "task_id": task_id,
                "session_id": session_id,
                "agent_id": agent_id,
                "error": error_msg,
            }
        finally:
            self.registry.set_agent_status(agent_id, "active")
