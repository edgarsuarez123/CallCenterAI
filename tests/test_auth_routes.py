# tests/test_auth_routes.py
"""
Unit tests for auth routes (Routes/auth.py) and admin staff endpoints.
All external calls (Google OAuth, DB) are mocked.
"""
import os
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Force values so tests stay deterministic even if database.load_dotenv() ran first
# (see Clinic_app/common/database.py) and populated GOOGLE_* from .env.
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-unit-tests-only"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/auth/google/callback"
os.environ["ADMIN_API_KEY"] = "test-admin-key"


def _make_mock_staff(clinic_id: uuid.UUID, role: str = "viewer", google_sub: str = "sub123"):
    """Helper: build a MagicMock that looks like a ClinicStaff ORM row."""
    staff = MagicMock()
    staff.id = uuid.uuid4()
    staff.clinic_id = clinic_id
    staff.google_sub = google_sub
    staff.email = "staff@clinic.com"
    staff.role = role
    staff.created_at = datetime.now(timezone.utc)
    return staff


@pytest.mark.unit
class TestGoogleLoginRedirect:
    def test_redirects_to_google(self):
        """GET /auth/google must return a 302 redirect to Google."""
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/google", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert "accounts.google.com" in location
        assert "test-client-id" in location
        assert "state=" in location

    def test_redirect_url_contains_required_params(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/google", follow_redirects=False)
        location = response.headers["location"]
        assert "response_type=code" in location
        assert "openid" in location


@pytest.mark.unit
class TestGoogleCallback:
    def _make_id_token(self, sub: str = "sub123", email: str = "staff@clinic.com") -> str:
        """Create a minimal Google-style ID token (unsigned — we skip verification)."""
        import jwt as pyjwt
        payload = {"sub": sub, "email": email, "aud": "test-client-id"}
        return pyjwt.encode(payload, "any-key", algorithm="HS256")

    def _valid_state(self) -> str:
        from Clinic_app.common.jwt import create_state_token
        return create_state_token()

    def test_invalid_state_returns_400(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/google/callback?code=abc&state=bad-state")
        app.dependency_overrides.clear()
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_STATE"

    def test_single_clinic_returns_scoped_token(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        clinic_id = uuid.uuid4()
        mock_staff = _make_mock_staff(clinic_id, role="admin")
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("Clinic_app.Routes.auth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch("Clinic_app.Routes.auth.extract_google_user", return_value=("sub123", "staff@clinic.com")), \
             patch("Clinic_app.Routes.auth.upsert_staff_email", new_callable=AsyncMock), \
             patch("Clinic_app.Routes.auth.get_staff_clinics", new_callable=AsyncMock, return_value=[mock_staff]):
            mock_exchange.return_value = {"id_token": self._make_id_token()}

            client = TestClient(app, raise_server_exceptions=False)
            state = self._valid_state()
            response = client.get(f"/auth/google/callback?code=authcode&state={state}")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "scoped"
        assert "token" in data
        assert data.get("requires_clinic_selection") is False

    def test_multiple_clinics_returns_unscoped_token(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        staff1 = _make_mock_staff(uuid.uuid4(), "admin")
        staff2 = _make_mock_staff(uuid.uuid4(), "viewer")
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("Clinic_app.Routes.auth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch("Clinic_app.Routes.auth.extract_google_user", return_value=("sub123", "staff@clinic.com")), \
             patch("Clinic_app.Routes.auth.upsert_staff_email", new_callable=AsyncMock), \
             patch("Clinic_app.Routes.auth.get_staff_clinics", new_callable=AsyncMock, return_value=[staff1, staff2]):
            mock_exchange.return_value = {"id_token": self._make_id_token()}

            client = TestClient(app, raise_server_exceptions=False)
            state = self._valid_state()
            response = client.get(f"/auth/google/callback?code=authcode&state={state}")

        app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "unscoped"
        assert data["requires_clinic_selection"] is True

    def test_zero_clinics_returns_403(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("Clinic_app.Routes.auth.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch("Clinic_app.Routes.auth.extract_google_user", return_value=("sub123", "e@e.com")), \
             patch("Clinic_app.Routes.auth.upsert_staff_email", new_callable=AsyncMock), \
             patch("Clinic_app.Routes.auth.get_staff_clinics", new_callable=AsyncMock, return_value=[]):
            mock_exchange.return_value = {"id_token": self._make_id_token()}

            client = TestClient(app, raise_server_exceptions=False)
            state = self._valid_state()
            response = client.get(f"/auth/google/callback?code=authcode&state={state}")

        app.dependency_overrides.clear()
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "NOT_PROVISIONED"


@pytest.mark.unit
class TestGetMe:
    def _scoped_token(self, clinic_id: uuid.UUID) -> str:
        from Clinic_app.common.jwt import create_scoped_token
        return create_scoped_token("sub123", "staff@clinic.com", clinic_id, "admin")

    def test_no_token_returns_401(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/me")
        assert response.status_code == 401

    def test_valid_token_returns_clinic_list(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app

        clinic_id = uuid.uuid4()
        mock_staff_row = _make_mock_staff(clinic_id, "admin")

        mock_clinic = MagicMock()
        mock_clinic.name = "Test Clinic"

        with patch("Clinic_app.Routes.auth.get_staff_clinics", new_callable=AsyncMock, return_value=[mock_staff_row]):
            client = TestClient(app, raise_server_exceptions=False)
            token = self._scoped_token(clinic_id)

            with patch("Clinic_app.Routes.auth.AsyncSession") as mock_session_class:
                mock_db = AsyncMock()
                mock_db.get = AsyncMock(return_value=mock_clinic)
                # Provide db via override
                from Clinic_app.common.database import get_db
                app.dependency_overrides[get_db] = lambda: mock_db

                response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["google_sub"] == "sub123"
        assert isinstance(data["clinics"], list)


@pytest.mark.unit
class TestSelectClinic:
    def _unscoped_token(self) -> str:
        from Clinic_app.common.jwt import create_unscoped_token
        return create_unscoped_token("sub123", "staff@clinic.com")

    def test_no_token_returns_401(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/auth/select-clinic", json={"clinic_id": str(uuid.uuid4())})
        assert response.status_code == 401

    def test_valid_membership_returns_scoped_token(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        clinic_id = uuid.uuid4()
        mock_staff = _make_mock_staff(clinic_id, "viewer")

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("Clinic_app.Routes.auth.get_staff_for_clinic", new_callable=AsyncMock, return_value=mock_staff):
            client = TestClient(app, raise_server_exceptions=False)
            token = self._unscoped_token()
            response = client.post(
                "/auth/select-clinic",
                json={"clinic_id": str(clinic_id)},
                headers={"Authorization": f"Bearer {token}"},
            )

        app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "scoped"

    def test_no_membership_returns_403(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("Clinic_app.Routes.auth.get_staff_for_clinic", new_callable=AsyncMock, return_value=None):
            client = TestClient(app, raise_server_exceptions=False)
            token = self._unscoped_token()
            response = client.post(
                "/auth/select-clinic",
                json={"clinic_id": str(uuid.uuid4())},
                headers={"Authorization": f"Bearer {token}"},
            )

        app.dependency_overrides.clear()
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ACCESS_DENIED"


@pytest.mark.unit
class TestAdminStaffEndpoints:
    def _admin_headers(self) -> dict:
        return {"X-Admin-Key": "test-admin-key"}

    def test_provision_staff_success(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        clinic_id = uuid.uuid4()
        mock_staff = _make_mock_staff(clinic_id, "viewer")
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("Clinic_app.Routes.admin.create_staff", new_callable=AsyncMock, return_value=mock_staff):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/admin/clinics/{clinic_id}/staff",
                json={"google_sub": "sub999", "email": "new@clinic.com", "role": "viewer"},
                headers=self._admin_headers(),
            )

        app.dependency_overrides.clear()
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True

    def test_provision_staff_missing_admin_key_returns_401(self):
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/admin/clinics/{uuid.uuid4()}/staff",
            json={"google_sub": "sub", "email": "e@e.com", "role": "viewer"},
        )
        assert response.status_code == 401

    def test_duplicate_staff_returns_409(self):
        from fastapi import HTTPException
        from fastapi.testclient import TestClient
        from Clinic_app.main import app
        from Clinic_app.common.database import get_db

        clinic_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_db.rollback = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        conflict = HTTPException(status_code=409, detail={"code": "ALREADY_PROVISIONED", "message": "Already exists"})
        with patch("Clinic_app.Routes.admin.create_staff", new_callable=AsyncMock, side_effect=conflict):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/admin/clinics/{clinic_id}/staff",
                json={"google_sub": "sub", "email": "e@e.com", "role": "viewer"},
                headers=self._admin_headers(),
            )

        app.dependency_overrides.clear()
        assert response.status_code == 409
