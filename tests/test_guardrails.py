from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

from app.db import connection
from app.services.call_context import issue_case_capability


def _headers(case_id: str, conversation_id: str) -> dict[str, str]:
    capability = issue_case_capability(case_id)
    return {
        "X-ClearPath-Tool-Key": os.environ["TOOL_API_KEY"],
        "X-ClearPath-Case-Capability": capability,
        "X-Conversation-Id": conversation_id,
    }


def _verify(client, headers: dict[str, str], otp: str) -> str:
    response = client.post("/tools/verify-applicant", headers=headers, json={"one_time_code": otp})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _preview_primary(client, headers: dict[str, str], session_id: str) -> dict:
    response = client.post(
        "/tools/preview-correction",
        headers=headers,
        json={"session_id": session_id, "field_name": "passport_expiry"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_preverification_context_hides_case_detail(client, primary_headers):
    response = client.post("/tools/get-case-context", headers=primary_headers, json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verification_required"] is True
    assert "return_code" not in payload
    assert "correction_envelope" not in payload
    assert "correction_deadline" not in payload


def test_tool_authentication_is_required(client, primary_headers):
    headers = dict(primary_headers)
    headers["X-ClearPath-Tool-Key"] = "wrong-key"
    response = client.post("/tools/get-case-context", headers=headers, json={})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_tool_credentials"


def test_case_capability_binds_to_one_conversation(client):
    capability = issue_case_capability("DXB-R-260901")
    base = {
        "X-ClearPath-Tool-Key": os.environ["TOOL_API_KEY"],
        "X-ClearPath-Case-Capability": capability,
    }
    first = client.post(
        "/tools/get-case-context",
        headers={**base, "X-Conversation-Id": "conv_a"},
        json={},
    )
    assert first.status_code == 200

    second = client.post(
        "/tools/get-case-context",
        headers={**base, "X-Conversation-Id": "conv_b"},
        json={},
    )
    assert second.status_code == 403
    assert second.json()["detail"] == "conversation_binding_mismatch"


def test_three_failed_otps_lock_automation(client):
    headers = _headers("DXB-R-260901", "conv_lock")
    for _ in range(3):
        response = client.post(
            "/tools/verify-applicant",
            headers=headers,
            json={"one_time_code": "000000"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "verification_failed"

    locked = client.post(
        "/tools/verify-applicant",
        headers=headers,
        json={"one_time_code": "482731"},
    )
    assert locked.status_code == 423
    assert locked.json()["detail"] == "verification_locked"


def test_successful_verification_returns_conversation_bound_session(client):
    headers = _headers("DXB-R-260901", "conv_verify")
    session_id = _verify(client, headers, "482731")
    assert session_id.startswith("sess_")

    context = client.post(
        "/tools/get-case-context",
        headers=headers,
        json={"session_id": session_id},
    )
    assert context.status_code == 200
    payload = context.json()
    assert payload["verification_required"] is False
    assert payload["return_code"] == "PASSPORT_EXPIRY_MISMATCH"


def test_caller_cannot_dictate_sensitive_identity_value(client):
    headers = _headers("DXB-R-260901", "conv_dispute")
    session_id = _verify(client, headers, "482731")

    response = client.post(
        "/tools/preview-correction",
        headers=headers,
        json={
            "session_id": session_id,
            "field_name": "passport_expiry",
            "caller_stated_value": "2029-02-11",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DISPUTED_VALUE"
    assert payload["requires_human"] is True
    assert "action_token" not in payload


def test_preview_value_comes_from_document_of_record(client):
    headers = _headers("DXB-R-260901", "conv_doc")
    session_id = _verify(client, headers, "482731")
    preview = _preview_primary(client, headers, session_id)

    assert "2028-02-11" in preview["spoken_summary"]
    assert preview["source_evidence"]["method"] == "ICAO9303_MRZ"
    assert preview["caller_statement_status"] == "NOT_PROVIDED"


def test_commit_schema_requires_explicit_confirmation(client):
    headers = _headers("DXB-R-260901", "conv_confirm")
    session_id = _verify(client, headers, "482731")
    preview = _preview_primary(client, headers, session_id)

    response = client.post(
        "/tools/commit-correction",
        headers=headers,
        json={
            "session_id": session_id,
            "action_token": preview["action_token"],
            "explicit_confirmation": False,
        },
    )
    assert response.status_code == 422


def test_high_stakes_commit_rejects_forged_session(client):
    headers = _headers("DXB-R-260901", "conv_forged")
    session_id = _verify(client, headers, "482731")
    preview = _preview_primary(client, headers, session_id)

    response = client.post(
        "/tools/commit-correction",
        headers=headers,
        json={
            "session_id": "sess_forged",
            "action_token": preview["action_token"],
            "explicit_confirmation": True,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "verified_session_required"


def test_document_tampering_invalidates_high_stakes_commit(client):
    headers = _headers("DXB-R-260901", "conv_tamper")
    session_id = _verify(client, headers, "482731")
    preview = _preview_primary(client, headers, session_id)

    with connection() as conn:
        conn.execute(
            "UPDATE documents SET raw_reference = raw_reference || 'X' WHERE id=?",
            (preview["source_evidence"]["document_id"],),
        )

    response = client.post(
        "/tools/commit-correction",
        headers=headers,
        json={
            "session_id": session_id,
            "action_token": preview["action_token"],
            "explicit_confirmation": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "document_of_record_integrity_failed"


def test_successful_commit_is_document_grounded_and_idempotent(client):
    headers = _headers("DXB-R-260901", "conv_commit")
    session_id = _verify(client, headers, "482731")
    preview = _preview_primary(client, headers, session_id)
    request = {
        "session_id": session_id,
        "action_token": preview["action_token"],
        "explicit_confirmation": True,
    }

    first = client.post("/tools/commit-correction", headers=headers, json=request)
    second = client.post("/tools/commit-correction", headers=headers, json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "CORRECTION_SUBMITTED"
    assert first.json()["source"] == "document_of_record"
    assert second.json()["status"] == "CORRECTION_SUBMITTED"


def test_no_contact_consent_blocks_outbound_dispatch(client):
    response = client.post(
        "/events/rejection",
        headers={"X-ClearPath-Event-Key": os.environ["EVENT_API_KEY"]},
        json={"case_id": "DXB-R-260905", "force_dry_run": True},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "contact_consent_required"


def test_escalation_only_case_goes_to_human_queue(client):
    response = client.post(
        "/events/rejection",
        headers={"X-ClearPath-Event-Key": os.environ["EVENT_API_KEY"]},
        json={"case_id": "DXB-R-260904", "force_dry_run": True},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "human_queue", "reason": "escalation_only_policy"}


def test_dispute_can_freeze_case_for_human_review(client):
    headers = _headers("DXB-R-260901", "conv_freeze")
    session_id = _verify(client, headers, "482731")

    response = client.post(
        "/tools/freeze-for-review",
        headers=headers,
        json={
            "session_id": session_id,
            "reason": "Caller disputes the document-of-record value.",
            "reason_category": "DISPUTE",
            "vulnerability_signal": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "HUMAN_REVIEW"
    assert response.json()["case_frozen"] is True


def test_post_call_webhook_verifies_signature_redacts_and_deduplicates(client):
    conversation_id = "conv_post_call"
    headers = _headers("DXB-R-260901", conversation_id)

    # First tool call binds the capability to the conversation ID.
    bound = client.post("/tools/get-case-context", headers=headers, json={})
    assert bound.status_code == 200

    event = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": conversation_id,
            "status": "done",
            "transcript": [
                {"role": "agent", "message": "Please verify the one-time code."},
                {"role": "user", "message": "My code is 482731 and my phone is +971500000101."},
            ],
            "analysis": {"call_successful": True, "guardrail_passed": True},
        },
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        os.environ["ELEVENLABS_WEBHOOK_SECRET"].encode(),
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    webhook_headers = {
        "Content-Type": "application/json",
        "ElevenLabs-Signature": f"t={timestamp},v0={signature}",
    }

    first = client.post("/webhooks/elevenlabs/post-call", content=raw, headers=webhook_headers)
    second = client.post("/webhooks/elevenlabs/post-call", content=raw, headers=webhook_headers)
    assert first.status_code == 200
    assert first.json()["status"] == "received"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_ignored"

    with connection() as conn:
        stored = conn.execute(
            "SELECT transcript_redacted FROM post_call_reports WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
    assert stored is not None
    transcript = stored["transcript_redacted"]
    assert "482731" not in transcript
    assert "+971500000101" not in transcript
    assert "[REDACTED_CODE]" in transcript
    assert "[REDACTED_PHONE]" in transcript


def test_audit_chain_verifies_after_security_events(client):
    headers = _headers("DXB-R-260901", "conv_audit")
    _verify(client, headers, "482731")

    response = client.get(
        "/admin/audit/verify",
        headers={"X-ClearPath-Admin-Key": os.environ["ADMIN_API_KEY"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["events_checked"] >= 1
