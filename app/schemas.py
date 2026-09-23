from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class CaseContextRequest(BaseModel):
    session_id: str | None = None


class VerifyApplicantRequest(BaseModel):
    one_time_code: str = Field(min_length=4, max_length=8)


class PreviewCorrectionRequest(BaseModel):
    session_id: str
    field_name: str
    # Optional speech capture is evidence only. It can never become the value written.
    caller_stated_value: str | None = Field(default=None, min_length=1, max_length=300)


class CommitCorrectionRequest(BaseModel):
    session_id: str
    action_token: str
    explicit_confirmation: Literal[True]


class PreviewDocumentRequest(BaseModel):
    session_id: str
    document_type: str


class CommitDocumentRequest(BaseModel):
    session_id: str
    action_token: str
    explicit_confirmation: Literal[True]


class BookAppointmentRequest(BaseModel):
    session_id: str
    slot: str
    location: str = "AMER Centre - Demo"
    explicit_confirmation: Literal[True]


class ReferHumanRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    reason_category: Literal["VERIFICATION_FAILED", "WRONG_PERSON", "VOICEMAIL", "UNSUPPORTED_REQUEST", "OTHER"] = "OTHER"


class FreezeReviewRequest(BaseModel):
    session_id: str
    reason: str = Field(min_length=3, max_length=500)
    reason_category: Literal["DISPUTE", "VULNERABILITY", "COMPLAINT"]
    vulnerability_signal: bool = False


class DemoCallContextRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=100)
    ttl_seconds: int = Field(default=1800, ge=60, le=3600)


class RejectionEvent(BaseModel):
    case_id: str
    force_dry_run: bool = False


class PostCallPayload(BaseModel):
    conversation_id: str
    case_id: str | None = None
    transcript: str | None = None
    outcome: str | None = None
    evaluation: dict[str, Any] = {}
