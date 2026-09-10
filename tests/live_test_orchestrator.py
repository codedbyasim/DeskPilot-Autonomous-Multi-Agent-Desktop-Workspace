"""
DeskPilot — Live Agent Orchestrator Verification
Runs a fast, live instruction on Personal Assistant using Bedrock Nova Pro
to verify tool invocation, streaming callbacks, and audit logging.
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.orchestrator import AgentOrchestrator
from backend.agent.registry import AgentRegistry

def main():
    print("=== DeskPilot Live Agent Test ===")
    registry = AgentRegistry()
    orchestrator = AgentOrchestrator(registry)

    logs = []
    steps = []

    def on_log(text: str):
        print(f"[LOG] {text}", end="")
        logs.append(text)

    def on_step(tool: str, status: str):
        print(f"\n[STEP] Tool: {tool} -> Status: {status}")
        steps.append((tool, status))

    instruction = "List the files in the project root directory and summarize what you find."
    print(f"\nExecuting instruction for 'personal_assistant':\n{instruction}\n")

    res = orchestrator.run_task(
        agent_id="personal_assistant",
        instruction=instruction,
        on_log=on_log,
        on_step=on_step,
    )

    print("\n\n=== Execution Result ===")
    print(f"Success: {res.get('success')}")
    print(f"Result preview: {str(res.get('result', ''))[:300]}...")
    print(f"Audit log path: {res.get('audit_path')}")
    print(f"Total steps captured: {len(steps)}")

    assert res.get("success") is True, f"Execution failed: {res.get('error')}"
    print("\n✅ Live Orchestrator Test PASSED!")

if __name__ == "__main__":
    main()
