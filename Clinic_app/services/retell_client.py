"""
Async Retell REST client for outbound phone calls.

POST https://api.retellai.com/v2/create-phone-call
See: https://docs.retellai.com/api-references/create-phone-call
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

RETELL_API_BASE = "https://api.retellai.com"


def _retell_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code == 429
    return False


class RetellClientError(RuntimeError):
    """Raised when Retell API returns an error or unexpected response."""


def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Retell metadata must be JSON-serializable; coerce values to strings."""
    out: dict[str, str] = {}
    for k, v in metadata.items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out


@retry(
    retry=retry_if_exception(_retell_retryable),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def create_outbound_call(
    agent_id: str,
    from_number: str,
    to_number: str,
    metadata: Mapping[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """
    Create an outbound call. Returns Retell call_id.

    Retries on HTTPStatusError (e.g. 5xx) up to 3 times with exponential backoff.
    """
    api_key = os.environ.get("RETELL_API_KEY", "")
    if not api_key:
        raise RetellClientError("RETELL_API_KEY is not set")

    body: dict[str, Any] = {
        "from_number": from_number,
        "to_number": to_number,
        "override_agent_id": agent_id,
        "metadata": _normalize_metadata(metadata),
    }

    # Dynamic variables for Response Engine prompts / tools
    dyn = _normalize_metadata(metadata)
    if dyn:
        body["retell_llm_dynamic_variables"] = dyn

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=30.0)

    try:
        resp = await client.post(
            f"{RETELL_API_BASE}/v2/create-phone-call",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        if own_client:
            await client.aclose()

    call_id = data.get("call_id")
    if not call_id:
        logger.error("Retell create-phone-call missing call_id: %s", data)
        raise RetellClientError("Retell API response missing call_id")
    return str(call_id)
