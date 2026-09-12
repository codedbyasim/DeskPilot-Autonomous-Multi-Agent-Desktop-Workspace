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

logger = get_logger("tools.file")


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
def delete_file(file_path: str) -> str:
    """
    Delete a file or folder permanently.
    Requires RED tier explicit approval before execution.

    Args:
        file_path: Path of the file or folder to delete

    Returns:
        Success or error message
    """
    path = _resolve_path(file_path)
    logger.info(f"Delete requested: {path}")

    if not path.exists():
        return f"Error: Item not found: '{file_path}' (resolved: '{path}')"

    item_type = "folder" if path.is_dir() else "file"

    # Human-in-the-loop Red tier approval gate
    if not request_approval("delete_file", f"Permanently delete {item_type} '{path.name}' at '{path}'?"):
        return f"Cancelled: User denied permission to delete '{path.name}'"

    try:
        if path.is_dir():
            _safe_retry_op(lambda: shutil.rmtree(str(path)))
            logger.info(f"Directory permanently deleted: {path}")
            return f"SUCCESS: Permanently deleted folder '{path.name}'"
        else:
            _safe_retry_op(lambda: path.unlink())
            logger.info(f"File permanently deleted: {path}")
            return f"SUCCESS: Permanently deleted file '{path.name}'"
    except Exception as e:
        return f"Error deleting {item_type}: {str(e)}"


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
