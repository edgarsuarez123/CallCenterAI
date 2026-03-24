"""
Claude helpers for HEDIS campaign calls.

- Appointment-based gaps: one-sentence summary (`summarize_transcript_sync`).
- Order-based gaps: structured extraction (`extract_order_based_notes_sync`); the note
  string is encrypted in `campaign_audit.call_summary_encrypted`.

Raw transcripts are not stored.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, TypedDict

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

_ORDER_NOTES_SYSTEM = """\
You analyze healthcare outreach phone calls for order-based care gaps (kits, lab orders, referrals).
Respond with exactly one JSON object and no other text. Keys:
- "patient_agreed": true if the patient agreed to the order or kit, false if they clearly declined, null if ambiguous or not discussed.
- "action_for_staff": short imperative for clinic staff (e.g. "Send colorectal stool kit order") or an empty string if none.
- "note": one or two sentences for internal staff; no PHI (no name, DOB, phone, address, MRN).
If the transcript is empty or unusable, respond with:
{"patient_agreed":null,"action_for_staff":"","note":"Call completed; no usable transcript."}
"""

_FALLBACK_UNAVAILABLE: dict[str, Any] = {
    "patient_agreed": None,
    "action_for_staff": "",
    "note": "Call completed; summary unavailable.",
}


class OrderNotesDict(TypedDict):
    """Structured extraction for order-based gap calls (stored note only in campaign_audit)."""

    patient_agreed: Optional[bool]
    action_for_staff: str
    note: str


def _parse_order_notes_json(text: str) -> Optional[dict[str, Any]]:
    """Parse Claude output into a dict; return None if invalid."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Brace slice (handles markdown fences or extra prose)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _normalize_order_notes(obj: dict[str, Any]) -> OrderNotesDict:
    """Coerce parsed JSON into OrderNotesDict with safe defaults."""
    pa_raw = obj.get("patient_agreed")
    if pa_raw is True:
        patient_agreed: Optional[bool] = True
    elif pa_raw is False:
        patient_agreed = False
    else:
        patient_agreed = None

    action = obj.get("action_for_staff")
    action_for_staff = action.strip() if isinstance(action, str) else ""

    note = obj.get("note")
    note_str = note.strip() if isinstance(note, str) else ""
    if not note_str:
        note_str = _FALLBACK_UNAVAILABLE["note"]

    return {
        "patient_agreed": patient_agreed,
        "action_for_staff": action_for_staff,
        "note": note_str,
    }


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


@retry(
    retry=retry_if_exception_type(anthropic.APIConnectionError),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    stop=stop_after_attempt(3),
)
def extract_order_based_notes_sync(transcript: str, gap_type: str) -> OrderNotesDict:
    """
    Structured JSON extraction for order-based care gaps. Runs synchronous Anthropic client;
    call from asyncio via asyncio.to_thread if needed.

    Returns patient_agreed (True/False/None), action_for_staff, and human-readable note.
    On parse failure, returns a safe fallback (ambiguous agreement).
    """
    text = (transcript or "").strip()
    if not text:
        return {
            "patient_agreed": None,
            "action_for_staff": "",
            "note": "Call completed; no usable transcript.",
        }

    client = _get_anthropic_client()
    user_msg = (
        f"Care gap type (HEDIS measure code): {gap_type}\n\n"
        f"Call transcript:\n{text}"
    )
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=400,
        system=_ORDER_NOTES_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw_text = response.content[0].text.strip()
    parsed = _parse_order_notes_json(raw_text)
    if not parsed:
        logger.warning(
            "extract_order_based_notes_sync: could not parse JSON from Claude response"
        )
        return _normalize_order_notes(_FALLBACK_UNAVAILABLE)
    return _normalize_order_notes(parsed)
