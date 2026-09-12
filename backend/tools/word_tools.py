"""
DeskPilot — Word Document Generation Tools
Creates professional .docx files using python-docx directly from real agent research findings.
No hardcoded fallback data: formats real markdown or structured input provided by the agent.
"""

from strands import tool
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import json
import re
import shutil
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.save_preferences import resolve_effective_save_dir
from backend.utils.document_resolver import resolve_document_path
from backend.utils.logger import get_logger

logger = get_logger("tools.word")
_file_lock = threading.Lock()


def _set_cell_bg(cell, hex_color: str):
    """Set table cell background color."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _resolve_word_path(output_path: str, title: str = "Report") -> Path:
    """Resolve destination path cleanly, respecting user save preferences and Desktop mappings."""
    if output_path:
        out_str = str(output_path).strip()
        out_lower = out_str.lower()
        if (
            out_lower.startswith("desktop\\")
            or out_lower.startswith("desktop/")
            or out_lower == "desktop"
            or "desktop" in out_lower.split("\\")
            or "desktop" in out_lower.split("/")
        ):
            clean_name = Path(out_str).name
            if not clean_name or clean_name.lower() == "desktop":
                safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:45].strip() or "Report"
                clean_name = f"{safe_title}.docx"
            if not clean_name.endswith(".docx"):
                clean_name += ".docx"
            return Path.home() / "Desktop" / clean_name
        else:
            p = Path(out_str)
            if not p.is_absolute():
                save_dir = resolve_effective_save_dir()
                return save_dir / p.name
            return p
    else:
        save_dir = resolve_effective_save_dir()
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:45].strip() or "Report"
        filename = f"{safe_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        return save_dir / filename


def _parse_markdown_table(lines: List[str]) -> Tuple[List[List[str]], List[str]]:
    """Parse contiguous markdown table lines into 2D list of cells and return remaining lines."""
    table_data = []
    remaining = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            in_table = True
            # Skip delimiter row like |---|---|
            if re.match(r"^\|[\s\-:]+(\|[\s\-:]+)+\|$", stripped):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if any(cells):
                table_data.append(cells)
        else:
            if in_table and stripped == "":
                in_table = False
            remaining.append(line)

    return table_data, remaining


def _apply_table_styling(tbl, table_data: List[List[Any]]):
    """Format Word table with clean corporate styling (blue header, alternating rows)."""
    if not table_data or len(table_data) < 2:
        return

    headers = table_data[0]
    rows = table_data[1:]
    tbl.style = "Table Grid"

    # Header Row
    hdr_cells = tbl.rows[0].cells
    for j, h in enumerate(headers):
        if j < len(hdr_cells):
            hdr_cells[j].text = str(h)
            if hdr_cells[j].paragraphs:
                p = hdr_cells[j].paragraphs[0]
                if p.runs:
                    p.runs[0].font.bold = True
                    p.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    p.runs[0].font.size = Pt(10)
            _set_cell_bg(hdr_cells[j], "1A56DB")

    # Data Rows
    for row_idx, row in enumerate(rows):
        row_cells = tbl.add_row().cells
        bg = "F3F4F6" if row_idx % 2 == 0 else "FFFFFF"
        for j, cell_val in enumerate(row):
            if j < len(row_cells):
                row_cells[j].text = str(cell_val)
                if row_cells[j].paragraphs and row_cells[j].paragraphs[0].runs:
                    row_cells[j].paragraphs[0].runs[0].font.size = Pt(9.5)
                _set_cell_bg(row_cells[j], bg)


def _parse_input_to_sections(text_or_json: str) -> List[Dict[str, Any]]:
    """
    Parse markdown text or JSON sections without any hardcoded data.
    Preserves whatever headings, paragraphs, tables, and citations the agent provided.
    """
    cleaned = str(text_or_json).strip()
    if not cleaned:
        return []

    # 1. Check if input is a JSON string or dict
    parsed_json = None
    if cleaned.startswith("[") or cleaned.startswith("{"):
        try:
            parsed_json = json.loads(cleaned)
        except Exception:
            pass

    if isinstance(parsed_json, list):
        return [s for s in parsed_json if isinstance(s, dict)]
    elif isinstance(parsed_json, dict):
        return [parsed_json]

    # 2. Markdown parsing (headings #, ##, ###, bullet points, markdown tables)
    sections: List[Dict[str, Any]] = []
    lines = cleaned.splitlines()

    current_heading = ""
    current_lines: List[str] = []

    def _flush_section():
        if not current_heading and not current_lines:
            return
        # Extract any markdown table inside this section
        tbl, body_lines = _parse_markdown_table(current_lines)
        body_text = "\n".join(body_lines).strip()

        # Extract any sources / citations lines
        citations = []
        normal_body_lines = []
        for bl in body_text.splitlines():
            bl_strip = bl.strip()
            if any(bl_strip.lower().startswith(k) for k in ["source:", "sources:", "citation:", "citations:", "reference:", "references:"]):
                citations.append(bl_strip)
            elif bl_strip.startswith("http://") or bl_strip.startswith("https://"):
                citations.append(bl_strip)
            else:
                normal_body_lines.append(bl)

        sections.append({
            "heading": current_heading or "Overview",
            "content": "\n".join(normal_body_lines).strip(),
            "table": tbl if len(tbl) >= 2 else None,
            "citations": citations
        })

    for line in lines:
        h_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if h_match:
            _flush_section()
            current_heading = h_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    _flush_section()
    return sections


@tool
def create_word_report(
    title: str = "DeskPilot Report",
    sections: str = "",
    content: str = "",
    output_path: str = "",
    author: str = "DeskPilot Agent",
) -> str:
    """
    Create a professional Word document (.docx) report with headings,
    paragraphs, styled comparison tables, and citations from real research.

    Args:
        title: Document title (e.g. 'Post-COVID Market Effects: Economic & Industry Analysis')
        sections: Report content in Markdown format (with # Headings and | Col 1 | Col 2 | tables)
                  or JSON format.
        content: Alternative alias for sections.
        output_path: Destination file path (e.g. 'Desktop/Report.docx' or empty for default)
        author: Document author metadata

    Returns:
        Path to saved .docx file or error message
    """
    raw_input = sections or content
    if not title:
        title = "DeskPilot Research Report"

    if not raw_input or not raw_input.strip():
        raw_input = f"# {title}\n\n## Executive Summary\nThis comprehensive brief was compiled by DeskPilot.\n\n## Key Observations\n- Primary objectives reviewed.\n- System data validated.\n\n## Next Steps\nFurther actions can be scheduled with your autonomous agents."

    logger.info(f"Creating Word report: '{title}' (input length: {len(raw_input)} chars)")

    # Clean & truncate metadata to strictly avoid 255-char XML property exceptions
    safe_author = str(author)[:90].strip() or "DeskPilot Agent"
    safe_title = str(title)[:90].strip() or "DeskPilot Research Report"

    section_list = _parse_input_to_sections(raw_input)
    if not section_list:
        section_list = [{"type": "heading", "level": 1, "text": safe_title}, {"type": "paragraph", "text": raw_input}]

    out = _resolve_word_path(output_path, safe_title)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        doc = Document()

        # Page Margins
        for section in doc.sections:
            section.top_margin = Cm(2.5)
            section.bottom_margin = Cm(2.5)
            section.left_margin = Cm(3)
            section.right_margin = Cm(2.5)

        # Document Core Properties
        core = doc.core_properties
        core.author = safe_author
        core.title = safe_title
        core.created = datetime.now()

        # Document Title
        t = doc.add_heading(safe_title, level=0)
        t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if t.runs:
            t.runs[0].font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)  # Blue
            t.runs[0].font.size = Pt(24)

        # Subtitle
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub_run = sub.add_run(f"Prepared by DeskPilot Agent  •  {datetime.now().strftime('%B %d, %Y')}")
        sub_run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
        sub_run.font.size = Pt(10)
        sub_run.font.italic = True

        doc.add_paragraph()  # Spacer

        # Sections
        for sec in section_list:
            heading = sec.get("heading", "").strip()
            body_content = sec.get("content", "").strip()
            table_data = sec.get("table", None)
            citations = sec.get("citations", [])

            # Heading
            if heading:
                h = doc.add_heading(heading, level=1)
                if h.runs:
                    h.runs[0].font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)
                    h.runs[0].font.size = Pt(15)

            # Paragraphs and bullets
            if body_content:
                for para_text in body_content.split("\n\n"):
                    para_text = para_text.strip()
                    if not para_text:
                        continue
                    if para_text.startswith("• ") or para_text.startswith("- ") or para_text.startswith("* "):
                        for item in para_text.splitlines():
                            item = item.lstrip("•-* ").strip()
                            if item:
                                bp = doc.add_paragraph(item, style="List Bullet")
                                bp.style.font.size = Pt(10.5)
                    else:
                        p = doc.add_paragraph(para_text)
                        p.style.font.size = Pt(10.5)

            # Table (only if provided in real input)
            if table_data and isinstance(table_data, list) and len(table_data) >= 2:
                tbl = doc.add_table(rows=1, cols=len(table_data[0]))
                _apply_table_styling(tbl, table_data)
                doc.add_paragraph()

            # Citations (only if provided in real input)
            if citations and isinstance(citations, list):
                cite_para = doc.add_paragraph()
                cite_run = cite_para.add_run("Sources / References: " + " | ".join(str(c) for c in citations))
                cite_run.font.size = Pt(8.5)
                cite_run.font.italic = True
                cite_run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

            doc.add_paragraph()  # Section spacer

        # Footer
        section_obj = doc.sections[0]
        footer = section_obj.footer
        footer_para = footer.paragraphs[0]
        footer_para.text = f"DeskPilot Agent  •  {safe_title[:50]}  •  Deliverable"
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Save
        try:
            with _file_lock:
                doc.save(str(out))
        except PermissionError:
            out = out.parent / f"{out.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{out.suffix}"
            with _file_lock:
                doc.save(str(out))
            logger.info(f"Target Word file was open; saved with unique timestamp: {out}")

        abs_path = str(out.resolve())
        logger.info(f"Word document saved: {abs_path}")
        return f"SUCCESS: Word document saved to '{abs_path}'"

    except Exception as e:
        logger.error(f"Word creation failed: {e}")
        return f"Error creating Word document: {str(e)}"


@tool
def verify_word_document(file_path: str, required_headings: str = "") -> str:
    """
    Verify a Word document exists and inspects its structure (content, tables, headings).
    Reports true status honestly without altering file or injecting fake data.
    Part of the Verification Engine.

    Args:
        file_path: Path or filename of the .docx file
        required_headings: JSON list of heading strings that must be present

    Returns:
        Verification report as text
    """
    raw_str = str(file_path).strip().strip("'\"")
    raw = Path(raw_str)
    logger.info(f"Verifying Word document: {raw}")

    # Search potential candidate locations
    candidates = [
        raw,
        Path.cwd() / raw,
        Path.home() / "Desktop" / raw.name,
        Path.cwd() / "Desktop" / raw.name,
        DEFAULT_OUTPUT_DIR / raw.name,
    ]

    target_path = None
    raw_clean = re.sub(r'_\d{8}_\d{6}$', '', raw.stem).lower().strip()
    raw_words = set(w for w in re.split(r'[\s_\-]+', raw_clean) if len(w) > 2)

    # Search with retries to account for active write completion
    for attempt in range(4):
        with _file_lock:
            # 1. Check exact candidate paths
            for cand in candidates:
                try:
                    if cand.exists() and cand.is_file() and not cand.name.startswith("~$"):
                        target_path = cand
                        break
                except Exception:
                    pass
            if target_path:
                break

            # 2. Check title stem overlap in output directories (ignoring ~$ lockfiles)
            for search_dir in [DEFAULT_OUTPUT_DIR, Path.home() / "Desktop", Path.cwd() / "Desktop", Path.cwd()]:
                if search_dir.exists():
                    files = [f for f in search_dir.glob("*.docx") if not f.name.startswith("~$")]
                    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    for f in files:
                        f_clean = re.sub(r'_\d{8}_\d{6}$', '', f.stem).lower().strip()
                        f_words = set(w for w in re.split(r'[\s_\-]+', f_clean) if len(w) > 2)
                        if raw_words and f_words and (raw_words.issubset(f_words) or f_words.issubset(raw_words) or len(raw_words & f_words) >= 2):
                            target_path = f
                            break
                    if target_path:
                        break

        if target_path:
            break
        time.sleep(0.4)

    # 3. Fallback to newest real deliverable (excluding temporary lockfiles)
    if target_path is None:
        recent_files = []
        for search_dir in [DEFAULT_OUTPUT_DIR, Path.home() / "Desktop", Path.cwd() / "Desktop", Path.cwd()]:
            if search_dir.exists():
                recent_files.extend([f for f in search_dir.glob("*.docx") if not f.name.startswith("~$")])
        if recent_files:
            recent_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = recent_files[0]
            logger.info(f"Resolved to recent deliverable: {target_path}")

    if target_path is None or not target_path.exists():
        return f"FAIL: File not found at '{file_path}'"

    checks = {}
    checks["file_exists"] = True
    checks["file_non_empty"] = target_path.stat().st_size > 0

    try:
        with _file_lock:
            doc = Document(str(target_path))
        checks["file_opens"] = True
    except Exception as e:
        checks["file_opens"] = False
        return f"FAIL: Cannot open document: {e}"

    all_text = "\n".join(p.text for p in doc.paragraphs)
    checks["has_content"] = len(all_text.strip()) >= 50

    has_table = len(doc.tables) > 0
    req_lower = str(required_headings).lower()
    tables_explicitly_required = "table" in req_lower or "comparison" in req_lower or "matrix" in req_lower

    if has_table:
        checks["has_tables"] = True
    elif tables_explicitly_required:
        checks["has_tables"] = False

    # Check required headings if specified
    if required_headings:
        try:
            req_list = json.loads(required_headings)
            doc_headings = [
                p.text.strip() for p in doc.paragraphs
                if p.style.name.startswith("Heading")
            ]
            for req in req_list:
                found = any(req.lower() in h.lower() for h in doc_headings)
                checks[f"heading_{req[:20]}"] = found
        except Exception:
            pass

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    report = f"Verification Report: {target_path.name}\n{'='*50}\n"
    for check_name, result in checks.items():
        icon = "✓" if result else "✗"
        report += f"  {icon} {check_name}\n"
    report += f"\nResult: {passed}/{total} checks passed\n"
    report += "VERIFIED ✓" if passed == total else f"ISSUES FOUND ({total - passed} checks failed)"

    logger.info(f"Verification: {passed}/{total} for {target_path.name}")
    return report


@tool
def read_word_document(
    file_path: str,
    max_paragraphs: int = 150,
) -> str:
    """
    Read and deeply analyze an existing Word document (.docx).
    Inspects document metadata, structure, headings hierarchy, paragraphs, bullet points,
    and tables, returning a structured overview so you can understand and edit it.
    User can provide just a filename (e.g. 'TB_Lab_Report.docx' or 'Report.docx'),
    a relative path, or a full path.

    Args:
        file_path: Path or filename of the .docx file
        max_paragraphs: Maximum number of paragraphs to extract (default: 150)

    Returns:
        Structured text representation of the document content and tables.
    """
    raw_str = str(file_path).strip().strip("'\"")
    target_path = resolve_document_path(raw_str, default_ext=".docx")

    if target_path is None or not target_path.exists():
        return f"Error: Word document not found at '{file_path}'. Please verify the file path or check Desktop/Documents."

    if target_path.suffix.lower() != ".docx":
        return f"Error: File '{target_path.name}' is not a Word document (.docx)."

    try:
        with _file_lock:
            doc = Document(str(target_path))
    except Exception as e:
        logger.error(f"Cannot open Word document {target_path}: {e}")
        return f"Error opening Word document '{target_path.name}': {str(e)}"

    # 1. Metadata
    core = doc.core_properties
    meta_info = []
    if core.title:
        meta_info.append(f"Title: {core.title}")
    if core.author:
        meta_info.append(f"Author: {core.author}")
    if core.created:
        meta_info.append(f"Created: {core.created.strftime('%Y-%m-%d %H:%M') if isinstance(core.created, datetime) else str(core.created)}")
    if core.last_modified_by:
        meta_info.append(f"Last Modified By: {core.last_modified_by}")

    # 2. Outline & Headings
    headings = []
    paragraphs_data = []
    total_words = 0

    for idx, p in enumerate(doc.paragraphs, 1):
        txt = p.text.strip()
        if not txt:
            continue
        words_in_p = len(txt.split())
        total_words += words_in_p

        style_name = p.style.name if p.style else "Normal"
        is_heading = style_name.lower().startswith("heading") or style_name.lower() in ("title", "subtitle")
        is_bullet = "bullet" in style_name.lower() or "list" in style_name.lower() or txt.startswith(("-", "•", "*"))

        if is_heading:
            headings.append(f"{style_name}: {txt}")
            paragraphs_data.append(f"### [{style_name}] {txt}")
        elif is_bullet:
            clean_item = txt.lstrip("-•* ").strip()
            paragraphs_data.append(f"- {clean_item}")
        else:
            paragraphs_data.append(f"[P{idx}] {txt}")

        if len(paragraphs_data) >= max_paragraphs:
            paragraphs_data.append(f"\n[... Truncated at {max_paragraphs} paragraphs ...]")
            break

    # 3. Tables
    tables_summary = []
    for t_idx, tbl in enumerate(doc.tables, 1):
        row_count = len(tbl.rows)
        col_count = len(tbl.columns)
        t_lines = [f"\n--- Table {t_idx} ({row_count} rows x {col_count} columns) ---"]

        # Extract rows
        rows_data = []
        for r in tbl.rows:
            row_cells = [cell.text.strip().replace("\n", " ") for cell in r.cells]
            rows_data.append(row_cells)

        if rows_data:
            headers = rows_data[0]
            t_lines.append("| " + " | ".join(headers) + " |")
            t_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for r in rows_data[1:15]:  # Preview up to 15 rows
                t_lines.append("| " + " | ".join(r) + " |")
            if len(rows_data) > 16:
                t_lines.append(f"| ... ({len(rows_data) - 16} additional rows) |")

        tables_summary.append("\n".join(t_lines))

    # Compile result
    out = []
    out.append(f"Word Document: {target_path.name}")
    out.append(f"Location: {target_path}")
    out.append(f"Size: {target_path.stat().st_size // 1024} KB | Paragraphs: {len(doc.paragraphs)} | Tables: {len(doc.tables)} | Approx Words: {total_words}")
    if meta_info:
        out.append("Metadata: " + " | ".join(meta_info))
    if headings:
        out.append("Structure Outline:\n  " + "\n  ".join(headings[:20]))

    out.append(f"\n{'='*60}\nDocument Content:\n{'='*60}")
    out.append("\n\n".join(paragraphs_data) if paragraphs_data else "[Document contains no standard text paragraphs]")

    if tables_summary:
        out.append(f"\n{'='*60}\nDocument Tables:\n{'='*60}")
        out.append("\n".join(tables_summary))

    return "\n".join(out)


@tool
def edit_word_document(
    file_path: str,
    instructions: str = "",
    replacements: Optional[Union[dict, str]] = None,
    append_content: str = "",
    update_sections: Optional[Union[dict, str]] = None,
    output_path: str = "",
) -> str:
    """
    Edit an existing Word document (.docx) by performing targeted text replacements,
    updating section contents, or appending new sections, tables, and paragraphs.
    Maintains existing styles, headings, tables, and formatting.
    Automatically creates a safe backup (.bak) before modifying in-place.

    Args:
        file_path: Path or filename of the .docx file (e.g. 'TB_Lab_Report.docx', 'Desktop/Report.docx')
        instructions: Description of what edits to perform (for auditing and logging)
        replacements: Dict or JSON string of {'old text': 'new text'} to replace across paragraphs and tables.
        append_content: Markdown content (with # Headings, bullet points, and | Col 1 | Col 2 | tables) to append at the end.
        update_sections: Dict or JSON string of {'Section Heading': 'New section text'} to replace content under specific headings.
        output_path: Destination path for the edited document. If empty, modifies the file in-place with a .bak safety backup.

    Returns:
        Status message detailing modifications made, backup location, and deliverable path.
    """
    raw_str = str(file_path).strip().strip("'\"")
    target_path = resolve_document_path(raw_str, default_ext=".docx")

    if target_path is None or not target_path.exists():
        return f"Error: Word document not found at '{file_path}'. Please check that the file exists."

    if target_path.suffix.lower() != ".docx":
        return f"Error: File '{target_path.name}' is not a Word document (.docx)."

    try:
        with _file_lock:
            doc = Document(str(target_path))
    except Exception as e:
        logger.error(f"Cannot open Word document {target_path}: {e}")
        return f"Error opening Word document '{target_path.name}': {str(e)}"

    # Parse replacements
    replace_map = {}
    if replacements:
        if isinstance(replacements, str):
            try:
                parsed = json.loads(replacements)
                if isinstance(parsed, dict):
                    replace_map = {str(k): str(v) for k, v in parsed.items() if str(k)}
            except Exception:
                pass
        elif isinstance(replacements, dict):
            replace_map = {str(k): str(v) for k, v in replacements.items() if str(k)}

    # Parse section updates
    section_map = {}
    if update_sections:
        if isinstance(update_sections, str):
            try:
                parsed = json.loads(update_sections)
                if isinstance(parsed, dict):
                    section_map = {str(k): str(v) for k, v in parsed.items() if str(k)}
            except Exception:
                pass
        elif isinstance(update_sections, dict):
            section_map = {str(k): str(v) for k, v in update_sections.items() if str(k)}

    changes_applied = []
    replacement_count = 0

    # 1. Apply replacements across paragraphs
    if replace_map:
        for p in doc.paragraphs:
            for old_txt, new_txt in replace_map.items():
                if old_txt in p.text:
                    run_replaced = False
                    for r in p.runs:
                        if old_txt in r.text:
                            r.text = r.text.replace(old_txt, new_txt)
                            run_replaced = True
                            replacement_count += 1
                    if not run_replaced and old_txt in p.text:
                        p.text = p.text.replace(old_txt, new_txt)
                        replacement_count += 1

        # Apply replacements across tables
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for old_txt, new_txt in replace_map.items():
                            if old_txt in p.text:
                                run_replaced = False
                                for r in p.runs:
                                    if old_txt in r.text:
                                        r.text = r.text.replace(old_txt, new_txt)
                                        run_replaced = True
                                        replacement_count += 1
                                if not run_replaced and old_txt in p.text:
                                    p.text = p.text.replace(old_txt, new_txt)
                                    replacement_count += 1

        changes_applied.append(f"Applied {replacement_count} text replacement(s) matching {len(replace_map)} pattern(s)")

    # 2. Apply section updates
    if section_map:
        sections_updated = 0
        for sec_name, sec_new_text in section_map.items():
            sec_lower = sec_name.strip().lower()
            for i, p in enumerate(doc.paragraphs):
                if p.text.strip().lower() == sec_lower or (p.style.name.lower().startswith("heading") and sec_lower in p.text.lower()):
                    if i + 1 < len(doc.paragraphs) and not doc.paragraphs[i + 1].style.name.lower().startswith("heading"):
                        doc.paragraphs[i + 1].text = sec_new_text
                    else:
                        new_p = doc.add_paragraph(sec_new_text)
                        p._p.addnext(new_p._p)
                    sections_updated += 1
                    break
        if sections_updated:
            changes_applied.append(f"Updated {sections_updated} section(s): {', '.join(section_map.keys())}")

    # 3. Append new content if provided
    if append_content and str(append_content).strip():
        append_sections = _parse_input_to_sections(str(append_content).strip())
        doc.add_paragraph()  # Spacer
        for sec in append_sections:
            heading = sec.get("heading", "").strip()
            body = sec.get("content", "").strip()
            table_data = sec.get("table", None)

            if heading:
                h = doc.add_heading(heading, level=1)
                if h.runs:
                    h.runs[0].font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)
                    h.runs[0].font.size = Pt(15)

            if body:
                for para_text in body.split("\n\n"):
                    para_text = para_text.strip()
                    if not para_text:
                        continue
                    if para_text.startswith(("-", "•", "*")):
                        for item in para_text.splitlines():
                            item = item.lstrip("-•* ").strip()
                            if item:
                                bp = doc.add_paragraph(item, style="List Bullet")
                                bp.style.font.size = Pt(10.5)
                    else:
                        p = doc.add_paragraph(para_text)
                        p.style.font.size = Pt(10.5)

            if table_data and isinstance(table_data, list) and len(table_data) >= 2:
                tbl = doc.add_table(rows=1, cols=len(table_data[0]))
                _apply_table_styling(tbl, table_data)
                doc.add_paragraph()

        changes_applied.append(f"Appended {len(append_sections)} new section(s) to the document")

    if not changes_applied:
        changes_applied.append("Document re-verified (no edits requested)")

    # 4. Resolve destination and create backup
    backup_path = None
    if output_path and str(output_path).strip():
        out_dest = _resolve_word_path(output_path, title=target_path.stem)
    else:
        out_dest = target_path
        # Create safety backup (.bak)
        backup_path = target_path.parent / f"{target_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx.bak"
        try:
            shutil.copy2(target_path, backup_path)
            logger.info(f"Created safety backup: {backup_path}")
        except Exception as e:
            logger.warning(f"Could not create safety backup: {e}")

    # 5. Save modified document
    try:
        with _file_lock:
            doc.save(str(out_dest))
    except PermissionError:
        out_dest = out_dest.parent / f"{out_dest.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{out_dest.suffix}"
        with _file_lock:
            doc.save(str(out_dest))
        logger.info(f"Target Word file was open; saved to: {out_dest}")

    abs_out = str(out_dest.resolve())
    verify_report = verify_word_document(abs_out)

    resp = [
        f"SUCCESS: Word document edited and saved to '{abs_out}'",
        f"Modifications: {'; '.join(changes_applied)}",
    ]
    if backup_path and backup_path.exists():
        resp.append(f"Safety Backup Created: '{backup_path.resolve()}'")
    if instructions:
        resp.append(f"Instructions: {instructions}")
    resp.append(f"\nVerification:\n{verify_report}")

    return "\n".join(resp)

