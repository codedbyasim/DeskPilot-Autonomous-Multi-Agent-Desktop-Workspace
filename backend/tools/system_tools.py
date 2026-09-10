"""
DeskPilot — System Tools
Provides safe software management constrained exclusively to an explicit Winget allow-list.
Never downloads or executes arbitrary executables from the web.
Always classified as RED TIER (strict user confirmation required every time).
"""

import subprocess
from strands import tool
from backend.config.settings import WINGET_ALLOWLIST
from backend.utils.logger import get_logger
from backend.utils.trust import request_approval

logger = get_logger("tools.system")


@tool
def winget_install(package_id: str) -> str:
    """
    Safely install an approved software package via the official Windows Package Manager (Winget).
    Installation is strictly constrained to the DeskPilot Winget allow-list (Section 10 & 13).
    Always requires explicit human confirmation (RED tier).

    Args:
        package_id: Canonical Winget package ID (e.g., 'Git.Git', 'Mozilla.Firefox', 'Microsoft.VisualStudioCode')

    Returns:
        Status message with execution output or rejection details
    """
    clean_id = package_id.strip()
    logger.info(f"Requested software installation for package: '{clean_id}'")

    # 1. Hard validation against WINGET_ALLOWLIST
    if clean_id not in WINGET_ALLOWLIST:
        allowed_list_str = ", ".join(sorted(WINGET_ALLOWLIST.keys()))
        logger.warning(f"Installation rejected: '{clean_id}' is not in allow-list.")
        return (
            f"REJECTED: Package '{clean_id}' is not in the DeskPilot authorized software allow-list.\n"
            f"Authorized packages:\n{allowed_list_str}"
        )

    app_name = WINGET_ALLOWLIST[clean_id]

    # 2. Strict RED-tier Human-in-the-Loop approval gate
    approved = request_approval(
        action_name="winget_install",
        description=f"Install approved software: {app_name} ({clean_id}) via Windows Package Manager (winget)?",
        tier="RED"
    )
    if not approved:
        logger.info(f"User denied installation of '{clean_id}'")
        return f"CANCELLED: User denied permission to install '{app_name}' ({clean_id})."

    # 3. Execute winget command
    cmd = [
        "winget", "install",
        clean_id,
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent"
    ]
    logger.info(f"Executing winget install for {clean_id}...")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            shell=True
        )
        if proc.returncode == 0:
            logger.info(f"Successfully installed '{clean_id}'")
            return f"SUCCESS: '{app_name}' ({clean_id}) was installed successfully via Winget."
        else:
            err_output = (proc.stderr or proc.stdout or "").strip()
            logger.error(f"Winget install failed with code {proc.returncode}: {err_output}")
            return f"FAILED: Winget returned code {proc.returncode}: {err_output[:300]}"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT: Installation of '{clean_id}' timed out after 300 seconds."
    except Exception as e:
        logger.error(f"Execution error during winget install: {e}")
        return f"ERROR: Could not execute winget: {str(e)}"
