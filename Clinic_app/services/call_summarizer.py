"""
One-sentence Claude summary for HEDIS campaign calls.

Raw transcripts are not stored; this module produces a short summary only.
"""

from __future__ import annotations

import logging
import os

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-20250514"

_SUMMARY_SYSTEM = """\
You summarize healthcare outreach phone calls for internal clinic staff.
Return exactly one clear sentence describing the call outcome and next steps if any.
Do not include patient name, date of birth, phone number, address, MRN, or other PHI.
If the transcript is empty or unusable, respond with: "Call completed; no usable transcript."
"""


def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


@retry(
    retry=retry_if_exception_type(anthropic.APIConnectionError),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    stop=stop_after_attempt(3),
)
def summarize_transcript_sync(transcript: str, gap_type: str) -> str:
    """
    Generate a one-sentence summary. Runs synchronous Anthropic client;
    call from asyncio via asyncio.to_thread if needed.
    """
    text = (transcript or "").strip()
    if not text:
        return "Call completed; no usable transcript."

    client = _get_anthropic_client()
    user_msg = (
        f"Care gap type (HEDIS measure code): {gap_type}\n\n"
        f"Call transcript:\n{text}"
    )
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=150,
        system=_SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    out = response.content[0].text.strip()
    return out if out else "Call completed; summary unavailable."
