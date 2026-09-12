"""
DeskPilot — System Tools
Provides safe software management constrained exclusively to an explicit Winget allow-list.
Never downloads or executes arbitrary executables from the web.
Always classified as RED TIER (strict user confirmation required every time).
"""

import subprocess
import threading
import shutil
from strands import tool
from backend.config.settings import WINGET_ALLOWLIST
from backend.utils.logger import get_logger
from backend.utils.trust import request_approval
from backend.utils.events import emit_event

logger = get_logger("tools.system")


def _find_winget() -> str | None:
    """Locate the winget executable on the system via PATH or known locations."""
    # 1. Try PATH first
    found = shutil.which("winget")
    if found:
        return found

    # 2. Check well-known WindowsApps location
    import os
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidate = os.path.join(local_app_data, "Microsoft", "WindowsApps", "winget.exe")
    if os.path.isfile(candidate):
        return candidate

    return None


def _find_installed_app(app_name: str):
    """
    Search Windows Start Menu, Desktop, and Program directories for shortcuts or executables matching app_name.
    Returns list of (type, path).
    """
    import os
    from pathlib import Path
    query = app_name.lower().strip()
    name_map = {
        "slack": ["slack"],
        "vscode": ["code", "visual studio code"],
        "vs code": ["code", "visual studio code"],
        "chrome": ["chrome", "google chrome"],
        "firefox": ["firefox", "mozilla firefox"],
        "notepad++": ["notepad++", "notepadplusplus"],
        "vlc": ["vlc", "vlc media player"],
        "7zip": ["7-zip", "7zip"],
        "7-zip": ["7-zip", "7zip"],
        "obsidian": ["obsidian"],
        "zoom": ["zoom"],
        "git": ["git", "git bash"],
    }
    search_queries = name_map.get(query, [query])

    search_roots = [
        Path.home() / "Desktop",
        Path("C:/Users/Public/Desktop"),
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("ALLUSERSPROFILE", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("LOCALAPPDATA", "")),
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
    ]

    found = []
    # 1. Search shortcuts (.lnk) in Desktop and Start Menu
    for sdir in search_roots[:4]:
        if sdir.exists():
            try:
                for p in sdir.rglob("*.lnk"):
                    p_name_lower = p.stem.lower()
                    if any(q in p_name_lower for q in search_queries):
                        found.append(("shortcut", str(p)))
            except Exception:
                pass

    # 2. Check shutil.which
    for q in search_queries:
        which_path = shutil.which(q)
        if which_path:
            found.append(("executable", which_path))

    # 3. Search common app directories for executables
    for sdir in search_roots[4:]:
        if sdir.exists():
            try:
                for q in search_queries:
                    for p in sdir.glob(f"*{q}*/*.exe"):
                        if any(sq in p.stem.lower() for sq in search_queries):
                            found.append(("executable", str(p)))
            except Exception:
                pass

    return found


@tool
def check_software_installed(software_name: str) -> str:
    """
    Check whether a software application or tool (e.g., Slack, VS Code, Google Chrome, Firefox, 7-Zip, VLC, Git, Notepad++)
    is currently installed on this PC.
    Searches Windows Start Menu, Desktop shortcuts, Program Files, AppData, and Windows Package Manager.

    Args:
        software_name: Name of the application (e.g. 'Slack', 'Chrome', 'VS Code', 'Firefox')

    Returns:
        Clear status confirming whether the application is installed, along with shortcut or executable location.
    """
    clean_name = software_name.strip()
    logger.info(f"Checking if software is installed: '{clean_name}'")

    matches = _find_installed_app(clean_name)
    if matches:
        shortcuts = [path for kind, path in matches if kind == "shortcut"]
        executables = [path for kind, path in matches if kind == "executable"]

        details = [f"YES: '{clean_name}' is installed on your PC!\n"]
        if shortcuts:
            details.append(f"  • Shortcut: {shortcuts[0]}")
        if executables:
            details.append(f"  • Location: {executables[0]}")
        details.append(f"\nTip: You can ask me to 'open {clean_name}' to launch it immediately.")
        return "\n".join(details)

    # If not found via filesystem, also check winget if available
    winget_path = _find_winget()
    if winget_path:
        try:
            res = subprocess.run(
                [winget_path, "list", clean_name],
                capture_output=True, text=True, timeout=15, shell=False
            )
            if clean_name.lower() in res.stdout.lower():
                return f"YES: '{clean_name}' was detected via Windows Package Manager:\n{res.stdout.strip()[:300]}\n\nTip: You can ask me to 'open {clean_name}'."
        except Exception:
            pass

    # Check if it's in WINGET_ALLOWLIST for helpful install recommendation
    from backend.config.settings import WINGET_ALLOWLIST
    suggested_pkg = None
    for pkg_id, display_name in WINGET_ALLOWLIST.items():
        if clean_name.lower() in display_name.lower() or clean_name.lower() in pkg_id.lower():
            suggested_pkg = (pkg_id, display_name)
            break

    if suggested_pkg:
        return (
            f"NO: '{clean_name}' is not currently installed on this PC.\n\n"
            f"Good news: '{suggested_pkg[1]}' is in the DeskPilot authorized software catalog.\n"
            f"Would you like me to install it for you? (Package: {suggested_pkg[0]})"
        )

    return f"NO: '{clean_name}' does not appear to be installed on this PC."


@tool
def launch_application(app_name: str) -> str:
    """
    Open or launch an installed software application or tool (e.g., Slack, Visual Studio Code, Chrome, Firefox, Notepad, Calculator)
    on the user's desktop.

    Args:
        app_name: Name of the application to launch (e.g. 'Slack', 'VS Code', 'Chrome', 'Firefox', 'Notepad')

    Returns:
        Status message confirming the application was launched or error details if not found.
    """
    clean_name = app_name.strip()
    logger.info(f"Attempting to launch application: '{clean_name}'")

    matches = _find_installed_app(clean_name)
    if matches:
        # Prefer shortcut (.lnk) so that Windows launches it with all configured flags/environment
        target = matches[0][1]
        try:
            import os
            os.startfile(target)
            logger.info(f"Successfully launched application via: {target}")
            return f"SUCCESS: Launched '{clean_name}' on your desktop.\n  Target: {target}"
        except Exception as e:
            logger.warning(f"os.startfile failed on {target}, attempting subprocess: {e}")
            try:
                subprocess.Popen([target], shell=True)
                return f"SUCCESS: Started '{clean_name}' on your desktop."
            except Exception as e2:
                return f"Error launching '{clean_name}': {str(e2)}"

    # Special Windows built-in aliases
    builtins = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "terminal": "wt.exe",
        "powershell": "powershell.exe",
    }
    cmd = builtins.get(clean_name.lower())
    if cmd:
        try:
            subprocess.Popen([cmd], shell=True)
            return f"SUCCESS: Opened {clean_name}."
        except Exception as e:
            return f"Error opening {clean_name}: {str(e)}"

    return (
        f"Error: Could not find '{clean_name}' installed on this PC to launch.\n"
        f"Tip: Ask me 'is {clean_name} installed?' to check, or 'install {clean_name}' to install it if authorized."
    )


@tool
def get_winget_allowlist() -> str:
    """
    Returns the complete list of software packages that DeskPilot is authorized to install
    via Windows Package Manager (winget). Each entry shows the winget ID and display name.

    Returns:
        Formatted table of all approved installable packages
    """
    lines = ["Authorized Software Packages (DeskPilot Winget Allow-List):\n"]
    lines.append(f"{'Package ID':<40} {'Display Name'}")
    lines.append("─" * 65)
    for pkg_id, display_name in sorted(WINGET_ALLOWLIST.items()):
        lines.append(f"{pkg_id:<40} {display_name}")
    lines.append(f"\nTotal: {len(WINGET_ALLOWLIST)} authorized packages")
    return "\n".join(lines)


@tool
def winget_install(package_id: str) -> str:
    """
    Safely install an approved software package via the official Windows Package Manager (winget).
    Installation is strictly constrained to the DeskPilot Winget allow-list.
    Always requires explicit human confirmation (RED tier).
    Streams real-time installation progress to the frontend.

    Args:
        package_id: Canonical Winget package ID (e.g., 'Git.Git', 'Mozilla.Firefox', 'Microsoft.VisualStudioCode')

    Returns:
        Status message with execution output or rejection details
    """
    clean_id = package_id.strip()
    logger.info(f"Requested software installation for package: '{clean_id}'")

    # 1. Hard validation against WINGET_ALLOWLIST
    if clean_id not in WINGET_ALLOWLIST:
        allowed_list_str = "\n".join([f"  • {k} ({v})" for k, v in sorted(WINGET_ALLOWLIST.items())])
        logger.warning(f"Installation rejected: '{clean_id}' is not in allow-list.")
        return (
            f"REJECTED: Package '{clean_id}' is not in the DeskPilot authorized software allow-list.\n\n"
            f"Authorized packages:\n{allowed_list_str}\n\n"
            f"Tip: Ask me to 'show available software' to see the full allow-list."
        )

    app_name = WINGET_ALLOWLIST[clean_id]

    # 2. Check if winget is available on this system
    winget_path = _find_winget()
    if not winget_path:
        logger.error("Winget executable not found on this system.")
        return (
            f"ERROR: Windows Package Manager (winget) is not installed or not accessible.\n\n"
            f"To fix this:\n"
            f"  1. Open Microsoft Store\n"
            f"  2. Search for 'App Installer'\n"
            f"  3. Install or update 'App Installer' (by Microsoft Corporation)\n"
            f"  4. Restart DeskPilot and try again.\n\n"
            f"Alternatively, download '{app_name}' manually from its official website."
        )

    # 3. Check if package is already installed
    emit_event("deskpilot:install_progress", {
        "package_id": clean_id,
        "app_name": app_name,
        "stage": "checking",
        "message": f"Checking if {app_name} is already installed...",
        "percent": 5,
    })

    try:
        check_proc = subprocess.run(
            [winget_path, "list", "--id", clean_id, "--exact"],
            capture_output=True, text=True, timeout=30, shell=False
        )
        if clean_id.lower() in check_proc.stdout.lower():
            logger.info(f"Package '{clean_id}' is already installed.")
            emit_event("deskpilot:install_progress", {
                "package_id": clean_id,
                "app_name": app_name,
                "stage": "already_installed",
                "message": f"{app_name} is already installed on this system.",
                "percent": 100,
            })
            return f"INFO: '{app_name}' ({clean_id}) is already installed on your system. No action needed."
    except Exception:
        pass  # If check fails, proceed with install attempt

    # 4. Strict RED-tier Human-in-the-Loop approval gate
    approved = request_approval(
        action_name="winget_install",
        description=f"Install approved software: {app_name} ({clean_id}) via Windows Package Manager (winget)?",
        tier="RED"
    )
    if not approved:
        logger.info(f"User denied installation of '{clean_id}'")
        emit_event("deskpilot:install_progress", {
            "package_id": clean_id,
            "app_name": app_name,
            "stage": "denied",
            "message": f"Installation of {app_name} was denied by user.",
            "percent": 0,
        })
        return f"CANCELLED: User denied permission to install '{app_name}' ({clean_id})."

    # 5. Begin installation with real-time streaming progress
    emit_event("deskpilot:install_progress", {
        "package_id": clean_id,
        "app_name": app_name,
        "stage": "starting",
        "message": f"Starting installation of {app_name}...",
        "percent": 10,
    })

    cmd = [winget_path, "install", clean_id,
           "--accept-source-agreements", "--accept-package-agreements", "--silent"]
    logger.info(f"Executing winget install for {clean_id}: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False
        )

        output_lines = []
        percent = 15

        def _stream_output():
            nonlocal percent
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                output_lines.append(line)
                logger.info(f"[winget] {line}")

                # Parse progress hints from winget output
                lower = line.lower()
                if "downloading" in lower:
                    percent = min(percent + 10, 50)
                    stage = "downloading"
                    msg = f"Downloading {app_name}..."
                elif "installing" in lower or "extracting" in lower:
                    percent = min(percent + 15, 80)
                    stage = "installing"
                    msg = f"Installing {app_name}..."
                elif "successfully" in lower or "installed" in lower:
                    percent = 100
                    stage = "complete"
                    msg = f"{app_name} installed successfully!"
                elif "failed" in lower or "error" in lower:
                    stage = "error"
                    msg = f"Error during installation: {line}"
                else:
                    stage = "progress"
                    msg = line

                emit_event("deskpilot:install_progress", {
                    "package_id": clean_id,
                    "app_name": app_name,
                    "stage": stage,
                    "message": msg,
                    "percent": percent,
                    "raw_line": line,
                })

        stream_thread = threading.Thread(target=_stream_output, daemon=True)
        stream_thread.start()
        proc.wait(timeout=300)
        stream_thread.join(timeout=5)

        if proc.returncode == 0:
            logger.info(f"Successfully installed '{clean_id}'")
            emit_event("deskpilot:install_progress", {
                "package_id": clean_id,
                "app_name": app_name,
                "stage": "complete",
                "message": f"{app_name} has been installed successfully!",
                "percent": 100,
            })
            return f"SUCCESS: '{app_name}' ({clean_id}) was installed successfully via Windows Package Manager."
        else:
            err_output = "\n".join(output_lines[-5:]) if output_lines else "No output captured."
            logger.error(f"Winget install failed with code {proc.returncode}: {err_output}")
            emit_event("deskpilot:install_progress", {
                "package_id": clean_id,
                "app_name": app_name,
                "stage": "failed",
                "message": f"Installation failed (exit code {proc.returncode}).",
                "percent": 0,
            })
            return (
                f"FAILED: Installation of '{app_name}' failed (exit code {proc.returncode}).\n"
                f"Details: {err_output[:400]}\n\n"
                f"Tip: Try running DeskPilot as Administrator, or install {app_name} manually."
            )

    except subprocess.TimeoutExpired:
        proc.kill()
        emit_event("deskpilot:install_progress", {
            "package_id": clean_id,
            "app_name": app_name,
            "stage": "timeout",
            "message": f"Installation timed out after 5 minutes.",
            "percent": 0,
        })
        return f"TIMEOUT: Installation of '{clean_id}' timed out after 300 seconds."
    except Exception as e:
        logger.error(f"Execution error during winget install: {e}")
        emit_event("deskpilot:install_progress", {
            "package_id": clean_id,
            "app_name": app_name,
            "stage": "error",
            "message": f"Unexpected error: {str(e)}",
            "percent": 0,
        })
        return f"ERROR: Could not execute winget: {str(e)}"
