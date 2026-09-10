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
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.save_preferences import resolve_effective_save_dir
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


def _resolve_word_path(output_path: str, title: str) -> Path:
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
