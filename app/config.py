from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "ClearPath Voice")
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_path: str = os.getenv("DATABASE_PATH", "./clearpath.db")
    tool_api_key: str = os.getenv("TOOL_API_KEY", "dev-tool-key-change-me")
    event_api_key: str = os.getenv("EVENT_API_KEY", "dev-event-key-change-me")
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "dev-admin-key-change-me")
    action_signing_secret: str = os.getenv("ACTION_SIGNING_SECRET", "dev-signing-secret-change-me")
    audit_signing_secret: str = os.getenv("AUDIT_SIGNING_SECRET", "dev-audit-secret-change-me")
    elevenlabs_api_key: str | None = os.getenv("ELEVENLABS_API_KEY")
    elevenlabs_agent_id: str | None = os.getenv("ELEVENLABS_AGENT_ID")
    elevenlabs_phone_number_id: str | None = os.getenv("ELEVENLABS_PHONE_NUMBER_ID")
    elevenlabs_webhook_secret: str | None = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    demo_mode: bool = os.getenv("DEMO_MODE", "true").lower() == "true"


settings = Settings()


def _is_local_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _weak_secret(value: str) -> bool:
    lowered = (value or "").lower()
    return (
        len(value or "") < 32
        or lowered.startswith("dev-")
        or lowered.startswith("replace-with")
        or lowered.endswith("change-me")
    )


def is_local_development() -> bool:
    return settings.environment == "development" and _is_local_url(settings.public_base_url)


def validate_settings() -> None:
    """Fail closed on any non-local deployment, even when DEMO_MODE was left true."""
    if is_local_development():
        return

    required = {
        "TOOL_API_KEY": settings.tool_api_key,
        "EVENT_API_KEY": settings.event_api_key,
        "ADMIN_API_KEY": settings.admin_api_key,
        "ACTION_SIGNING_SECRET": settings.action_signing_secret,
        "AUDIT_SIGNING_SECRET": settings.audit_signing_secret,
        "ELEVENLABS_WEBHOOK_SECRET": settings.elevenlabs_webhook_secret or "",
    }
    bad = [name for name, value in required.items() if _weak_secret(value)]
    distinct_values = [value for value in required.values() if value]
    if len(set(distinct_values)) != len(distinct_values):
        bad.append("SECRETS_MUST_BE_DISTINCT")
    if bad:
        raise RuntimeError(f"Refusing public/non-development startup with insecure configuration: {', '.join(sorted(set(bad)))}")
