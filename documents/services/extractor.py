import io
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ExtractionError(Exception):
    """Custom exception raised when text extraction fails."""
    pass


def extract_pdf(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts text page-by-page from a PDF file using PyMuPDF.
    Returns a list of dicts containing page_number (1-indexed) and extracted text.
    """
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
    except ImportError as e:
        raise ExtractionError("PyMuPDF is not installed.") from e

    results = []
    try:
        doc = fitz.open(file_path)
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_text = page.get_text("text").strip()
            if page_text:
                results.append({
                    "page_number": page_idx + 1,
                    "text": page_text,
                    "is_structured_row": False,
                })
        doc.close()
    except Exception as e:
        logger.error(f"Failed to extract PDF text from {file_path}: {e}")
        raise ExtractionError(f"Failed to extract text from PDF: {str(e)}") from e

    return results


def extract_docx(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts text from a DOCX file using python-docx.
    Extracts headings, paragraphs, and tables, preserving semantic structure.
    """
    try:
        import docx
    except ImportError as e:
        raise ExtractionError("python-docx is not installed.") from e

    results = []
    try:
        doc = docx.Document(file_path)
        content_parts = []

        # 1. Extract paragraphs and headings
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            if para.style and para.style.name.startswith('Heading'):
                content_parts.append(f"\n## {text}\n")
            else:
                content_parts.append(text)

        # 2. Extract tables without silently discarding data
        for table_idx, table in enumerate(doc.tables, start=1):
            table_rows = []
            headers = []
            for r_idx, row in enumerate(table.rows):
                row_cells = [cell.text.strip() for cell in row.cells]
                dedup_cells = []
                for cell in row_cells:
                    if not dedup_cells or cell != dedup_cells[-1]:
                        dedup_cells.append(cell)

                if r_idx == 0:
                    headers = dedup_cells
                    table_rows.append(" | ".join(headers))
                    table_rows.append("-" * max(20, len(" | ".join(headers))))
                else:
                    table_rows.append(" | ".join(dedup_cells))

            if table_rows:
                content_parts.append(f"\n[Table {table_idx}]\n" + "\n".join(table_rows) + "\n")

        full_text = "\n\n".join(content_parts).strip()
        if full_text:
            results.append({
                "page_number": 1,
                "text": full_text,
                "is_structured_row": False,
            })
    except Exception as e:
        logger.error(f"Failed to extract DOCX text from {file_path}: {e}")
        raise ExtractionError(f"Failed to extract text from DOCX: {str(e)}") from e

    return results


def extract_txt(file_path: str) -> List[Dict[str, Any]]:
    """
    Safely extracts text from a plain text file using multiple fallback encodings.
    Handles UTF-8 with BOM, standard UTF-8, Latin-1, and CP1252.
    """
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    text = None
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                text = f.read().strip()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if text is None:
        raise ExtractionError("Unable to decode text file with supported encodings (UTF-8, Latin-1, CP1252).")

    if text:
        return [{
            "page_number": 1,
            "text": text,
            "is_structured_row": False,
        }]
    return []


def extract_csv(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts structured data from a CSV file.
    Converts each row into a meaningful key-value textual representation:
    Column Name: Value
    Preserves row_number and marks the item as a structured row for 1-row-1-chunk handling.
    """
    import csv

    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    rows_data = []

    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc, newline='') as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except Exception:
                    dialect = 'excel'

                reader = csv.reader(f, dialect=dialect)
                header = None
                for row_idx, row in enumerate(reader, start=1):
                    cleaned_cells = [c.strip() for c in row]
                    if not any(cleaned_cells):
                        continue
                    if header is None:
                        header = cleaned_cells
                        continue

                    row_pairs = []
                    for h, val in zip(header, cleaned_cells):
                        if h and val:
                            row_pairs.append(f"{h}: {val}")
                        elif val:
                            row_pairs.append(f"Value: {val}")

                    if row_pairs:
                        row_text = "\n".join(row_pairs)
                        rows_data.append({
                            "page_number": None,
                            "row_number": row_idx,
                            "text": row_text,
                            "is_structured_row": True,
                            "metadata": {
                                "row_number": row_idx,
                                "columns": header,
                            }
                        })
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            logger.error(f"Error reading CSV {file_path}: {e}")
            raise ExtractionError(f"Failed to read CSV file: {str(e)}") from e

    return rows_data


def extract_xlsx(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts structured data from an Excel XLSX file using openpyxl.
    Iterates through all sheets and converts each row into a meaningful textual entity:
    Sheet: <sheet_name>
    Column Name: Value
    Preserves sheet_name and row_number for 1-row-1-chunk processing.
    """
    try:
        import openpyxl
    except ImportError as e:
        raise ExtractionError("openpyxl is not installed.") from e

    results = []
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            header = None
            for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if not row or not any(row):
                    continue

                string_cells = [str(c).strip() if c is not None else "" for c in row]
                if not any(string_cells):
                    continue

                if header is None:
                    header = string_cells
                    continue

                row_pairs = [f"Sheet: {sheet_name}", f"Row: {row_idx}"]
                for h, val in zip(header, string_cells):
                    if h and val:
                        row_pairs.append(f"{h}: {val}")
                    elif val:
                        row_pairs.append(f"Value: {val}")

                if len(row_pairs) > 2:
                    row_text = "\n".join(row_pairs)
                    results.append({
                        "page_number": None,
                        "row_number": row_idx,
                        "sheet_name": sheet_name,
                        "text": row_text,
                        "is_structured_row": True,
                        "metadata": {
                            "row_number": row_idx,
                            "sheet_name": sheet_name,
                        }
                    })
        wb.close()
    except Exception as e:
        logger.error(f"Failed to extract XLSX from {file_path}: {e}")
        raise ExtractionError(f"Failed to extract text from Excel XLSX: {str(e)}") from e

    return results


def extract_document(file_path: str, file_type: str) -> List[Dict[str, Any]]:
    file_type = file_type.lower().strip()
    if file_type == 'pdf':
        return extract_pdf(file_path)
    elif file_type == 'docx':
        return extract_docx(file_path)
    elif file_type == 'txt':
        return extract_txt(file_path)
    elif file_type == 'csv':
        return extract_csv(file_path)
    elif file_type in ('xlsx', 'xls'):
        return extract_xlsx(file_path)
    else:
        raise ExtractionError(f"Unsupported file type: {file_type}")
