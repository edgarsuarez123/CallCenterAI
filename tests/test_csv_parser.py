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
    _try_direct_header_mapping,
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

    def test_unknown_returns_none(self):
        assert map_gap_type("UNKNOWN_MEASURE_XYZ", {}) is None

    def test_empty_returns_none(self):
        assert map_gap_type("", {}) is None


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

    def test_valid_csv_parses_correctly(self):
        # Uses canonical GapType values — direct header mapping handles this without Claude
        csv_bytes = self._make_csv(
            [
                {
                    "Member Phone": "7875551234",
                    "HEDIS Measure": "colorectal",
                    "Language": "es",
                    "Member Name": "Juan Perez",
                    "DOB": "1970-01-01",
                    "Plan ID": "ABC",
                },
                {
                    "Member Phone": "7875559999",
                    "HEDIS Measure": "kidney",
                    "Language": "en",
                    "Member Name": "Maria Lopez",
                    "DOB": "1980-06-15",
                    "Plan ID": "XYZ",
                },
            ]
        )
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 2
        assert len(errors) == 0
        assert rows[0].phone_e164 == "+17875551234"
        assert rows[0].gap_type == GapType.COLORECTAL
        assert rows[0].language == "es"
        assert rows[0].patient_name == "Juan Perez"
        assert rows[1].gap_type == GapType.KIDNEY

    def test_bad_phone_goes_to_errors_not_raises(self):
        csv_bytes = self._make_csv(
            [
                {
                    "Member Phone": "NOT_A_PHONE",
                    "HEDIS Measure": "colorectal",
                    "Language": "en",
                    "Member Name": "Test",
                    "DOB": "",
                    "Plan ID": "",
                },
            ]
        )
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 0
        assert len(errors) == 1
        assert "NOT_A_PHONE" in errors[0].reason or errors[0].row_number == 2

    def test_unrecognized_gap_type_is_parse_error(self):
        csv_bytes = self._make_csv(
            [
                {
                    "Member Phone": "7875551234",
                    "HEDIS Measure": "UNKNOWN_GAP",
                    "Language": "en",
                    "Member Name": "",
                    "DOB": "",
                    "Plan ID": "",
                },
            ]
        )
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 0
        assert len(errors) == 1
        assert errors[0].row_number == 2
        assert "Unrecognized gap type" in errors[0].reason

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_file(b"", filename="empty.csv")

    def test_mixed_valid_and_invalid_rows(self):
        csv_bytes = self._make_csv(
            [
                {
                    "Member Phone": "7875551234",
                    "HEDIS Measure": "colorectal",
                    "Language": "en",
                    "Member Name": "",
                    "DOB": "",
                    "Plan ID": "",
                },
                {
                    "Member Phone": "BADINPUT",
                    "HEDIS Measure": "colorectal",
                    "Language": "en",
                    "Member Name": "",
                    "DOB": "",
                    "Plan ID": "",
                },
                {
                    "Member Phone": "7875559999",
                    "HEDIS Measure": "eye_exam",
                    "Language": "es",
                    "Member Name": "",
                    "DOB": "",
                    "Plan ID": "",
                },
            ]
        )
        rows, errors = parse_file(csv_bytes, filename="patients.csv")
        assert len(rows) == 2
        assert len(errors) == 1

    def test_pipe_delimited_csv(self):
        csv_bytes = self._make_csv(
            [
                {
                    "Member Phone": "7875551234",
                    "HEDIS Measure": "colorectal",
                    "Language": "en",
                    "Member Name": "Test",
                    "DOB": "",
                    "Plan ID": "",
                },
            ],
            delimiter="|",
        )
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

    def test_valid_xlsx_parses_correctly(self):
        xlsx_bytes = self._make_xlsx(
            [
                {
                    "Member Phone": "7875551234",
                    "HEDIS Measure": "colorectal",
                    "Language": "en",
                    "Member Name": "Test",
                    "DOB": "1970-01-01",
                    "Plan ID": "A",
                },
            ]
        )
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


# ── _try_direct_header_mapping ─────────────────────────────────────────────────


@pytest.mark.unit
class TestDirectHeaderMapping:
    def _headers_and_samples(self, headers: list[str], gap_vals: list[str]) -> tuple:
        sample = [[v if h == headers[-1] else "7875551234" for h in headers] for v in gap_vals]
        return headers, sample

    def test_standard_headers_recognized(self):
        headers = ["Member Phone", "HEDIS Measure"]
        sample = [["7875551234", "colorectal"]]
        result = _try_direct_header_mapping(headers, sample)
        assert result is not None
        assert result["column_mapping"]["Member Phone"] == "phone"
        assert result["column_mapping"]["HEDIS Measure"] == "gap_type"

    def test_lowercase_and_underscore_headers_recognized(self):
        headers = ["phone_number", "care_gap"]
        sample = [["7875551234", "preventive_visit"]]
        result = _try_direct_header_mapping(headers, sample)
        assert result is not None
        assert result["column_mapping"]["phone_number"] == "phone"
        assert result["column_mapping"]["care_gap"] == "gap_type"

    def test_missing_phone_returns_none(self):
        headers = ["Patient Name", "HEDIS Measure"]
        sample = [["Juan", "colorectal"]]
        assert _try_direct_header_mapping(headers, sample) is None

    def test_missing_gap_type_returns_none(self):
        headers = ["Member Phone", "Patient Name"]
        sample = [["7875551234", "Juan"]]
        assert _try_direct_header_mapping(headers, sample) is None

    def test_gap_type_alias_resolved(self):
        headers = ["Member Phone", "HEDIS Measure"]
        # "mammogram" is an alias — not a valid GapType value directly
        sample = [["7875551234", "mammogram"]]
        result = _try_direct_header_mapping(headers, sample)
        assert result is not None
        assert result["gap_type_values"]["mammogram"] == "breast_cancer"

    def test_canonical_gap_value_not_added_to_gap_type_values(self):
        # "colorectal" is already a valid GapType — no alias entry needed
        headers = ["Member Phone", "HEDIS Measure"]
        sample = [["7875551234", "colorectal"]]
        result = _try_direct_header_mapping(headers, sample)
        assert result is not None
        assert "colorectal" not in result["gap_type_values"]

    def test_unrecognized_gap_value_not_added(self):
        headers = ["Member Phone", "HEDIS Measure"]
        sample = [["7875551234", "TOTALLY_UNKNOWN"]]
        result = _try_direct_header_mapping(headers, sample)
        assert result is not None
        assert "TOTALLY_UNKNOWN" not in result["gap_type_values"]

    def test_parse_file_uses_direct_mapping_for_standard_headers(self):
        # No Claude mock needed — direct mapping should succeed
        import io as _io

        csv_content = "Member Phone,Care Gap\n7875551234,preventive_visit\n"
        rows, errors = parse_file(csv_content.encode(), filename="test.csv")
        assert len(rows) == 1
        assert rows[0].gap_type == GapType.PREVENTIVE_VISIT

    def test_parse_file_falls_through_to_claude_for_unknown_headers(self):
        # Headers not in alias table → direct mapping returns None → Claude called
        from unittest.mock import patch, MagicMock
        import json

        mock_resp = {
            "column_mapping": {"Mbr_Ph": "phone", "Measure_Cd": "gap_type"},
            "gap_type_values": {"COL": "colorectal"},
        }
        mock_content = MagicMock()
        mock_content.text = json.dumps(mock_resp)
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch(
            "Clinic_app.services.csv_parser._get_anthropic_client", return_value=mock_client
        ):
            csv_content = "Mbr_Ph,Measure_Cd\n7875551234,COL\n"
            rows, errors = parse_file(csv_content.encode(), filename="test.csv")
        assert len(rows) == 1
        assert rows[0].gap_type == GapType.COLORECTAL
