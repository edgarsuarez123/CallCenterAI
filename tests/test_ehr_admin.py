"""Tests for admin NextGen EHR endpoints (Feature 5)."""

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

os.environ.setdefault("PHI_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")


@pytest.mark.unit
class TestApptTypesPutRequest:
    def test_rejects_invalid_gap_key(self):
        from Clinic_app.Routes.admin import ApptTypesPutRequest

        with pytest.raises(ValidationError):
            ApptTypesPutRequest(mapping={"not_a_real_gap": "CODE"})

    def test_accepts_valid_gap_keys(self):
        from Clinic_app.Routes.admin import ApptTypesPutRequest

        m = ApptTypesPutRequest(
            mapping={"colorectal": "FIT", "kidney": "DM1"}
        )
        assert m.mapping["colorectal"] == "FIT"


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetEhrConfigHandler:
    async def test_returns_data_without_secrets(self):
        from Clinic_app.Routes.admin import get_ehr_config

        cid = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.nextgen_url = "https://nextgen.example/"
        mock_row.appt_type_mapping = {"colorectal": "FIT"}
        mock_row.connection_verified_at = None
        mock_row.created_at = datetime.now(timezone.utc)
        mock_row.updated_at = datetime.now(timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_row)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await get_ehr_config(cid, mock_db)
        assert resp.success
        assert resp.data["nextgen_url"] == "https://nextgen.example/"
        assert "password" not in str(resp.data)
        assert "username" not in str(resp.data)


@pytest.mark.unit
@pytest.mark.asyncio
class TestUpsertEhrConfigHandler:
    async def test_invalidates_selector_cache(self):
        from Clinic_app.Routes.admin import upsert_ehr_config, EhrConfigUpsertRequest

        cid = uuid.uuid4()
        mock_clinic = MagicMock()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_clinic)

        existing = MagicMock()
        existing.nextgen_url = "old"
        existing.nextgen_username_encrypted = b""
        existing.nextgen_password_encrypted = b""
        existing.appt_type_mapping = {}
        existing.updated_at = None

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none = MagicMock(return_value=existing)
        mock_db.execute = AsyncMock(return_value=mock_exec_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        req = EhrConfigUpsertRequest(
            nextgen_url="https://ng.example/",
            nextgen_username="user",
            nextgen_password="secret",
        )

        with patch("Clinic_app.Routes.admin.encrypt_phi", side_effect=lambda s: b"enc_" + s.encode()), patch(
            "Clinic_app.Routes.admin.invalidate_clinic_ehr_cache", new_callable=AsyncMock
        ) as inv:
            await upsert_ehr_config(cid, req, mock_db)
            inv.assert_awaited_once_with(cid)


@pytest.mark.unit
@pytest.mark.asyncio
class TestEhrTestCredentials:
    async def test_updates_verified_at_on_success(self):
        from Clinic_app.Routes.admin import ehr_test_credentials

        cid = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.connection_verified_at = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_row)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch(
            "Clinic_app.Routes.admin.playwright_ehr_service"
        ) as svc:
            svc.test_credentials = AsyncMock(return_value={"success": True})
            resp = await ehr_test_credentials(cid, mock_db)

        assert resp.data["success"] is True
        assert mock_row.connection_verified_at is not None
        mock_db.commit.assert_awaited()
