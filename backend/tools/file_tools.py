"""
DeskPilot — File Management Tools
Provides safe file operations within an approved working directory or Desktop.
Enforces Human-in-the-Loop confirmation for Yellow (move/rename) and Red (delete) actions.
"""

from strands import tool
import os
import shutil
from pathlib import Path
from datetime import datetime
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.logger import get_logger
from backend.utils.trust import request_approval
from backend.utils.events import emit_event

try:
    import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False

logger = get_logger("tools.file")


def _format_size(num_bytes: int) -> str:
    """Format bytes into human readable KB, MB, GB."""
    n = float(num_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}".strip()
        n /= 1024.0
    return f"{n:.1f} PB"



def _resolve_path(path_str: str, prefer_desktop: bool = False) -> Path:
    """
    Safely resolves user/agent provided paths to absolute Path objects.
    Handles 'Desktop', 'desktop', '~/Desktop', relative paths, etc.
    """
    if not path_str or not path_str.strip():
        return (Path.home() / "Desktop").resolve() if prefer_desktop else DEFAULT_OUTPUT_DIR.resolve()

    p_str = path_str.strip().strip("'\"")
    if p_str.startswith("~"):
        return Path(p_str).expanduser().resolve()

    p_norm = p_str.replace("\\", "/").strip()
    if p_norm.lower() == "desktop":
        return (Path.home() / "Desktop").resolve()
    if p_norm.lower().startswith("desktop/"):
        return (Path.home() / "Desktop" / p_norm[8:]).resolve()

    p = Path(p_str)
    if p.is_absolute():
        return p.resolve()

    # If relative, check if exists on Desktop first, then output dir, then cwd
    desktop_cand = (Path.home() / "Desktop" / p).resolve()
    if desktop_cand.exists():
        return desktop_cand

    out_cand = (DEFAULT_OUTPUT_DIR / p).resolve()
    if out_cand.exists():
        return out_cand

    cwd_cand = p.resolve()
    if cwd_cand.exists():
        return cwd_cand

    # If path does not exist yet (creating new file/folder)
    return desktop_cand if prefer_desktop else out_cand


@tool
def list_files(folder_path: str = "", extension: str = "") -> str:
    """
    List files and folders in a directory, optionally filtered by extension.

    Args:
        folder_path: Folder to list. Pass 'Desktop' to scan the desktop, or leave empty for DeskPilot output directory.
        extension: File extension filter (e.g., '.docx', '.pdf', '.xlsx')

    Returns:
        Formatted list of files and folders with sizes and dates
    """
    folder = _resolve_path(folder_path, prefer_desktop=False)
    logger.info(f"Listing files in: {folder} (filter: '{extension}')")

    if not folder.exists():
        return f"Folder not found: '{folder}'"

    ext_filter = extension.strip()
    if ext_filter and not ext_filter.startswith("."):
        ext_filter = f".{ext_filter}"

    pattern = f"*{ext_filter}" if ext_filter else "*"
    try:
        items = list(folder.glob(pattern))
    except Exception as e:
        return f"Error scanning folder '{folder}': {str(e)}"

    if not items:
        return f"No items found in '{folder}'" + (f" with extension '{ext_filter}'" if ext_filter else "")

    result = f"Items in '{folder}':\n{'─'*65}\n"
    dirs = [item for item in items if item.is_dir()]
    files = [item for item in items if item.is_file() and not item.name.startswith("~$")]

    for d in sorted(dirs, key=lambda x: x.name.lower()):
        mtime = datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        result += f"  📁 [DIR]  {d.name:36s}  {'--':10s}  {mtime}\n"

    for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
        size = f.stat().st_size
        size_str = f"{size // 1024} KB" if size > 1024 else f"{size} B"
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        result += f"  📄 [FILE] {f.name:36s}  {size_str:10s}  {mtime}\n"

    result += f"\nTotal: {len(dirs)} folder(s), {len(files)} file(s)"
    return result


@tool
def verify_file_exists(file_path: str) -> str:
    """
    Verify a file exists at the given path and return its details.

    Args:
        file_path: Full path to the file to check

    Returns:
        Verification status with file details or error
    """
    path = _resolve_path(file_path)
    logger.info(f"Verifying file exists: {path}")

    if not path.exists():
        return f"FAIL: File not found at '{file_path}' (resolved: '{path}')"

    if not path.is_file():
        return f"FAIL: Path exists but is a directory, not a file: '{path}'"

    size = path.stat().st_size
    size_str = f"{size // 1024} KB" if size > 1024 else f"{size} B"
    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    return (
        f"✓ File verified: {path.name}\n"
        f"  Path: {path}\n"
        f"  Size: {size_str}\n"
        f"  Modified: {mtime}\n"
        f"  Extension: {path.suffix}"
    )


def _safe_retry_op(op, max_retries=3, delay=0.3):
    """Retries file operations that fail due to Windows indexing/defender locks."""
    import time
    for i in range(max_retries):
        try:
            return op()
        except PermissionError:
            if i == max_retries - 1:
                raise
            time.sleep(delay)


CATEGORY_RULES = {
    "Documents": {".docx", ".doc", ".txt", ".rtf", ".odt", ".md", ".tex", ".wpd"},
    "Spreadsheets": {".xlsx", ".xls", ".csv", ".tsv", ".ods"},
    "Presentations": {".pptx", ".ppt", ".key", ".odp"},
    "PDFs": {".pdf"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff"},
    "Code": {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".cpp", ".c", ".h", ".java", ".cs", ".sql", ".sh", ".bat", ".ps1"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "Shortcuts": {".lnk", ".url"},
}


def _get_file_category(filename: str) -> str:
    """Categorizes a file into standard desktop categories based on extension."""
    suffix = Path(filename).suffix.lower()
    for cat, exts in CATEGORY_RULES.items():
        if suffix in exts:
            return cat
    return "Other"


@tool
def organize_files(folder_path: str = "Desktop") -> str:
    """
    Scan a directory (defaults to Desktop) and automatically categorize and organize loose files into
    clean subfolders (Documents, Spreadsheets, Presentations, PDFs, Images, Code, Archives, Shortcuts).
    Requires a single YELLOW tier approval before moving all files in a batch.

    Args:
        folder_path: Target folder to organize. Pass 'Desktop' or leave empty for the user's Desktop.

    Returns:
        Structured summary of organized files by category or notification if no files need organization.
    """
    target_dir = _resolve_path(folder_path, prefer_desktop=True)
    logger.info(f"Batch organizing files in directory: {target_dir}")

    if not target_dir.exists():
        return f"Error: Target directory not found: '{folder_path}' (resolved: '{target_dir}')"

    # Scan for loose files only (exclude subdirectories, hidden files, and temp files)
    try:
        all_items = list(target_dir.iterdir())
    except Exception as e:
        return f"Error scanning directory '{target_dir}': {str(e)}"

    files_to_organize = [
        item for item in all_items
        if item.is_file()
        and not item.name.startswith((".", "~$", "desktop.ini", "Thumbs.db"))
    ]

    if not files_to_organize:
        return f"No loose files found to organize in '{target_dir.name}'."

    # Group files into categories
    categorized = {}
    for f in files_to_organize:
        cat = _get_file_category(f.name)
        categorized.setdefault(cat, []).append(f)

    # Build category breakdown string for single Human-in-the-Loop approval dialog
    cat_summary = ", ".join([f"{cat} ({len(fls)})" for cat, fls in categorized.items()])
    approval_prompt = (
        f"Organize {len(files_to_organize)} loose file(s) in '{target_dir.name}' into categorized folders: {cat_summary}?"
    )

    if not request_approval("organize_files", approval_prompt):
        return f"Cancelled: User denied permission to organize files in '{target_dir.name}'."

    moved_count = 0
    failed_moves = []
    category_results = {}

    for cat, files in categorized.items():
        cat_dir = target_dir / cat
        try:
            cat_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            failed_moves.append(f"Could not create folder '{cat}': {e}")
            continue

        category_results[cat] = []
        for f in files:
            dest = cat_dir / f.name
            if dest.exists() and dest != f:
                # Disambiguate duplicate name with timestamp
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = cat_dir / f"{f.stem}_{ts}{f.suffix}"

            try:
                _safe_retry_op(lambda: shutil.move(str(f), str(dest)))
                moved_count += 1
                category_results[cat].append(dest.name)
            except Exception as e:
                logger.error(f"Failed to move '{f.name}' to '{cat_dir}': {e}")
                failed_moves.append(f"{f.name} ({str(e)})")

    # Format result report
    lines = [f"SUCCESS: Organized {moved_count} file(s) in '{target_dir.name}' into categorized folders:\n"]
    for cat, names in sorted(category_results.items()):
        if names:
            preview = ", ".join([f"'{n}'" for n in names[:4]])
            if len(names) > 4:
                preview += f" ...and {len(names) - 4} more"
            lines.append(f"- 📁 **{cat}** ({len(names)} files): {preview}")

    if failed_moves:
        lines.append(f"\n⚠️ Note: {len(failed_moves)} file(s) could not be moved: {', '.join(failed_moves)}")

    logger.info(f"Batch organization completed: {moved_count} moved, {len(failed_moves)} failed.")
    return "\n".join(lines)


@tool
def move_file(source_path: str, destination_path: str) -> str:
    """
    Move a file from source to destination directory or target path.
    Requires YELLOW tier approval before execution.

    Args:
        source_path: Current file path
        destination_path: Target folder or file path

    Returns:
        Success or error message
    """
    src = _resolve_path(source_path)
    dst = _resolve_path(destination_path, prefer_desktop=True)
    logger.info(f"Moving file: {src} → {dst}")

    if not src.exists():
        return f"Error: Source file not found: '{source_path}' (resolved: '{src}')"

    # If destination is a directory or path without extension, treat as folder
    if dst.is_dir() or (not dst.suffix and "." not in dst.name):
        dst.mkdir(parents=True, exist_ok=True)
        target = dst / src.name
    else:
        target = dst

    # Human-in-the-loop Yellow tier approval gate
    if not request_approval("move_file", f"Move file '{src.name}' to '{target}'"):
        return f"Cancelled: User denied permission to move '{src.name}'"

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        _safe_retry_op(lambda: shutil.move(str(src), str(target)))
        logger.info(f"File moved successfully: {src} -> {target}")
        return f"SUCCESS: Moved '{src.name}' to '{target}'"
    except Exception as e:
        return f"Error moving file: {str(e)}"


@tool
def rename_file(file_path: str, new_name: str) -> str:
    """
    Rename a file in the same directory.
    Requires YELLOW tier approval.

    Args:
        file_path: Current path of the file
        new_name: New filename (without path)

    Returns:
        Success or error message
    """
    path = _resolve_path(file_path)
    logger.info(f"Renaming requested: {path.name} → {new_name}")

    if not path.exists():
        return f"Error: File not found: '{file_path}' (resolved: '{path}')"

    new_name_clean = Path(new_name).name
    new_path = path.parent / new_name_clean

    # Human-in-the-loop Yellow tier approval gate
    if not request_approval("rename_file", f"Rename file '{path.name}' to '{new_name_clean}'"):
        return f"Cancelled: User denied permission to rename '{path.name}'"

    try:
        _safe_retry_op(lambda: path.rename(new_path))
        logger.info(f"File renamed successfully: {path} -> {new_path}")
        return f"SUCCESS: Renamed to '{new_name_clean}' at '{new_path}'"
    except Exception as e:
        return f"Error renaming file: {str(e)}"


@tool
def delete_file(file_path: str, permanent: bool = False) -> str:
    """
    Delete a file or folder safely.
    By default (permanent=False), safely moves the file to the Windows Recycle Bin,
    allowing the user to restore it at any time.
    If permanent=True, deletes the file permanently without Recycle Bin recovery.
    Always requires RED tier user confirmation.

    Args:
        file_path: Path or filename of the file or folder to delete (e.g. 'TB_Lab_Report.docx', 'Desktop/temp.txt')
        permanent: If True, permanently destroy file. Default is False (safely move to Windows Recycle Bin).

    Returns:
        Detailed status message indicating successful deletion or cancellation.
    """
    path = _resolve_path(file_path)
    logger.info(f"Delete requested: {path} (permanent={permanent})")

    if not path.exists():
        cand = Path.home() / "Desktop" / Path(file_path).name
        if cand.exists():
            path = cand

    if not path.exists():
        return f"Error: Item not found: '{file_path}' (resolved: '{path}')"

    item_type = "folder" if path.is_dir() else "file"
    try:
        size_bytes = path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        size_str = _format_size(size_bytes)
    except Exception:
        size_str = "unknown size"

    action_desc = "Permanently delete" if permanent else "Move to Windows Recycle Bin"
    safety_note = "(Warning: Cannot be undone)" if permanent else "(Safe & 100% Recoverable from Recycle Bin)"
    approval_prompt = f"{action_desc} {item_type} '{path.name}' ({size_str})? {safety_note}"

    # Human-in-the-loop Red tier approval gate
    if not request_approval("delete_file", approval_prompt, tier="RED"):
        return f"Cancelled: User denied permission to delete '{path.name}'"

    try:
        if not permanent and HAS_SEND2TRASH:
            send2trash.send2trash(str(path))
            logger.info(f"Safely sent to Recycle Bin: {path}")
            emit_event("deskpilot:system_alert", {
                "type": "warning",
                "title": "Recycle Bin Deletion",
                "message": f"Moved '{path.name}' ({size_str}) to Windows Recycle Bin (Recoverable).",
                "action_type": "delete_file"
            })
            return (
                f"SUCCESS: Safely moved {item_type} '{path.name}' ({size_str}) to the Windows Recycle Bin.\n"
                f"Original location: {path.parent}\n"
                f"Status: Safe & Recoverable (You can restore this anytime from your Windows Recycle Bin)."
            )
        else:
            if path.is_dir():
                _safe_retry_op(lambda: shutil.rmtree(str(path)))
            else:
                _safe_retry_op(lambda: path.unlink())
            logger.info(f"File permanently deleted: {path}")
            emit_event("deskpilot:system_alert", {
                "type": "error",
                "title": "Permanent Deletion",
                "message": f"Permanently deleted '{path.name}' ({size_str}).",
                "action_type": "delete_file_permanent"
            })
            return f"SUCCESS: Permanently deleted {item_type} '{path.name}' ({size_str})."
    except Exception as e:
        return f"Error deleting {item_type}: {str(e)}"


@tool
def delete_files(file_paths: str, permanent: bool = False, reason: str = "") -> str:
    """
    Batch delete multiple files or folders safely in one unified operation.
    Accepts a comma-separated list of filenames/paths, or a wildcard pattern (e.g. 'Desktop/*.docx', 'Desktop/*.tmp').
    By default (permanent=False), moves all files to Windows Recycle Bin so they can be restored.
    Requests user confirmation ONCE for the entire batch to avoid multiple annoying prompts.

    Args:
        file_paths: Comma-separated paths, list of filenames, or wildcard pattern (e.g. 'file1.docx, file2.docx' or 'Desktop/*.tmp')
        permanent: If True, delete permanently. Default is False (move to Recycle Bin).
        reason: Optional user or agent reason for deletion (e.g. 'Cleaning duplicate Word documents')

    Returns:
        Comprehensive summary of deleted files, total storage reclaimed, and Recycle Bin status.
    """
    raw_paths = []
    if isinstance(file_paths, str):
        clean_str = file_paths.strip()
        if "*" in clean_str or "?" in clean_str:
            p = Path(clean_str)
            parent = _resolve_path(str(p.parent) if str(p.parent) != "." else "Desktop")
            if parent.exists():
                raw_paths = [str(f) for f in parent.glob(p.name)]
            else:
                raw_paths = [str(f) for f in (Path.home() / "Desktop").glob(p.name)]
        else:
            raw_paths = [p.strip().strip("'\"") for p in clean_str.split(",") if p.strip()]
    elif isinstance(file_paths, list):
        raw_paths = [str(p) for p in file_paths]

    if not raw_paths:
        return "Error: No file paths provided for batch deletion."

    items_to_delete = []
    missing = []
    total_bytes = 0

    for item in raw_paths:
        p = _resolve_path(item)
        if not p.exists():
            cand = Path.home() / "Desktop" / Path(item).name
            if cand.exists():
                p = cand
        if p.exists():
            items_to_delete.append(p)
            try:
                total_bytes += p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
            except Exception:
                pass
        else:
            missing.append(item)

    if not items_to_delete:
        msg = "Error: None of the specified files were found to delete."
        if missing:
            msg += f"\nMissing: {', '.join(missing)}"
        return msg

    total_size_str = _format_size(total_bytes)
    action_desc = "Permanently delete" if permanent else "Move to Windows Recycle Bin"
    safety_note = "(Warning: Permanent, cannot be undone)" if permanent else "(Safe & 100% Recoverable from Recycle Bin)"
    names_preview = ", ".join([f"'{p.name}'" for p in items_to_delete[:5]])
    if len(items_to_delete) > 5:
        names_preview += f" and {len(items_to_delete) - 5} more"

    approval_prompt = (
        f"{action_desc} {len(items_to_delete)} items ({total_size_str})?\n"
        f"Files: {names_preview}\n{safety_note}"
    )

    if not request_approval("delete_files", approval_prompt, tier="RED"):
        return f"Cancelled: User denied permission to delete {len(items_to_delete)} files."

    succeeded = []
    failed = []

    for p in items_to_delete:
        try:
            if not permanent and HAS_SEND2TRASH:
                send2trash.send2trash(str(p))
            else:
                if p.is_dir():
                    _safe_retry_op(lambda: shutil.rmtree(str(p)))
                else:
                    _safe_retry_op(lambda: p.unlink())
            succeeded.append(p.name)
        except Exception as e:
            failed.append((p.name, str(e)))

    dest = "permanently deleted" if permanent else "moved to the Windows Recycle Bin"
    emit_event("deskpilot:system_alert", {
        "type": "warning" if not permanent else "error",
        "title": "Batch Deletion Complete",
        "message": f"{len(succeeded)} files ({total_size_str}) {dest}.",
        "action_type": "delete_files"
    })

    lines = [f"SUCCESS: {len(succeeded)} file(s) safely {dest} (Reclaimed ~{total_size_str}):"]
    for name in succeeded:
        lines.append(f"  • {name}")
    if failed:
        lines.append("\nFailed to delete:")
        for name, err in failed:
            lines.append(f"  • {name}: {err}")
    if not permanent:
        lines.append("\nNote: All items are in your Windows Recycle Bin and can be restored at any time.")

    return "\n".join(lines)



@tool
def open_file(file_path: str) -> str:
    """
    Open a deliverable file (.docx, .xlsx, .pdf, .png, etc.) in its default desktop application
    (Word, Excel, PDF viewer, Photos, etc.).
    Automatically searches Desktop and DeskPilot output directory if path is relative.

    Args:
        file_path: Path to the file to open (absolute, relative, or just filename)

    Returns:
        Success or error message with file details
    """
    path = _resolve_path(file_path)

    # Extended search if not found — try Desktop, output dir, and DeskPilot_Output subdirs
    if not path.exists():
        filename = Path(file_path).name
        search_roots = [
            Path.home() / "Desktop",
            DEFAULT_OUTPUT_DIR,
            Path.home() / "Desktop" / "DeskPilot_Output",
            Path.home() / "Documents",
        ]
        for root in search_roots:
            candidate = root / filename
            if candidate.exists():
                path = candidate
                logger.info(f"Resolved '{file_path}' → '{path}' via extended search")
                break

    if not path.exists():
        return (
            f"Error: File not found: '{file_path}'\n"
            f"Searched: Desktop, Documents, DeskPilot Output folder.\n"
            f"Tip: Provide the full absolute path to ensure the file is found."
        )

    if not path.is_file():
        return f"Error: '{path}' is a directory. Use 'open_folder' to open a folder in Explorer."

    size = path.stat().st_size
    size_str = f"{size // 1024} KB" if size > 1024 else f"{size} B"

    try:
        os.startfile(str(path))
        logger.info(f"Opened file in default application: {path.name} ({size_str})")
        return (
            f"SUCCESS: Opened '{path.name}' in its default desktop application.\n"
            f"  Full path: {path}\n"
            f"  Size: {size_str}"
        )
    except FileNotFoundError:
        return f"Error: No default application is associated with '{path.suffix}' files. Please install a suitable application."
    except PermissionError:
        return f"Error: Permission denied when opening '{path.name}'. The file may be in use by another process."
    except Exception as e:
        return f"Error opening file '{path.name}': {str(e)}"


@tool
def open_folder(folder_path: str = "") -> str:
    """
    Open a folder in Windows Explorer so the user can browse its contents visually.
    Useful for revealing where generated deliverables (Word reports, Excel sheets, PDFs) were saved.

    Args:
        folder_path: Path to the folder to open. Pass 'Desktop' for the Desktop, or leave empty
                     for the DeskPilot output directory. Can also be a file path — will open the containing folder.

    Returns:
        Success or error message
    """
    if not folder_path or not folder_path.strip():
        target = DEFAULT_OUTPUT_DIR
    else:
        path = _resolve_path(folder_path, prefer_desktop=True)
        # If a file path is given, open its parent folder
        if path.is_file():
            target = path.parent
        else:
            target = path

    if not target.exists():
        return f"Error: Folder not found: '{folder_path}' (resolved: '{target}')"

    try:
        import subprocess
        subprocess.Popen(["explorer", str(target)])
        logger.info(f"Opened folder in Explorer: {target}")
        return f"SUCCESS: Opened folder '{target.name}' in Windows Explorer.\n  Path: {target}"
    except Exception as e:
        return f"Error opening folder: {str(e)}"


@tool
def get_file_info(file_path: str) -> str:
    """
    Get detailed metadata about a file without opening it — name, size, type, modification date, and full path.
    Useful for verifying a deliverable was saved correctly before presenting it to the user.

    Args:
        file_path: Path to the file (absolute or relative)

    Returns:
        Detailed file metadata or error
    """
    path = _resolve_path(file_path)

    # Extended search
    if not path.exists():
        filename = Path(file_path).name
        for root in [Path.home() / "Desktop", DEFAULT_OUTPUT_DIR]:
            candidate = root / filename
            if candidate.exists():
                path = candidate
                break

    if not path.exists():
        return f"Error: File not found: '{file_path}'"

    if not path.is_file():
        return f"Error: '{path}' is a directory, not a file."

    stat = path.stat()
    size = stat.st_size
    size_str = f"{size / 1024 / 1024:.2f} MB" if size > 1024 * 1024 else (f"{size // 1024} KB" if size > 1024 else f"{size} B")
    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    ctime = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")

    ext_labels = {
        ".docx": "Microsoft Word Document",
        ".xlsx": "Microsoft Excel Workbook",
        ".pdf": "PDF Document",
        ".png": "PNG Image",
        ".jpg": "JPEG Image",
        ".jpeg": "JPEG Image",
        ".txt": "Plain Text File",
        ".csv": "CSV Spreadsheet",
        ".pptx": "PowerPoint Presentation",
        ".mp4": "MP4 Video",
        ".zip": "ZIP Archive",
    }
    file_type = ext_labels.get(path.suffix.lower(), f"{path.suffix.upper()} File" if path.suffix else "Unknown Type")

    return (
        f"File Information:\n"
        f"{'─' * 50}\n"
        f"  Name:      {path.name}\n"
        f"  Type:      {file_type}\n"
        f"  Size:      {size_str} ({size:,} bytes)\n"
        f"  Location:  {path.parent}\n"
        f"  Full Path: {path}\n"
        f"  Modified:  {mtime}\n"
        f"  Created:   {ctime}"
    )


@tool
def take_screenshot(save_path: str = "") -> str:
    """
    Capture a screenshot of the Windows desktop screen and save to disk.

    Args:
        save_path: Optional path to save screenshot PNG. Defaults to Desktop.

    Returns:
        Path of saved screenshot or error
    """
    try:
        out = _resolve_path(save_path, prefer_desktop=True) if save_path else (Path.home() / "Desktop" / f"DeskPilot_Screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        out.parent.mkdir(parents=True, exist_ok=True)

        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.save(str(out))
        logger.info(f"Screenshot captured: {out}")
        return f"SUCCESS: Screenshot captured ({img.size[0]}x{img.size[1]}) and saved to '{out}'"
    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")
        return f"Error capturing screenshot: {str(e)}"


@tool
def create_folder(folder_path: str) -> str:
    """
    Create a new folder (and any missing parents).

    Args:
        folder_path: Path of the folder to create. Can be an absolute path, 'Desktop/folder_name', or just 'folder_name'.

    Returns:
        Success or error message
    """
    path = _resolve_path(folder_path, prefer_desktop=True)
    logger.info(f"Creating folder: {path}")

    try:
        path.mkdir(parents=True, exist_ok=True)
        return f"SUCCESS: Folder created at '{path}'"
    except Exception as e:
        return f"Error creating folder: {str(e)}"


@tool
def get_desktop_path() -> str:
    """
    Returns the current user's Desktop path.

    Returns:
        Desktop path string
    """
    desktop = Path.home() / "Desktop"
    return str(desktop)


@tool
def get_output_directory() -> str:
    """
    Returns the DeskPilot default output directory.

    Returns:
        Output directory path string
    """
    return str(DEFAULT_OUTPUT_DIR)


@tool
def read_file(file_path: str, max_chars: int = 8000) -> str:
    """
    Read content from a text file (.txt, .md, .csv, .json, .py, .html, .log, etc.).

    Args:
        file_path: Path of the file to read (e.g. 'Desktop/report.txt', 'notes.md')
        max_chars: Maximum characters to read (defaults to 8000)

    Returns:
        Content of the file or error message
    """
    path = _resolve_path(file_path)
    logger.info(f"Reading file: {path}")

    if not path.exists():
        candidates = [
            Path.home() / "Desktop" / Path(file_path).name,
            DEFAULT_OUTPUT_DIR / Path(file_path).name,
            Path("sample_data") / Path(file_path).name,
        ]
        for c in candidates:
            if c.exists():
                path = c
                break

    if not path.exists():
        return f"Error: File not found at '{file_path}'"

    if path.is_dir():
        return f"Error: '{path}' is a directory, not a file. Use 'list_files' to inspect directories."

    encodings = ["utf-8", "cp1252", "latin-1"]
    content = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read(max_chars + 1)
            break
        except Exception:
            continue

    if content is None:
        return f"Error: Unable to decode file '{path.name}' with standard text encodings."

    if len(content) > max_chars:
        return content[:max_chars] + f"\n\n[... Truncated at {max_chars} characters. File size: {path.stat().st_size} bytes ...]"

    return content


@tool
def write_file(file_path: str, content: str = "") -> str:
    """
    Create or write text content to a file (.txt, .md, .csv, .json, .py, etc.).

    Args:
        file_path: Target path (e.g. 'Desktop/summary.md', 'notes.txt')
        content: Text content to write

    Returns:
        Success message with path or error
    """
    path = _resolve_path(file_path, prefer_desktop=True)
    logger.info(f"Writing file: {path} ({len(content)} chars)")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
        return f"SUCCESS: File written to '{path}' ({len(content)} characters)"
    except Exception as e:
        logger.error(f"Failed to write file {path}: {e}")
        return f"Error writing file: {str(e)}"


@tool
def explain_file_purpose(file_path: str) -> str:
    """
    Intelligently inspects a file on your system (Desktop, Documents, Project, Downloads)
    to explain WHERE it is, WHAT kind of file it is, and WHAT ITS EXACT PURPOSE & CONTENT IS.
    Reads file headers, document titles (.docx), spreadsheets (.xlsx), PDF pages, scripts (.py, .js),
    and explains in clear plain language whether it is important, a deliverable, or safe to delete.

    Args:
        file_path: Absolute or relative path, or filename (e.g. 'Forensic Exam Preparation.docx', 'main.py')

    Returns:
        Structured explanation of the file's location, type, contents summary, purpose, and importance rating.
    """
    path = _resolve_path(file_path)
    if not path.exists():
        candidates = [
            Path.home() / "Desktop" / Path(file_path).name,
            DEFAULT_OUTPUT_DIR / Path(file_path).name,
            Path.home() / "Documents" / Path(file_path).name,
            Path.home() / "Downloads" / Path(file_path).name,
        ]
        for c in candidates:
            if c.exists():
                path = c
                break

    if not path.exists():
        return f"Error: File '{file_path}' could not be found to analyze."

    stat = path.stat()
    size_str = _format_size(stat.st_size)
    mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    ext = path.suffix.lower()

    category = "Unknown"
    purpose = ""
    importance = "NORMAL"
    safe_to_delete = "CAUTION: Verify before deleting"

    if ext == ".docx":
        category = "Word Document"
        importance = "IMPORTANT (User Deliverable / Study Document)"
        safe_to_delete = "NO (User study/work document - move to Recycle Bin if unneeded)"
        try:
            import docx
            doc = docx.Document(str(path))
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            headings = [p.text.strip() for p in doc.paragraphs if p.style.name.startswith("Heading") or (p.text.strip().isupper() and len(p.text.strip()) < 50)]
            title = paras[0] if paras else "Untitled"
            summary_points = []
            if title:
                summary_points.append(f"Document Topic: '{title[:80]}'")
            if headings:
                summary_points.append(f"Key Sections: {', '.join(headings[:4])}")
            summary_points.append(f"Length: {len(paras)} paragraphs, {len(doc.tables)} tables")
            purpose = f"Created as a Word report / document. {'; '.join(summary_points)}."
        except Exception as e:
            purpose = f"Word document created on {mod_time}."

    elif ext in [".xlsx", ".xls"]:
        category = "Excel Spreadsheet"
        importance = "IMPORTANT (Data / Financial Worksheet)"
        safe_to_delete = "NO (Contains structured data records)"
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True)
            sheets = wb.sheetnames
            purpose = f"Excel workbook containing {len(sheets)} sheet(s): {', '.join(sheets)}."
        except Exception:
            purpose = "Excel workbook containing financial, data, or calculation records."

    elif ext == ".pdf":
        category = "PDF Document"
        importance = "IMPORTANT (Published Report / Reference)"
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            page_count = len(reader.pages)
            first_text = reader.pages[0].extract_text()[:180].replace("\n", " ").strip() if page_count > 0 else ""
            purpose = f"PDF publication with {page_count} page(s). Preview: '{first_text}'"
        except Exception:
            purpose = "PDF document containing formatted reading or reference material."

    elif ext in [".py", ".js", ".html", ".css", ".json"]:
        category = "Source Code & Script"
        importance = "CRITICAL (DeskPilot or Project Code)"
        safe_to_delete = "NO (Deleting will break software/project functionality)"
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = [f.readline().strip() for _ in range(10)]
            purpose = f"Application code file. Header preview: {' '.join([h for h in head if h][:3])[:150]}"
        except Exception:
            purpose = "Application code file necessary for system logic."

    elif ext in [".tmp", ".bak", ".log"] or path.name.lower() in ["desktop.ini", "thumbs.db"]:
        category = "Temporary / Cache / System Junk"
        importance = "LOW (Transient cache)"
        safe_to_delete = "YES (Completely safe to delete to reclaim storage)"
        purpose = "Temporary cache or runtime log generated by system or applications."

    elif ext in [".zip", ".tar", ".gz", ".7z", ".rar"]:
        category = "Compressed Archive"
        importance = "NORMAL"
        purpose = "Archive package containing compressed files or backups."

    elif ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]:
        category = "Image / Media"
        importance = "NORMAL"
        purpose = "Visual image asset or screenshot."

    else:
        category = f"{ext.upper() or 'Binary'} File"
        purpose = f"General file residing in {path.parent.name}."

    report = [
        f"📄 **File Analysis for '{path.name}'**",
        f"• **Location**: `{path}`",
        f"• **Directory**: `{path.parent}` ({'Desktop' if 'Desktop' in str(path) else 'System/Project'})",
        f"• **Category**: {category}",
        f"• **Size**: {size_str} ({stat.st_size:,} bytes)",
        f"• **Last Modified**: {mod_time}",
        f"• **What this file does / Purpose**: {purpose}",
        f"• **Importance Level**: {importance}",
        f"• **Safe to Delete**: {safe_to_delete}",
    ]
    return "\n".join(report)


@tool
def scan_and_categorize_files(directory_path: str = "Desktop", max_files: int = 40) -> str:
    """
    Scans a folder (e.g. Desktop, Documents, Downloads, or DeskPilot workspace)
    and provides an intelligent breakdown: what files exist, where they are,
    what category they belong to, what their purpose is, and which ones are safe to clean up.

    Args:
        directory_path: Directory to inspect (default 'Desktop')
        max_files: Maximum number of files to inspect (default 40)

    Returns:
        Structured categorization of files with plain language purpose explanations and storage totals.
    """
    target_dir = _resolve_path(directory_path, prefer_desktop=True)
    if not target_dir.exists() or not target_dir.is_dir():
        return f"Error: Directory '{directory_path}' not found (resolved: '{target_dir}')"

    entries = []
    try:
        for item in target_dir.iterdir():
            if item.name.startswith(".") or item.name.lower() in ["desktop.ini"]:
                continue
            entries.append(item)
    except Exception as e:
        return f"Error reading directory '{target_dir}': {str(e)}"

    if not entries:
        return f"The directory '{target_dir}' is currently empty."

    entries.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    inspected = entries[:max_files]

    categories = {
        "📚 Study & Office Documents (.docx, .pdf, .txt, .md)": [],
        "📊 Spreadsheets & Data (.xlsx, .csv, .json)": [],
        "💻 Code & Scripts (.py, .js, .html, .css)": [],
        "🖼️ Media & Images (.png, .jpg, .svg, .mp4)": [],
        "📦 Archives & Setups (.zip, .7z, .exe, .msi)": [],
        "🗑️ Temporary & Cache (.tmp, .bak, .log)": [],
        "📁 Subfolders": [],
        "📄 Other Files": [],
    }

    total_bytes = 0
    for item in inspected:
        try:
            is_dir = item.is_dir()
            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file()) if is_dir else item.stat().st_size
            total_bytes += size
            size_str = _format_size(size)
            ext = item.suffix.lower()

            if is_dir:
                categories["📁 Subfolders"].append((item.name, size_str, "Directory / Workspace folder"))
            elif ext in [".docx", ".pdf", ".txt", ".md"]:
                desc = "Word study/report document" if ext == ".docx" else ("PDF document" if ext == ".pdf" else "Text document")
                categories["📚 Study & Office Documents (.docx, .pdf, .txt, .md)"].append((item.name, size_str, desc))
            elif ext in [".xlsx", ".xls", ".csv", ".json"]:
                categories["📊 Spreadsheets & Data (.xlsx, .csv, .json)"].append((item.name, size_str, "Data table / workbook"))
            elif ext in [".py", ".js", ".html", ".css"]:
                categories["💻 Code & Scripts (.py, .js, .html, .css)"].append((item.name, size_str, "Source code / logic file"))
            elif ext in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".mp4"]:
                categories["🖼️ Media & Images (.png, .jpg, .svg, .mp4)"].append((item.name, size_str, "Visual media"))
            elif ext in [".zip", ".7z", ".rar", ".exe", ".msi"]:
                categories["📦 Archives & Setups (.zip, .7z, .exe, .msi)"].append((item.name, size_str, "Installer / archive"))
            elif ext in [".tmp", ".bak", ".log"]:
                categories["🗑️ Temporary & Cache (.tmp, .bak, .log)"].append((item.name, size_str, "Safe to clean junk file"))
            else:
                categories["📄 Other Files"].append((item.name, size_str, f"{ext or 'binary'} file"))
        except Exception:
            pass

    lines = [
        f"📂 **Workspace File Inventory: {target_dir}**",
        f"Showing {len(inspected)} item(s) • Total Size: ~{_format_size(total_bytes)}\n"
    ]

    for cat_name, items in categories.items():
        if items:
            lines.append(f"**{cat_name}** ({len(items)}):")
            for name, sz, role in items:
                lines.append(f"  • `{name}` ({sz}) — {role}")
            lines.append("")

    lines.append("Tip: Ask me 'explain file <name>' for an in-depth breakdown of any specific file, or ask me to delete/organize any group.")
    return "\n".join(lines)

