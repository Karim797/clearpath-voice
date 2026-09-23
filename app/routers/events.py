from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException

from ..audit import append_audit
from ..policy import POLICIES
from ..schemas import RejectionEvent
from ..security import require_event_key
from ..services.case_service import get_case
from ..services.elevenlabs import initiate_outbound_call

router = APIRouter(prefix="/events", tags=["orchestration"], dependencies=[Depends(require_event_key)])


@router.post("/rejection")
async def rejection_event(event: RejectionEvent):
    case = get_case(event.case_id)
    policy = POLICIES.get(case["rejection_code"])
    if not case["contact_consent"]:
        append_audit(case["id"], "outbound_eligibility", "blocked", "orchestrator", {"reason": "no_contact_consent"})
        raise HTTPException(status_code=403, detail="contact_consent_required")
    if policy and policy.escalation_only:
        append_audit(case["id"], "outbound_eligibility", "human_queue", "orchestrator", {"reason": "escalation_only_policy"})
        return {"status": "human_queue", "reason": "escalation_only_policy"}
    hour = datetime.now(ZoneInfo("Asia/Dubai")).hour
    if not (case["contact_window_start"] <= hour < case["contact_window_end"]):
        append_audit(case["id"], "outbound_eligibility", "deferred", "orchestrator", {"reason": "outside_contact_window", "hour": hour})
        return {"status": "deferred", "reason": "outside_contact_window"}
    if case["status"] not in {"RETURNED_FOR_AMENDMENT", "MISSING_INFORMATION", "ATTENDANCE_REQUIRED"}:
        raise HTTPException(status_code=409, detail="case_not_eligible_for_resolution_call")
    return await initiate_outbound_call(case, force_dry_run=event.force_dry_run)
