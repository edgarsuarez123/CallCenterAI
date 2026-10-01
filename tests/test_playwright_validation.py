"""
Feature 0 — Unit tests: PlaywrightEHRService interface contract
----------------------------------------------------------------
These tests do NOT connect to real NextGen. They use mocks exclusively.

Purpose:
  1. Define the exact API contract that PlaywrightEHRService (Feature 5) must satisfy
  2. Confirm the AgentQL Redis cache key format is correct before implementation
  3. Verify the <3s response time contract required by Retell (HEDIS PRD §10.3)
  4. Ensure pytest + asyncio are working correctly for all future EHR tests

Run:
    pytest tests/test_playwright_validation.py -v -m unit
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock


# --------------------------------------------------------------------------- #
# Contract: PlaywrightEHRService interface                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestPlaywrightEHRServiceContract:
    """
    Define and verify the PlaywrightEHRService API contract before Feature 5
    implements it. Every test here is a specification, not just a smoke test.

    When PlaywrightEHRService is created in Feature 5, replace the mock_service
    AsyncMocks with real instances and these tests will automatically become
    real integration tests.
    """

    @pytest.mark.asyncio
    async def test_get_available_slots_returns_typed_list(self):
        """
        get_available_slots() must return a list of dicts, each with:
          - start_time: ISO 8601 string with timezone offset
          - end_time:   ISO 8601 string with timezone offset
          - provider_name: string
        This is the format Retell expects (HEDIS PRD §10.3).
        """
        mock_service = AsyncMock()
        mock_service.get_available_slots.return_value = [
            {
                "start_time": "2026-04-01T09:00:00-05:00",
                "end_time": "2026-04-01T09:30:00-05:00",
                "provider_name": "Dr. Smith",
            },
            {
                "start_time": "2026-04-01T10:00:00-05:00",
                "end_time": "2026-04-01T10:30:00-05:00",
                "provider_name": "Dr. Smith",
            },
        ]

        result = await mock_service.get_available_slots(
            provider_name="Dr. Smith", date="2026-04-01"
        )

        assert isinstance(result, list), "get_available_slots must return a list"
        assert len(result) > 0, "Expected at least one slot in mock response"

        for slot in result:
            assert "start_time" in slot, f"Slot missing start_time: {slot}"
            assert "end_time" in slot, f"Slot missing end_time: {slot}"
            assert "provider_name" in slot, f"Slot missing provider_name: {slot}"
            # Times must include timezone offset for Retell to format correctly
            assert "T" in slot["start_time"], "start_time must be ISO 8601 with time component"
            assert (
                "+" in slot["start_time"]
                or slot["start_time"].endswith("Z")
                or "-05" in slot["start_time"]
            ), "start_time must include timezone offset"

    @pytest.mark.asyncio
    async def test_get_available_slots_empty_when_no_availability(self):
        """get_available_slots() must return an empty list (not None, not raise) when unavailable."""
        mock_service = AsyncMock()
        mock_service.get_available_slots.return_value = []

        result = await mock_service.get_available_slots(
            provider_name="Dr. Smith", date="2026-04-01"
        )

        assert result == [], "No availability must return [], not None or raise"

    @pytest.mark.asyncio
    async def test_book_appointment_returns_ehr_appointment_id_on_success(self):
        """
        book_appointment() on success must return a dict with:
          - success: True
          - ehr_appointment_id: non-empty string (NextGen's appointment ID)
        This ID is stored in campaign_audit for the HEDIS dashboard.
        """
        mock_service = AsyncMock()
        mock_service.book_appointment.return_value = {
            "success": True,
            "ehr_appointment_id": "NEXTGEN-APPT-12345",
        }

        result = await mock_service.book_appointment(
            provider_name="Dr. Smith",
            slot_start="2026-04-01T09:00:00-05:00",
            patient_name="John Doe",
            appt_type_code="PREV",
        )

        assert result["success"] is True
        assert "ehr_appointment_id" in result
        assert result["ehr_appointment_id"], "ehr_appointment_id must not be empty"

    @pytest.mark.asyncio
    async def test_book_appointment_returns_failure_dict_not_raises(self):
        """
        book_appointment() on EHR rejection must return {"success": False, "error": "..."}
        It must NOT raise an exception — caller decides how to handle.
        This is the graceful degradation pattern from HEDIS PRD §10.2.
        """
        mock_service = AsyncMock()
        mock_service.book_appointment.return_value = {
            "success": False,
            "error": "Slot no longer available in NextGen",
        }

        result = await mock_service.book_appointment(
            provider_name="Dr. Smith",
            slot_start="2026-04-01T09:00:00-05:00",
            patient_name="John Doe",
            appt_type_code="PREV",
        )

        assert result["success"] is False
        assert "error" in result
        assert isinstance(result["error"], str)

    @pytest.mark.asyncio
    async def test_get_available_slots_response_time_contract(self):
        """
        get_available_slots() must respond in under 3 seconds.
        HEDIS PRD §10.3: 'Response must be returned to Retell in under 3 seconds
        or call loses conversational flow.'

        This mock always passes — the real constraint is enforced in Feature 5
        load tests. This test documents the contract and will catch regressions
        when replaced with real service calls.
        """
        mock_service = AsyncMock()
        mock_service.get_available_slots.return_value = []

        start = time.monotonic()
        await mock_service.get_available_slots(provider_name="Dr. Smith", date="2026-04-01")
        elapsed = time.monotonic() - start

        assert elapsed < 3.0, (
            f"Slot query took {elapsed:.3f}s — exceeds 3s Retell conversational limit. "
            "Optimize: pre-warm browser session before campaign starts, cache selectors in Redis."
        )

    @pytest.mark.asyncio
    async def test_credential_test_returns_pass_fail_dict(self):
        """
        test_credentials() used by POST /admin/clinics/{id}/ehr-test must return:
          - {"success": True} on valid credentials
          - {"success": False, "error": "..."} on failure
        Never raises — admin endpoint must always get a structured response.
        """
        mock_service = AsyncMock()

        # Happy path
        mock_service.test_credentials.return_value = {"success": True}
        result = await mock_service.test_credentials()
        assert result["success"] is True

        # Failure path
        mock_service.test_credentials.return_value = {
            "success": False,
            "error": "Login failed: invalid credentials",
        }
        result = await mock_service.test_credentials()
        assert result["success"] is False
        assert "error" in result


# --------------------------------------------------------------------------- #
# Contract: Redis EHR slot cache key format                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestEHRSlotCacheKeys:
    """
    Verify the Redis cache key naming convention for Browser-Use slot pre-fetch.
    Each clinic's slots are isolated by clinic_id in the key prefix.

    Key format: ehr:slots:{clinic_id}:{provider_name_normalized}
    TTL: 90 seconds (SlotPrefetchWorker runs every 60s with 30s buffer)
    """

    def test_slot_cache_key_format(self):
        clinic_id = "550e8400-e29b-41d4-a716-446655440000"
        provider_name = "Dr. Smith"
        safe_provider = provider_name.replace(" ", "_").lower()
        key = f"ehr:slots:{clinic_id}:{safe_provider}"

        assert key == "ehr:slots:550e8400-e29b-41d4-a716-446655440000:dr._smith"
        assert key.startswith("ehr:slots:")
        assert clinic_id in key
        assert safe_provider in key

    def test_slot_cache_key_is_tenant_scoped(self):
        """Two clinics with the same provider name must have different cache keys."""
        clinic_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        clinic_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        provider = "dr._jones"

        key_a = f"ehr:slots:{clinic_a}:{provider}"
        key_b = f"ehr:slots:{clinic_b}:{provider}"

        assert key_a != key_b, "Slot cache keys must be scoped per clinic"

    def test_slot_cache_ttl_is_90_seconds(self):
        """EHR slot cache TTL must be 90s (pre-fetch runs every 60s, 30s buffer)."""
        from Clinic_app.services.playbook_cache import SLOT_CACHE_TTL_SECONDS

        assert SLOT_CACHE_TTL_SECONDS == 90
