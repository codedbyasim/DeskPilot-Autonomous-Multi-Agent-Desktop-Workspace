"""
DeskPilot — System Tools
Provides safe software management constrained exclusively to an explicit Winget allow-list.
Never downloads or executes arbitrary executables from the web.
Always classified as RED TIER (strict user confirmation required every time).
"""

import subprocess
import threading
import shutil
import os
import platform
import socket
from datetime import datetime, timedelta
from pathlib import Path
from strands import tool
from backend.config.settings import WINGET_ALLOWLIST
from backend.utils.logger import get_logger
from backend.utils.trust import request_approval
from backend.utils.events import emit_event

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = get_logger("tools.system")


def _format_bytes(num_bytes: int) -> str:
    """Format bytes into readable string."""
    n = float(num_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}".strip()
        n /= 1024.0
    return f"{n:.1f} PB"



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


@tool
def get_storage_status() -> str:
    """
    Comprehensive inspection of your PC's storage drives (C:, D:, etc.), available free space,
    used space percentages, and potential cleanup areas (%TEMP% files, Downloads folder, Desktop clutter).
    Automatically alerts if primary disk space is critically low (< 15%).

    Returns:
        Structured storage breakdown with visual capacity gauges, health warnings, and cleanup tips.
    """
    if not HAS_PSUTIL:
        return "Error: psutil library is not available for storage inspection."

    lines = ["💾 **DeskPilot System Storage Report**\n"]
    low_space_warnings = []
    primary_c_free_gb = 0
    primary_c_pct = 0

    # 1. Drive Partitions
    lines.append("### 💽 Drive Partitions & Capacities")
    partitions = psutil.disk_partitions(all=False)
    for part in partitions:
        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            percent = usage.percent

            # Visual progress bar (10 blocks)
            filled = int(percent / 10)
            bar = "█" * filled + "░" * (10 - filled)

            status_flag = "🟢 Healthy"
            if percent >= 90:
                status_flag = "🔴 CRITICAL LOW"
                low_space_warnings.append(f"Drive {part.mountpoint} has only {free_gb:.1f} GB ({100 - percent:.1f}% free) remaining!")
            elif percent >= 80:
                status_flag = "🟡 Warning"
                low_space_warnings.append(f"Drive {part.mountpoint} is {percent:.1f}% full ({free_gb:.1f} GB free).")

            if "C:" in part.mountpoint.upper():
                primary_c_free_gb = free_gb
                primary_c_pct = 100 - percent

            lines.append(
                f"• **{part.mountpoint}** [{part.fstype or 'NTFS'}] {status_flag}\n"
                f"  `[{bar}]` {percent:.1f}% used\n"
                f"  Free: **{free_gb:.1f} GB** / Total: {total_gb:.1f} GB (Used: {used_gb:.1f} GB)"
            )
        except Exception:
            continue

    # 2. Key Directories Cleanup Opportunity
    lines.append("\n### 🧹 Storage Usage in Common Locations")

    # Temp Folder
    temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", "C:/Windows/Temp")))
    temp_size = 0
    temp_count = 0
    if temp_dir.exists():
        try:
            for entry in temp_dir.iterdir():
                temp_count += 1
                try:
                    temp_size += entry.stat().st_size if entry.is_file() else sum(f.stat().st_size for f in entry.rglob('*') if f.is_file())
                except Exception:
                    pass
        except Exception:
            pass

    # Downloads Folder
    dl_dir = Path.home() / "Downloads"
    dl_size = 0
    dl_count = 0
    if dl_dir.exists():
        try:
            for entry in dl_dir.iterdir():
                dl_count += 1
                try:
                    dl_size += entry.stat().st_size if entry.is_file() else 0
                except Exception:
                    pass
        except Exception:
            pass

    # Desktop Folder
    desk_dir = Path.home() / "Desktop"
    desk_size = 0
    desk_count = 0
    if desk_dir.exists():
        try:
            for entry in desk_dir.iterdir():
                if not entry.name.startswith("."):
                    desk_count += 1
                    try:
                        desk_size += entry.stat().st_size if entry.is_file() else sum(f.stat().st_size for f in entry.rglob('*') if f.is_file())
                    except Exception:
                        pass
        except Exception:
            pass

    lines.append(f"• **Temporary Junk Files (`%TEMP%`)**: {_format_bytes(temp_size)} ({temp_count} items) — *Can be safely cleaned*")
    lines.append(f"• **Downloads Folder**: {_format_bytes(dl_size)} ({dl_count} items)")
    lines.append(f"• **Desktop Workspace**: {_format_bytes(desk_size)} ({desk_count} items)")

    # 3. Actionable Recommendations
    lines.append("\n### 💡 Recommendations & Actions")
    if low_space_warnings:
        lines.append("⚠️ **Attention Required**:")
        for w in low_space_warnings:
            lines.append(f"  • {w}")
        lines.append(f"  • You can ask me: **'Clean my temporary files'** to reclaim ~{_format_bytes(temp_size)} immediately.")
        lines.append(f"  • You can also ask me: **'Scan Desktop for files to organize or delete'**.")
    else:
        lines.append("✅ All system drives have adequate free storage space.")
        if temp_size > 500 * (1024 ** 2):  # > 500 MB
            lines.append(f"• Tip: You have {_format_bytes(temp_size)} of temp files. Ask me: 'Clean temp files' anytime.")

    # Emit real-time storage event for the frontend top banner / header pill
    emit_event("deskpilot:storage_update", {
        "c_free_gb": f"{primary_c_free_gb:.1f}",
        "c_free_pct": f"{primary_c_pct:.1f}",
        "temp_size_str": _format_bytes(temp_size),
        "is_low": bool(low_space_warnings),
        "timestamp": datetime.now().isoformat()
    })

    if low_space_warnings:
        emit_event("deskpilot:system_alert", {
            "type": "warning",
            "title": "Storage Warning",
            "message": f"Drive C: has {primary_c_free_gb:.1f} GB remaining ({primary_c_pct:.1f}% free). Reclaim {_format_bytes(temp_size)} via temp clean.",
            "action_type": "storage_alert"
        })

    return "\n".join(lines)


@tool
def clean_temporary_files(dry_run: bool = True) -> str:
    """
    Scans or cleans temporary junk files and application cache from your user %TEMP% directory.
    When dry_run=True (default), safely analyzes and reports how much storage can be freed without deleting anything.
    When dry_run=False, asks user confirmation (YELLOW tier) and deletes safe temporary files, returning reclaimed space.

    Args:
        dry_run: If True (default), inspect and report only. If False, clean and delete temporary files.

    Returns:
        Summary of temporary files inspected/cleaned and total storage space reclaimed.
    """
    temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", "C:/Windows/Temp")))
    if not temp_dir.exists():
        return f"Error: Temporary directory '{temp_dir}' does not exist."

    total_files = 0
    total_bytes = 0
    candidates = []

    try:
        for entry in temp_dir.iterdir():
            try:
                if entry.name.startswith("~") or entry.suffix.lower() in [".tmp", ".log", ".bak", ".dat", ".txt", ".dmp"] or entry.is_dir():
                    size = entry.stat().st_size if entry.is_file() else sum(f.stat().st_size for f in entry.rglob('*') if f.is_file())
                    total_bytes += size
                    total_files += 1
                    candidates.append((entry, size))
            except Exception:
                continue
    except Exception as e:
        return f"Error accessing temp directory: {str(e)}"

    size_str = _format_bytes(total_bytes)

    if dry_run:
        return (
            f"🧹 **Temporary Storage Analysis**\n\n"
            f"• Found **{total_files:,}** temporary and cache items in `{temp_dir}`.\n"
            f"• Potential space to reclaim: **{size_str}**.\n\n"
            f"To safely clean these files, ask me: **'Clean my temporary files now'** (or pass dry_run=False)."
        )

    # Human-in-the-loop Yellow tier approval gate for actual deletion
    approval_prompt = f"Clean {total_files} temporary files and reclaim ~{size_str} from user %TEMP% folder?"
    if not request_approval("clean_temporary_files", approval_prompt, tier="YELLOW"):
        return f"Cancelled: User denied permission to clean temporary files."

    deleted_count = 0
    reclaimed_bytes = 0
    locked_count = 0

    for entry, size in candidates:
        try:
            if entry.is_dir():
                shutil.rmtree(str(entry), ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            deleted_count += 1
            reclaimed_bytes += size
        except Exception:
            locked_count += 1

    reclaimed_str = _format_bytes(reclaimed_bytes)
    emit_event("deskpilot:system_alert", {
        "type": "success",
        "title": "Storage Cleaned",
        "message": f"Cleaned {deleted_count} temporary files and reclaimed {reclaimed_str}.",
        "action_type": "clean_temp"
    })

    return (
        f"SUCCESS: Reclaimed **{reclaimed_str}** of disk storage!\n"
        f"• Deleted: {deleted_count:,} temporary files.\n"
        f"• In-use/Skipped: {locked_count:,} active files currently locked by running Windows applications."
    )


@tool
def get_system_info() -> str:
    """
    Comprehensive system information & hardware diagnostics helper.
    Returns executive details about your Operating System, CPU specifications & utilization,
    RAM memory usage, battery/power status (laptop/desktop), system uptime, and network IP.

    Returns:
        Structured table of system specifications, resource loads, and operational metrics.
    """
    lines = ["💻 **DeskPilot System Diagnostics & Hardware Specs**\n"]

    # 1. Operating System
    uname = platform.uname()
    lines.append("### 🖥️ Operating System & Machine")
    lines.append(f"• **OS**: {uname.system} {uname.release} (Build {uname.version.split('.')[2] if '.' in uname.version else uname.version})")
    lines.append(f"• **Architecture**: {platform.architecture()[0]} ({uname.machine})")
    lines.append(f"• **Computer Name**: `{uname.node}`")

    # 2. Processor (CPU)
    lines.append("\n### ⚡ Processor (CPU)")
    if HAS_PSUTIL:
        phys_cores = psutil.cpu_count(logical=False) or 1
        log_cores = psutil.cpu_count(logical=True) or 1
        cpu_pct = psutil.cpu_percent(interval=0.1)
        lines.append(f"• **Processor Model**: {uname.processor or 'x86_64 Compatible'}")
        lines.append(f"• **Cores**: {phys_cores} Physical, {log_cores} Logical Threads")
        lines.append(f"• **Current CPU Load**: **{cpu_pct}%** {'🟢 (Optimal)' if cpu_pct < 50 else ('🟡 (Moderate)' if cpu_pct < 80 else '🔴 (High Load)')}")
    else:
        lines.append(f"• **Processor**: {uname.processor}")

    # 3. RAM Memory
    lines.append("\n### 🧠 Memory (RAM)")
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        total_gb = vm.total / (1024 ** 3)
        used_gb = vm.used / (1024 ** 3)
        free_gb = vm.available / (1024 ** 3)
        pct = vm.percent
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"• **Total RAM**: {total_gb:.1f} GB")
        lines.append(f"• **Used**: **{used_gb:.1f} GB** ({pct}%) `[{bar}]`")
        lines.append(f"• **Available / Free**: **{free_gb:.1f} GB**")
        status_ram = "🟢 Healthy" if pct < 75 else ("🟡 Moderate" if pct < 90 else "🔴 High Memory Pressure")
        lines.append(f"• **RAM Status**: {status_ram}")

    # 4. Power & Battery Status
    lines.append("\n### 🔋 Power & Battery")
    if HAS_PSUTIL:
        battery = psutil.sensors_battery()
        if battery:
            plugged = "🔌 Plugged in (Charging/A/C)" if battery.power_plugged else "🔋 On Battery Power"
            pct = battery.percent
            lines.append(f"• **Battery Level**: **{pct}%** ({plugged})")
        else:
            lines.append("• **Power Source**: 🔌 Desktop PC / Continuous Wall A/C Power (No battery)")
    else:
        lines.append("• **Power**: Standard System Power")

    # 5. Uptime & Network
    lines.append("\n### ⏱️ System Uptime & Network")
    if HAS_PSUTIL:
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"
        lines.append(f"• **System Uptime**: **{uptime_str}** (Booted: {boot_time.strftime('%Y-%m-%d %H:%M')})")

    # Network IP
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        lines.append(f"• **Local Network IP**: `{local_ip}`")
    except Exception:
        pass

    return "\n".join(lines)


@tool
def get_running_processes(sort_by: str = "memory", limit: int = 10) -> str:
    """
    List active running processes and applications on your system, sorted by memory or CPU usage.
    Helps identify which programs are consuming the most system resources or slowing down the computer.

    Args:
        sort_by: Criteria to sort by: 'memory' (RAM usage in MB) or 'cpu' (CPU percentage)
        limit: Number of top processes to return (default 10, max 25)

    Returns:
        Formatted table of top resource-consuming applications with process names, PIDs, and usage stats.
    """
    if not HAS_PSUTIL:
        return "Error: psutil is required to inspect running processes."

    clean_limit = min(max(1, limit), 25)
    procs = []

    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
        try:
            info = p.info
            mem_mb = (info['memory_info'].rss / (1024 * 1024)) if info.get('memory_info') else 0
            cpu_pct = info.get('cpu_percent') or 0.0
            procs.append({
                "pid": info['pid'],
                "name": info['name'] or 'Unknown',
                "memory_mb": mem_mb,
                "cpu_percent": cpu_pct,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if sort_by.lower() == "cpu":
        procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
        title_sort = "CPU Usage (%)"
    else:
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        title_sort = "RAM Memory Usage (MB)"

    top_procs = procs[:clean_limit]

    lines = [f"📊 **Top {len(top_procs)} Active Processes (Sorted by {title_sort})**\n"]
    lines.append(f"{'PID':<8} {'Process Name':<28} {'RAM (MB)':<12} {'CPU (%)'}")
    lines.append("─" * 60)

    total_mem = 0
    for pr in top_procs:
        total_mem += pr["memory_mb"]
        lines.append(f"{pr['pid']:<8} {pr['name'][:26]:<28} {pr['memory_mb']:>8.1f} MB   {pr['cpu_percent']:>5.1f}%")

    lines.append("─" * 60)
    lines.append(f"Combined RAM of top {len(top_procs)} processes: **{_format_bytes(int(total_mem * 1024 * 1024))}**")
    lines.append("\nTip: If an application is frozen or consuming excessive RAM, you can check its PID above.")
    return "\n".join(lines)

