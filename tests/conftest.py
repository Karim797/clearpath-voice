from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DB = Path(__file__).resolve().parent / "clearpath_test.db"

# Settings are instantiated at import time, so configure the test environment first.
os.environ["DATABASE_PATH"] = str(TEST_DB)
os.environ["ENVIRONMENT"] = "development"
os.environ["DEMO_MODE"] = "true"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:8000"
os.environ["TOOL_API_KEY"] = "test-tool-key"
os.environ["EVENT_API_KEY"] = "test-event-key"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["ACTION_SIGNING_SECRET"] = "test-action-signing-secret"
os.environ["AUDIT_SIGNING_SECRET"] = "test-audit-signing-secret"
os.environ["ELEVENLABS_WEBHOOK_SECRET"] = "test-elevenlabs-webhook-secret"

from app.main import app  # noqa: E402
from app.services.call_context import issue_case_capability  # noqa: E402
from scripts.seed import main as seed  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    if TEST_DB.exists():
        TEST_DB.unlink()
    seed(reset=True)
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def headers_for(case_id: str, conversation_id: str = "conv_test_001") -> dict[str, str]:
    capability = issue_case_capability(case_id)
    return {
        "X-ClearPath-Tool-Key": os.environ["TOOL_API_KEY"],
        "X-ClearPath-Case-Capability": capability,
        "X-Conversation-Id": conversation_id,
    }


@pytest.fixture
def primary_headers() -> dict[str, str]:
    return headers_for("DXB-R-260901")
