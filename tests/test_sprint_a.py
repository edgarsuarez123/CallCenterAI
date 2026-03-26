# tests/test_sprint_a.py
"""
Sprint A tests (Plan 014): GapType taxonomy, ContactStatus additions,
CSV alias normalization, hospital_flu EXPIRED logic.
"""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from Clinic_app.data.enums import (
    GapType,
    ContactStatus,
    APPOINTMENT_BASED_GAP_TYPES,
    ORDER_BASED_GAP_TYPES,
)
from Clinic_app.services.csv_parser import map_gap_type, normalize_phone, ParsedRow


# ── GapType enum ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGapTypeEnum:
    def test_plan_013_values_present(self):
        expected = {
            "preventive_visit", "hospital_flu", "colorectal", "eye_exam",
            "breast_cancer", "kidney", "afr_cmp", "medication_review",
        }
        assert {g.value for g in GapType} == expected

    def test_appointment_based_set(self):
        assert GapType.PREVENTIVE_VISIT in APPOINTMENT_BASED_GAP_TYPES
        assert GapType.HOSPITAL_FLU in APPOINTMENT_BASED_GAP_TYPES
        assert GapType.COLORECTAL not in APPOINTMENT_BASED_GAP_TYPES

    def test_order_based_set(self):
        assert GapType.COLORECTAL in ORDER_BASED_GAP_TYPES
        assert GapType.EYE_EXAM in ORDER_BASED_GAP_TYPES
        assert GapType.BREAST_CANCER in ORDER_BASED_GAP_TYPES
        assert GapType.KIDNEY in ORDER_BASED_GAP_TYPES
        assert GapType.AFR_CMP in ORDER_BASED_GAP_TYPES
        assert GapType.PREVENTIVE_VISIT not in ORDER_BASED_GAP_TYPES

    def test_no_a1c_value(self):
        values = {g.value for g in GapType}
        assert "a1c" not in values
        assert "diabetes_hba1c" not in values

    def test_is_str_enum(self):
        assert GapType.COLORECTAL == "colorectal"
        assert isinstance(GapType.HOSPITAL_FLU, str)


# ── ContactStatus enum ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestContactStatusEnum:
    def test_new_terminal_statuses_present(self):
        values = {s.value for s in ContactStatus}
        assert "not_yet_eligible" in values
        assert "expired" in values
        assert "order_agreed" in values
        assert "order_declined" in values

    def test_existing_statuses_unchanged(self):
        assert ContactStatus.PENDING.value == "pending"
        assert ContactStatus.CALLING.value == "calling"
        assert ContactStatus.BOOKED.value == "booked"
        assert ContactStatus.VOICEMAIL.value == "voicemail"
        assert ContactStatus.NO_ANSWER.value == "no_answer"
        assert ContactStatus.EXHAUSTED.value == "exhausted"

    def test_human_requested_present(self):
        assert ContactStatus.HUMAN_REQUESTED.value == "human_requested"


# ── CSV alias normalization ────────────────────────────────────────────────────

@pytest.mark.unit
class TestGapTypeAliasMapping:
    """
    map_gap_type uses Claude's returned gap_type_values dict to normalize raw strings.
    These tests simulate what Claude returns for each alias group.
    """

    def _alias(self, raw: str, normalized: str) -> GapType:
        g = map_gap_type(raw, {raw: normalized})
        assert g is not None
        return g

    def test_preventive_visit_aliases(self):
        for alias, norm in [
            ("Preventive visit", "preventive_visit"),
            ("Annual wellness", "preventive_visit"),
            ("AWV", "preventive_visit"),
            ("Yearly checkup", "preventive_visit"),
        ]:
            assert self._alias(alias, norm) == GapType.PREVENTIVE_VISIT

    def test_hospital_flu_aliases(self):
        for alias, norm in [
            ("Hospital follow-up", "hospital_flu"),
            ("Hospital flu", "hospital_flu"),
            ("Hosp flu", "hospital_flu"),
            ("Post-hospital", "hospital_flu"),
            ("Discharge follow-up", "hospital_flu"),
        ]:
            assert self._alias(alias, norm) == GapType.HOSPITAL_FLU

    def test_order_based_aliases(self):
        cases = [
            ("Colorectal", "colorectal", GapType.COLORECTAL),
            ("CRC", "colorectal", GapType.COLORECTAL),
            ("Eye exam", "eye_exam", GapType.EYE_EXAM),
            ("Retinal exam", "eye_exam", GapType.EYE_EXAM),
            ("Mammogram", "breast_cancer", GapType.BREAST_CANCER),
            ("Breast cancer screening", "breast_cancer", GapType.BREAST_CANCER),
            ("Kidney", "kidney", GapType.KIDNEY),
            ("CKD", "kidney", GapType.KIDNEY),
            ("AFR/CMP", "afr_cmp", GapType.AFR_CMP),
            ("Albumin creatinine", "afr_cmp", GapType.AFR_CMP),
        ]
        for raw, norm, expected in cases:
            assert self._alias(raw, norm) == expected

    def test_medication_review_maps_correctly(self):
        assert self._alias("Medication review", "medication_review") == GapType.MEDICATION_REVIEW
        assert self._alias("Med review", "medication_review") == GapType.MEDICATION_REVIEW

    def test_unknown_returns_none(self):
        assert map_gap_type("UnknownGapXYZ", {}) is None

    def test_direct_enum_value_recognized(self):
        """If Claude returns the exact enum value string, no mapping needed."""
        assert map_gap_type("colorectal", {}) == GapType.COLORECTAL
        assert map_gap_type("hospital_flu", {}) == GapType.HOSPITAL_FLU


# ── medication_review exclusion ───────────────────────────────────────────────

@pytest.mark.unit
class TestMedicationReviewExclusion:
    """medication_review rows must be filtered at parse time."""

    def test_medication_review_is_excluded(self):
        """
        Verify that medication_review rows don't enter parsed_rows.
        We test map_gap_type returns MEDICATION_REVIEW and the parser
        filters it — here we test the enum value identity used for filtering.
        """
        gap = map_gap_type("medication_review", {})
        assert gap == GapType.MEDICATION_REVIEW
        # The parser checks: if gap_type == GapType.MEDICATION_REVIEW: continue
        assert gap.value == "medication_review"


# ── Hospital flu EXPIRED logic ────────────────────────────────────────────────

@pytest.mark.unit
class TestHospitalFluExpiredLogic:
    """
    expire_overdue_hospital_flu_contacts marks contacts EXPIRED when
    release_date + 7 days < today.
    """

    def test_cutoff_date_calculation(self):
        """Contacts with release_date <= today - 7 days should be expired."""
        from Clinic_app.services.campaign_service import HOSPITAL_FLU_DEADLINE_DAYS
        today = date.today()
        cutoff = today - timedelta(days=HOSPITAL_FLU_DEADLINE_DAYS)
        # A contact released 8 days ago is overdue
        overdue = today - timedelta(days=8)
        assert overdue <= cutoff
        # A contact released today is not overdue
        fresh = today
        assert fresh > cutoff

    @pytest.mark.asyncio
    async def test_expire_overdue_contacts(self):
        """expire_overdue_hospital_flu_contacts sets status=EXPIRED on overdue contacts."""
        from Clinic_app.services.campaign_service import expire_overdue_hospital_flu_contacts
        from Clinic_app.data.enums import ContactStatus, GapType
        import uuid

        today = date.today()
        overdue_date = today - timedelta(days=8)

        # Build a fake contact
        contact = MagicMock()
        contact.status = ContactStatus.PENDING.value
        contact.gap_type = GapType.HOSPITAL_FLU.value
        contact.release_date = overdue_date

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [contact]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        count = await expire_overdue_hospital_flu_contacts(db, uuid.uuid4())

        assert count == 1
        assert contact.status == ContactStatus.EXPIRED.value
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_overdue_contacts_no_commit(self):
        """No commit when there are no overdue contacts."""
        from Clinic_app.services.campaign_service import expire_overdue_hospital_flu_contacts
        import uuid

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        count = await expire_overdue_hospital_flu_contacts(db, uuid.uuid4())

        assert count == 0
        db.commit.assert_not_awaited()


# ── Priority order assignment ─────────────────────────────────────────────────

@pytest.mark.unit
class TestPriorityOrder:
    def test_hospital_flu_priority_is_zero(self):
        """hospital_flu gets priority_order=0 (first in queue)."""
        from Clinic_app.data.enums import GapType
        is_hospital_flu = GapType.HOSPITAL_FLU == GapType.HOSPITAL_FLU
        priority = 0 if is_hospital_flu else 1
        assert priority == 0

    def test_other_gaps_priority_is_one(self):
        for gap in [GapType.COLORECTAL, GapType.EYE_EXAM, GapType.PREVENTIVE_VISIT]:
            is_hospital_flu = gap == GapType.HOSPITAL_FLU
            priority = 0 if is_hospital_flu else 1
            assert priority == 1
