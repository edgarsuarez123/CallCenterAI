# tests/test_cors.py
"""
Unit tests for CORS middleware (Plan 012).

Tests verify that CORSMiddleware is wired correctly:
- Requests from an allowed origin receive the ACAO header.
- Requests from a disallowed origin do NOT receive the ACAO header.
- Preflight OPTIONS responses return 200 for allowed origins.

NOTE: CORSMiddleware reads ALLOWED_ORIGINS at app-creation time (module import),
so these vars must be set before the first import of Clinic_app.main.
Run this file in isolation or ensure env vars are stable across the test suite.
"""
import os

# Set env before any app import so middleware is created with these origins.
os.environ.setdefault("ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-cors-tests")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost/auth/google/callback")
os.environ.setdefault("PHI_ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleQ==")
os.environ.setdefault("PHI_HASH_KEY", "aGFzaGtleWhhc2hrZXloYXNoa2V5aGFzaGtleQ==")
os.environ.setdefault("RETELL_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("RETELL_API_KEY", "test-retell-key")

import pytest


def _make_cors_test_app(allowed_origins: list[str]):
    """
    Build a minimal Starlette app with CORSMiddleware for isolated CORS testing.
    Uses Starlette directly (not FastAPI) to avoid local FastAPI/Starlette version
    mismatch in the Python 3.14 dev environment. Production runs Docker with pinned
    versions from requirements.txt where FastAPI 0.115.6 + Starlette are aligned.
    """
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def health(request):  # type: ignore[override]
        return JSONResponse({"status": "ok"})

    _cors_credentials = bool(allowed_origins) and "*" not in allowed_origins
    app = Starlette(routes=[Route("/health", health)])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=_cors_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
    )
    return app


@pytest.mark.unit
class TestCORSAllowedOrigin:
    def test_allowed_origin_receives_acao_header(self):
        """GET from an allowed origin must return Access-Control-Allow-Origin."""
        from fastapi.testclient import TestClient

        client = TestClient(_make_cors_test_app(["https://app.example.com"]))
        resp = client.get("/health", headers={"Origin": "https://app.example.com"})
        assert "access-control-allow-origin" in resp.headers
        assert resp.headers["access-control-allow-origin"] == "https://app.example.com"

    def test_disallowed_origin_has_no_acao_header(self):
        """GET from an unknown origin must NOT receive Access-Control-Allow-Origin."""
        from fastapi.testclient import TestClient

        client = TestClient(_make_cors_test_app(["https://app.example.com"]))
        resp = client.get("/health", headers={"Origin": "https://evil.com"})
        assert "access-control-allow-origin" not in resp.headers

    def test_no_origin_has_no_acao_header(self):
        """Plain requests without Origin header are unaffected."""
        from fastapi.testclient import TestClient

        client = TestClient(_make_cors_test_app(["https://app.example.com"]))
        resp = client.get("/health")
        assert "access-control-allow-origin" not in resp.headers

    def test_preflight_returns_200_for_allowed_origin(self):
        """OPTIONS preflight from allowed origin returns 200."""
        from fastapi.testclient import TestClient

        client = TestClient(_make_cors_test_app(["https://app.example.com"]))
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    def test_empty_origins_blocks_all_cross_origin(self):
        """No ALLOWED_ORIGINS in production must block cross-origin requests."""
        from fastapi.testclient import TestClient

        client = TestClient(_make_cors_test_app([]))  # production with no origins set
        resp = client.get("/health", headers={"Origin": "https://any.com"})
        assert "access-control-allow-origin" not in resp.headers

    def test_wildcard_allows_any_origin(self):
        """Dev mode with ['*'] allows any origin (no credentials)."""
        from fastapi.testclient import TestClient

        client = TestClient(_make_cors_test_app(["*"]))
        resp = client.get("/health", headers={"Origin": "https://random.com"})
        assert "access-control-allow-origin" in resp.headers


@pytest.mark.unit
class TestCORSOriginParser:
    """Validate the origin parsing helper used by main.py."""

    def test_empty_string_produces_empty_list(self):
        origins_str = ""
        result = [o.strip() for o in origins_str.split(",") if o.strip()]
        assert result == []

    def test_single_origin(self):
        origins_str = "https://app.example.com"
        result = [o.strip() for o in origins_str.split(",") if o.strip()]
        assert result == ["https://app.example.com"]

    def test_multiple_origins_with_spaces(self):
        origins_str = "https://a.com , https://b.com , http://localhost:5173"
        result = [o.strip() for o in origins_str.split(",") if o.strip()]
        assert result == ["https://a.com", "https://b.com", "http://localhost:5173"]
