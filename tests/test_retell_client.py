"""Unit tests for Retell outbound call client."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from Clinic_app.services import retell_client


@pytest.mark.unit
def test_normalize_metadata_coerces_to_str() -> None:
    meta = retell_client._normalize_metadata({"a": 1, "b": None, "c": "x"})
    assert meta == {"a": "1", "c": "x"}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_outbound_call_success() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"call_id": "abc123"}
    mock_resp.raise_for_status = MagicMock()

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(return_value=mock_resp)

    with patch.dict(os.environ, {"RETELL_API_KEY": "k"}):
        cid = await retell_client.create_outbound_call(
            agent_id="agent1",
            from_number="+15551234567",
            to_number="+15559876543",
            metadata={"call_type": "hedis_campaign", "campaign_contact_id": "uuid"},
            client=client,
        )

    assert cid == "abc123"
    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert kwargs["json"]["from_number"] == "+15551234567"
    assert kwargs["json"]["to_number"] == "+15559876543"
    assert kwargs["json"]["override_agent_id"] == "agent1"
    assert "metadata" in kwargs["json"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_outbound_call_missing_key_raises() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("RETELL_API_KEY", None)
        with pytest.raises(retell_client.RetellClientError, match="RETELL_API_KEY"):
            await retell_client.create_outbound_call(
                "a",
                "+1",
                "+1",
                {},
                client=AsyncMock(),
            )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_outbound_call_retries_on_500() -> None:
    bad_resp = MagicMock()
    bad_resp.status_code = 500
    bad = MagicMock()
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "err", request=MagicMock(), response=bad_resp
    )
    good = MagicMock()
    good.json.return_value = {"call_id": "ok"}
    good.raise_for_status = MagicMock()

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=[bad, good])

    with patch.dict(os.environ, {"RETELL_API_KEY": "k"}):
        cid = await retell_client.create_outbound_call(
            "agent",
            "+15551111111",
            "+15552222222",
            {"x": "y"},
            client=client,
        )
    assert cid == "ok"
    assert client.post.call_count == 2
