from __future__ import annotations

import re
from fastapi import APIRouter, HTTPException
from ..audit import verify_audit_chain, audit_head
from ..db import fetch_all, json_load
from ..security import redact_text

router = APIRouter(prefix="/demo-api", tags=["public demo evidence"])


def _mask_value(value: object) -> str:
    s = str(value or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return f"••••-{s[5:]}"
    if len(s) >= 5:
        return f"{s[:1]}••••{s[-2:]}"
    return "••••"


def _document_fields(document_id: str | None) -> dict:
    if not document_id:
        return {}
    rows = fetch_all("SELECT extracted_fields_json FROM documents WHERE id=?", (document_id,))
    return json_load(rows[0]["extracted_fields_json"]) if rows else {}


def _safe_case(row: dict) -> dict:
    allowed = json_load(row.pop("allowed_fields_json"))
    required = json_load(row.pop("required_documents_json"))
    current = json_load(row.pop("current_data_json"))
    legacy_authoritative = row.pop("authoritative_data_json", None)
    _ = legacy_authoritative  # retained in the DB only for backwards-compatible fixtures; not used as authority.
    authoritative = _document_fields(row.get("authoritative_document_id"))
    return {
        **row,
        "allowed_fields": allowed,
        "required_documents": required,
        "field_evidence": {
            field: {
                "current_masked": _mask_value(current.get(field)),
                "document_masked": _mask_value(authoritative.get(field)),
                "matches": str(current.get(field, "")) == str(authoritative.get(field, "")),
            }
            for field in sorted(set(current) | set(authoritative))
        },
    }


def _sanitize_audit_details(details: dict) -> dict:
    sensitive = {"before", "after", "old_value", "new_value", "session_id", "action_token", "token", "otp"}
    out = {}
    for key, value in details.items():
        if key in sensitive:
            out[key] = "[REDACTED]"
        elif key == "reason" and isinstance(value, str):
            out[key] = redact_text(value) or ""
        else:
            out[key] = value
    return out


@router.get("/cases")
def cases():
    rows = fetch_all(
        "SELECT id,preferred_language,contact_role,status,rejection_code,correction_deadline,allowed_fields_json,required_documents_json,current_data_json,authoritative_data_json,authoritative_document_id FROM cases ORDER BY id"
    )
    return [_safe_case(r) for r in rows]


@router.get("/cases/{case_id}")
def case_detail(case_id: str):
    rows = fetch_all(
        "SELECT id,preferred_language,contact_role,status,rejection_code,correction_deadline,allowed_fields_json,required_documents_json,current_data_json,authoritative_data_json,authoritative_document_id FROM cases WHERE id=?",
        (case_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="case_not_found")
    safe = _safe_case(rows[0])
    if safe.get("authoritative_document_id"):
        docs = fetch_all("SELECT id,version,method,sha256 FROM documents WHERE id=?", (safe["authoritative_document_id"],))
        safe["document_anchor"] = {"id": docs[0]["id"], "version": docs[0]["version"], "method": docs[0]["method"], "sha256_prefix": docs[0]["sha256"][:12]} if docs else None
    safe.pop("authoritative_document_id", None)
    return safe


@router.get("/audit")
def audit(case_id: str):
    rows = fetch_all("SELECT id,timestamp,case_id,event_type,outcome,actor,details_json,event_hash FROM audit_events WHERE case_id=? ORDER BY id", (case_id,))
    for r in rows:
        r["details"] = _sanitize_audit_details(json_load(r.pop("details_json")))
        r["event_hash"] = f"{r['event_hash'][:12]}…"
    return rows


@router.get("/audit/verify")
def verify():
    valid, checked = verify_audit_chain()
    head = audit_head()
    return {"valid": valid, "events_checked": checked, "head": {**head, "head_hash": f"{head['head_hash'][:12]}…" if head["head_hash"] != "GENESIS" else "GENESIS"}}
