from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import HTTPException

from ..audit import append_audit, audit_head
from ..db import connection, json_dump, json_load, utcnow
from ..policy import POLICIES, approved_message, validate_field_value, format_iso_date_ar
from ..mrz import extract_passport_fields
from ..security import hash_secret, random_id, sign_action_token, verify_action_token, verify_secret

CORRECTABLE_STATES = {"RETURNED_FOR_AMENDMENT"}
DOCUMENT_STATES = {"RETURNED_FOR_AMENDMENT", "MISSING_INFORMATION"}
ATTENDANCE_STATES = {"ATTENDANCE_REQUIRED"}
FREEZABLE_STATES = {"RETURNED_FOR_AMENDMENT", "MISSING_INFORMATION", "ATTENDANCE_REQUIRED", "CORRECTION_SUBMITTED"}
ALLOWED_APPOINTMENT_LOCATIONS = {"AMER Centre - Demo", "GDRFA Service Centre - Demo"}


def _dubai_today() -> date:
    return datetime.now(ZoneInfo("Asia/Dubai")).date()


def get_case(case_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="case_not_found")
    case = dict(row)
    case["allowed_fields"] = json_load(case.pop("allowed_fields_json"))
    case["required_documents"] = json_load(case.pop("required_documents_json"))
    case["current_data"] = json_load(case.pop("current_data_json"))
    case["authoritative_data"] = json_load(case.pop("authoritative_data_json"))
    case["contact_consent"] = bool(case["contact_consent"])
    case["requires_attendance"] = bool(case["requires_attendance"])
    case["verification_locked"] = bool(case["verification_locked"])
    return case


def _get_document(case: dict[str, Any]) -> dict[str, Any] | None:
    doc_id = case.get("authoritative_document_id")
    if not doc_id:
        return None
    with connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=? AND case_id=?", (doc_id, case["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="authoritative_document_missing")
    doc = dict(row)
    computed_hash = hashlib.sha256(doc["raw_reference"].encode()).hexdigest()
    if computed_hash != doc["sha256"]:
        raise HTTPException(status_code=409, detail="authoritative_document_integrity_failed")
    stored_fields = json_load(doc.pop("extracted_fields_json"))
    if doc["method"] == "ICAO9303_MRZ":
        try:
            extracted = extract_passport_fields(doc["raw_reference"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="authoritative_document_integrity_failed") from exc
        if extracted != stored_fields:
            raise HTTPException(status_code=409, detail="authoritative_document_extraction_mismatch")
        doc["extracted_fields"] = extracted
    else:
        doc["extracted_fields"] = stored_fields
    return doc


def _assert_case_actionable(case: dict[str, Any], action: str) -> None:
    try:
        deadline = date.fromisoformat(case["correction_deadline"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="invalid_case_deadline") from exc
    if _dubai_today() > deadline:
        raise HTTPException(status_code=409, detail="correction_deadline_expired")
    if case["status"] == "HUMAN_REVIEW":
        raise HTTPException(status_code=409, detail="case_frozen_for_human_review")
    allowed = {
        "correction": CORRECTABLE_STATES,
        "document": DOCUMENT_STATES,
        "appointment": ATTENDANCE_STATES,
    }[action]
    if case["status"] not in allowed:
        raise HTTPException(status_code=409, detail=f"invalid_state_for_{action}")


def public_case_context(case_id: str, session_id: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
    case = get_case(case_id)
    minimal = {
        "applicant_first_name": case["applicant_name"].split()[0],
        "preferred_language": case["preferred_language"],
        "contact_role": case.get("contact_role", "applicant"),
        "verification_required": True,
        "safe_statement": "Do not disclose application details until verification succeeds.",
    }
    if not session_id:
        return minimal
    _require_session(case_id, session_id, conversation_id)
    policy = POLICIES.get(case["rejection_code"])
    if not policy:
        raise HTTPException(status_code=422, detail="unknown_return_policy")
    doc = _get_document(case)
    return {
        **minimal,
        "verification_required": False,
        "status": case["status"],
        "return_code": case["rejection_code"],
        "approved_explanation": approved_message(case["rejection_code"], case["preferred_language"]) or case["rejection_message"],
        "correction_deadline": case["correction_deadline"],
        "correction_envelope": {
            "allowed_fields": case["allowed_fields"],
            "required_documents": case["required_documents"],
            "requires_attendance": case["requires_attendance"],
            "escalation_only": policy.escalation_only,
            "document_anchor_available": bool(doc),
        },
        "safe_statement": "The agent may resolve only the returned-for-amendment item. It cannot approve, reject, cancel, or start an application.",
    }


def verify_applicant(case_id: str, otp: str, conversation_id: str | None = None) -> dict[str, Any]:
    failure: tuple[int, str] | None = None
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            failure = (404, "case_not_found")
        elif row["verification_locked"]:
            append_audit(case_id, "verification", "blocked", "voice_agent", {"reason": "locked"}, conn=conn)
            failure = (423, "verification_locked")
        elif not verify_secret(otp, row["demo_otp_hash"]):
            attempts = int(row["failed_verification_attempts"]) + 1
            locked = 1 if attempts >= 3 else 0
            conn.execute(
                "UPDATE cases SET failed_verification_attempts=?, verification_locked=?, updated_at=? WHERE id=?",
                (attempts, locked, utcnow(), case_id),
            )
            append_audit(case_id, "verification", "denied", "voice_agent", {"attempt": attempts, "locked": bool(locked)}, conn=conn)
            failure = (401, "verification_failed")
        else:
            session_id = random_id("sess")
            expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            conn.execute(
                "INSERT INTO verification_sessions(id,case_id,conversation_id,verified,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                (session_id, case_id, conversation_id, 1, expires, utcnow()),
            )
            conn.execute("UPDATE cases SET failed_verification_attempts=0, updated_at=? WHERE id=?", (utcnow(), case_id))
            append_audit(case_id, "verification", "allowed", "voice_agent", {"conversation_bound": bool(conversation_id), "expires_at": expires}, conn=conn)
    if failure:
        raise HTTPException(status_code=failure[0], detail=failure[1])
    return {
        "verified": True,
        "session_id": session_id,
        "expires_at": expires,
        "case_context": public_case_context(case_id, session_id, conversation_id),
    }


def _require_session(case_id: str, session_id: str, conversation_id: str | None = None) -> None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM verification_sessions WHERE id=? AND case_id=? AND verified=1",
            (session_id, case_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="verified_session_required")
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="verification_session_expired")
    if conversation_id and row["conversation_id"] and row["conversation_id"] != conversation_id:
        raise HTTPException(status_code=403, detail="verification_session_conversation_mismatch")


def preview_correction(case_id: str, session_id: str, field_name: str, caller_stated_value: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
    """Create a preview from the document of record; caller speech never supplies the writable value."""
    _require_session(case_id, session_id, conversation_id)
    case = get_case(case_id)
    _assert_case_actionable(case, "correction")
    policy = POLICIES[case["rejection_code"]]
    if policy.escalation_only or case["requires_attendance"]:
        append_audit(case_id, "correction_preview", "blocked", "voice_agent", {"field": field_name, "reason": "non_correctable_case"})
        raise HTTPException(status_code=403, detail="case_not_voice_correctable")
    if field_name not in case["allowed_fields"] or field_name not in policy.allowed_fields:
        append_audit(case_id, "correction_preview", "blocked", "voice_agent", {"field": field_name, "reason": "outside_correction_envelope"})
        raise HTTPException(status_code=403, detail="field_outside_correction_envelope")

    doc = _get_document(case)
    if not doc:
        append_audit(case_id, "correction_preview", "blocked", "voice_agent", {"field": field_name, "reason": "authoritative_document_unavailable"})
        raise HTTPException(status_code=409, detail="authoritative_document_unavailable")
    authoritative = str(doc["extracted_fields"].get(field_name, "")).strip()
    if not authoritative:
        append_audit(case_id, "correction_preview", "blocked", "voice_agent", {"field": field_name, "reason": "authoritative_value_unavailable"})
        raise HTTPException(status_code=409, detail="authoritative_value_unavailable")
    valid, reason, normalized_authoritative = validate_field_value(field_name, authoritative)
    if not valid:
        append_audit(case_id, "correction_preview", "blocked", "system", {"field": field_name, "reason": reason})
        raise HTTPException(status_code=409, detail="authoritative_value_invalid")

    caller_statement_status = "NOT_PROVIDED"
    if caller_stated_value:
        stated_valid, stated_reason, normalized_stated = validate_field_value(field_name, caller_stated_value)
        if not stated_valid:
            caller_statement_status = "UNPARSED_STATEMENT"
            append_audit(case_id, "correction_preview", "unparsed", "voice_agent", {
                "field": field_name, "reason": stated_reason, "document_id": doc["id"], "document_version": doc["version"],
            })
        elif normalized_stated != normalized_authoritative:
            append_audit(case_id, "correction_preview", "disputed", "voice_agent", {
                "field": field_name, "reason": "caller_value_differs_from_document", "document_id": doc["id"], "document_version": doc["version"],
            })
            return {
                "status": "DISPUTED_VALUE",
                "requires_human": True,
                "recommended_action": "freeze_for_review_or_refer_human",
                "message": "The caller-stated value differs from the document of record. Do not write the caller value; route to qualified review or safe human referral.",
            }
        else:
            caller_statement_status = "MATCHED_DOCUMENT"

    current_value = str(case["current_data"].get(field_name, ""))
    if normalized_authoritative == current_value:
        raise HTTPException(status_code=409, detail="no_correction_needed")

    action_id = random_id("act")
    payload = {
        "field_name": field_name,
        "old_value": current_value,
        "new_value": normalized_authoritative,
        "source": "document_of_record",
        "document_id": doc["id"],
        "document_version": int(doc["version"]),
        "document_sha256": doc["sha256"],
        "extraction_method": doc["method"],
    }
    token = sign_action_token({"action_id": action_id, "case_id": case_id, "session_id": session_id, "action_type": "field_correction"})
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    if field_name == "passport_expiry":
        summary = f"Change passport expiry from {current_value or 'not provided'} to {normalized_authoritative}, matching the passport on file."
        current_value_ar = format_iso_date_ar(current_value) if current_value else "غير مسجل"
        authoritative_ar = format_iso_date_ar(normalized_authoritative)
        summary_ar = f"سيتم تعديل تاريخ انتهاء جواز السفر من {current_value_ar} إلى {authoritative_ar} ليتطابق مع جواز السفر الموجود بالملف."
    elif field_name == "passport_number":
        summary = f"Change passport number from {current_value or 'not provided'} to {normalized_authoritative}, matching the passport on file."
        summary_ar = f"سيتم تعديل رقم جواز السفر من {current_value or 'غير مسجل'} إلى {normalized_authoritative} ليتطابق مع جواز السفر الموجود بالملف."
    else:
        summary = f"Change {field_name.replace('_', ' ')} from {current_value or 'not provided'} to {normalized_authoritative}, matching the document of record."
        summary_ar = summary

    with connection() as conn:
        conn.execute(
            """INSERT INTO pending_actions(id,case_id,session_id,action_type,payload_json,spoken_summary,token_hash,expires_at,committed,created_at)
               VALUES(?,?,?,?,?,?,?,?,0,?)""",
            (action_id, case_id, session_id, "field_correction", json_dump(payload), summary, hash_secret(token), expires, utcnow()),
        )
    append_audit(case_id, "correction_preview", "allowed", "voice_agent", {
        "action_id": action_id, "field": field_name, "source": "document_of_record", "document_id": doc["id"], "document_version": doc["version"],
    })
    return {
        "action_token": token,
        "spoken_summary": summary,
        "spoken_summary_ar": summary_ar,
        "caller_statement_status": caller_statement_status,
        "source_evidence": {"document_id": doc["id"], "version": doc["version"], "method": doc["method"]},
        "instruction": "Read the summary back exactly. The caller may confirm or dispute it, but may not dictate a replacement value for this action.",
        "expires_at": expires,
        "audit_head": audit_head(),
    }


def _load_pending_from_token(case_id: str, session_id: str, token: str, expected_type: str, allow_committed: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = verify_action_token(token)
    if payload.get("case_id") != case_id or payload.get("session_id") != session_id or payload.get("action_type") != expected_type:
        raise HTTPException(status_code=403, detail="action_token_scope_mismatch")
    action_id = payload.get("action_id")
    with connection() as conn:
        row = conn.execute("SELECT * FROM pending_actions WHERE id=?", (action_id,)).fetchone()
    if not row or row["case_id"] != case_id or row["session_id"] != session_id:
        raise HTTPException(status_code=403, detail="pending_action_not_found")
    if row["committed"] and not allow_committed:
        raise HTTPException(status_code=409, detail="action_already_committed")
    if not verify_secret(token, row["token_hash"]):
        raise HTTPException(status_code=403, detail="action_token_invalid")
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="pending_action_expired")
    return dict(row), payload


def _idempotency_get(key: str, case_id: str, action_type: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT response_json,case_id,action_type FROM idempotency_keys WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    if row["case_id"] != case_id or row["action_type"] != action_type:
        raise HTTPException(status_code=409, detail="idempotency_key_scope_conflict")
    return json_load(row["response_json"])


def _idempotency_store_conn(conn, key: str, case_id: str, action_type: str, response: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO idempotency_keys(key,case_id,action_type,response_json,created_at) VALUES(?,?,?,?,?)",
        (key, case_id, action_type, json_dump(response), utcnow()),
    )


def _commit_correction_transaction(case_id: str, row: dict[str, Any], data: dict[str, Any], server_key: str) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        case_row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail="case_not_found")
        case = dict(case_row)
        case["allowed_fields"] = json_load(case.pop("allowed_fields_json"))
        case["current_data"] = json_load(case.pop("current_data_json"))
        case["authoritative_data"] = json_load(case.pop("authoritative_data_json"))
        case["requires_attendance"] = bool(case["requires_attendance"])
        _assert_case_actionable(case, "correction")

        if data["field_name"] not in case["allowed_fields"]:
            raise HTTPException(status_code=403, detail="correction_envelope_changed")
        if str(case["current_data"].get(data["field_name"], "")) != str(data["old_value"]):
            raise HTTPException(status_code=409, detail="correction_preview_stale")
        if case_row["authoritative_document_id"] != data["document_id"]:
            raise HTTPException(status_code=409, detail="document_of_record_replaced")
        doc = conn.execute("SELECT * FROM documents WHERE id=? AND case_id=?", (data["document_id"], case_id)).fetchone()
        if not doc or int(doc["version"]) != int(data["document_version"]) or doc["sha256"] != data["document_sha256"]:
            raise HTTPException(status_code=409, detail="document_of_record_changed")
        computed_hash = hashlib.sha256(doc["raw_reference"].encode()).hexdigest()
        if computed_hash != doc["sha256"]:
            raise HTTPException(status_code=409, detail="document_of_record_integrity_failed")
        extracted = json_load(doc["extracted_fields_json"])
        if doc["method"] == "ICAO9303_MRZ":
            try:
                recomputed = extract_passport_fields(doc["raw_reference"])
            except ValueError as exc:
                raise HTTPException(status_code=409, detail="document_of_record_integrity_failed") from exc
            if recomputed != extracted:
                raise HTTPException(status_code=409, detail="document_of_record_extraction_mismatch")
            extracted = recomputed
        valid, _, normalized_doc_value = validate_field_value(data["field_name"], str(extracted.get(data["field_name"], "")))
        if not valid or normalized_doc_value != str(data["new_value"]):
            raise HTTPException(status_code=409, detail="document_of_record_changed")

        claimed = conn.execute("UPDATE pending_actions SET committed=1 WHERE id=? AND committed=0", (row["id"],))
        if claimed.rowcount != 1:
            prior = conn.execute("SELECT response_json FROM idempotency_keys WHERE key=?", (server_key,)).fetchone()
            if prior:
                return json_load(prior["response_json"])
            raise HTTPException(status_code=409, detail="action_already_committed")

        current_data = case["current_data"]
        current_data[data["field_name"]] = data["new_value"]
        updated = conn.execute(
            "UPDATE cases SET current_data_json=?, status='CORRECTION_SUBMITTED', updated_at=? WHERE id=? AND status='RETURNED_FOR_AMENDMENT'",
            (json_dump(current_data), utcnow(), case_id),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="case_state_changed_during_commit")
        response = {
            "status": "CORRECTION_SUBMITTED", "updated_field": data["field_name"], "source": "document_of_record",
            "source_evidence": {"document_id": data["document_id"], "version": data["document_version"], "method": data["extraction_method"]},
        }
        _idempotency_store_conn(conn, server_key, case_id, "field_correction", response)
        append_audit(case_id, "correction_commit", "allowed", "voice_agent", {
            "action_id": row["id"], "field": data["field_name"], "before": data["old_value"], "after": data["new_value"],
            "source": "document_of_record", "document_id": data["document_id"], "document_version": data["document_version"],
        }, conn=conn)
    return response


def commit_correction(case_id: str, session_id: str, token: str, conversation_id: str | None = None) -> dict[str, Any]:
    _require_session(case_id, session_id, conversation_id)
    payload = verify_action_token(token)
    action_id = str(payload.get("action_id", ""))
    if payload.get("case_id") != case_id or payload.get("session_id") != session_id or payload.get("action_type") != "field_correction":
        raise HTTPException(status_code=403, detail="action_token_scope_mismatch")
    server_key = f"field_correction:{action_id}"
    previous = _idempotency_get(server_key, case_id, "field_correction")
    if previous is not None:
        previous["audit_head"] = audit_head()
        return previous
    row, _ = _load_pending_from_token(case_id, session_id, token, "field_correction", allow_committed=True)
    data = json_load(row["payload_json"])
    try:
        response = _commit_correction_transaction(case_id, row, data, server_key)
    except HTTPException as exc:
        append_audit(case_id, "correction_commit", "blocked", "backend_guard", {
            "action_id": row["id"], "field": data.get("field_name"), "reason": str(exc.detail),
            "document_id": data.get("document_id"), "document_version": data.get("document_version"),
        })
        raise
    response["audit_head"] = audit_head()
    return response


def preview_document(case_id: str, session_id: str, document_type: str, conversation_id: str | None = None) -> dict[str, Any]:
    _require_session(case_id, session_id, conversation_id)
    case = get_case(case_id)
    _assert_case_actionable(case, "document")
    if document_type not in case["required_documents"]:
        append_audit(case_id, "document_link_preview", "blocked", "voice_agent", {"document_type": document_type})
        raise HTTPException(status_code=403, detail="document_not_requested_for_case")
    action_id = random_id("act")
    payload = {"document_type": document_type}
    token = sign_action_token({"action_id": action_id, "case_id": case_id, "session_id": session_id, "action_type": "document_link"})
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    summary = f"Send an authority-approved upload route for the required {document_type.replace('_', ' ')}."
    with connection() as conn:
        conn.execute(
            """INSERT INTO pending_actions(id,case_id,session_id,action_type,payload_json,spoken_summary,token_hash,expires_at,committed,created_at)
               VALUES(?,?,?,?,?,?,?,?,0,?)""",
            (action_id, case_id, session_id, "document_link", json_dump(payload), summary, hash_secret(token), expires, utcnow()),
        )
    append_audit(case_id, "document_link_preview", "allowed", "voice_agent", {"action_id": action_id, "document_type": document_type})
    return {"action_token": token, "spoken_summary": summary, "expires_at": expires, "audit_head": audit_head()}


def commit_document_link(case_id: str, session_id: str, token: str, conversation_id: str | None = None) -> dict[str, Any]:
    _require_session(case_id, session_id, conversation_id)
    payload = verify_action_token(token)
    server_key = f"document_link:{payload.get('action_id', '')}"
    previous = _idempotency_get(server_key, case_id, "document_link")
    if previous is not None:
        return previous
    row, _ = _load_pending_from_token(case_id, session_id, token, "document_link")
    case = get_case(case_id)
    _assert_case_actionable(case, "document")
    data = json_load(row["payload_json"])
    upload_token = sign_action_token({"case_id": case_id, "document_type": data["document_type"], "action_type": "upload_access"}, ttl_seconds=900)
    response = {"status": "upload_link_created", "document_type": data["document_type"], "secure_upload_path": f"/demo-upload/{upload_token}", "expires_in_minutes": 15}
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claimed = conn.execute("UPDATE pending_actions SET committed=1 WHERE id=? AND committed=0", (row["id"],))
        if claimed.rowcount != 1:
            raise HTTPException(status_code=409, detail="action_already_committed")
        _idempotency_store_conn(conn, server_key, case_id, "document_link", response)
        append_audit(case_id, "document_link_commit", "allowed", "voice_agent", {"document_type": data["document_type"], "signed_link": True}, conn=conn)
    response["audit_head"] = audit_head()
    return response


def book_appointment(case_id: str, session_id: str, slot: str, location: str, conversation_id: str | None = None) -> dict[str, Any]:
    _require_session(case_id, session_id, conversation_id)
    case = get_case(case_id)
    _assert_case_actionable(case, "appointment")
    if location not in ALLOWED_APPOINTMENT_LOCATIONS:
        raise HTTPException(status_code=422, detail="appointment_location_not_allowed")
    try:
        slot_dt = datetime.fromisoformat(slot)
        if slot_dt.tzinfo is None:
            raise ValueError("timezone required")
        dubai_slot = slot_dt.astimezone(ZoneInfo("Asia/Dubai"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="appointment_slot_must_be_iso8601_with_timezone") from exc
    now_dubai = datetime.now(ZoneInfo("Asia/Dubai"))
    if not (now_dubai < dubai_slot <= now_dubai + timedelta(days=45)):
        raise HTTPException(status_code=422, detail="appointment_slot_outside_booking_horizon")
    if dubai_slot.hour < 8 or dubai_slot.hour >= 18 or dubai_slot.minute not in {0, 30}:
        raise HTTPException(status_code=422, detail="appointment_slot_outside_demo_service_hours")
    server_key = f"appointment:{case_id}"
    previous = _idempotency_get(server_key, case_id, "appointment")
    if previous is not None:
        return previous
    appointment_id = random_id("apt")
    response = {"status": "BOOKED", "appointment_id": appointment_id, "slot": slot, "location": location}
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT * FROM appointments WHERE case_id=? AND status='BOOKED'", (case_id,)).fetchone()
        if existing:
            return {"status": "already_booked", "appointment_id": existing["id"], "slot": existing["slot"], "location": existing["location"]}
        conn.execute("INSERT INTO appointments(id,case_id,slot,location,status,created_at) VALUES(?,?,?,?,?,?)", (appointment_id, case_id, slot, location, "BOOKED", utcnow()))
        _idempotency_store_conn(conn, server_key, case_id, "appointment", response)
        append_audit(case_id, "appointment", "allowed", "voice_agent", {"appointment_id": appointment_id, "slot": slot, "location": location}, conn=conn)
    response["audit_head"] = audit_head()
    return response


def refer_to_human(case_id: str, reason: str, reason_category: str) -> dict[str, Any]:
    """Safe referral. No verification required, no state mutation, no protected data returned."""
    _ = get_case(case_id)
    append_audit(case_id, "human_referral", "allowed", "voice_agent", {"reason": reason, "reason_category": reason_category, "case_frozen": False})
    return {"status": "REFERRED", "case_frozen": False, "message": "A qualified human queue has been requested."}


def freeze_for_review(case_id: str, session_id: str, reason: str, reason_category: str, vulnerability_signal: bool, conversation_id: str | None = None) -> dict[str, Any]:
    _require_session(case_id, session_id, conversation_id)
    case = get_case(case_id)
    if case["status"] not in FREEZABLE_STATES:
        raise HTTPException(status_code=409, detail="case_not_freezable_from_current_state")
    priority = "urgent" if vulnerability_signal or reason_category == "VULNERABILITY" else "standard"
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute(
            f"UPDATE cases SET status='HUMAN_REVIEW', updated_at=? WHERE id=? AND status IN ({','.join('?' * len(FREEZABLE_STATES))})",
            (utcnow(), case_id, *sorted(FREEZABLE_STATES)),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="case_state_changed_before_freeze")
        append_audit(case_id, "human_escalation", "allowed", "voice_agent", {"reason": reason, "reason_category": reason_category, "priority": priority, "case_frozen": True}, conn=conn)
    return {"status": "HUMAN_REVIEW", "priority": priority, "case_frozen": True, "message": "The case is frozen for qualified human review.", "audit_head": audit_head()}
