from __future__ import annotations

from datetime import date

_WEIGHTS = (7, 3, 1)


def _char_value(ch: str) -> int:
    if ch == "<":
        return 0
    if ch.isdigit():
        return int(ch)
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 10
    raise ValueError(f"invalid MRZ character: {ch!r}")


def check_digit(value: str) -> str:
    total = sum(_char_value(ch) * _WEIGHTS[i % 3] for i, ch in enumerate(value))
    return str(total % 10)


def _fmt_passport_number(value: str) -> str:
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum())
    if not 1 <= len(cleaned) <= 9:
        raise ValueError("passport number must be 1-9 alphanumeric characters for TD3 demo")
    return cleaned.ljust(9, "<")


def build_synthetic_td3_line2(passport_number: str, expiry: str) -> str:
    """Build a deterministic synthetic TD3 line 2 for demo/test evidence.

    This is not a document generator. It exists so the prototype can prove that
    authoritative fields are derived from a versioned artifact with ICAO-style
    check digits rather than typed by the caller or LLM.
    """
    expiry_date = date.fromisoformat(expiry)
    pnum = _fmt_passport_number(passport_number)
    dob = "900101"
    personal = "<<<<<<<<<<<<<<"
    exp = expiry_date.strftime("%y%m%d")
    base = (
        pnum + check_digit(pnum) +
        "XXX" + dob + check_digit(dob) + "<" +
        exp + check_digit(exp) +
        personal + check_digit(personal)
    )
    composite_source = pnum + check_digit(pnum) + dob + check_digit(dob) + exp + check_digit(exp) + personal + check_digit(personal)
    line = base + check_digit(composite_source)
    if len(line) != 44:
        raise AssertionError(f"TD3 line 2 must be 44 chars, got {len(line)}")
    return line


def extract_passport_fields(line2: str) -> dict[str, str]:
    if len(line2) != 44:
        raise ValueError("TD3 line 2 must be 44 characters")
    passport_raw = line2[0:9]
    passport_cd = line2[9]
    dob_raw = line2[13:19]
    dob_cd = line2[19]
    expiry_raw = line2[21:27]
    expiry_cd = line2[27]
    personal_raw = line2[28:42]
    personal_cd = line2[42]
    composite_cd = line2[43]

    checks = (
        (passport_raw, passport_cd, "passport number"),
        (dob_raw, dob_cd, "date of birth"),
        (expiry_raw, expiry_cd, "passport expiry"),
        (personal_raw, personal_cd, "personal number"),
    )
    for raw, supplied, label in checks:
        if check_digit(raw) != supplied:
            raise ValueError(f"{label} check digit invalid")

    composite_source = passport_raw + passport_cd + dob_raw + dob_cd + expiry_raw + expiry_cd + personal_raw + personal_cd
    if check_digit(composite_source) != composite_cd:
        raise ValueError("composite check digit invalid")

    yy, mm, dd = int(expiry_raw[:2]), int(expiry_raw[2:4]), int(expiry_raw[4:6])
    expiry = date(2000 + yy, mm, dd).isoformat()
    return {
        "passport_number": passport_raw.replace("<", ""),
        "passport_expiry": expiry,
    }
