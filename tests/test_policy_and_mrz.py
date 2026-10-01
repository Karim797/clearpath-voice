from __future__ import annotations

import pytest

from app.mrz import build_synthetic_td3_line2, extract_passport_fields
from app.policy import format_iso_date_ar, validate_field_value
from app.security import redact_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2028-02-11", "2028-02-11"),
        ("11/02/2028", "2028-02-11"),
        ("11 February 2028", "2028-02-11"),
        ("١١ فبراير ٢٠٢٨", "2028-02-11"),
    ],
)
def test_passport_expiry_normalizes_supported_date_forms(raw, expected):
    valid, reason, normalized = validate_field_value("passport_expiry", raw)
    assert valid is True
    assert reason == "ok"
    assert normalized == expected


def test_passport_number_normalizes_to_uppercase():
    valid, reason, normalized = validate_field_value("passport_number", "n1234567")
    assert valid is True
    assert reason == "ok"
    assert normalized == "N1234567"


def test_unknown_identity_field_has_no_validator():
    valid, reason, _ = validate_field_value("national_id", "123456789")
    assert valid is False
    assert reason == "field_validator_not_defined"


def test_synthetic_mrz_round_trip():
    line = build_synthetic_td3_line2("N1234567", "2028-02-11")
    assert len(line) == 44
    assert extract_passport_fields(line) == {
        "passport_number": "N1234567",
        "passport_expiry": "2028-02-11",
    }


def test_tampered_mrz_is_rejected():
    line = build_synthetic_td3_line2("N1234567", "2028-02-11")
    tampered = ("A" if line[0] != "A" else "B") + line[1:]
    with pytest.raises(ValueError):
        extract_passport_fields(tampered)


def test_arabic_readback_format_is_human_friendly():
    rendered = format_iso_date_ar("2028-02-11")
    assert "فبراير" in rendered
    assert "٢٠٢٨" in rendered


def test_redaction_preserves_iso_dates_but_hides_codes_and_phones():
    text = "Date 2028-02-11, OTP 482731, phone +971 50 000 0101."
    redacted = redact_text(text)
    assert "2028-02-11" in redacted
    assert "482731" not in redacted
    assert "971 50 000 0101" not in redacted
    assert "[REDACTED_CODE]" in redacted
    assert "[REDACTED_PHONE]" in redacted
