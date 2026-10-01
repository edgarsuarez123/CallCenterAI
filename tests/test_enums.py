# tests/test_enums.py
"""
Unit tests for Feature 2 enums.
Validates that all enum values match the PRD spec.
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
        # Core values — must always be present
        assert {
            "pending",
            "calling",
            "booked",
            "declined",
            "voicemail",
            "no_answer",
            "error",
            "exhausted",
        }.issubset(values)
        # Plan 013 additions
        assert {
            "order_agreed",
            "order_declined",
            "not_yet_eligible",
            "expired",
            "human_requested",
        }.issubset(values)

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
    def test_is_str_enum(self):
        assert isinstance(GapType.COLORECTAL, str)
        assert GapType.COLORECTAL == "colorectal"

    def test_plan_013_measures_present(self):
        """Verify the finalized Plan 013 gap type taxonomy is present."""
        expected = {
            "preventive_visit",
            "hospital_flu",
            "colorectal",
            "eye_exam",
            "breast_cancer",
            "kidney",
            "afr_cmp",
            "medication_review",
        }
        assert {g.value for g in GapType} == expected

    def test_count(self):
        """8 gap types total (medication_review excluded at parse; no generic fallback)."""
        assert len(GapType) == 8

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
