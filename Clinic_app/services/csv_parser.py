# Clinic_app/services/csv_parser.py
"""
HEDIS CSV parser using Claude API for column normalization.

Pipeline:
  1. Detect CSV delimiter (comma, pipe, tab)
  2. Extract header + first 2 data rows → Claude API for column mapping
  3. Apply mapping to all rows
  4. Normalize phones to E.164 (+1XXXXXXXXXX)
  5. Map gap type strings to GapType enum values
  6. Return (list[ParsedRow], list[ParseError])

Claude is called ONCE per upload — only header + 2 sample rows are sent.
The full dataset is processed locally using the returned column mapping.
"""

import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic
import openpyxl
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from Clinic_app.data.enums import GapType, APPOINTMENT_BASED_GAP_TYPES

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-20250514"

# The set of normalized field names Claude must map to.
NORMALIZED_FIELD_NAMES = {
    "phone",
    "gap_type",
    "language",
    "patient_name",
    "patient_dob",
    "provider_name",
    "payer",
    "release_date",  # hospital_flu only: date of hospital discharge (YYYY-MM-DD)
    "ignore",
}

# The set of valid gap type values Claude must map gap_type values to.
VALID_GAP_TYPES = {gt.value for gt in GapType}

_SYSTEM_PROMPT = """\
You are a HEDIS data normalization assistant. You will receive the first 3 rows
of a patient outreach CSV (header row + up to 2 data rows) and return a JSON
object that:

1. Maps each input column header to exactly one of these normalized field names:
   phone, gap_type, language, patient_name, patient_dob, provider_name, payer, ignore

2. For gap_type values found in the data rows, provides a "gap_type_values" mapping
   from raw strings to one of these standard codes:
   preventive_visit, hospital_flu, colorectal, eye_exam, breast_cancer,
   kidney, afr_cmp, medication_review, generic

   Alias guide (non-exhaustive):
   - "Preventive visit", "Annual wellness", "AWV", "Yearly checkup"  →  preventive_visit
   - "Hospital follow-up", "Hospital flu", "Hosp flu", "Post-hospital", "Discharge follow-up"  →  hospital_flu
   - "Colorectal", "CRC", "Colonoscopy", "Stool test", "FIT"  →  colorectal
   - "Eye exam", "Eye", "Vision", "Ophthalmology", "Retinal exam"  →  eye_exam
   - "Breast cancer", "Breast cancer screening", "Mammogram", "BSE"  →  breast_cancer
   - "Kidney", "Kidney function", "CKD", "Renal"  →  kidney
   - "AFR/CMP", "Albumin creatinine", "Alb/Cr ratio", "urine albumin", "bw/uA"  →  afr_cmp
   - "Medication review", "Med review", "Medication management"  →  medication_review
   - Anything unrecognized  →  generic

Return ONLY a valid JSON object. No explanation, no markdown. Example:
{
  "column_mapping": {
    "Member Phone": "phone",
    "COL_SCREEN": "gap_type",
    "LANG": "language",
    "Member Name": "patient_name",
    "DOB": "patient_dob",
    "PCP Name": "provider_name",
    "Payer": "payer",
    "Plan ID": "ignore"
  },
  "gap_type_values": {
    "COL": "colorectal",
    "PREV": "preventive_visit",
    "HOSP FLU": "hospital_flu"
  }
}
"""

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    """A normalized, validated patient row ready for campaign ingestion."""
    phone_e164: str              # E.164 format, e.g. "+17875551234"
    gap_type: GapType
    language: str                # "en" | "es" | other BCP-47 code
    patient_name: Optional[str] = None   # Encrypted at campaign ingest
    patient_dob: Optional[str] = None    # Encrypted at campaign ingest
    provider_name: Optional[str] = None  # Plain text — Retell metadata
    payer: Optional[str] = None          # Plain text — Retell metadata
    release_date: Optional[str] = None   # hospital_flu only: discharge date ISO string (YYYY-MM-DD)
    raw_row_number: int = 0      # 1-indexed row number in original file (for error reporting)


@dataclass
class ParseError:
    """A row that could not be parsed. Upload is not aborted — errors are reported."""
    row_number: int
    reason: str
    raw_data: dict = field(default_factory=dict)


@dataclass
class ColumnMapping:
    """Claude-returned column mapping for a specific CSV layout."""
    phone_col: Optional[str]
    gap_type_col: Optional[str]
    language_col: Optional[str]
    name_col: Optional[str]
    dob_col: Optional[str]
    provider_col: Optional[str]
    payer_col: Optional[str]
    release_date_col: Optional[str]   # hospital_flu discharge date column
    gap_type_values: dict[str, str]   # raw gap type string → GapType.value


# ── E.164 phone normalization ──────────────────────────────────────────────────

_DIGITS_RE = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """
    Normalize a phone string to E.164 format (+1XXXXXXXXXX).
    Raises ValueError if the number cannot be normalized to a 10-digit US number.
    """
    digits = _DIGITS_RE.sub("", raw or "")
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError(f"Cannot normalize phone to E.164: {raw!r} → {digits!r}")


# ── Claude API call ────────────────────────────────────────────────────────────

def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


@retry(
    retry=retry_if_exception_type(anthropic.APIConnectionError),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    stop=stop_after_attempt(3),
)
def _call_claude_for_column_mapping(
    header_row: list[str],
    sample_rows: list[list[str]],
) -> dict:
    """
    Call Claude API with the CSV header + up to 2 sample data rows.
    Returns the parsed JSON dict. Retries on connection errors (up to 3x).
    """
    client = _get_anthropic_client()

    # Build a compact CSV snippet (header + up to 2 rows) for Claude
    snippet_lines = [",".join(header_row)]
    for row in sample_rows[:2]:
        snippet_lines.append(",".join(str(c) for c in row))
    snippet = "\n".join(snippet_lines)

    user_message = f"Normalize this HEDIS CSV header and sample data:\n\n{snippet}"

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_text = response.content[0].text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error(f"Claude returned non-JSON: {raw_text[:200]}")
        raise ValueError(f"Claude returned invalid JSON: {exc}") from exc


def _build_column_mapping(claude_response: dict, header_row: list[str]) -> ColumnMapping:
    """Convert Claude's raw response dict into a typed ColumnMapping."""
    col_map: dict[str, str] = claude_response.get("column_mapping", {})
    gap_type_vals: dict[str, str] = claude_response.get("gap_type_values", {})

    def find_col(normalized_name: str) -> Optional[str]:
        for header, norm in col_map.items():
            if norm == normalized_name and header in header_row:
                return header
        return None

    return ColumnMapping(
        phone_col=find_col("phone"),
        gap_type_col=find_col("gap_type"),
        language_col=find_col("language"),
        name_col=find_col("patient_name"),
        dob_col=find_col("patient_dob"),
        provider_col=find_col("provider_name"),
        payer_col=find_col("payer"),
        release_date_col=find_col("release_date"),
        gap_type_values=gap_type_vals,
    )


# ── Gap type mapping ───────────────────────────────────────────────────────────

def map_gap_type(raw: str, gap_type_values: dict[str, str]) -> GapType:
    """
    Map a raw gap type string to a GapType enum value using Claude's mapping.
    Falls back to GapType.GENERIC if not found — never raises.
    """
    normalized = gap_type_values.get(raw, raw)
    try:
        return GapType(normalized)
    except ValueError:
        logger.warning(f"Unknown gap type value {raw!r} → defaulting to GapType.GENERIC")
        return GapType.GENERIC


# ── Delimiter detection ────────────────────────────────────────────────────────

def _detect_delimiter(header_line: str) -> str:
    """Heuristically detect CSV delimiter from the header line."""
    counts = {",": header_line.count(","), "|": header_line.count("|"), "\t": header_line.count("\t")}
    return max(counts, key=counts.get)


# ── Excel → row list conversion ────────────────────────────────────────────────

def _read_excel_rows(file_bytes: bytes) -> tuple[list[str], list[dict]]:
    """
    Read an Excel workbook (.xlsx) and return (header_row, all_rows).
    Uses the first sheet. Empty cells become empty strings.
    Raises ValueError if the workbook is empty or unreadable.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Cannot read Excel file: {exc}") from exc

    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)

    try:
        raw_header = next(rows_iter)
    except StopIteration:
        raise ValueError("Excel file is empty.")

    header = [str(cell).strip() if cell is not None else "" for cell in raw_header]
    # Filter out trailing empty columns
    header = [h for h in header if h]
    if not header:
        raise ValueError("Excel header row has no non-empty column names.")

    all_rows: list[dict] = []
    for raw_row in rows_iter:
        row_dict = {}
        for i, h in enumerate(header):
            cell_val = raw_row[i] if i < len(raw_row) else None
            row_dict[h] = str(cell_val).strip() if cell_val is not None else ""
        # Skip fully empty rows
        if any(v for v in row_dict.values()):
            all_rows.append(row_dict)

    wb.close()
    return header, all_rows


# ── Main parse function ────────────────────────────────────────────────────────

def parse_file(
    file_bytes: bytes,
    filename: str = "",
    encoding: str = "utf-8",
) -> tuple[list[ParsedRow], list[ParseError]]:
    """
    Parse a HEDIS patient file (CSV or Excel) using Claude for column normalization.

    Accepts:
      - CSV (.csv) with comma, pipe, or tab delimiter
      - Excel (.xlsx, .xls) — first sheet used

    Returns:
        (parsed_rows, parse_errors)
        - parsed_rows: successfully normalized rows
        - parse_errors: rows that could not be parsed (bad phone, missing required field)
          Upload is NOT aborted on parse errors — caller decides whether to proceed.

    Raises:
        ValueError: file is empty, unreadable, or Claude call fails after retries.
    """
    fname_lower = filename.lower()
    is_excel = fname_lower.endswith(".xlsx") or fname_lower.endswith(".xls")

    if is_excel:
        header_row, all_rows = _read_excel_rows(file_bytes)
    else:
        # CSV path
        try:
            text = file_bytes.decode(encoding)
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")

        lines = text.splitlines()
        if not lines:
            raise ValueError("File is empty.")

        delimiter = _detect_delimiter(lines[0])
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        all_rows = list(reader)
        if not all_rows:
            raise ValueError("File has a header but no data rows.")
        header_row = list(all_rows[0].keys())

    if not all_rows:
        raise ValueError("File has no data rows.")

    sample_rows = [[row.get(h, "") for h in header_row] for row in all_rows[:2]]

    # Claude API call — once per upload
    logger.info(f"Calling Claude to normalize file columns. header_count={len(header_row)}")
    claude_response = _call_claude_for_column_mapping(header_row, sample_rows)
    mapping = _build_column_mapping(claude_response, header_row)

    if not mapping.phone_col:
        raise ValueError("Could not identify a phone number column. Check your file format.")
    if not mapping.gap_type_col:
        raise ValueError("Could not identify a gap type column. Check your file format.")

    parsed_rows: list[ParsedRow] = []
    parse_errors: list[ParseError] = []

    for idx, row in enumerate(all_rows, start=2):  # start=2: row 1 is header
        raw_phone = row.get(mapping.phone_col, "").strip()
        raw_gap = row.get(mapping.gap_type_col, "").strip()
        raw_lang = row.get(mapping.language_col, "en").strip() if mapping.language_col else "en"
        raw_name = row.get(mapping.name_col, "").strip() if mapping.name_col else None
        raw_dob = row.get(mapping.dob_col, "").strip() if mapping.dob_col else None
        raw_provider = row.get(mapping.provider_col, "").strip() if mapping.provider_col else None
        raw_payer = row.get(mapping.payer_col, "").strip() if mapping.payer_col else None
        raw_release_date = row.get(mapping.release_date_col, "").strip() if mapping.release_date_col else None

        try:
            phone_e164 = normalize_phone(raw_phone)
        except ValueError as exc:
            parse_errors.append(ParseError(
                row_number=idx,
                reason=str(exc),
                raw_data=dict(row),
            ))
            continue

        gap_type = map_gap_type(raw_gap, mapping.gap_type_values)

        # medication_review is always excluded — never enters the campaign queue
        if gap_type == GapType.MEDICATION_REVIEW:
            logger.info(f"Row {idx}: medication_review excluded per taxonomy — skipping")
            continue

        language = raw_lang if raw_lang else "en"

        parsed_rows.append(ParsedRow(
            phone_e164=phone_e164,
            gap_type=gap_type,
            language=language,
            patient_name=raw_name or None,
            patient_dob=raw_dob or None,
            provider_name=raw_provider or None,
            payer=raw_payer or None,
            release_date=raw_release_date or None,
            raw_row_number=idx,
        ))

    logger.info(f"File parse complete. parsed={len(parsed_rows)}, errors={len(parse_errors)}")
    return parsed_rows, parse_errors
