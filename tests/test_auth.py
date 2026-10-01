"""
Tests for admin API key authentication dependency.
"""

import os
import pytest
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException


@pytest.mark.unit
class TestVerifyAdminApiKey:
    """Test cases for verify_admin_api_key dependency."""

    @pytest.mark.asyncio
    async def test_valid_key_passes(self):
        with patch.dict(os.environ, {"ADMIN_API_KEY": "secret-key-123"}):
            from Clinic_app.common.auth import verify_admin_api_key

            result = await verify_admin_api_key("secret-key-123")
            assert result == "secret-key-123"

    @pytest.mark.asyncio
    async def test_missing_key_raises_401(self):
        with patch.dict(os.environ, {"ADMIN_API_KEY": "secret-key-123"}):
            from Clinic_app.common.auth import verify_admin_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_admin_api_key(None)
            assert exc_info.value.status_code == 401
            assert "MISSING_API_KEY" in exc_info.value.detail["code"]

    @pytest.mark.asyncio
    async def test_wrong_key_raises_403(self):
        with patch.dict(os.environ, {"ADMIN_API_KEY": "secret-key-123"}):
            from Clinic_app.common.auth import verify_admin_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_admin_api_key("wrong-key")
            assert exc_info.value.status_code == 403
            assert "INVALID_API_KEY" in exc_info.value.detail["code"]

    @pytest.mark.asyncio
    async def test_empty_string_key_raises_401(self):
        with patch.dict(os.environ, {"ADMIN_API_KEY": "secret-key-123"}):
            from Clinic_app.common.auth import verify_admin_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_admin_api_key("")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_env_var_set_raises_500(self):
        # Remove ADMIN_API_KEY from environment
        env = {k: v for k, v in os.environ.items() if k != "ADMIN_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            from Clinic_app.common.auth import verify_admin_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_admin_api_key("some-key")
            assert exc_info.value.status_code == 500
            assert "SERVER_MISCONFIGURATION" in exc_info.value.detail["code"]
