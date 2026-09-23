from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from fastapi import Header, HTTPException, status

from .config import settings


def require_tool_key(x_clearpath_tool_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_clearpath_tool_key, settings.tool_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_tool_credentials")


def require_event_key(x_clearpath_event_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_clearpath_event_key, settings.event_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_event_credentials")


def require_admin_key(x_clearpath_admin_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_clearpath_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_admin_credentials")


def hash_secret(value: str) -> str:
    return hmac.new(settings.action_signing_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def verify_secret(value: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_secret(value), hashed)


def random_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_action_token(payload: dict[str, Any], ttl_seconds: int = 300) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_seconds
    body["nonce"] = secrets.token_urlsafe(8)
    encoded = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(settings.action_signing_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def verify_action_token(token: str) -> dict[str, Any]:
    try:
        encoded, sig = token.split(".", 1)
        expected = hmac.new(settings.action_signing_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(encoded))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=403, detail="invalid_or_expired_action_token") from exc


def mask_phone(phone: str) -> str:
    if len(phone) < 6:
        return "***"
    return f"{phone[:3]}***{phone[-3:]}"


def redact_text(text: str | None) -> str | None:
    if not text:
        return text
    import re

    # Redact phone-like sequences before short numeric challenges so a spaced
    # phone number is not partially transformed into a fake OTP fragment.
    phoneish = re.compile(r"\+?\d(?:[\d\s\-()]{7,})\d")

    def phone_repl(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            return candidate
        digits = re.sub(r"\D", "", candidate)
        return "[REDACTED_PHONE]" if len(digits) >= 9 else candidate

    text = phoneish.sub(phone_repl, text)
    # 4-8 digit standalone challenges are redacted, but ISO dates remain evidence.
    text = re.sub(r"(?<![\d-])\d{4,8}(?![\d-])", "[REDACTED_CODE]", text)
    return text
