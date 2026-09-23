from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
import re


@dataclass(frozen=True)
class RejectionPolicy:
    code: str
    allowed_fields: tuple[str, ...]
    required_documents: tuple[str, ...] = ()
    requires_attendance: bool = False
    escalation_only: bool = False


POLICIES: dict[str, RejectionPolicy] = {
    "PASSPORT_EXPIRY_MISMATCH": RejectionPolicy(
        code="PASSPORT_EXPIRY_MISMATCH",
        allowed_fields=("passport_expiry",),
    ),
    "PASSPORT_NUMBER_TYPO": RejectionPolicy(
        code="PASSPORT_NUMBER_TYPO",
        allowed_fields=("passport_number",),
    ),
    "MISSING_PASSPORT_COPY": RejectionPolicy(
        code="MISSING_PASSPORT_COPY",
        allowed_fields=(),
        required_documents=("passport_copy",),
    ),
    "MISSING_PHOTO": RejectionPolicy(
        code="MISSING_PHOTO",
        allowed_fields=(),
        required_documents=("white_background_photo",),
    ),
    "BIOMETRIC_REQUIRED": RejectionPolicy(
        code="BIOMETRIC_REQUIRED",
        allowed_fields=(),
        requires_attendance=True,
    ),
    "LEGAL_OR_DISPUTED": RejectionPolicy(
        code="LEGAL_OR_DISPUTED",
        allowed_fields=(),
        escalation_only=True,
    ),
}


APPROVED_MESSAGES: dict[str, dict[str, str]] = {
    "PASSPORT_EXPIRY_MISMATCH": {
        "en": "The passport expiry date in the submitted application does not match the passport document on file.",
        "ar": "تاريخ انتهاء جواز السفر في الطلب المقدم لا يطابق تاريخ الانتهاء في مستند جواز السفر الموجود بالملف.",
    },
    "PASSPORT_NUMBER_TYPO": {
        "en": "The passport number in the submitted application does not match the passport document on file.",
        "ar": "رقم جواز السفر في الطلب المقدم لا يطابق رقم الجواز في المستند الموجود بالملف.",
    },
    "MISSING_PASSPORT_COPY": {
        "en": "A readable passport copy is required to continue processing the submitted application.",
        "ar": "يلزم إرفاق نسخة واضحة من جواز السفر لاستكمال معالجة الطلب المقدم.",
    },
    "MISSING_PHOTO": {
        "en": "A compliant personal photo is required to continue processing the submitted application.",
        "ar": "يلزم إرفاق صورة شخصية مستوفية للمتطلبات لاستكمال معالجة الطلب المقدم.",
    },
    "BIOMETRIC_REQUIRED": {
        "en": "In-person biometric attendance is required before processing can continue.",
        "ar": "يلزم الحضور شخصياً لاستكمال إجراء البيانات البيومترية قبل متابعة معالجة الطلب.",
    },
}


def approved_message(code: str, language: str) -> str | None:
    messages = APPROVED_MESSAGES.get(code)
    if not messages:
        return None
    return messages.get(language) or messages.get("en")


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_BIDI_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_AR_MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5, "يونيو": 6,
    "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10,
    "نوفمبر": 11, "ديسمبر": 12,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_AR_MONTH_NAMES = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو", 7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}
_TO_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def normalize_digits(value: str) -> str:
    return value.translate(_ARABIC_DIGITS)


def _clean_human_text(value: str) -> str:
    return _BIDI_MARKS.sub("", normalize_digits(value)).strip()


def _parse_human_date(value: str) -> date | None:
    cleaned = _clean_human_text(value)
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", cleaned)
    if m:
        day, month, year = map(int, m.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})\s+([^\d]+?)\s+(\d{4})", cleaned)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).strip().lower()
        month = _AR_MONTHS.get(month_name) or _EN_MONTHS.get(month_name)
        if month:
            try:
                return date(int(m.group(3)), month, day)
            except ValueError:
                return None
    return None


def format_iso_date_ar(value: str) -> str:
    """Format an ISO date for a natural Arabic consent/read-back sentence."""
    try:
        d = date.fromisoformat(_clean_human_text(value))
    except ValueError:
        return value.translate(_TO_ARABIC_INDIC)
    rendered = f"{d.day} {_AR_MONTH_NAMES[d.month]} {d.year}"
    return rendered.translate(_TO_ARABIC_INDIC)


def validate_field_value(field_name: str, value: str) -> tuple[bool, str, str]:
    """Return (valid, reason, normalized_value).

    Validation is semantic, not regex-only. Sensitive identity corrections are
    later compared against the authority's document-of-record value.
    """
    normalized = _clean_human_text(value)
    if field_name == "passport_expiry":
        parsed = _parse_human_date(normalized)
        if parsed is None:
            return False, "passport_expiry_unparseable", normalized
        normalized = parsed.isoformat()
        if parsed <= datetime.now(ZoneInfo("Asia/Dubai")).date():
            return False, "passport_expiry_must_be_future_date", normalized
    elif field_name == "passport_number":
        normalized = normalized.upper()
        if not re.fullmatch(r"[A-Z0-9]{6,12}", normalized):
            return False, "passport_number_format_invalid", normalized
    else:
        return False, "field_validator_not_defined", normalized
    return True, "ok", normalized
