"""Shared logging utilities — PHI masking helpers."""

import re

_E164_PATTERN = re.compile(r"\+?\d{7,15}")


def mask_phone_e164(e164: str) -> str:
    """Mask an E.164 phone number as ***-***-XXXX (last 4 digits visible)."""
    digits = "".join(c for c in e164 if c.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else "****"
    return f"***-***-{last4}"


def mask_phone_in_string(text: str) -> str:
    """Replace any phone-like digit sequences (7+ digits) in a string with masked form."""

    def _replace(match: re.Match) -> str:
        return mask_phone_e164(match.group(0))

    return _E164_PATTERN.sub(_replace, text)
