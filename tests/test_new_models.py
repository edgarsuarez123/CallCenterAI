# tests/test_new_models.py
"""
Unit tests for Feature 2 ORM models.
Tests model instantiation, field defaults, repr, and relationship declarations.
No real DB connection — uses SQLAlchemy in-memory SQLite for structural tests.
"""
import uuid
import pytest
from datetime import datetime, timezone


@pytest.mark.unit
class TestClinicStaffModel:
    def test_import(self):
        from Clinic_app.data.models.clinic_staff import ClinicStaff
        assert ClinicStaff.__tablename__ == "clinic_staff"

    def test_instantiation_with_required_fields(self):
        from Clinic_app.data.models.clinic_staff import ClinicStaff
        clinic_id = uuid.uuid4()
        staff = ClinicStaff(
            clinic_id=clinic_id,
            google_sub="123456789",
            email="doctor@clinic.com",
            role="viewer",
        )
        assert staff.clinic_id == clinic_id
        assert staff.google_sub == "123456789"
        assert staff.email == "doctor@clinic.com"
        assert staff.role == "viewer"

    def test_role_column_default(self):
        """Column-level default for role is 'viewer' (applied at INSERT, not Python instantiation)."""
        from Clinic_app.data.models.clinic_staff import ClinicStaff
        col = ClinicStaff.__table__.columns["role"]
        assert col.default.arg == "viewer"

    def test_repr(self):
        from Clinic_app.data.models.clinic_staff import ClinicStaff
        staff = ClinicStaff(
            id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            google_sub="sub123",
            email="x@x.com",
            role="admin",
        )
        r = repr(staff)
        assert "ClinicStaff" in r
        assert "admin" in r

    def test_unique_constraint_declared(self):
        from Clinic_app.data.models.clinic_staff import ClinicStaff
        constraint_names = {
            c.name for c in ClinicStaff.__table_args__
            if hasattr(c, 'name') and c.name
        }
        assert "uq_clinic_staff_clinic_sub" in constraint_names


@pytest.mark.unit
class TestCampaignModel:
    def test_import(self):
        from Clinic_app.data.models.campaign import Campaign
        assert Campaign.__tablename__ == "campaign"

    def test_defaults(self):
        """Column-level defaults applied at INSERT — verify via table metadata."""
        from Clinic_app.data.models.campaign import Campaign
        cols = {c.name: c for c in Campaign.__table__.columns}
        assert cols["status"].default.arg == "pending"
        assert cols["total_contacts"].default.arg == 0
        assert cols["called_count"].default.arg == 0
        assert cols["booked_count"].default.arg == 0
        assert cols["failed_count"].default.arg == 0
        assert cols["calling_hours_start"].default.arg == "09:00"
        assert cols["calling_hours_end"].default.arg == "18:00"
        assert cols["campaign_concurrency_limit"].default.arg == 3
        assert cols["voicemail_retry_hours"].default.arg == 4
        assert cols["no_answer_retry_hours"].default.arg == 2
        assert cols["error_retry_hours"].default.arg == 24
        assert cols["max_attempts"].default.arg == 3
        assert cols["created_by"].nullable is True

    def test_repr(self):
        from Clinic_app.data.models.campaign import Campaign
        campaign = Campaign(
            id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            name="Test Campaign",
        )
        r = repr(campaign)
        assert "Campaign" in r
        assert "Test Campaign" in r

    def test_check_constraint_declared(self):
        from Clinic_app.data.models.campaign import Campaign
        constraint_names = {
            c.name for c in Campaign.__table_args__
            if hasattr(c, 'name') and c.name
        }
        assert "check_campaign_counts_sane" in constraint_names


@pytest.mark.unit
class TestCampaignContactModel:
    def test_import(self):
        from Clinic_app.data.models.campaign_contact import CampaignContact
        assert CampaignContact.__tablename__ == "campaign_contact"

    def test_defaults(self):
        """Column-level defaults applied at INSERT — verify via table metadata."""
        from Clinic_app.data.models.campaign_contact import CampaignContact
        cols = {c.name: c for c in CampaignContact.__table__.columns}
        assert cols["status"].default.arg == "pending"
        assert cols["attempt_count"].default.arg == 0
        assert cols["preferred_language"].default.arg == "en"
        assert cols["last_attempted_at"].nullable is True
        assert cols["next_attempt_after"].nullable is True
        assert cols["ehr_appointment_id"].nullable is True

    def test_phone_stored_as_bytes(self):
        from Clinic_app.data.models.campaign_contact import CampaignContact
        contact = CampaignContact(
            campaign_id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            phone_encrypted=b"\xde\xad\xbe\xef",
            phone_hash="b" * 64,
            gap_type="colorectal_cancer_screening",
        )
        assert isinstance(contact.phone_encrypted, bytes)

    def test_phone_hash_is_64_chars(self):
        from Clinic_app.data.models.campaign_contact import CampaignContact
        hash_value = "c" * 64
        contact = CampaignContact(
            campaign_id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            phone_encrypted=b"\x00",
            phone_hash=hash_value,
            gap_type="depression_screening",
        )
        assert len(contact.phone_hash) == 64

    def test_repr(self):
        from Clinic_app.data.models.campaign_contact import CampaignContact
        contact = CampaignContact(
            id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            phone_encrypted=b"\x00",
            phone_hash="d" * 64,
            gap_type="well_child_visit",
            status="pending",
            attempt_count=0,
        )
        r = repr(contact)
        assert "CampaignContact" in r
        assert "pending" in r


@pytest.mark.unit
class TestCampaignAuditModel:
    def test_import(self):
        from Clinic_app.data.models.campaign_audit import CampaignAudit
        assert CampaignAudit.__tablename__ == "campaign_audit"

    def test_instantiation(self):
        from Clinic_app.data.models.campaign_audit import CampaignAudit
        audit = CampaignAudit(
            campaign_contact_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            retell_call_id="retell_abc123",
            outcome="booked",
            attempt_number=1,
            called_at=datetime.now(timezone.utc),
        )
        assert audit.outcome == "booked"
        assert audit.attempt_number == 1
        assert audit.patient_name_encrypted is None   # nullable
        assert audit.call_summary_encrypted is None   # nullable
        assert audit.ehr_appointment_id is None       # nullable

    def test_phi_fields_are_nullable(self):
        """patient_name_encrypted and call_summary_encrypted must be nullable (webhook edge cases)."""
        from Clinic_app.data.models.campaign_audit import CampaignAudit
        col_map = {c.name: c for c in CampaignAudit.__table__.columns}
        assert col_map["patient_name_encrypted"].nullable is True
        assert col_map["call_summary_encrypted"].nullable is True

    def test_repr(self):
        from Clinic_app.data.models.campaign_audit import CampaignAudit
        audit = CampaignAudit(
            id=uuid.uuid4(),
            campaign_contact_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            clinic_id=uuid.uuid4(),
            retell_call_id="call_xyz",
            outcome="voicemail",
            attempt_number=2,
            called_at=datetime.now(timezone.utc),
        )
        r = repr(audit)
        assert "CampaignAudit" in r
        assert "voicemail" in r


@pytest.mark.unit
class TestClinicEHRConfigModel:
    def test_import(self):
        from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
        assert ClinicEHRConfig.__tablename__ == "clinic_ehr_config"

    def test_instantiation(self):
        from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
        config = ClinicEHRConfig(
            clinic_id=uuid.uuid4(),
            nextgen_url="https://nextgen.example.com",
            nextgen_username_encrypted=b"\x01\x02",
            nextgen_password_encrypted=b"\x03\x04",
        )
        assert config.nextgen_url == "https://nextgen.example.com"
        assert config.connection_verified_at is None  # not yet verified

    def test_appt_type_mapping_default_is_empty_dict(self):
        """Column default is dict callable — produces {} at INSERT time."""
        from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
        col = ClinicEHRConfig.__table__.columns["appt_type_mapping"]
        # SQLAlchemy wraps callable defaults as context-aware; verify the arg is the dict callable
        assert callable(col.default.arg) and col.default.arg.__name__ == "dict"

    def test_appt_type_mapping_accepts_dict(self):
        from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
        mapping = {"colorectal_cancer_screening": "PREV", "diabetes_hba1c": "DM_A1C"}
        config = ClinicEHRConfig(
            clinic_id=uuid.uuid4(),
            nextgen_url="https://x.com",
            nextgen_username_encrypted=b"\x00",
            nextgen_password_encrypted=b"\x00",
            appt_type_mapping=mapping,
        )
        assert config.appt_type_mapping["colorectal_cancer_screening"] == "PREV"

    def test_credentials_stored_as_bytes(self):
        from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
        config = ClinicEHRConfig(
            clinic_id=uuid.uuid4(),
            nextgen_url="https://x.com",
            nextgen_username_encrypted=b"\xde\xad",
            nextgen_password_encrypted=b"\xbe\xef",
        )
        assert isinstance(config.nextgen_username_encrypted, bytes)
        assert isinstance(config.nextgen_password_encrypted, bytes)

    def test_repr(self):
        from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
        clinic_id = uuid.uuid4()
        config = ClinicEHRConfig(
            clinic_id=clinic_id,
            nextgen_url="https://x.com",
            nextgen_username_encrypted=b"\x00",
            nextgen_password_encrypted=b"\x00",
        )
        r = repr(config)
        assert "ClinicEHRConfig" in r


@pytest.mark.unit
class TestClinicIntegrationHEDISColumns:
    """Verify the 9 new columns were added to the existing ClinicIntegration model."""

    def test_new_columns_exist(self):
        from Clinic_app.data.models.clinic_integration import ClinicIntegration
        col_names = {c.name for c in ClinicIntegration.__table__.columns}
        hedis_cols = {
            "timezone", "calling_hours_start", "calling_hours_end",
            "campaign_concurrency_limit", "voicemail_retry_hours",
            "no_answer_retry_hours", "error_retry_hours",
            "max_attempts", "retell_outbound_number",
        }
        assert hedis_cols.issubset(col_names)

    def test_defaults(self):
        """Column-level defaults applied at INSERT — verify via table metadata."""
        from Clinic_app.data.models.clinic_integration import ClinicIntegration
        cols = {c.name: c for c in ClinicIntegration.__table__.columns}
        assert cols["timezone"].default.arg == "America/New_York"
        assert cols["calling_hours_start"].default.arg == "09:00"
        assert cols["calling_hours_end"].default.arg == "18:00"
        assert cols["campaign_concurrency_limit"].default.arg == 3
        assert cols["voicemail_retry_hours"].default.arg == 4
        assert cols["no_answer_retry_hours"].default.arg == 2
        assert cols["error_retry_hours"].default.arg == 24
        assert cols["max_attempts"].default.arg == 3
        assert cols["retell_outbound_number"].nullable is True


@pytest.mark.unit
class TestModelsInitExportsAll:
    """Verify __init__.py exports all 5 new models."""

    def test_all_hedis_models_exported(self):
        from Clinic_app.data import models
        for name in ("ClinicStaff", "Campaign", "CampaignContact", "CampaignAudit", "ClinicEHRConfig"):
            assert hasattr(models, name), f"{name} not exported from data.models"
