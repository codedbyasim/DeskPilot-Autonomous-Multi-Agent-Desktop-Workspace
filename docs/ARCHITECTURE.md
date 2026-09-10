# DeskPilot Technical Architecture

[![Amazon Bedrock](https://img.shields.io/badge/AWS-Amazon_Bedrock-FF9900?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![Strands Agents SDK](https://img.shields.io/badge/Orchestrator-Strands_Agents_SDK-7952B3)](https://github.com/strands-agents)
[![Framework](https://img.shields.io/badge/Desktop_Shell-pywebview-0078D7)](https://pywebview.flowrl.com/)

This document details the internal architecture, component interactions, safety mechanisms, and Amazon Bedrock integration powering **DeskPilot**.

![DeskPilot Enterprise Architecture Diagram](../assets/architecture_diagram.png)

---

## 1. System Overview

DeskPilot is architected around a **decoupled hybrid desktop model**:
- **Presentation Layer**: A high-performance, dark glassmorphism interface running inside Microsoft Edge WebView2 (via `pywebview`) or served locally via Flask for standard browsers.
- **Bridge Layer**: A two-way event bus bridging JavaScript UI actions to Python threads via native pywebview bindings and Server-Sent Events (SSE).
- **Agent Orchestration Engine**: Built with the **Strands Agents SDK**, dynamically instantiating agents backed by **Amazon Bedrock Nova Pro** (`amazon.nova-pro-v1:0`).
- **Trust & Autonomy Engine**: A stateful Human-in-the-Loop approval gate categorizing all agent actions into **Green**, **Yellow**, or **Red** tiers.
- **Tool Execution Framework**: 28 native desktop tools covering file management, Word/Excel document creation, PDF analysis, web research, and system software installations.

```mermaid
flowchart TB
    %% Master Styles
    classDef runtime fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef agent fill:#431407,stroke:#fb923c,stroke-width:2px,color:#f8fafc;
    classDef tool fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;
    classDef state fill:#701a75,stroke:#f472b6,stroke-width:2px,color:#f8fafc;
    classDef client fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;

    subgraph Packaging ["Runtimes & Packaging"]
        direction TB
        Spec["Windows Packaging Executable Installer [deskpilot.spec]"]
        Settings["Settings & Credentials Runtime Configuration [settings.py]"]
        Main["Unified Launcher Python Entry Point [main.py]"]
        Docker["Container Deployment Docker Runtime [Dockerfile]"]

        Spec -->|packages| Main
    end

    subgraph AgentRuntime ["Agent Runtime & Intelligence"]
        direction TB
        Manifests["Agent Manifests JSON Persona Definition (8 Built-in Agents)"]
        Builder["Custom Agent Builder Model-Assisted Builder [builder.py]"]
        Registry["Agent Registry Manifest Store [registry.py]"]
        Orchestrator["Agent Orchestrator Strands Runtime [orchestrator.py]"]
        Bedrock["Amazon Bedrock Nova Pro External Model Service"]

        Manifests -->|defines persona & tools| Registry
        Builder -->|activates reviewed agent| Registry
        Registry -->|selected definition| Orchestrator
        Orchestrator <-->|reasoning & tool calls| Bedrock
    end

    subgraph Tools ["Privileged Tools & Autonomy Gate"]
        direction TB
        TrustGate{"Trust Policy Approval Gate [trust.py]"}
        Adapters["Tool Domains Local Capability Adapters (File, Word, PDF, Web, System) [file_tools.py]"]
        Deliverables["Office Deliverables Generation & Verification Tools [excel_tools.py & word_tools.py]"]

        TrustGate -->|permits side effects| Adapters
        Adapters -->|office deliverables| Deliverables
    end

    subgraph LocalState ["Local State & Persistence"]
        direction TB
        SavePref[("Save Preferences Local Store [save_preferences.json]")]
        ChatStore[("Chat Sessions JSON Store [session_manager.py]")]
    end

    subgraph ClientSurfaces ["Client Surfaces & Presentation"]
        direction TB
        DesktopHost["Desktop Shell pywebview Host [app.py]"]
        FlaskServer["Web API & SSE Flask Server [server.py]"]
        SPA["Workspace UI Vanilla JS SPA [app.js]"]
        BridgeJS["Client Bridge Transport Adapter [bridge.js]"]
        BridgePY["Native Bridge & Approvals Python Bridge [bridge.py]"]

        DesktopHost -->|hosts| SPA
        FlaskServer -->|serves| SPA
        SPA -->|requests & events| BridgeJS
        BridgeJS -->|desktop transport| BridgePY
        BridgeJS -->|HTTP/SSE transport| FlaskServer
    end

    %% Cross-Subsystem Interconnections
    Settings -.->|credentials| Orchestrator
    Main -->|default desktop mode| DesktopHost
    Main -->|web mode| FlaskServer
    Docker -->|runs web mode| FlaskServer

    Orchestrator -->|authorized invocation| Adapters
    Orchestrator -->|requests action authorization| TrustGate
    BridgePY -->|approval decisions| TrustGate
    Orchestrator -->|streams events| FlaskServer
    Orchestrator -->|reads & writes history| ChatStore

    Adapters -.->|uses destination preference| SavePref
    Deliverables -->|submits work / deliverables| SPA
```

---

## 2. Agent Orchestration & AWS Bedrock Integration

DeskPilot leverages the **Strands Agents SDK** combined with **Amazon Bedrock** for high-speed agentic reasoning and deterministic tool invocation.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Frontend as Frontend UI
    participant Bridge as Bridge API
    participant Orchestrator as Agent Orchestrator
    participant Bedrock as Amazon Bedrock (Nova Pro)
    participant Tool as Tool Registry
    participant Trust as Trust Tier Engine

    User->>Frontend: "Organize desktop files into categorized folders"
    Frontend->>Bridge: send_chat_message(sessionId, prompt)
    Bridge->>Orchestrator: run_chat_turn(agentId, prompt, history)
    Orchestrator->>Bedrock: Stream Prompt + Whitelisted Tools Schema
    
    loop Reasoning & Tool Execution
        Bedrock-->>Orchestrator: Stream reasoning tokens & ToolCall (organize_files)
        Orchestrator-->>Frontend: Emit 'deskpilot:chat_chunk' & 'deskpilot:chat_step'
        Orchestrator->>Tool: execute organize_files("Desktop")
        Tool->>Trust: request_approval("organize_files", description)
        
        alt Yellow / Red Tier
            Trust->>Frontend: Emit 'deskpilot:approval_required'
            Frontend-->>User: Display Interactive Confirmation Modal
            User->>Frontend: Click "Approve" (or "Approve All")
            Frontend->>Bridge: respond_to_approval(requestId, approved=True)
            Bridge->>Trust: resolve_approval(requestId, True)
            Trust-->>Tool: Resume Execution
        end
        
        Tool->>Tool: Batch organize files & create subfolders
        Tool-->>Orchestrator: Tool Result Summary
        Orchestrator->>Bedrock: Send ToolResult to Bedrock
    end

    Bedrock-->>Orchestrator: Final conversational summary
    Orchestrator->>Bridge: Turn Complete
    Bridge->>Frontend: Emit 'deskpilot:chat_turn_complete'
    Frontend-->>User: Display structured report & update UI
```

---

## 3. Human-in-the-Loop Trust Model

Every action executed by an agent is evaluated by the **Trust Tier Classifier** (`backend/utils/trust.py`):

| Trust Tier | Behavioral Model | Example Tools | User Experience |
|---|---|---|---|
| **🟢 Green (Autonomous)** | Auto-executed without human interruption | `list_files`, `verify_file_exists`, `read_file`, `create_folder`, `create_word_report`, `create_excel_workbook`, `search_web` | Immediate execution with pulsing tool badges in chat |
| **🟡 Yellow (Confirmation Required)** | Thread pauses; requires user confirmation | `move_file`, `rename_file`, `organize_files`, `write_file` | Modal popup with action description. Supports **Approve All** for batch operations |
| **🔴 Red (Unbypassable Approval)** | Mandatory explicit approval; strict allowlists | `delete_file`, `install_software`, `run_shell_command` | High-visibility warning dialog with full path/package verification |

### "Approve All" Batch Caching
In batch operations (e.g., reorganizing multiple files or multi-document workflows), DeskPilot implements **Session-Scoped Approval Caching**:
1. When a user clicks **Approve All** on an approval modal, the approval engine caches authorization for that specific action type.
2. Subsequent calls of the same action type within that turn execute immediately without modal interruptions.
3. The cache automatically clears at the start of every new chat turn.

![Trust Tier Audit Log and Execution History](../assets/screenshots/audit_history.png)

---

## 4. Multi-Agent Registry Architecture

Agents are defined as lightweight, declarative JSON manifests stored in `agents/`:

```json
{
  "id": "personal_assistant",
  "name": "Personal Assistant",
  "description": "Handles daily tasks like desktop cleanup, file organization, and light research.",
  "icon": "home",
  "color": "green",
  "persona": "System prompt guardrails and behavioral guidelines...",
  "allowed_tools": [
    "list_files",
    "create_folder",
    "move_file",
    "organize_files",
    "create_word_report",
    "create_excel_workbook"
  ],
  "category": "default",
  "status": "active"
}
```

![Pre-Configured Template Agent Catalog](../assets/screenshots/template_gallery.png)

### Strict Tool Whitelisting (Section 13 Compliance)
When an agent is loaded, `AgentOrchestrator.build_agent()` strictly resolves only the tools listed in `allowed_tools`. Tools outside the whitelist are never exposed to the foundation model, preventing unauthorized capabilities or hallucinated tool use.

---

## 5. Deliverable Pipeline & Self-Verification

When generating documents, DeskPilot enforces a closed-loop creation and verification lifecycle:

```
[User Request] 
      │
      ▼
[Tool: create_excel_workbook] ──► Writes formulas, formats currency, auto-fits columns
      │
      ▼
[Tool: verify_excel_workbook] ──► Inspects workbook using openpyxl, validates data and formulas
      │
      ▼
[Deliverable Card in Chat]    ──► Renders clickable deliverable chip with one-click "Open File"
```

1. **Excel Workbooks**: Numeric cells are cast to real numbers (`int`/`float`), formulas like `=SUM(B2:B10)` are inserted natively, and headers are styled with theme fills.
2. **Word Reports**: Markdown headers, lists, and tables are converted into native Microsoft Word headings, bullet points, and styled tables.
3. **Save Preferences**: All deliverables respect the user's active save location (Desktop, Documents, or Custom) configured via the top navigation bar.
