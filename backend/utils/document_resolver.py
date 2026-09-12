"""
DeskPilot — Document Path Resolver
Intelligently locates documents (Word .docx, PDF .pdf, Excel .xlsx, text/markdown)
when a user provides a bare filename, relative path, or friendly desktop shortcut.
"""

import os
from pathlib import Path
from typing import Optional, List
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.logger import get_logger

logger = get_logger("utils.doc_resolver")


def resolve_document_path(file_path: str, default_ext: str = "") -> Optional[Path]:
    """
    Intelligently resolves a document path or bare filename across:
    1. Direct file path (absolute or relative to current working directory)
    2. User Desktop (~/Desktop)
    3. User Documents (~/Documents)
    4. User Downloads (~/Downloads)
    5. DeskPilot DEFAULT_OUTPUT_DIR
    6. sample_data/ directory
    7. Case-insensitive filename & stem matching with extension fallback.

    Args:
        file_path: Raw input string from user or agent (e.g. 'TB_Lab_Report.docx', 'Desktop/Report.docx')
        default_ext: Optional default extension to append if missing (e.g. '.docx', '.pdf', '.xlsx')

    Returns:
        Resolved Path object if found, or None.
    """
    if not file_path or not str(file_path).strip():
        return None

    clean_str = str(file_path).strip().strip("'\"")
    if not clean_str:
        return None

    # Handle ~ home directory expansion
    if clean_str.startswith("~"):
        expanded = Path(clean_str).expanduser()
        if expanded.exists() and expanded.is_file():
            return expanded.resolve()

    # Normalize slashes for prefix detection
    norm_slash = clean_str.replace("\\", "/")
    norm_lower = norm_slash.lower()

    # Friendly prefix mapping
    target_path = None
    if norm_lower.startswith("desktop/"):
        target_path = Path.home() / "Desktop" / norm_slash[8:]
    elif norm_lower == "desktop":
        target_path = Path.home() / "Desktop"
    elif norm_lower.startswith("documents/"):
        target_path = Path.home() / "Documents" / norm_slash[10:]
    elif norm_lower == "documents":
        target_path = Path.home() / "Documents"
    elif norm_lower.startswith("downloads/"):
        target_path = Path.home() / "Downloads" / norm_slash[10:]
    else:
        target_path = Path(clean_str)

    # 1. Direct check
    if target_path and target_path.exists() and target_path.is_file():
        return target_path.resolve()

    # 2. Direct check with default_ext appended
    if default_ext and target_path and not target_path.name.lower().endswith(default_ext.lower()):
        ext_candidate = target_path.with_suffix(default_ext)
        if ext_candidate.exists() and ext_candidate.is_file():
            return ext_candidate.resolve()

    # 3. Search common directories
    file_name = Path(clean_str).name
    file_stem = Path(clean_str).stem

    search_dirs: List[Path] = [
        Path.cwd(),
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        DEFAULT_OUTPUT_DIR,
        Path.cwd() / "sample_data",
        Path.cwd() / "outputs",
        Path.cwd() / "Desktop",
    ]

    # Deduplicate existing search dirs
    valid_dirs = []
    seen = set()
    for d in search_dirs:
        try:
            if d.exists() and d.is_dir():
                d_res = d.resolve()
                if d_res not in seen:
                    valid_dirs.append(d_res)
                    seen.add(d_res)
        except Exception:
            pass

    # Pass A: Exact filename or filename with default extension
    for d in valid_dirs:
        # Exact name
        c1 = d / file_name
        if c1.exists() and c1.is_file() and not c1.name.startswith("~$"):
            return c1.resolve()

        # With default_ext
        if default_ext and not file_name.lower().endswith(default_ext.lower()):
            c2 = d / f"{file_name}{default_ext}"
            if c2.exists() and c2.is_file() and not c2.name.startswith("~$"):
                return c2.resolve()

    # Pass B: Case-insensitive match on file name
    file_name_lower = file_name.lower()
    alt_name_lower = f"{file_name}{default_ext}".lower() if default_ext else ""

    for d in valid_dirs:
        try:
            for item in d.iterdir():
                if item.is_file() and not item.name.startswith("~$"):
                    item_name_lower = item.name.lower()
                    if item_name_lower == file_name_lower or (alt_name_lower and item_name_lower == alt_name_lower):
                        return item.resolve()
        except Exception:
            pass

    # Pass C: Stem matching (e.g. user entered "TB_Lab_Report" without extension)
    stem_lower = file_stem.lower()
    for d in valid_dirs:
        try:
            for item in d.iterdir():
                if item.is_file() and not item.name.startswith("~$"):
                    if item.stem.lower() == stem_lower:
                        if default_ext:
                            if item.suffix.lower() == default_ext.lower():
                                return item.resolve()
                        else:
                            return item.resolve()
        except Exception:
            pass

    # Pass D: Depth-1 search in sample_data and outputs
    for parent_dir in [Path.cwd() / "sample_data", DEFAULT_OUTPUT_DIR]:
        if parent_dir.exists() and parent_dir.is_dir():
            try:
                for sub_item in parent_dir.rglob("*"):
                    if sub_item.is_file() and not sub_item.name.startswith("~$"):
                        if sub_item.name.lower() == file_name_lower or (alt_name_lower and sub_item.name.lower() == alt_name_lower):
                            return sub_item.resolve()
                        if sub_item.stem.lower() == stem_lower:
                            if default_ext:
                                if sub_item.suffix.lower() == default_ext.lower():
                                    return sub_item.resolve()
                            else:
                                return sub_item.resolve()
            except Exception:
                pass

    logger.debug(f"Document not found across search directories: '{file_path}'")
    return None
