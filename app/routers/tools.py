from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from ..schemas import (
    BookAppointmentRequest, CaseContextRequest, CommitCorrectionRequest, CommitDocumentRequest,
    FreezeReviewRequest, PreviewCorrectionRequest, PreviewDocumentRequest, ReferHumanRequest,
    VerifyApplicantRequest,
)
from ..security import require_tool_key
from ..services.call_context import resolve_context_from_capability
from ..services.case_service import (
    book_appointment, commit_correction, commit_document_link, freeze_for_review, preview_correction,
    preview_document, public_case_context, refer_to_human, verify_applicant,
)

router = APIRouter(prefix="/tools", tags=["ElevenLabs tools"], dependencies=[Depends(require_tool_key)])


def _context(
    x_clearpath_case_capability: str = Header(default=""),
    x_conversation_id: str = Header(default=""),
) -> dict[str, str | None]:
    if not x_clearpath_case_capability:
        raise HTTPException(status_code=401, detail="missing_case_capability")
    return resolve_context_from_capability(x_clearpath_case_capability, x_conversation_id or None)


@router.post("/get-case-context")
def get_case_context(req: CaseContextRequest, ctx: dict = Depends(_context)):
    return public_case_context(str(ctx["case_id"]), req.session_id, ctx.get("conversation_id"))


@router.post("/verify-applicant")
def verify(req: VerifyApplicantRequest, ctx: dict = Depends(_context)):
    return verify_applicant(str(ctx["case_id"]), req.one_time_code, conversation_id=ctx.get("conversation_id"))


@router.post("/preview-correction")
def preview(req: PreviewCorrectionRequest, ctx: dict = Depends(_context)):
    return preview_correction(
        str(ctx["case_id"]), req.session_id, req.field_name, req.caller_stated_value, ctx.get("conversation_id")
    )


@router.post("/commit-correction")
def commit(req: CommitCorrectionRequest, ctx: dict = Depends(_context)):
    return commit_correction(str(ctx["case_id"]), req.session_id, req.action_token, ctx.get("conversation_id"))


@router.post("/preview-document-link")
def preview_doc(req: PreviewDocumentRequest, ctx: dict = Depends(_context)):
    return preview_document(str(ctx["case_id"]), req.session_id, req.document_type, ctx.get("conversation_id"))


@router.post("/commit-document-link")
def commit_doc(req: CommitDocumentRequest, ctx: dict = Depends(_context)):
    return commit_document_link(str(ctx["case_id"]), req.session_id, req.action_token, ctx.get("conversation_id"))


@router.post("/book-appointment")
def appointment(req: BookAppointmentRequest, ctx: dict = Depends(_context)):
    return book_appointment(str(ctx["case_id"]), req.session_id, req.slot, req.location, ctx.get("conversation_id"))


@router.post("/refer-human")
def refer_human(req: ReferHumanRequest, ctx: dict = Depends(_context)):
    return refer_to_human(str(ctx["case_id"]), req.reason, req.reason_category)


@router.post("/freeze-for-review")
def freeze_review(req: FreezeReviewRequest, ctx: dict = Depends(_context)):
    return freeze_for_review(
        str(ctx["case_id"]), req.session_id, req.reason, req.reason_category, req.vulnerability_signal, ctx.get("conversation_id")
    )
