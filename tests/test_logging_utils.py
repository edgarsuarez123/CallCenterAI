# tests/test_logging_utils.py
"""Unit tests for PHI masking utilities in common/logging_utils.py."""

import pytest
from Clinic_app.common.logging_utils import mask_phone_e164, mask_phone_in_string


@pytest.mark.unit
class TestMaskPhoneE164:
    def test_standard_e164(self):
        assert mask_phone_e164("+12125551234") == "***-***-1234"

    def test_no_plus_prefix(self):
        assert mask_phone_e164("12125551234") == "***-***-1234"

    def test_ten_digit(self):
        assert mask_phone_e164("2125551234") == "***-***-1234"

    def test_puerto_rico_number(self):
        assert mask_phone_e164("+17875551234") == "***-***-1234"

    def test_short_number_returns_stars(self):
        assert mask_phone_e164("123") == "***-***-****"

    def test_empty_string_returns_stars(self):
        assert mask_phone_e164("") == "***-***-****"

    def test_last_four_visible(self):
        result = mask_phone_e164("+12125559876")
        assert result.endswith("9876")
        assert "212" not in result


@pytest.mark.unit
class TestMaskPhoneInString:
    def test_masks_phone_in_sentence(self):
        result = mask_phone_in_string("Calling +12125551234 now")
        assert "2125551234" not in result
        assert "***-***-1234" in result

    def test_no_phone_unchanged(self):
        assert mask_phone_in_string("No phone here") == "No phone here"

    def test_multiple_phones(self):
        result = mask_phone_in_string("From +11111111111 to +12222222222")
        assert result.count("***-***-") == 2
        assert "1111111111" not in result
        assert "2222222222" not in result

    def test_short_digits_not_masked(self):
        # 6 digits — below threshold, not a phone
        result = mask_phone_in_string("code 123456")
        assert result == "code 123456"
