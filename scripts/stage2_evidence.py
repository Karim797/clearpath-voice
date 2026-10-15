"""Run isolated synthetic API scenarios; never calls ElevenLabs or resets a user's DB."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(output: Path) -> None:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clearpath-stage2-") as temp:
        env = dict(os.environ)
        env.update(DATABASE_PATH=str(Path(temp) / "evidence.db"), ENVIRONMENT="development",
                   PUBLIC_BASE_URL="http://localhost:8000", DEMO_MODE="true",
                   TOOL_API_KEY="local-evidence-tool", EVENT_API_KEY="local-evidence-event",
                   ADMIN_API_KEY="local-evidence-admin", ACTION_SIGNING_SECRET="local-evidence-action",
                   AUDIT_SIGNING_SECRET="local-evidence-audit")
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(output)],
                       cwd=ROOT, env=env, check=True)

def worker(output: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import fetch_all
    from app.services.call_context import issue_case_capability
    from scripts.seed import main as seed
    results = []
    def headers(label):
        return {"X-ClearPath-Tool-Key": os.environ["TOOL_API_KEY"],
                "X-ClearPath-Case-Capability": issue_case_capability("DXB-R-260901"),
                "X-Conversation-Id": f"local_api_{label}"}
    with TestClient(app) as client:
        for scenario in ("correction", "dispute", "verification_lockout", "no_consent", "legal_escalation"):
            seed(reset=True)
            checks = []
            def check(name, value):
                if not value:
                    raise RuntimeError(f"{scenario}: {name}")
                checks.append({"check": name, "passed": True})
            if scenario in {"correction", "dispute", "verification_lockout"}:
                h = headers(scenario)
                context = client.post("/tools/get-case-context", headers=h, json={}).json()
                check("Pre-verification details withheld", context.get("verification_required") is True and "return_code" not in context)
                if scenario == "verification_lockout":
                    for _ in range(3):
                        r = client.post("/tools/verify-applicant", headers=h, json={"one_time_code": "000000"})
                        check("Incorrect verification rejected", r.status_code == 401)
                    r = client.post("/tools/verify-applicant", headers=h, json={"one_time_code": "482731"})
                    check("Automation locked after three failures", r.status_code == 423)
                    outcome = "VERIFICATION_LOCKED"
                else:
                    r = client.post("/tools/verify-applicant", headers=h, json={"one_time_code": "482731"})
                    check("Verification succeeded", r.status_code == 200)
                    session = r.json()["session_id"]
                    body = {"session_id": session, "field_name": "passport_expiry"}
                    if scenario == "dispute":
                        body["caller_stated_value"] = "2029-02-11"
                    r = client.post("/tools/preview-correction", headers=h, json=body)
                    check("Preview returned", r.status_code == 200)
                    preview = r.json()
                    if scenario == "dispute":
                        check("Conflicting value receives no commit token", preview.get("requires_human") is True and "action_token" not in preview)
                        r = client.post("/tools/freeze-for-review", headers=h, json={"session_id": session, "reason": "Synthetic caller disputes document value", "reason_category": "DISPUTE"})
                        check("Case frozen for qualified human review", r.status_code == 200 and r.json().get("case_frozen") is True)
                        outcome = "HUMAN_REVIEW"
                    else:
                        check("Document of record anchors preview", preview.get("source_evidence", {}).get("method") == "ICAO9303_MRZ")
                        body = {"session_id": session, "action_token": preview["action_token"], "explicit_confirmation": True}
                        a = client.post("/tools/commit-correction", headers=h, json=body)
                        b = client.post("/tools/commit-correction", headers=h, json=body)
                        check("Correction submitted, never application approval", a.status_code == 200 and a.json().get("status") == "CORRECTION_SUBMITTED")
                        check("Retry is idempotent", b.status_code == 200 and a.json() == b.json())
                        outcome = "CORRECTION_SUBMITTED"
            else:
                case = "DXB-R-260905" if scenario == "no_consent" else "DXB-R-260904"
                r = client.post("/events/rejection", headers={"X-ClearPath-Event-Key": os.environ["EVENT_API_KEY"]}, json={"case_id": case, "force_dry_run": True})
                if scenario == "no_consent":
                    check("No consent blocks outbound dispatch", r.status_code == 403 and r.json().get("detail") == "contact_consent_required")
                    outcome = "CONTACT_BLOCKED"
                else:
                    check("Legal case routed to human queue", r.status_code == 200 and r.json().get("status") == "human_queue")
                    outcome = "HUMAN_QUEUE"
            if scenario != "correction":
                committed = fetch_all("SELECT id FROM pending_actions WHERE committed=1")
                check("No sensitive mutation committed", not committed)
            audit = client.get("/admin/audit/verify", headers={"X-ClearPath-Admin-Key": os.environ["ADMIN_API_KEY"]}).json()
            check("Audit chain verifies", audit.get("valid") is True)
            results.append({"scenario": scenario, "outcome": outcome, "checks": checks,
                            "audit_events_checked": audit["events_checked"], "evidence_kind": "local_synthetic_api"})
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "scope": "Local synthetic backend scenarios. Not voice calls, transcripts, ElevenLabs Agent Testing, or live latency evidence.",
              "scenarios_passed": len(results), "scenarios_total": 5, "results": results}
    (output / "backend-scenarios.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Passed {len(results)}/5 isolated API scenarios. Evidence: {output / 'backend-scenarios.json'}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]))
    else:
        run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runtime" / "stage2")
