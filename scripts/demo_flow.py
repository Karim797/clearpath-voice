from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", str(ROOT / "demo_clearpath.db"))
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8000")
os.environ.setdefault("TOOL_API_KEY", "demo-tool-key")
os.environ.setdefault("EVENT_API_KEY", "demo-event-key")
os.environ.setdefault("ADMIN_API_KEY", "demo-admin-key")
os.environ.setdefault("ACTION_SIGNING_SECRET", "demo-action-secret")
os.environ.setdefault("AUDIT_SIGNING_SECRET", "demo-audit-secret")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from scripts.seed import main as seed  # noqa: E402
from app.db import connection  # noqa: E402
from app.services.call_context import issue_case_capability  # noqa: E402


def pp(label, response):
    print(f"\n=== {label} ===")
    print(response.status_code)
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


def main():
    seed(reset=True)
    with connection() as conn:
        conn.execute("UPDATE cases SET contact_window_start=0, contact_window_end=24 WHERE id=?", ("DXB-R-260901",))
    event = {"X-ClearPath-Event-Key": "demo-event-key"}
    admin = {"X-ClearPath-Admin-Key": "demo-admin-key"}
    capability = issue_case_capability("DXB-R-260901")
    tool = {
        "X-ClearPath-Tool-Key": "demo-tool-key",
        "X-ClearPath-Case-Capability": capability,
        "X-Conversation-Id": "conv_local_demo_001",
    }
    with TestClient(app) as c:
        pp("1) Return-for-amendment trigger (dry run)", c.post("/events/rejection", headers=event, json={"case_id": "DXB-R-260901", "force_dry_run": True}))
        pp("2) Pre-verification safe context", c.post("/tools/get-case-context", headers=tool, json={}))
        vr = c.post("/tools/verify-applicant", headers=tool, json={"one_time_code": "482731"})
        pp("3) Verification", vr)
        session = vr.json()["session_id"]
        pr = c.post("/tools/preview-correction", headers=tool, json={"session_id": session, "field_name": "passport_expiry"})
        pp("4) Server-proposed document value / read-back", pr)
        cm = c.post("/tools/commit-correction", headers=tool, json={
            "session_id": session, "action_token": pr.json()["action_token"], "explicit_confirmation": True,
        })
        pp("5) Atomic commit", cm)
        pp("6) Audit-chain verification", c.get("/admin/audit/verify", headers=admin))


if __name__ == "__main__":
    main()
