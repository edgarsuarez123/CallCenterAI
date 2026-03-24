# tests/test_csv_parser.py
"""
Unit tests for services/csv_parser.py.
Claude API is fully mocked — no real API calls.
"""

import io
import json
import pytest
from unittest.mock import MagicMock, patch

from Clinic_app.data.enums import GapType
from Clinic_app.services.csv_parser import (
    ColumnMapping,
    ParsedRow,
    ParseError,
    normalize_phone,
    map_gap_type,
    _build_column_mapping,
    _detect_delimiter,
    parse_file,
)

# ── Shared mock Claude response ────────────────────────────────────────────────

MOCK_CLAUDE_RESPONSE = {
    "column_mapping": {
        "Member Phone": "phone",
        "HEDIS Measure": "gap_type",
        "Language": "language",
        "Member Name": "patient_name",
        "DOB": "patient_dob",
        "Plan ID": "ignore",
    },
    "gap_type_values": {
        "COL": "colorectal",
        "DM_A1C": "kidney",
        "HBP": "eye_exam",
        "PREV": "preventive_visit",
    },
}


def _make_mock_anthropic(response_json: dict = None):
    """Build a mock anthropic client that returns a fixed column mapping JSON."""
    if response_json is None:
        response_json = MOCK_CLAUDE_RESPONSE
    mock_content = MagicMock()
    mock_content.text = json.dumps(response_json)
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


# ── normalize_phone ────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNormalizePhone:
    def test_10_digit_no_formatting(self):
        assert normalize_phone("7875551234") == "+17875551234"

    def test_dashes(self):
        assert normalize_phone("787-555-1234") == "+17875551234"

    def test_parens_and_spaces(self):
        assert normalize_phone("(787) 555-1234") == "+17875551234"

    def test_already_e164(self):
        assert normalize_phone("+17875551234") == "+17875551234"

    def test_11_digit_with_country_code(self):
        assert normalize_phone("17875551234") == "+17875551234"

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            normalize_phone("555-1234")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            normalize_phone("")

    def test_non_us_raises(self):
        with pytest.raises(ValueError):
            normalize_phone("44-20-7946-0958")  # UK number


# ── map_gap_type ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMapGapType:
    def test_known_mapping(self):
        mapping = {"COL": "colorectal"}
        assert map_gap_type("COL", mapping) == GapType.COLORECTAL

    def test_direct_enum_value(self):
        # Raw value is already a valid GapType enum value
        assert map_gap_type("kidney", {}) == GapType.KIDNEY

    def test_unknown_falls_back_to_generic(self):
        assert map_gap_type("UNKNOWN_MEASURE_XYZ", {}) == GapType.GENERIC

    def test_empty_falls_back_to_generic(self):
        assert map_gap_type("", {}) == GapType.GENERIC


# ── _detect_delimiter ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDetectDelimiter:
    def test_comma(self):
        assert _detect_delimiter("Name,Phone,Gap") == ","

    def test_pipe(self):
        assert _detect_delimiter("Name|Phone|Gap") == "|"

    def test_tab(self):
        assert _detect_delimiter("Name\tPhone\tGap") == "\t"


# ── _build_column_mapping ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestBuildColumnMapping:
    def test_maps_all_fields(self):
        header = ["Member Phone", "HEDIS Measure", "Language", "Member Name", "DOB", "Plan ID"]
        mapping = _build_column_mapping(MOCK_CLAUDE_RESPONSE, header)
        assert mapping.phone_col == "Member Phone"
        assert mapping.gap_type_col == "HEDIS Measure"
        assert mapping.language_col == "Language"
        assert mapping.name_col == "Member Name"
        assert mapping.dob_col == "DOB"
        assert mapping.provider_col is None
        assert mapping.payer_col is None

    def test_missing_optional_fields_are_none(self):
        response = {
            "column_mapping": {"Phone": "phone", "Gap": "gap_type"},
            "gap_type_values": {},
        }
        mapping = _build_column_mapping(response, ["Phone", "Gap"])
        assert mapping.phone_col == "Phone"
        assert mapping.language_col is None
        assert mapping.name_col is None
        assert mapping.dob_col is None
        assert mapping.provider_col is None
        assert mapping.payer_col is None

    def test_header_column_not_in_file_is_none(self):
        # Claude returns a column that isn't actually in the file header
        response = {
            "column_mapping": {"Ghost Column": "phone"},
            "gap_type_values": {},
        }
        mapping = _build_column_mapping(response, ["Phone", "Gap"])
        assert mapping.phone_col is None  # "Ghost Column" not in header


# ── parse_file (CSV) ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestParseCSV:
    def _make_csv(self, rows: list[dict], delimiter: str = ",") -> bytes:
        headers = list(rows[0].keys())
        lines = [delimiter.join(headers)]
        for row in rows:
            lines.append(delimiter.join(str(row[h]) for h in headers))
        return "\n".join(lines).encode("utf-8")

    @patch("Clinic_app.services.csv_parser._get_anthropic_client")
    def test_valid_csv_parses_correctly(self, mock_get_client):
        mock_get_client.return_value = _make_mock_anthropic()
        csv_bytes = self._make_csv([
            {"Member Phone": "7875551234", "HEDIS Measure": "COL", "Language": "es",
             "Member Name": "Juan Perez", "DOB": "1970-01-01", "Plan ID": "ABC"},
            {"Member Phone": "7875559999", "HEDIS Measure": "DM_A1C", "Language": "en",
             "Member Name": "Maria Lopez", "DOB": "1980-06-15", "Plan ID": "XYZ"},
        ])
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 2
        assert len(errors) == 0
        assert rows[0].phone_e164 == "+17875551234"
        assert rows[0].gap_type == GapType.COLORECTAL
        assert rows[0].language == "es"
        assert rows[0].patient_name == "Juan Perez"
        assert rows[1].gap_type == GapType.KIDNEY

    @patch("Clinic_app.services.csv_parser._get_anthropic_client")
    def test_bad_phone_goes_to_errors_not_raises(self, mock_get_client):
        mock_get_client.return_value = _make_mock_anthropic()
        csv_bytes = self._make_csv([
            {"Member Phone": "NOT_A_PHONE", "HEDIS Measure": "COL", "Language": "en",
             "Member Name": "Test", "DOB": "", "Plan ID": ""},
        ])
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 0
        assert len(errors) == 1
        assert "NOT_A_PHONE" in errors[0].reason or errors[0].row_number == 2

    @patch("Clinic_app.services.csv_parser._get_anthropic_client")
    def test_unrecognized_gap_type_maps_to_generic(self, mock_get_client):
        mock_get_client.return_value = _make_mock_anthropic()
        csv_bytes = self._make_csv([
            {"Member Phone": "7875551234", "HEDIS Measure": "UNKNOWN_GAP", "Language": "en",
             "Member Name": "", "DOB": "", "Plan ID": ""},
        ])
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 1
        assert rows[0].gap_type == GapType.GENERIC

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_file(b"", filename="empty.csv")

    @patch("Clinic_app.services.csv_parser._get_anthropic_client")
    def test_mixed_valid_and_invalid_rows(self, mock_get_client):
        mock_get_client.return_value = _make_mock_anthropic()
        csv_bytes = self._make_csv([
            {"Member Phone": "7875551234", "HEDIS Measure": "COL", "Language": "en",
             "Member Name": "", "DOB": "", "Plan ID": ""},
            {"Member Phone": "BADINPUT", "HEDIS Measure": "COL", "Language": "en",
             "Member Name": "", "DOB": "", "Plan ID": ""},
            {"Member Phone": "7875559999", "HEDIS Measure": "HBP", "Language": "es",
             "Member Name": "", "DOB": "", "Plan ID": ""},
        ])
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 2
        assert len(errors) == 1

    @patch("Clinic_app.services.csv_parser._get_anthropic_client")
    def test_pipe_delimited_csv(self, mock_get_client):
        mock_get_client.return_value = _make_mock_anthropic()
        csv_bytes = self._make_csv([
            {"Member Phone": "7875551234", "HEDIS Measure": "COL", "Language": "en",
             "Member Name": "Test", "DOB": "", "Plan ID": ""},
        ], delimiter="|")
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 1
        assert rows[0].phone_e164 == "+17875551234"


# ── parse_file (Excel) ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestParseExcel:
    def _make_xlsx(self, rows: list[dict]) -> bytes:
        import openpyxl, io
        wb = openpyxl.Workbook()
        ws = wb.active
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row[h] for h in headers])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @patch("Clinic_app.services.csv_parser._get_anthropic_client")
    def test_valid_xlsx_parses_correctly(self, mock_get_client):
        mock_get_client.return_value = _make_mock_anthropic()
        xlsx_bytes = self._make_xlsx([
            {"Member Phone": "7875551234", "HEDIS Measure": "COL", "Language": "en",
             "Member Name": "Test", "DOB": "1970-01-01", "Plan ID": "A"},
        ])
        rows, errors = parse_file(xlsx_bytes, filename="patients.xlsx")
        assert len(rows) == 1
        assert rows[0].phone_e164 == "+17875551234"
        assert rows[0].gap_type == GapType.COLORECTAL

    def test_empty_xlsx_raises(self):
        import openpyxl, io
        wb = openpyxl.Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        with pytest.raises(ValueError):
            parse_file(buf.getvalue(), filename="empty.xlsx")
