"""
DeskPilot — PDF Reading & Extraction Tools
Uses pdfplumber for resilient text, table, and invoice extraction.
"""

from strands import tool
import pdfplumber
import json
import re
from pathlib import Path
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.logger import get_logger

logger = get_logger("tools.pdf")


def _resolve_pdf_path(file_path: str) -> Path:
    """
    Resolves relative or friendly PDF paths across cwd, sample_data, Desktop, and output directories.
    """
    if not file_path or not file_path.strip():
        return Path("sample_data")

    p_str = file_path.strip().strip("'\"")
    if p_str.startswith("~"):
        return Path(p_str).expanduser().resolve()

    p_norm = p_str.replace("\\", "/").strip()
    if p_norm.lower() == "desktop":
        return (Path.home() / "Desktop").resolve()
    if p_norm.lower().startswith("desktop/"):
        return (Path.home() / "Desktop" / p_norm[8:]).resolve()

    p = Path(p_str)
    if p.exists():
        return p.resolve()

    # Check in sample_data directory
    sample_candidate = (Path("sample_data") / p.name).resolve()
    if sample_candidate.exists():
        return sample_candidate

    # Check on user's Desktop
    desktop_candidate = (Path.home() / "Desktop" / p).resolve()
    if desktop_candidate.exists():
        return desktop_candidate

    # Check in DeskPilot output directory
    output_candidate = (DEFAULT_OUTPUT_DIR / p).resolve()
    if output_candidate.exists():
        return output_candidate

    return p.resolve()


@tool
def list_pdfs_in_folder(folder_path: str = "") -> str:
    """
    List all PDF files in a given folder with file paths and sizes.

    Args:
        folder_path: Path to folder to scan. Defaults to 'sample_data' or 'Desktop'.

    Returns:
        Formatted list of PDF file paths found
    """
    target_str = folder_path.strip() if folder_path else "sample_data"
    folder = _resolve_pdf_path(target_str)
    logger.info(f"Scanning for PDFs in: {folder}")

    if not folder.exists():
        return f"Folder not found: '{folder_path}' (resolved: '{folder}')"

    if not folder.is_dir():
        return f"Path is not a directory: '{folder_path}' (resolved: '{folder}')"

    pdfs = sorted(list(folder.glob("*.pdf")), key=lambda x: x.name.lower())
    if not pdfs:
        return f"No PDF files found in '{folder}'"

    result = f"PDF files in '{folder}':\n{'─'*60}\n"
    for i, p in enumerate(pdfs, 1):
        size_kb = p.stat().st_size // 1024
        try:
            rel_path = p.relative_to(Path.cwd()).as_posix()
        except ValueError:
            rel_path = p.as_posix()
        result += f"  {i}. {rel_path} ({size_kb} KB)\n"

    logger.info(f"Found {len(pdfs)} PDFs in {folder}")
    result += f"\nTotal: {len(pdfs)} PDF file(s)"
    return result


@tool
def read_pdf(file_path: str) -> str:
    """
    Read and extract all text from a PDF file page by page.

    Args:
        file_path: Absolute or relative path to the PDF file

    Returns:
        Extracted text content from the PDF
    """
    path = _resolve_pdf_path(file_path)
    logger.info(f"Reading PDF: {path}")

    if not path.exists():
        return f"Error: PDF file not found at '{file_path}' (resolved: '{path}')"
    if not path.suffix.lower() == ".pdf":
        return f"Error: File is not a PDF: '{file_path}' (extension: '{path.suffix}')"

    try:
        pages_content = []
        total_text_chars = 0
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text() or ""
                clean_text = page_text.strip()
                total_text_chars += len(clean_text)
                pages_content.append(f"--- Page {i}/{total_pages} ---\n{clean_text if clean_text else '[No digital text on this page]'}")

        if total_text_chars == 0:
            return f"PDF Content: {path.name}\n{'='*60}\nNotice: No digital text found across {total_pages} page(s). This document may be a scanned image."

        full_text = "\n\n".join(pages_content)
        logger.info(f"Extracted {total_text_chars} chars from {path.name} ({total_pages} pages)")
        return f"PDF Content: {path.name} ({total_pages} pages)\n{'='*60}\n{full_text}"

    except Exception as e:
        logger.error(f"PDF read failed: {e}")
        return f"Error reading PDF '{path.name}': {str(e)}"


@tool
def extract_pdf_tables(file_path: str) -> str:
    """
    Extract all tables from a PDF file as structured JSON and Markdown preview.

    Args:
        file_path: Path to the PDF file

    Returns:
        JSON and Markdown tables extracted from the PDF
    """
    path = _resolve_pdf_path(file_path)
    logger.info(f"Extracting tables from PDF: {path}")

    if not path.exists():
        return f"Error: PDF file not found at '{file_path}' (resolved: '{path}')"

    try:
        all_tables = []
        md_tables = []
        with pdfplumber.open(path) as pdf:
            for page_idx, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if tables:
                    for t_idx, raw_table in enumerate(tables):
                        cleaned_rows = []
                        for row in raw_table:
                            if not row or all(c is None or str(c).strip() == "" for c in row):
                                continue
                            cleaned_row = [str(c).strip().replace("\n", " ") if c is not None else "" for c in row]
                            cleaned_rows.append(cleaned_row)

                        if cleaned_rows:
                            all_tables.append({
                                "page": page_idx,
                                "table_index": t_idx,
                                "rows": cleaned_rows
                            })

                            if len(cleaned_rows) >= 1:
                                headers = cleaned_rows[0]
                                md = f"\nTable (Page {page_idx}, #{t_idx+1}):\n"
                                md += "| " + " | ".join(headers) + " |\n"
                                md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                for r in cleaned_rows[1:]:
                                    padded = r + [""] * (len(headers) - len(r))
                                    md += "| " + " | ".join(padded[:len(headers)]) + " |\n"
                                md_tables.append(md)

        if not all_tables:
            return f"No tables found in '{path.name}'."

        result_json = json.dumps(all_tables, indent=2, ensure_ascii=False)
        preview = "\n".join(md_tables)
        logger.info(f"Found {len(all_tables)} tables in {path.name}")
        return f"Extracted Tables from {path.name}:\n{preview}\n\nStructured JSON:\n{result_json}"

    except Exception as e:
        logger.error(f"Table extraction failed: {e}")
        return f"Error extracting tables from '{path.name}': {str(e)}"


@tool
def extract_pdf_invoice(file_path: str) -> str:
    """
    Extract structured invoice data from a PDF — vendor, invoice number, date, total, line items.
    Returns structured JSON for reconciliation and financial reporting workflows.

    Args:
        file_path: Path to invoice PDF

    Returns:
        JSON with invoice fields: vendor, invoice_number, date, total, line_items, tables
    """
    path = _resolve_pdf_path(file_path)
    logger.info(f"Extracting invoice data from: {path}")

    if not path.exists():
        return f"Error: File not found: '{file_path}' (resolved: '{path}')"

    try:
        text_lines = []
        raw_tables = []

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_lines.extend([line.strip() for line in page_text.splitlines() if line.strip()])
                tables = page.extract_tables()
                if tables:
                    raw_tables.extend(tables)

        full_text = "\n".join(text_lines)

        v_match = (
            re.search(r"(?:Vendor|Supplier|From|Company|Billed By):\s*([^\n\r]+)", full_text, re.IGNORECASE)
            or re.search(r"TAX INVOICE\s*\n+([^\n\r]+)", full_text, re.IGNORECASE)
        )
        inv_match = re.search(r"(?:Invoice\s*(?:Number|No\.?|#|ID)?|Bill\s*No\.?):\s*([^\n\r]+)", full_text, re.IGNORECASE)
        d_match = re.search(r"(?:Invoice\s*Date|Date|Dated):\s*([^\n\r]+)", full_text, re.IGNORECASE)
        t_match = (
            re.search(r"(?:Total\s*Amount\s*Due|Grand\s*Total|Total\s*Due|Amount\s*Due|Total):\s*\$?([0-9,]+\.?[0-9]*)", full_text, re.IGNORECASE)
            or re.search(r"\$\s*([0-9,]+\.[0-9]{2})", full_text)
        )

        vendor = v_match.group(1).strip() if v_match else "Unknown Vendor"
        invoice_number = inv_match.group(1).strip() if inv_match else path.stem
        invoice_date = d_match.group(1).strip() if d_match else ""
        total_amount = float(t_match.group(1).replace(",", "")) if t_match else 0.0

        line_items = []
        cleaned_tables = []
        for tbl in raw_tables:
            if not tbl or len(tbl) < 2:
                continue
            cleaned_tbl = []
            for row in tbl:
                cleaned_row = [str(c).strip().replace("\n", " ") if c is not None else "" for c in row]
                cleaned_tbl.append(cleaned_row)
            cleaned_tables.append(cleaned_tbl)

            for row in tbl[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                cells = [str(c).strip() if c else "" for c in row]
                if len(cells) >= 4:
                    line_items.append({
                        "description": cells[0],
                        "quantity": cells[1],
                        "unit_price": cells[2],
                        "total": cells[3]
                    })
                elif len(cells) >= 2:
                    line_items.append({
                        "description": cells[0],
                        "amount": cells[-1]
                    })

        invoice_data = {
            "file": path.name,
            "file_path": path.as_posix(),
            "vendor": vendor,
            "invoice_number": invoice_number,
            "date": invoice_date,
            "total": total_amount,
            "line_items": line_items,
            "tables": cleaned_tables,
            "line_count": len(text_lines),
        }

        logger.info(f"Invoice extracted: {vendor}, {invoice_number}, ${total_amount:,.2f} ({len(line_items)} line items)")
        return json.dumps(invoice_data, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Invoice extraction failed: {e}")
        return f"Error extracting invoice from '{path.name}': {str(e)}"
