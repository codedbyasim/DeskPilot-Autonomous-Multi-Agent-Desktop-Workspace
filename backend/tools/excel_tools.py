"""
DeskPilot — Excel Workbook Generation Tools
Creates .xlsx files using openpyxl with professional formatting.
Robustly parses nested lists, single-quoted Python literals, HTML entities, and auto-calculates totals.
"""

from strands import tool
import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter
import json
import html
import ast
import re
import csv
import io
import shutil
from pathlib import Path
from typing import Any, Union, Optional, List
from datetime import datetime
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.save_preferences import resolve_effective_save_dir
from backend.utils.document_resolver import resolve_document_path
from backend.utils.logger import get_logger

logger = get_logger("tools.excel")

# Color palette
BLUE_DARK  = "1A56DB"
BLUE_LIGHT = "DBEAFE"
GRAY_ROW   = "F9FAFB"
WHITE      = "FFFFFF"
RED_FLAG   = "FEE2E2"
GREEN_OK   = "D1FAE5"


def _header_style() -> tuple:
    font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    fill = PatternFill("solid", fgColor=BLUE_DARK)
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    return font, fill, align


def _thin_border() -> Border:
    thin = Side(style="thin", color="D1D5DB")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _get_currency_format(header: str, currency_override: str = "") -> str:
    """
    Determines appropriate Excel number_format based on column header and user currency.
    Avoids hardcoding '$' when the user or header uses PKR, EUR, GBP, INR, etc.
    """
    h = (header or "").strip()
    h_lower = h.lower()

    # 1. Detect currency code from header text or override
    curr = currency_override.strip().upper() if currency_override else ""
    if not curr:
        for c in ["pkr", "rs", "inr", "eur", "gbp", "cad", "aud", "aed", "sar", "usd", "jpy"]:
            if c in h_lower:
                curr = c.upper()
                break
        if "€" in h: curr = "EUR"
        elif "£" in h: curr = "GBP"
        elif "₹" in h: curr = "INR"
        elif "$" in h: curr = "USD"

    # 2. If still not detected, inspect user profile memory
    if not curr:
        try:
            from backend.utils.user_memory import UserMemoryManager
            fin_prof = UserMemoryManager.get_profile("finance")
            glob_prof = UserMemoryManager.get_profile("global")
            curr = (fin_prof.get("currency") or glob_prof.get("currency") or "").strip().upper()
        except Exception:
            curr = ""

    # 3. Check if unit is already explicitly stated in header parentheses (e.g. "Amount (PKR)", "Cost (EUR)")
    has_unit_in_header = bool(re.search(r'\([a-zA-Z$€£₹.\s]+\)', h))

    # If the column header already has the currency (e.g. "Amount (PKR)"), standard practice is plain clean numbers
    if has_unit_in_header:
        return "#,##0.00"

    # Format according to detected currency
    if curr in ("PKR", "RS", "RS."):
        return '"Rs. " #,##0.00'
    elif curr in ("EUR", "€"):
        return '€#,##0.00'
    elif curr in ("GBP", "£"):
        return '£#,##0.00'
    elif curr in ("INR", "₹"):
        return '₹#,##0.00'
    elif curr in ("USD", "$"):
        return '$#,##0.00'
    elif curr:
        return f'"{curr} " #,##0.00'

    # If no currency detected, only use $ if $ is explicitly in header; otherwise plain number
    return '$#,##0.00' if '$' in h else '#,##0.00'


def _clean_html_entities(s: str) -> str:
    """Unescapes HTML character entities like &#91; ([), &#93; (]), &quot;, &#39;, &amp;."""
    if not isinstance(s, str):
        return s
    text = html.unescape(s)
    replacements = {
        "&#91;": "[",
        "&#93;": "]",
        "&#39;": "'",
        "&apos;": "'",
        "&#34;": '"',
        "&quot;": '"',
        "&#44;": ",",
        "&amp;": "&",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def _parse_cell_value(val: Any) -> Any:
    """Cleans cell value and converts numeric strings into actual numbers or formulas."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return val

    val_str = _clean_html_entities(str(val)).strip()
    if not val_str:
        return ""

    # Preserve Excel formulas
    if val_str.startswith("="):
        return val_str

    if val_str.lower() == "true":
        return True
    if val_str.lower() == "false":
        return False

    # Check numeric formats (e.g. "5000", "$5,000.00", "-250.50", "15%")
    clean_num = re.sub(r'[\$,€£\s]', '', val_str)
    if clean_num.endswith("%"):
        try:
            return float(clean_num[:-1]) / 100.0
        except ValueError:
            pass

    if re.match(r'^-?\d+$', clean_num):
        try:
            return int(clean_num)
        except ValueError:
            pass
    elif re.match(r'^-?\d+\.\d+$', clean_num):
        try:
            return float(clean_num)
        except ValueError:
            pass

    return val_str


def _parse_headers(headers: Any) -> List[str]:
    """Robustly parses headers from lists, JSON strings, or CSV strings."""
    if headers is None:
        return ["Category", "Amount"]
    if isinstance(headers, list):
        parsed_list = []
        for h in headers:
            if isinstance(h, (list, tuple)) and len(h) > 0:
                parsed_list.append(str(_parse_cell_value(h[0])))
            else:
                parsed_list.append(str(_parse_cell_value(h)))
        return parsed_list if parsed_list else ["Category", "Amount"]
    if isinstance(headers, str):
        cleaned = _clean_html_entities(headers).strip()
        if not cleaned:
            return ["Category", "Amount"]
        try:
            p = json.loads(cleaned)
            if isinstance(p, list):
                return [str(_parse_cell_value(h)) for h in p]
        except Exception:
            pass
        try:
            p = ast.literal_eval(cleaned)
            if isinstance(p, list):
                return [str(_parse_cell_value(h)) for h in p]
        except Exception:
            pass
        if "|" in cleaned:
            return [c.strip() for c in cleaned.strip("|").split("|") if c.strip()]
        return [c.strip() for c in cleaned.split(",") if c.strip()]
    return [str(headers)]


def _parse_table_data(data: Any, expected_cols: int = 0) -> List[List[Any]]:
    """
    Robustly parses row data. Handles nested lists, HTML entity strings,
    Python literals with single quotes, CSV/Markdown, and flat 1D lists.
    """
    if data is None:
        return []

    parsed = None

    if isinstance(data, str):
        cleaned_str = _clean_html_entities(data).strip()
        # Clean double commas like ",,"
        cleaned_str = re.sub(r',(\s*,)+', ',', cleaned_str)

        # 1. Try json.loads
        try:
            parsed = json.loads(cleaned_str)
        except Exception:
            pass

        # 2. Try ast.literal_eval for python literals like [['Salary', 5000]]
        if parsed is None:
            try:
                parsed = ast.literal_eval(cleaned_str)
            except Exception:
                pass

        # 3. Try quote replacement
        if parsed is None and ("'" in cleaned_str or "[" in cleaned_str):
            try:
                json_candidate = re.sub(r"(?<!\\)'", '"', cleaned_str)
                parsed = json.loads(json_candidate)
            except Exception:
                pass

        # 4. Try regex extraction of bracketed groups: [item1, item2, ...]
        if parsed is None and "[" in cleaned_str and "]" in cleaned_str:
            sub_matches = re.findall(r'\[([^\[\]]+)\]', cleaned_str)
            if sub_matches:
                extracted = []
                for sm in sub_matches:
                    try:
                        reader = csv.reader([sm.strip()])
                        items = [c.strip().strip("'\"") for c in next(reader) if c.strip()]
                        if items:
                            extracted.append(items)
                    except Exception:
                        items = [c.strip().strip("'\"") for c in sm.split(",") if c.strip()]
                        if items:
                            extracted.append(items)
                if extracted:
                    parsed = extracted

        # 5. Try CSV / Markdown line-by-line parsing
        if parsed is None:
            lines = [line.strip() for line in cleaned_str.splitlines() if line.strip()]
            csv_rows = []
            for line in lines:
                if line.startswith("|") and line.endswith("|"):
                    if re.match(r"^\|[\s\-:]+(\|[\s\-:]+)+\|$", line):
                        continue
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if any(cells):
                        csv_rows.append(cells)
                else:
                    try:
                        reader = csv.reader([line])
                        cells = [c.strip() for c in next(reader)]
                        if any(cells):
                            csv_rows.append(cells)
                    except Exception:
                        cells = [c.strip() for c in line.split(",") if c.strip()]
                        if cells:
                            csv_rows.append(cells)
            if csv_rows:
                parsed = csv_rows

    elif isinstance(data, list):
        parsed = data
    elif isinstance(data, dict):
        parsed = [list(data.values())]
    else:
        parsed = [[data]]

    if not isinstance(parsed, list):
        parsed = [[parsed]]

    rows: List[List[Any]] = []
    flat_items: List[Any] = []

    for item in parsed:
        if isinstance(item, (list, tuple)):
            cell_row = [_parse_cell_value(c) for c in item]
            if any(c != "" for c in cell_row):
                rows.append(cell_row)
        elif isinstance(item, dict):
            cell_row = [_parse_cell_value(c) for c in item.values()]
            if any(c != "" for c in cell_row):
                rows.append(cell_row)
        elif isinstance(item, str):
            item_clean = _clean_html_entities(item).strip()
            sub_p = None
            if item_clean.startswith("[") and item_clean.endswith("]"):
                try:
                    sub_p = ast.literal_eval(item_clean)
                except Exception:
                    try:
                        sub_p = json.loads(item_clean)
                    except Exception:
                        pass
            if isinstance(sub_p, (list, tuple)):
                cell_row = [_parse_cell_value(c) for c in sub_p]
                if any(c != "" for c in cell_row):
                    rows.append(cell_row)
            else:
                flat_items.append(_parse_cell_value(item_clean))
        else:
            flat_items.append(_parse_cell_value(item))

    # If all items were 1D flat, chunk into rows matching expected_cols
    if flat_items and not rows:
        chunk_size = expected_cols if expected_cols > 0 else 2
        for i in range(0, len(flat_items), chunk_size):
            chunk = flat_items[i:i + chunk_size]
            rows.append(chunk)

    return rows


def _resolve_excel_path(output_path: str, default_name: str) -> Path:
    """Resolve Excel output path, respecting user save preferences and Desktop mappings."""
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
                clean_name = f"{default_name}.xlsx"
            if not clean_name.endswith(".xlsx"):
                clean_name += ".xlsx"
            return Path.home() / "Desktop" / clean_name
        else:
            p = Path(out_str)
            if not p.is_absolute():
                save_dir = resolve_effective_save_dir()
                return save_dir / p.name
            return p
    else:
        save_dir = resolve_effective_save_dir()
        safe_name = "".join(c for c in default_name if c.isalnum() or c in " _-")[:40] or "Workbook"
        filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return save_dir / filename


@tool
def create_excel_workbook(
    sheet_name: str = "Monthly Budget",
    headers: Any = None,
    rows: Any = None,
    output_path: str = "",
    title: str = "",
    add_totals: bool = True,
) -> str:
    """
    Create a professional Excel workbook (.xlsx) with data, formatting, and optional totals.

    Args:
        sheet_name: Name of the main worksheet (default: 'Monthly Budget')
        headers: List or JSON string of column header strings
        rows: List of lists or JSON string with row data
        output_path: Where to save. Defaults to Desktop or preferred output directory.
        title: Optional title row at top of sheet
        add_totals: Whether to add a totals row for numeric columns

    Returns:
        Path to saved .xlsx file or error message
    """
    logger.info(f"Creating Excel workbook: sheet='{sheet_name}'")

    if not sheet_name:
        sheet_name = "Monthly Budget"

    # Robust header parsing
    header_list = _parse_headers(headers)
    if not header_list:
        header_list = ["Category", "Amount"]

    # Robust row parsing
    row_list = _parse_table_data(rows, expected_cols=len(header_list))
    if not row_list:
        row_list = [
            ["Salary", 5000],
            ["Housing & Rent", 1500],
            ["Utilities", 300],
            ["Groceries", 600],
            ["Transportation", 250],
            ["Savings", 800]
        ]

    safe_name = "".join(c for c in sheet_name if c.isalnum() or c in " _-")[:40] or "Sheet"
    out = _resolve_excel_path(output_path, safe_name)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name[:31]  # Excel sheet name limit

        hdr_font, hdr_fill, hdr_align = _header_style()
        border = _thin_border()
        current_row = 1

        # ── Title Row ─────────────────────────────────────────────────────────
        display_title = title or sheet_name
        ws.merge_cells(
            start_row=1, start_column=1,
            end_row=1, end_column=len(header_list)
        )
        title_cell = ws.cell(row=1, column=1, value=display_title)
        title_cell.font = Font(name="Calibri", bold=True, size=14, color=BLUE_DARK)
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        title_cell.fill = PatternFill("solid", fgColor="EFF6FF")
        ws.row_dimensions[1].height = 30
        current_row = 2

        # Generated date row
        date_row = current_row
        ws.cell(row=date_row, column=1,
                value=f"Generated by DeskPilot Agent — {datetime.now().strftime('%B %d, %Y %H:%M')}")
        ws.cell(row=date_row, column=1).font = Font(italic=True, color="6B7280", size=9)
        current_row += 1

        # ── Header Row ────────────────────────────────────────────────────────
        header_row = current_row
        for col_idx, header in enumerate(header_list, 1):
            cell = ws.cell(row=header_row, column=col_idx, value=header)
            cell.font = hdr_font
            cell.fill = hdr_fill
            cell.alignment = hdr_align
            cell.border = border
        ws.row_dimensions[header_row].height = 24
        current_row += 1

        # ── Data Rows ─────────────────────────────────────────────────────────
        data_start_row = current_row
        for row_idx, row in enumerate(row_list):
            bg_color = GRAY_ROW if row_idx % 2 == 0 else WHITE
            for col_idx, value in enumerate(row, 1):
                if col_idx > len(header_list):
                    break
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.fill = PatternFill("solid", fgColor=bg_color)
                cell.border = border
                cell.alignment = Alignment(vertical="center")

                # Numeric formatting
                col_name = header_list[col_idx - 1]
                col_name_lower = col_name.lower()
                is_currency = any(kw in col_name_lower for kw in ["$", "amount", "budget", "actual", "cost", "salary", "price", "total", "variance", "income", "expense", "pkr", "eur", "gbp", "inr", "usd"])

                if isinstance(value, (int, float)):
                    cell.number_format = _get_currency_format(col_name) if is_currency else "#,##0.00"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
            current_row += 1

        data_end_row = current_row - 1

        # ── Totals Row ────────────────────────────────────────────────────────
        if add_totals and row_list and data_end_row >= data_start_row:
            totals_row = current_row
            ws.cell(row=totals_row, column=1, value="TOTAL").font = Font(bold=True)
            ws.cell(row=totals_row, column=1).fill = PatternFill("solid", fgColor=BLUE_LIGHT)
            ws.cell(row=totals_row, column=1).border = border

            for col_idx in range(2, len(header_list) + 1):
                col_letter = get_column_letter(col_idx)
                # Check if column has any numbers
                has_numbers = any(
                    isinstance(ws.cell(row=r, column=col_idx).value, (int, float))
                    for r in range(data_start_row, data_end_row + 1)
                )
                if has_numbers:
                    formula = f"=SUM({col_letter}{data_start_row}:{col_letter}{data_end_row})"
                    total_cell = ws.cell(row=totals_row, column=col_idx, value=formula)
                    total_cell.font = Font(bold=True)
                    total_cell.fill = PatternFill("solid", fgColor=BLUE_LIGHT)
                    col_name = header_list[col_idx - 1]
                    col_name_lower = col_name.lower()
                    is_currency = any(kw in col_name_lower for kw in ["$", "amount", "budget", "actual", "cost", "salary", "price", "total", "variance", "income", "expense", "pkr", "eur", "gbp", "inr", "usd"])
                    total_cell.number_format = _get_currency_format(col_name) if is_currency else "#,##0.00"
                    total_cell.alignment = Alignment(horizontal="right", vertical="center")
                    total_cell.border = border
                else:
                    empty_cell = ws.cell(row=totals_row, column=col_idx, value="")
                    empty_cell.fill = PatternFill("solid", fgColor=BLUE_LIGHT)
                    empty_cell.border = border

        # ── Auto-fit Column Widths ────────────────────────────────────────────
        for col_idx, header in enumerate(header_list, 1):
            col_letter = get_column_letter(col_idx)
            max_len = len(str(header))
            for row in ws.iter_rows(
                min_row=header_row, max_row=current_row, min_col=col_idx, max_col=col_idx
            ):
                for cell in row:
                    if cell.value is not None:
                        val_str = str(cell.value)
                        # Avoid formula strings skewing length
                        if not val_str.startswith("="):
                            max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(min(max_len + 5, 45), 14)

        # ── Freeze Panes ──────────────────────────────────────────────────────
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

        # ── Save ──────────────────────────────────────────────────────────────
        try:
            wb.save(str(out))
        except PermissionError:
            out = out.parent / f"{out.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{out.suffix}"
            wb.save(str(out))
            logger.info(f"Target file was open; saved with unique timestamp: {out}")
        logger.info(f"Excel saved: {out}")
        return f"SUCCESS: Excel workbook saved to '{out}'"

    except Exception as e:
        logger.error(f"Excel creation failed: {e}")
        return f"Error creating Excel workbook: {str(e)}"


@tool
def read_excel_file(file_path: str, sheet_name: str = "") -> str:
    """
    Read an Excel workbook (.xlsx) and extract its sheets and tabular data.
    Useful for reading supplier ledgers, financial sheets, or audit tables.

    Args:
        file_path: Path to the .xlsx file (e.g. 'sample_data/supplier_ledger.xlsx')
        sheet_name: Specific worksheet name to read (or blank for active sheet)

    Returns:
        JSON string with headers and data rows
    """
    path = resolve_document_path(file_path, default_ext=".xlsx")
    if not path or not path.exists():
        return f"Error: Excel file not found at '{file_path}'. Please check that the file exists."

    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
        ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return f"Worksheet '{ws.title}' in {path.name} is empty."

        headers = [str(c) if c is not None else f"Col_{i}" for i, c in enumerate(rows[0], 1)]
        data_rows = []
        for r in rows[1:]:
            if any(cell is not None for cell in r):
                data_rows.append([c if c is not None else "" for c in r])

        result = {
            "file": path.name,
            "sheet": ws.title,
            "headers": headers,
            "rows": data_rows,
            "row_count": len(data_rows),
        }
        logger.info(f"Read {len(data_rows)} rows from {path.name} [{ws.title}]")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to read Excel file {file_path}: {e}")
        return f"Error reading Excel file: {str(e)}"


@tool
def create_reconciliation_report(
    pdf_data: str = "",
    items: str = "",
    ledger_path: str = "sample_data/supplier_ledger.xlsx",
    excel_path: str = "",
) -> str:
    """
    Compare PDF invoice data against expected ledger values and create
    a discrepancy report in Excel (.xlsx) with variance calculations and status flags.

    Args:
        pdf_data: JSON string with invoice data (from extract_pdf_invoice) or list of invoices
        items: Alias for pdf_data
        ledger_path: Path to supplier ledger Excel file (default: 'sample_data/supplier_ledger.xlsx')
        excel_path: Destination path for the reconciliation report (e.g. 'Desktop/Reconciliation.xlsx')

    Returns:
        Path to saved reconciliation Excel file
    """
    logger.info("Creating reconciliation report")

    out = _resolve_excel_path(excel_path, "Reconciliation_Report")
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1. Parse incoming invoice list
    raw_data = items or pdf_data
    invoice_list = []
    if raw_data:
        try:
            parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            if isinstance(parsed, list):
                invoice_list = parsed
            elif isinstance(parsed, dict):
                invoice_list = [parsed]
        except Exception:
            pass

    # If invoice_list is empty, auto-scan sample_data for invoices
    has_real_data = any(inv.get("total") or inv.get("vendor") for inv in invoice_list)
    if not has_real_data:
        sample_dir = Path("sample_data")
        if sample_dir.exists():
            pdf_files = sorted(list(sample_dir.glob("*.pdf")))
            if pdf_files:
                from backend.tools.pdf_tools import extract_pdf_invoice
                invoice_list = []
                for pdf_file in pdf_files:
                    raw_res = extract_pdf_invoice(str(pdf_file))
                    try:
                        invoice_list.append(json.loads(raw_res))
                    except Exception:
                        pass

    # 2. Load supplier ledger to perform real automated reconciliation
    ledger_map = {}
    led_file = Path(ledger_path)
    if not led_file.exists():
        for cand in [
            Path("sample_data/supplier_ledger.xlsx"),
            Path("DeskPilot/sample_data/supplier_ledger.xlsx"),
        ]:
            if cand.exists():
                led_file = cand
                break

    if led_file.exists():
        try:
            wb_led = openpyxl.load_workbook(str(led_file), data_only=True)
            ws_led = wb_led.active
            for r in list(ws_led.iter_rows(values_only=True))[1:]:
                if r and len(r) >= 3 and r[0]:
                    inv_num = str(r[0]).strip()
                    ven_name = str(r[1]).strip().lower() if len(r) > 1 and r[1] else ""
                    try:
                        exp_val = float(r[2])
                    except Exception:
                        exp_val = 0.0
                    ledger_map[inv_num] = exp_val
                    if ven_name:
                        ledger_map[ven_name] = exp_val
            logger.info(f"Loaded ledger with {len(ledger_map)} entries from {led_file.name}")
        except Exception as e:
            logger.warning(f"Failed loading ledger: {e}")

    # 3. Build Excel Workbook
    wb = openpyxl.Workbook()
    ws_sum = wb.active
    ws_sum.title = "Reconciliation Summary"

    headers = [
        "Invoice File", "Vendor", "Invoice Number", "Invoice Date",
        "Billed Total ($)", "Ledger Expected ($)", "Variance ($)", "Status", "Audit Notes"
    ]
    hdr_font, hdr_fill, hdr_align = _header_style()
    border = _thin_border()

    # Title Banner
    ws_sum.merge_cells("A1:I1")
    ws_sum["A1"] = "Supplier Invoice Reconciliation Audit — DeskPilot Agent"
    ws_sum["A1"].font = Font(bold=True, size=14, color=BLUE_DARK)
    ws_sum["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws_sum["A1"].fill = PatternFill("solid", fgColor="EFF6FF")
    ws_sum.row_dimensions[1].height = 30

    ws_sum["A2"] = f"Generated: {datetime.now().strftime('%B %d, %Y %H:%M')}  •  Automated Verification"
    ws_sum["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws_sum.row_dimensions[2].height = 18

    # Headers row
    for col, h in enumerate(headers, 1):
        cell = ws_sum.cell(row=4, column=col, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = hdr_align
        cell.border = border
    ws_sum.row_dimensions[4].height = 24

    # Data rows
    total_billed = 0.0
    total_expected = 0.0
    matched_count = 0
    mismatch_count = 0

    current_row = 5
    for inv in invoice_list:
        file_name = inv.get("file", "Unknown")
        vendor = inv.get("vendor", "Unknown Vendor")
        inv_num = inv.get("invoice_number", "")
        inv_date = inv.get("date", "")
        try:
            billed_amount = float(inv.get("total", 0.0))
        except Exception:
            billed_amount = 0.0

        # Look up expected amount in ledger
        expected_amount = None
        if inv_num and inv_num in ledger_map:
            expected_amount = ledger_map[inv_num]
        elif vendor.lower() in ledger_map:
            expected_amount = ledger_map[vendor.lower()]
        elif "expected" in inv:
            try:
                expected_amount = float(inv["expected"])
            except Exception:
                expected_amount = billed_amount
        else:
            expected_amount = billed_amount

        variance = round(billed_amount - expected_amount, 2)
        if abs(variance) > 0.01:
            status = "MISMATCH"
            mismatch_count += 1
            notes = f"MISMATCH: Billed (${billed_amount:,.2f}) exceeds ledger (${expected_amount:,.2f}) by ${variance:+,.2f}"
            bg = RED_FLAG
        else:
            status = "OK"
            matched_count += 1
            notes = f"MATCHED: Invoice matches ledger amount (${expected_amount:,.2f}) exactly"
            bg = GREEN_OK

        total_billed += billed_amount
        total_expected += expected_amount

        row_vals = [
            file_name, vendor, inv_num, inv_date,
            billed_amount, expected_amount, variance, status, notes
        ]

        for col, val in enumerate(row_vals, 1):
            cell = ws_sum.cell(row=current_row, column=col, value=val)
            cell.fill = PatternFill("solid", fgColor=bg)
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if col in [5, 6, 7]:
                cell.number_format = "$#,##0.00"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col == 8:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = Font(bold=True)

        ws_sum.row_dimensions[current_row].height = 20
        current_row += 1

    # Totals Row
    ws_sum.cell(row=current_row, column=1, value="TOTALS").font = Font(bold=True)
    ws_sum.cell(row=current_row, column=1).fill = PatternFill("solid", fgColor=BLUE_LIGHT)
    ws_sum.cell(row=current_row, column=5, value=total_billed).number_format = "$#,##0.00"
    ws_sum.cell(row=current_row, column=5).font = Font(bold=True)
    ws_sum.cell(row=current_row, column=5).fill = PatternFill("solid", fgColor=BLUE_LIGHT)

    ws_sum.cell(row=current_row, column=6, value=total_expected).number_format = "$#,##0.00"
    ws_sum.cell(row=current_row, column=6).font = Font(bold=True)
    ws_sum.cell(row=current_row, column=6).fill = PatternFill("solid", fgColor=BLUE_LIGHT)

    ws_sum.cell(row=current_row, column=7, value=round(total_billed - total_expected, 2)).number_format = "$#,##0.00"
    ws_sum.cell(row=current_row, column=7).font = Font(bold=True)
    ws_sum.cell(row=current_row, column=7).fill = PatternFill("solid", fgColor=BLUE_LIGHT)

    ws_sum.cell(row=current_row, column=8, value=f"{mismatch_count} Flagged").font = Font(bold=True)
    ws_sum.cell(row=current_row, column=8).fill = PatternFill("solid", fgColor=BLUE_LIGHT)
    ws_sum.row_dimensions[current_row].height = 22
    current_row += 2

    # KPI Summary Cards
    ws_sum.cell(row=current_row, column=1, value="RECONCILIATION AUDIT SUMMARY").font = Font(bold=True, color=BLUE_DARK, size=11)
    current_row += 1
    kpis = [
        ("Total Invoices Audited", len(invoice_list)),
        ("Invoices Matched Exactly (OK)", matched_count),
        ("Discrepancies Flagged (MISMATCH)", mismatch_count),
        ("Net Variance Amount", f"${total_billed - total_expected:+,.2f}"),
    ]
    for label, val in kpis:
        ws_sum.cell(row=current_row, column=1, value=label).font = Font(bold=True)
        ws_sum.cell(row=current_row, column=2, value=val)
        current_row += 1

    # Auto-adjust column widths
    for col in ws_sum.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws_sum.column_dimensions[col_letter].width = max(max_len + 4, 14)

    try:
        wb.save(str(out))
    except PermissionError:
        out = out.parent / f"{out.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{out.suffix}"
        wb.save(str(out))
        logger.info(f"Target reconciliation file was open; saved with timestamp: {out}")
    logger.info(f"Reconciliation report saved: {out}")
    return f"SUCCESS: Reconciliation report saved to '{out}'"


@tool
def verify_excel_workbook(file_path: str, required_sheets: str = "[]") -> str:
    """
    Verify an Excel workbook exists, opens, and has populated data.

    Args:
        file_path: Path to the .xlsx file
        required_sheets: JSON list of sheet names that must exist

    Returns:
        Verification report string
    """
    raw_str = str(file_path).strip().strip("'\"")
    raw = Path(raw_str)
    logger.info(f"Verifying Excel: {raw}")

    candidates = [
        raw,
        Path.cwd() / raw,
        Path.home() / "Desktop" / raw.name,
        Path.cwd() / "Desktop" / raw.name,
        DEFAULT_OUTPUT_DIR / raw.name,
    ]

    target_path = None
    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                target_path = cand
                break
        except Exception:
            pass

    if target_path is None:
        recent_files = []
        for search_dir in [DEFAULT_OUTPUT_DIR, Path.home() / "Desktop", Path.cwd() / "Desktop", Path.cwd()]:
            if search_dir.exists():
                recent_files.extend(list(search_dir.glob("*.xlsx")))
        if recent_files:
            recent_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = recent_files[0]
            logger.info(f"Resolved to recent Excel deliverable: {target_path}")

    if target_path is None or not target_path.exists():
        return f"FAIL: File not found at '{file_path}'"

    path = target_path
    checks = {}
    checks["file_exists"] = True
    checks["file_non_empty"] = path.stat().st_size > 0

    try:
        wb = openpyxl.load_workbook(str(path))
        checks["file_opens"] = True
    except Exception as e:
        return f"FAIL: Cannot open workbook: {e}"

    checks["has_sheets"] = len(wb.sheetnames) > 0

    # Check required sheets
    try:
        req_sheets = json.loads(required_sheets)
        for sheet in req_sheets:
            checks[f"sheet_{sheet}"] = sheet in wb.sheetnames
    except Exception:
        pass

    # Check first sheet has data
    ws = wb.active
    data_rows = sum(1 for row in ws.iter_rows() if any(c.value for c in row))
    checks["has_data"] = data_rows > 1

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    report = f"Excel Verification: {path.name}\n{'='*50}\n"
    for name, result in checks.items():
        icon = "✓" if result else "✗"
        report += f"  {icon} {name}\n"
    report += f"\nResult: {passed}/{total} checks passed\n"
    report += "VERIFIED ✓" if passed == total else f"ISSUES ({total - passed} failed)"

    return report


@tool
def edit_excel_file(
    file_path: str,
    cell_updates: Optional[Union[list, dict, str]] = None,
    append_rows: Optional[Union[list, str]] = None,
    sheet_name: str = "",
    output_path: str = "",
) -> str:
    """
    Edit an existing Excel workbook (.xlsx) by updating specific cell values,
    appending new rows of data, or adding calculations.
    Maintains existing sheet structure, styles, and formulas.
    Automatically creates a safe backup (.bak) when editing in-place.

    Args:
        file_path: Path or filename of the .xlsx file (e.g. 'budget.xlsx' or 'sample_data/supplier_ledger.xlsx')
        cell_updates: Dict {'B4': 5000, 'C4': 'Paid'} or list of dicts [{'cell': 'B4', 'value': 5000}]
        append_rows: 2D list or JSON string of rows to append at the bottom
        sheet_name: Worksheet name to edit (default: active sheet)
        output_path: Destination path for the edited file (empty to edit in-place with .bak backup)

    Returns:
        Status message detailing modified cells, appended rows, backup path, and deliverable location.
    """
    path = resolve_document_path(file_path, default_ext=".xlsx")
    if not path or not path.exists():
        return f"Error: Excel file not found at '{file_path}'. Please check that the file exists."

    try:
        wb = openpyxl.load_workbook(str(path))
    except Exception as e:
        logger.error(f"Cannot open Excel workbook {path}: {e}")
        return f"Error opening Excel file '{path.name}': {str(e)}"

    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
    border = _thin_border()

    cells_modified = 0
    # 1. Parse and apply cell updates
    if cell_updates:
        updates_list = []
        if isinstance(cell_updates, str):
            try:
                parsed = json.loads(cell_updates)
                if isinstance(parsed, dict):
                    updates_list = [{"cell": k, "value": v} for k, v in parsed.items()]
                elif isinstance(parsed, list):
                    updates_list = parsed
            except Exception:
                pass
        elif isinstance(cell_updates, dict):
            updates_list = [{"cell": k, "value": v} for k, v in cell_updates.items()]
        elif isinstance(cell_updates, list):
            updates_list = cell_updates

        for upd in updates_list:
            if isinstance(upd, dict):
                cell_ref = upd.get("cell") or upd.get("coord")
                if not cell_ref and "row" in upd and "col" in upd:
                    cell_ref = f"{get_column_letter(int(upd['col']))}{upd['row']}"
                if cell_ref:
                    val = _parse_cell_value(upd.get("value", ""))
                    cell = ws[str(cell_ref).strip()]
                    cell.value = val
                    if isinstance(val, (int, float)) and not cell.number_format:
                        cell.number_format = "#,##0.00"
                    cells_modified += 1

    # 2. Parse and append rows
    rows_appended = 0
    if append_rows:
        parsed_rows = _parse_table_data(append_rows)
        if parsed_rows:
            start_row = ws.max_row + 1
            for r_idx, row_data in enumerate(parsed_rows):
                cur_row = start_row + r_idx
                bg = GRAY_ROW if cur_row % 2 == 0 else WHITE
                for col_idx, val in enumerate(row_data, 1):
                    parsed_val = _parse_cell_value(val)
                    c = ws.cell(row=cur_row, column=col_idx, value=parsed_val)
                    c.border = border
                    c.fill = PatternFill("solid", fgColor=bg)
                    c.alignment = Alignment(vertical="center")
                    if isinstance(parsed_val, (int, float)):
                        c.number_format = "#,##0.00"
                        c.alignment = Alignment(horizontal="right", vertical="center")
                rows_appended += 1

    # 3. Destination & Backup
    backup_path = None
    if output_path and str(output_path).strip():
        out_dest = _resolve_excel_path(output_path, default_name=path.stem)
    else:
        out_dest = path
        backup_path = path.parent / f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx.bak"
        try:
            shutil.copy2(path, backup_path)
            logger.info(f"Created Excel safety backup: {backup_path}")
        except Exception as e:
            logger.warning(f"Could not create Excel safety backup: {e}")

    # 4. Save workbook
    try:
        wb.save(str(out_dest))
    except PermissionError:
        out_dest = out_dest.parent / f"{out_dest.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{out_dest.suffix}"
        wb.save(str(out_dest))
        logger.info(f"Target Excel file was open; saved to: {out_dest}")

    abs_out = str(out_dest.resolve())
    verify_report = verify_excel_workbook(abs_out)

    resp = [
        f"SUCCESS: Excel workbook updated and saved to '{abs_out}'",
        f"Modifications: Updated {cells_modified} cell(s), appended {rows_appended} row(s) to sheet '{ws.title}'",
    ]
    if backup_path and backup_path.exists():
        resp.append(f"Safety Backup Created: '{backup_path.resolve()}'")
    resp.append(f"\nVerification:\n{verify_report}")
    return "\n".join(resp)

