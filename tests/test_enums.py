# tests/test_enums.py
"""
Unit tests for Feature 2 enums.
Validates that all enum values match the PRD spec and that critical
members exist (e.g., GapType.OTHER fallback for Claude CSV parsing).
"""
import pytest
from Clinic_app.data.enums import (
    CampaignStatus,
    ContactStatus,
    GapType,
    # Existing enums — verify they haven't been broken
    BookingStatus,
    CallStatus,
)


@pytest.mark.unit
class TestCampaignStatus:
    def test_all_values_present(self):
        values = {s.value for s in CampaignStatus}
        assert values == {"pending", "active", "paused", "completed", "canceled"}

    def test_is_str_enum(self):
        assert isinstance(CampaignStatus.ACTIVE, str)
        assert CampaignStatus.ACTIVE == "active"

    def test_pending_is_default_start(self):
        """PENDING is the initial state — must exist."""
        assert CampaignStatus.PENDING.value == "pending"

    def test_terminal_states(self):
        """COMPLETED and CANCELED are terminal — worker stops on these."""
        assert CampaignStatus.COMPLETED.value == "completed"
        assert CampaignStatus.CANCELED.value == "canceled"


@pytest.mark.unit
class TestContactStatus:
    def test_all_values_present(self):
        values = {s.value for s in ContactStatus}
        assert values == {
            "pending", "calling", "booked", "declined",
            "voicemail", "no_answer", "error", "exhausted",
        }

    def test_is_str_enum(self):
        assert isinstance(ContactStatus.BOOKED, str)
        assert ContactStatus.BOOKED == "booked"

    def test_retryable_states(self):
        """VOICEMAIL, NO_ANSWER, ERROR are retryable — must exist."""
        assert ContactStatus.VOICEMAIL.value == "voicemail"
        assert ContactStatus.NO_ANSWER.value == "no_answer"
        assert ContactStatus.ERROR.value == "error"

    def test_terminal_states(self):
        """BOOKED, DECLINED, EXHAUSTED are terminal — no more retries."""
        assert ContactStatus.BOOKED.value == "booked"
        assert ContactStatus.DECLINED.value == "declined"
        assert ContactStatus.EXHAUSTED.value == "exhausted"

    def test_calling_is_in_progress(self):
        assert ContactStatus.CALLING.value == "calling"


@pytest.mark.unit
class TestGapType:
    def test_other_fallback_exists(self):
        """GapType.OTHER must exist — prevents Claude CSV parsing from throwing on unknown measures."""
        assert GapType.OTHER.value == "other"

    def test_is_str_enum(self):
        assert isinstance(GapType.DIABETES_HBA1C, str)
        assert GapType.DIABETES_HBA1C == "diabetes_hba1c"

    def test_core_hedis_measures_present(self):
        """Verify the measures most common in NextGen primary care clinics are present."""
        expected = {
            "colorectal_cancer_screening",
            "breast_cancer_screening",
            "cervical_cancer_screening",
            "diabetes_hba1c",
            "diabetes_eye_exam",
            "diabetes_nephropathy",
            "hypertension_control",
            "depression_screening",
            "well_child_visit",
            "adolescent_well_care",
            "adult_bmi_assessment",
            "medication_adherence_diabetes",
            "medication_adherence_hypertension",
            "other",
        }
        actual = {g.value for g in GapType}
        assert expected == actual

    def test_count(self):
        """14 gap types total (13 measures + OTHER)."""
        assert len(GapType) == 14

    def test_values_are_snake_case(self):
        """All values must be snake_case — used as JSONB keys in clinic_ehr_config."""
        for gap in GapType:
            assert gap.value == gap.value.lower()
            assert " " not in gap.value


@pytest.mark.unit
class TestExistingEnumsUnbroken:
    """Smoke test that adding new enums didn't break existing ones."""

    def test_booking_status_intact(self):
        values = {s.value for s in BookingStatus}
        assert "tentative" in values
        assert "confirmed" in values
        assert "canceled" in values

    def test_call_status_intact(self):
        values = {s.value for s in CallStatus}
        assert "active" in values
        assert "ended" in values
