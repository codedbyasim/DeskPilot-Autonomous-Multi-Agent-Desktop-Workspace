"""
DeskPilot — Live Agent Tool Selection Test for File Organization
Verifies that Personal Assistant invokes 'organize_files' when asked to organize files.
"""

import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.orchestrator import AgentOrchestrator
from backend.agent.registry import AgentRegistry

def main():
    print("=== Testing Live Agent Tool Invocation for Organize Files ===")
    registry = AgentRegistry()
    orchestrator = AgentOrchestrator(registry)

    # Create temporary folder with some test files
    temp_dir = Path(tempfile.mkdtemp())
    (temp_dir / "report.docx").write_text("dummy doc")
    (temp_dir / "budget.xlsx").write_text("dummy xlsx")
    (temp_dir / "paper.pdf").write_text("dummy pdf")

    tools_called = []
    def on_step(tool: str, status: str):
        print(f"[STEP] {tool} -> {status}")
        if tool not in tools_called:
            tools_called.append(tool)

    instruction = f"Organize the files in the directory '{temp_dir}' into categorized folders."
    print(f"Instruction: {instruction}")

    with patch("backend.tools.file_tools.request_approval", return_value=True):
        res = orchestrator.run_task(
            agent_id="personal_assistant",
            instruction=instruction,
            on_step=on_step,
        )

    print(f"\nSuccess: {res.get('success')}")
    print(f"Tools called: {tools_called}")
    print(f"Response preview: {str(res.get('result', ''))[:300]}")

    shutil.rmtree(str(temp_dir), ignore_errors=True)

    assert "organize_files" in tools_called or "move_file" in tools_called, f"Expected organize_files or move_file, got: {tools_called}"
    print("\n✅ Live Organize Files Agent Directive PASSED!")

if __name__ == "__main__":
    main()
