# DeskPilot — Technical Architecture & System Design

[![Amazon Bedrock](https://img.shields.io/badge/AWS-Amazon_Bedrock_Nova_Pro-FF9900?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![Strands Agents SDK](https://img.shields.io/badge/Orchestrator-Strands_Agents_SDK-7952B3)](https://github.com/strands-agents)
[![Framework](https://img.shields.io/badge/Desktop_Shell-pywebview_WebView2-0078D7)](https://pywebview.flowrl.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)

DeskPilot is an enterprise-grade, autonomous multi-agent desktop workspace built for Windows. It couples cloud foundation model intelligence (**Amazon Bedrock Nova Pro**) with local operating system automation, office document processing, dynamic user memory, and an unbypassable 3-tier Human-in-the-Loop (HITL) safety framework.

![DeskPilot End-to-End System Architecture](architecture_diagram.png)

---

## 1. High-Level Architecture Overview

DeskPilot is architected into five decoupled layers:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       1. PRESENTATION LAYER                             │
│   • Microsoft Edge WebView2 (pywebview)   • Browser Web Shell (Flask)   │
│   • Responsive Glassmorphism SPA (CSS Grid/Flex, Drawer Navigation)     │
│   • Live Streaming Chat with <thinking>   • Dynamic Modals & Forms      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Bidirectional RPC / Events
┌────────────────────────────────────▼────────────────────────────────────┐
│                         2. BRIDGE & API LAYER                           │
│   • DeskPilotBridge (Python Thread Pool)  • Flask REST & SSE Router     │
│   • Approval Event Synchronization        • Form Engine Synchronizer    │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Invocation & Event Bus
┌────────────────────────────────────▼────────────────────────────────────┐
│                    3. AGENT ORCHESTRATION LAYER                         │
│   • Strands Agents SDK Runtime            • Amazon Bedrock Nova Pro     │
│   • Multi-Agent Registry (4 Personas)     • Dynamic Form Clarifier      │
│   • Chat-First Guardrails                 • Long-Term User Memory       │
└───────────────────┬─────────────────────────────────┬───────────────────┘
                    │ Tool Invocation                 │ Read / Write
┌───────────────────▼─────────────────┐   ┌───────────▼───────────────────┐
│   4. PRIVILEGED TOOL EXECUTION      │   │ 5. LOCAL STATE & PERSISTENCE  │
│   • 3-Tier Trust Gate (HITL Engine) │   │   • Chat History (chats/*.json│
│   • Document Suite (Word/Excel/PDF) │   │   • User Memory (profiles)    │
│   • Desktop Files & Recycle Bin     │   │   • Save Prefs & App Settings │
│   • Winget & System Diagnostics     │   │   • Audit Trail (logs/*.jsonl)│
└─────────────────────────────────────┘   └───────────────────────────────┘
```

---

## 2. Interactive System Topology (Mermaid)

```mermaid
flowchart TD
    %% Theme Styling
    classDef userNode fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#ffffff;
    classDef brainNode fill:#2e1065,stroke:#a855f7,stroke-width:2px,color:#ffffff;
    classDef formNode fill:#701a75,stroke:#f472b6,stroke-width:2px,color:#ffffff;
    classDef trustNode fill:#1c1917,stroke:#f59e0b,stroke-width:2px,color:#ffffff;
    classDef toolNode fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff;
    classDef outNode fill:#0284c7,stroke:#bae6fd,stroke-width:2px,color:#ffffff;

    %% STEP 1: USER INTERACTION
    subgraph Step1 ["Step 1: User Request & Desktop UI"]
        direction TB
        User["👤 User on Windows Desktop"]:::userNode
        UI["Desktop Glassmorphism UI\n• Chat Input & History\n• Mobile Drawer Navigation\n• Real-Time Token Streaming"]:::userNode
        User -->|1. Asks question, budget, or task| UI
    end

    %% STEP 2: AGENT INTELLIGENCE
    subgraph Step2 ["Step 2: Multi-Agent Brain & Reasoning"]
        direction TB
        Fleet["Multi-Agent Fleet (Strands SDK)\n• Personal Assistant (Daily chores)\n• Finance Agent (Budget & Ledgers)\n• Work Agent (Reports & Research)\n• Health Agent (Wellness routines)"]:::brainNode
        NovaBrain["Amazon Bedrock Nova Pro\n• Streaming Reasoning (<thinking>)\n• Chat-First & Anti-Hallucination Guardrails"]:::brainNode
        Fleet <--> NovaBrain
    end

    UI -->|2. Dispatches Prompt via Bridge| Fleet

    %% STEP 3: DYNAMIC FORM CLARIFICATION
    subgraph Step3 ["Step 3: Interactive Clarification (ask_user_form)"]
        direction TB
        CheckInfo{"Are vital numbers or\ngoals missing?"}:::formNode
        FormModal["Dynamic Form Modal Popup\n(Numeric inputs, Currency, Dropdowns)"]:::formNode
        UserProfile[("User Memory Store\nconfig/user_profiles.json")]:::formNode

        CheckInfo -->|YES: Missing budget/facts| FormModal
        FormModal -->|User submits real answers| UserProfile
        UserProfile -->|Injected back into context| Fleet
    end

    Fleet --> CheckInfo

    %% STEP 4: 3-TIER TRUST GATE
    subgraph Step4 ["Step 4: 3-Tier Human-in-the-Loop Safety Gate"]
        direction TB
        TrustGate{"Action Trust Classifier\n'Only surfaces when decision needed'"}:::trustNode
        Green["🟢 Green Tier (Autonomous)\nRead, search, diagnostics, doc creation\n(Runs silently with zero interruption)"]:::trustNode
        Yellow["🟡 Yellow Tier (Confirmation Required)\nMove/organize files, edit documents\n(Modal popup with 'Approve All' caching)"]:::trustNode
        Red["🔴 Red Tier (Unbypassable Gate)\nDelete files, install software\n(High-visibility modal + Safe Recycle Bin)"]:::trustNode

        TrustGate -->|Read / Search / Make Docs| Green
        TrustGate -->|Move / Organize / Edit| Yellow
        TrustGate -->|Delete / Install Apps| Red
    end

    CheckInfo -->|NO: Has raw data / action ready| TrustGate

    %% STEP 5: DESKTOP EXECUTION SUITE
    subgraph Step5 ["Step 5: Privileged Desktop Tools (37 Tools)"]
        direction TB
        ExcelTool["📊 Excel Engine (excel_tools.py)\n• Native =SUM formulas & real numbers\n• Multi-currency: PKR, EUR, USD, INR\n• Automated self-verification"]:::toolNode
        WordTool["📝 Word Engine (word_tools.py)\n• Executive reports with headings & tables\n• Document editing & verification"]:::toolNode
        PdfTool["📑 PDF Engine (pdf_tools.py)\n• Invoice extraction & tabular parsing\n• Content editing to Word/PDF"]:::toolNode
        FileTool["📁 File & System Control (file_tools.py / system_tools.py)\n• organize_files: Single batch approval\n• Safe Recycle Bin (send2trash)\n• Winget install (10-App allowlist)"]:::toolNode
    end

    Green --> ExcelTool & WordTool & PdfTool & FileTool
    Yellow -->|User Approves| FileTool & ExcelTool & WordTool
    Red -->|User Confirms Explicitly| FileTool

    %% STEP 6: DELIVERABLE PRESENTATION
    subgraph Step6 ["Step 6: User Deliverables & Experience"]
        direction TB
        ChatResult["Conversational Markdown Report\n+ Collapsible <thinking> Reasoning Accordion"]:::outNode
        DeliverableCard["Interactive Deliverable Action Card\n• Clickable File Chip\n• One-Click 'Open File' Button"]:::outNode
    end

    ExcelTool & WordTool & PdfTool & FileTool --> DeliverableCard
    Fleet --> ChatResult
    ChatResult & DeliverableCard -->|Streamed Back| UI
```

---

## 3. End-to-End Runtime Execution Sequences

### 3.1. Chat-First Reasoning & Tool Execution Flow
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Responsive UI (app.js)
    participant Bridge as Bridge (bridge.py)
    participant Orch as Orchestrator (orchestrator.py)
    participant Bedrock as Amazon Bedrock (Nova Pro)
    participant Trust as Trust Gate (trust.py)
    participant Tool as Tool Implementation

    User->>UI: Types: "Can you organize desktop files into folders?"
    UI->>Bridge: send_chat_message(sessionId, prompt)
    Bridge->>Orch: run_chat_turn(agentId, prompt, history)
    Orch->>Bedrock: Stream Prompt + Core Guardrails + Tool Whitelist
    
    loop Streaming Reasoning & Actions
        Bedrock-->>Orch: Stream <thinking> tokens (Nova Pro)
        Orch-->>UI: emit('deskpilot:chat_chunk', reasoning)
        Bedrock-->>Orch: ToolCall: organize_files(folder="Desktop")
        Orch-->>UI: emit('deskpilot:chat_step', {tool: 'organize_files', status: 'running'})
        Orch->>Trust: request_approval('organize_files', 'Categorize files on Desktop')
        
        alt Yellow Action Confirmation
            Trust-->>UI: emit('deskpilot:approval_required', {requestId, action, description})
            UI-->>User: Displays Modal Dialog (Approve / Reject / Approve All)
            User->>UI: Clicks "Approve"
            UI->>Bridge: respond_to_approval(requestId, approved=True)
            Bridge->>Trust: resolve_approval(requestId, True)
            Trust-->>Orch: Approved
        end

        Orch->>Tool: organize_files("Desktop")
        Tool-->>Orch: Tool Result: "Categorized 14 files into Documents, PDFs, Spreadsheets"
        Orch->>Bedrock: Send ToolResult
    end

    Bedrock-->>Orch: Final conversational answer & summary
    Orch->>Bridge: Chat Turn Completed
    Bridge-->>UI: emit('deskpilot:chat_turn_complete')
    UI-->>User: Renders formatted summary & audit badge
```

---

### 3.2. Interactive User Onboarding & Dynamic Form Flow (`ask_user_form`)
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Workspace UI
    participant Orch as Orchestrator
    participant FormTool as user_tools.ask_user_form
    participant Engine as form_engine.py
    participant Mem as user_memory.py

    Orch->>FormTool: ask_user_form(title, questions=[income, currency, goals])
    FormTool->>Engine: request_form(title, questions)
    Engine-->>UI: emit('deskpilot:form_requested', {formId, schema})
    UI-->>User: Modal popup with dynamic text/select/numeric fields
    User->>UI: Fills form & clicks "Submit Preferences"
    UI->>Engine: submit_form_response(formId, answers)
    Engine-->>FormTool: Unblocks waiting thread with answers dict
    FormTool->>Mem: update_user_profile(agent_id, answers)
    Mem-->>Orch: Persisted to config/user_profiles.json
    FormTool-->>Orch: Form answers returned to foundation model
    Orch-->>UI: Synthesizes personalized plan using real numbers
```

---

### 3.3. Closed-Loop Office Deliverables Pipeline
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orch as Orchestrator
    participant Excel as excel_tools.py
    participant Verify as verify_excel_workbook
    participant UI as Workspace UI

    User->>Orch: "Generate an Excel budget sheet in PKR"
    Orch->>Excel: create_excel_workbook(filename, headers, rows, currency="PKR")
    Excel->>Excel: Format numbers, insert native formulas (=SUM), apply PKR format
    Excel-->>Orch: File created at "Desktop/DeskPilot_Output/Budget.xlsx"
    Orch->>Verify: verify_excel_workbook(file_path)
    Verify->>Verify: Inspect openpyxl structure, data integrity, sheets
    Verify-->>Orch: Verification Report (Valid=True)
    Orch-->>UI: emit('deskpilot:chat_chunk', "Here is your spreadsheet:")
    Orch-->>UI: emit('deskpilot:deliverable', {path, filename, type: 'excel'})
    UI-->>User: Renders Deliverable Action Card with "Open File" button
```

---

## 4. 3-Tier Human-in-the-Loop (HITL) Safety Framework

DeskPilot enforces deterministic boundaries through `backend/utils/trust.py`:

| Tier | Policy | Execution Semantics | Tool Coverage |
|---|---|---|---|
| **🟢 Green** | **Autonomous** | Auto-executes immediately. Non-destructive operations, read-only sweeps, search, diagnostics, and new document generation. | `search_web`, `read_pdf`, `read_word_document`, `read_excel_file`, `create_word_report`, `create_excel_workbook`, `list_files`, `verify_file_exists`, `get_system_info`, `get_storage_status`, `ask_user_form`, `get_user_profile` |
| **🟡 Yellow** | **Confirmation Required** | Execution thread halts. UI presents interactive confirmation dialog. Supports **Approve All** turn caching for batch file actions. | `organize_files`, `move_file`, `rename_file`, `write_file`, `edit_word_document`, `edit_pdf_document`, `edit_excel_file`, `clean_temporary_files` |
| **🔴 Red** | **Unbypassable Approval** | Mandatory high-visibility warning dialog. Never auto-executes. Deletions route to safe Windows Recycle Bin via `send2trash`. Software installations validated against strict allowlist. | `delete_file`, `delete_files`, `winget_install` (validated against 10 allowlisted Windows applications), `run_shell_command` |

### Session-Scoped "Approve All" Caching
When a user approves a batch file move or document update with "Approve All", the approval engine adds the action name to `_approved_actions_cache`. Subsequent calls of that exact action within that turn succeed instantly without modal prompts, and the cache auto-resets when the next user turn starts.

---

## 5. Comprehensive Tool Library Taxonomy (37 Tools Across 7 Domains)

All tools are registered in `backend/tools/__init__.py` and mapped to `@tool` decorated functions:

### 1. Document Intelligence — Microsoft Word (4 Tools)
- `read_word_document(file_path)`: Reads paragraphs, tables, and document metadata.
- `edit_word_document(file_path, replacements, sections_to_add, output_path)`: Performs precise text replacements, appends formatted sections, and preserves styles.
- `create_word_report(title, sections, tables, output_path)`: Compiles professional `.docx` with executive formatting.
- `verify_word_document(file_path)`: Verifies file exists, can be parsed by `docx`, and is non-empty.

### 2. Document Intelligence — Microsoft Excel (5 Tools)
- `read_excel_file(file_path, sheet_name)`: Reads cell values, computed values, and sheet names.
- `edit_excel_file(file_path, sheet_name, cell_updates, append_rows)`: Modifies cells and appends real numeric data rows.
- `create_excel_workbook(filename, sheets_data, currency)`: Generates `.xlsx` with real numerical formats, currency styling (`PKR`, `EUR`, `USD`, `INR`), and native `=SUM()` formulas.
- `create_reconciliation_report(file_path_a, file_path_b)`: Performs row-by-row cross-ledger auditing.
- `verify_excel_workbook(file_path)`: Inspects workbook formulas and data using `openpyxl`.

### 3. Document Intelligence — Adobe PDF (5 Tools)
- `read_pdf(file_path, max_pages)`: Extracts high-fidelity text with `pypdf`.
- `edit_pdf_document(file_path, modification_instructions, output_format)`: Extracts content, applies intelligent changes, and exports to editable Word or PDF.
- `extract_pdf_tables(file_path)`: Extracts structured tables into tabular data.
- `extract_pdf_invoice(file_path)`: Extracts invoice numbers, dates, line items, and totals.
- `list_pdfs_in_folder(folder_path)`: Lists and indexes PDF files in any directory.

### 4. Desktop File Management & Safe Control (14 Tools)
- `list_files(directory, pattern)`: Lists directory contents with sizes and modification dates.
- `verify_file_exists(file_path)`: Validates file existence on disk.
- `move_file(source, destination)`: Relocates files safely.
- `rename_file(old_path, new_name)`: Renames files safely.
- `delete_file(file_path)`: Safely moves file to **Windows Recycle Bin** via `send2trash`.
- `delete_files(file_paths)`: Batch-sends files to Recycle Bin after single confirmation.
- `create_folder(folder_path)`: Creates directories recursively.
- `organize_files(folder_path)`: Categorizes loose files into subfolders (Documents, Spreadsheets, PDFs, Images, Code, Archives) with a single confirmation.
- `scan_and_categorize_files(folder_path)`: Pre-scans a directory without moving anything.
- `open_file(file_path)`: Launches file in default Windows application (`os.startfile`).
- `open_folder(folder_path)`: Reveals directory in Windows File Explorer.
- `get_file_info(file_path)`: Returns size, permissions, hashes, and dates.
- `explain_file_purpose(file_path)`: Inspects file headers to explain what a file is.
- `read_file` / `write_file`: General text file inspection and writing.

### 5. System Diagnostics & Package Management (8 Tools)
- `winget_install(package_id)`: Installs software via Windows Package Manager (`winget`) restricted to `WINGET_ALLOWLIST`.
- `get_winget_allowlist()`: Returns the approved software catalog (Firefox, Chrome, VS Code, Git, 7-Zip, Notepad++, VLC, Obsidian, Slack, Zoom).
- `check_software_installed(app_name)`: Checks registry and PATH for installed software.
- `launch_application(app_name)`: Launches approved desktop applications.
- `get_storage_status()`: Checks disk capacity and free space across all drives.
- `clean_temporary_files()`: Safely clears Windows user `%TEMP%` directory.
- `get_system_info()`: Reports CPU, RAM, OS version, and machine hostname.
- `get_running_processes(filter_name)`: Returns process list and memory utilization.

### 6. Web Intelligence (3 Tools)
- `search_web(query)`: High-speed web search with DuckDuckGo.
- `read_webpage(url)`: Fetches HTML and strips readable text with BeautifulSoup.
- `search_and_read(query)`: Combined search and content synthesis pipeline.

### 7. Dynamic User Memory & Dynamic Forms (3 Tools)
- `ask_user_form(title, questions)`: Opens a synchronous modal form in the UI to ask the user structured questions (text, number, select, textarea, checkbox).
- `get_user_profile(agent_id)`: Retrieves persisted user background and preferences.
- `update_user_profile(agent_id, updates)`: Updates long-term memory in `config/user_profiles.json`.

---

## 6. Multi-Agent Manifest Architecture

DeskPilot uses declarative JSON manifests (`agents/*.json`):

```json
{
  "id": "finance_agent",
  "name": "Finance Agent",
  "description": "Handles budgets, expenses, invoice extraction, and financial spreadsheets.",
  "icon": "circle-dollar-sign",
  "color": "emerald",
  "persona": "You are DeskPilot's Financial Assistant. You strictly format numbers, verify workbooks...",
  "allowed_tools": [
    "create_excel_workbook",
    "read_excel_file",
    "edit_excel_file",
    "verify_excel_workbook",
    "create_reconciliation_report",
    "extract_pdf_invoice",
    "ask_user_form",
    "get_user_profile"
  ],
  "category": "default",
  "status": "active"
}
```

### Manifest Fleet:
1. **Default Fleet**:
   - `personal_assistant`: General desktop productivity, organization, and light research.
   - `finance_agent`: Bookkeeping, spreadsheets, invoice extraction, and financial modeling.
   - `work_agent`: Executive reporting, multi-page business briefs, and PDF analysis.
   - `health_agent`: Wellness routines, nutrition planning, research (strict no-diagnosis safety guardrails).
2. **Template Fleet**:
   - `code_mentor`: Code reviews, refactoring, and debugging assistance.
   - `data_analyst`: Statistical analysis, CSV/Excel trend exploration, and visualization planning.
   - `travel_planner`: Itinerary creation, hotel comparison tables, and packing lists.
3. **Custom Agents**:
   - Created on the fly via `backend/agent/builder.py` using natural language prompts.
   - Foundation model automatically selects an authorized subset from `TOOL_REGISTRY`.

---

## 7. Responsive Client Shell & UI Design System

- **Desktop Shell**: Embedded Microsoft Edge Chromium engine via `pywebview` with custom window chrome and min-dimensions `420x500` for compact displays.
- **Web / Mobile Mode**: Served by Flask with Server-Sent Events (`/api/events/stream`).
- **Responsive Drawer Navigation**:
  - Desktop (>1024px): Persistent sidebar with session tree, agent switcher, and preferences.
  - Tablet/Mobile (<768px): Collapsible off-canvas drawer with hamburger toggle and backdrop overlay.
- **Modern Typography & Glassmorphism**: Tailored HSL dark palette (`#0a0d14`), translucent cards (`rgba(255,255,255,0.03)`), Lucide icons, and fluid `clamp()` responsive typography.
- **Collapsible Reasoning Accordions**: Captures Bedrock Nova Pro `<thinking>` tags in collapsible disclosure blocks so internal thought processes don't clutter executive summaries.

---

## 8. Directory & File Structure Mapping

```
DeskPilot/
├── agents/                       # Declarative JSON agent manifests
│   ├── personal_assistant.json
│   ├── finance_agent.json
│   ├── work_agent.json
│   └── health_agent.json
├── backend/                      # Python 3.12 Backend Architecture
│   ├── agent/                    # Strands Orchestrator, Builder, Registry
│   │   ├── builder.py            # Natural language agent synthesizer
│   │   ├── orchestrator.py       # Bedrock Converse API + Strands runner
│   │   └── registry.py           # Manifest storage & template manager
│   ├── chat/                     # Chat Session Management
│   │   └── session_manager.py    # Multi-turn chat persistence (chats/*.json)
│   ├── config/                   # Central Settings & Allow-lists
│   │   ├── settings.py           # AWS credentials, Trust Tiers, Winget list
│   │   └── user_profiles.json    # Long-term user memory database
│   ├── tools/                    # 37 Specialized Autonomous Tools
│   │   ├── __init__.py           # Canonical lookup & resolver
│   │   ├── excel_tools.py        # Excel creation, editing & verification
│   │   ├── file_tools.py         # File operations & safe send2trash
│   │   ├── pdf_tools.py          # PDF reading, editing & invoice extraction
│   │   ├── system_tools.py       # Winget installation & system stats
│   │   ├── user_tools.py         # Dynamic forms & user profile memory
│   │   ├── web_tools.py          # DuckDuckGo search & scraping
│   │   └── word_tools.py         # Word report creation & editing
│   ├── utils/                    # Infrastructure Utilities
│   │   ├── document_resolver.py  # Universal path & output resolver
│   │   ├── form_engine.py        # Synchronous modal form engine
│   │   ├── logger.py             # JSONL structured audit logging
│   │   ├── trust.py              # 3-tier HITL safety gate
│   │   └── user_memory.py        # User memory context injector
│   ├── app.py                    # pywebview desktop entrypoint
│   ├── bridge.py                 # JavaScript ↔ Python two-way bridge
│   └── server.py                 # Flask REST API + SSE stream
├── config/                       # Runtime persistent configuration
├── docs/                         # Technical Architecture & Deployment Specs
│   ├── ARCHITECTURE.md           # This document
│   └── DEPLOYMENT.md             # AWS & local deployment manual
├── frontend/                     # Presentation Layer (Vanilla SPA)
│   ├── css/styles.css            # Dark glassmorphism stylesheet
│   ├── js/app.js                 # Workspace UI controller & stream handler
│   ├── js/bridge.js              # Dual-mode desktop/HTTP transport
│   └── index.html                # HTML5 semantic structure
├── installer/                    # Inno Setup 6 Windows packaging script
├── logs/                         # Runtime JSONL audit trails
├── main.py                       # Root launcher (desktop or web mode)
└── tests/                        # Pytest automated test suite (42 unit tests)
```
