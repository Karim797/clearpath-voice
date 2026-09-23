from __future__ import annotations

from fastapi import APIRouter, Depends

from ..audit import verify_audit_chain, audit_head
from ..db import fetch_all, json_load
from ..security import mask_phone, require_admin_key
from ..services.case_service import get_case
from ..services.call_context import issue_case_capability
from ..schemas import DemoCallContextRequest

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


@router.get("/cases")
def list_cases():
    rows = fetch_all("SELECT id,applicant_name,phone,preferred_language,status,rejection_code,correction_deadline FROM cases ORDER BY id")
    for row in rows:
        row["phone"] = mask_phone(row["phone"])
    return rows


@router.get("/cases/{case_id}")
def case_details(case_id: str):
    case = get_case(case_id)
    case["phone"] = mask_phone(case["phone"])
    case.pop("demo_otp_hash", None)
    return case


@router.get("/audit")
def audit(case_id: str | None = None):
    if case_id:
        rows = fetch_all("SELECT * FROM audit_events WHERE case_id=? ORDER BY id", (case_id,))
    else:
        rows = fetch_all("SELECT * FROM audit_events ORDER BY id DESC LIMIT 200")
    for row in rows:
        row["details"] = json_load(row.pop("details_json"))
    return rows


@router.get("/audit/verify")
def verify_audit():
    valid, checked = verify_audit_chain()
    return {"valid": valid, "events_checked": checked, "head": audit_head()}


@router.post("/demo-call-context")
def demo_call_context(req: DemoCallContextRequest):
    """Issue a short-lived capability for a synthetic Stage-1 web demo. Admin-only.

    The first ElevenLabs tool call binds the capability to system__conversation_id.
    """
    _ = get_case(req.case_id)
    capability = issue_case_capability(req.case_id, ttl_seconds=req.ttl_seconds)
    return {
        "case_id": req.case_id,
        "secret__case_capability": capability,
        "expires_in_seconds": req.ttl_seconds,
        "tool_header": "X-ClearPath-Case-Capability",
        "conversation_header": "X-Conversation-Id",
    }
