# tests/test_jwt.py
"""
Unit tests for JWT utilities in common/jwt.py.
All tests run without a real DB or network — purely in-process.
"""
import os
import time
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

# Set required env var before importing the module
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")


@pytest.mark.unit
class TestStateToken:
    def test_create_and_verify_round_trip(self):
        from Clinic_app.common.jwt import create_state_token, verify_state_token
        state = create_state_token()
        assert isinstance(state, str)
        assert verify_state_token(state) is True

    def test_tampered_state_fails(self):
        from Clinic_app.common.jwt import create_state_token, verify_state_token
        state = create_state_token()
        tampered = state[:-4] + "xxxx"
        assert verify_state_token(tampered) is False

    def test_garbage_string_fails(self):
        from Clinic_app.common.jwt import verify_state_token
        assert verify_state_token("not.a.token") is False

    def test_empty_string_fails(self):
        from Clinic_app.common.jwt import verify_state_token
        assert verify_state_token("") is False

    def test_expired_state_fails(self):
        """An expired state token must be rejected."""
        import jwt as pyjwt
        from Clinic_app.common.jwt import verify_state_token
        payload = {
            "nonce": "abc123",
            "type": "oauth_state",
            "iat": datetime.now(timezone.utc) - timedelta(seconds=400),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=100),
        }
        expired_token = pyjwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
        assert verify_state_token(expired_token) is False

    def test_wrong_type_fails(self):
        """A valid JWT with wrong type claim is rejected."""
        import jwt as pyjwt
        from Clinic_app.common.jwt import verify_state_token
        from datetime import timezone, timedelta
        payload = {
            "nonce": "abc",
            "type": "scoped",  # wrong type
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        token = pyjwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
        assert verify_state_token(token) is False


@pytest.mark.unit
class TestUnscopedToken:
    def test_create_and_decode(self):
        from Clinic_app.common.jwt import create_unscoped_token, decode_token
        token = create_unscoped_token("google_sub_123", "staff@clinic.com")
        result = decode_token(token)
        assert result.google_sub == "google_sub_123"
        assert result.email == "staff@clinic.com"
        assert result.clinic_id is None
        assert result.role is None
        assert result.token_type == "unscoped"

    def test_is_string(self):
        from Clinic_app.common.jwt import create_unscoped_token
        assert isinstance(create_unscoped_token("sub", "e@e.com"), str)


@pytest.mark.unit
class TestScopedToken:
    def test_create_and_decode(self):
        from Clinic_app.common.jwt import create_scoped_token, decode_token
        clinic_id = uuid.uuid4()
        token = create_scoped_token("google_sub_456", "admin@clinic.com", clinic_id, "admin")
        result = decode_token(token)
        assert result.google_sub == "google_sub_456"
        assert result.email == "admin@clinic.com"
        assert result.clinic_id == clinic_id
        assert result.role == "admin"
        assert result.token_type == "scoped"

    def test_viewer_role(self):
        from Clinic_app.common.jwt import create_scoped_token, decode_token
        clinic_id = uuid.uuid4()
        token = create_scoped_token("sub", "e@e.com", clinic_id, "viewer")
        result = decode_token(token)
        assert result.role == "viewer"

    def test_clinic_id_preserved_as_uuid(self):
        from Clinic_app.common.jwt import create_scoped_token, decode_token
        clinic_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        token = create_scoped_token("sub", "e@e.com", clinic_id, "admin")
        result = decode_token(token)
        assert result.clinic_id == clinic_id


@pytest.mark.unit
class TestDecodeToken:
    def test_expired_token_raises_401(self):
        import jwt as pyjwt
        from fastapi import HTTPException
        from Clinic_app.common.jwt import decode_token
        payload = {
            "sub": "sub123",
            "email": "e@e.com",
            "type": "scoped",
            "clinic_id": str(uuid.uuid4()),
            "role": "admin",
            "iat": datetime.now(timezone.utc) - timedelta(hours=10),
            "exp": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired = pyjwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_token(expired)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "TOKEN_EXPIRED"

    def test_tampered_token_raises_401(self):
        from fastapi import HTTPException
        from Clinic_app.common.jwt import create_unscoped_token, decode_token
        token = create_unscoped_token("sub", "e@e.com")
        tampered = token[:-6] + "xxxxxx"
        with pytest.raises(HTTPException) as exc_info:
            decode_token(tampered)
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_401(self):
        import jwt as pyjwt
        from fastapi import HTTPException
        from Clinic_app.common.jwt import decode_token
        payload = {
            "sub": "sub",
            "email": "e@e.com",
            "type": "unscoped",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_invalid_type_raises_401(self):
        import jwt as pyjwt
        from fastapi import HTTPException
        from Clinic_app.common.jwt import decode_token
        payload = {
            "sub": "sub",
            "email": "e@e.com",
            "type": "oauth_state",  # not a staff token type
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        }
        token = pyjwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestGetCurrentStaff:
    @pytest.mark.asyncio
    async def test_valid_token_returns_staff_token(self):
        from fastapi.security import HTTPAuthorizationCredentials
        from Clinic_app.common.jwt import create_unscoped_token, get_current_staff
        token = create_unscoped_token("sub123", "staff@clinic.com")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        result = await get_current_staff(credentials=creds)
        assert result.google_sub == "sub123"

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_401(self):
        from fastapi import HTTPException
        from Clinic_app.common.jwt import get_current_staff
        with pytest.raises(HTTPException) as exc_info:
            await get_current_staff(credentials=None)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestRequireScopedStaff:
    @pytest.mark.asyncio
    async def test_scoped_token_passes(self):
        from Clinic_app.common.jwt import StaffToken, require_scoped_staff
        clinic_id = uuid.uuid4()
        staff = StaffToken(
            google_sub="sub",
            email="e@e.com",
            clinic_id=clinic_id,
            role="admin",
            token_type="scoped",
        )
        result = await require_scoped_staff(staff=staff)
        assert result.clinic_id == clinic_id

    @pytest.mark.asyncio
    async def test_unscoped_token_raises_403(self):
        from fastapi import HTTPException
        from Clinic_app.common.jwt import StaffToken, require_scoped_staff
        staff = StaffToken(
            google_sub="sub",
            email="e@e.com",
            clinic_id=None,
            role=None,
            token_type="unscoped",
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_scoped_staff(staff=staff)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "CLINIC_NOT_SELECTED"
