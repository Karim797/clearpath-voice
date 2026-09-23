from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from ..db import connection, utcnow
from ..security import hash_secret, sign_action_token, verify_action_token


def issue_case_capability(case_id: str, ttl_seconds: int = 1800) -> str:
    token = sign_action_token({"case_id": case_id, "action_type": "call_context"}, ttl_seconds=ttl_seconds)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO call_contexts(capability_hash,case_id,conversation_id,expires_at,created_at) VALUES(?,?,?,?,?)",
            (hash_secret(token), case_id, None, expires, utcnow()),
        )
    return token


def _validate_capability_payload(capability: str) -> tuple[str, str]:
    payload = verify_action_token(capability)
    if payload.get("action_type") != "call_context":
        raise HTTPException(status_code=403, detail="invalid_case_capability_scope")
    case_id = str(payload.get("case_id", ""))
    if not case_id:
        raise HTTPException(status_code=403, detail="invalid_case_capability_scope")
    return case_id, hash_secret(capability)


def bind_conversation(capability: str, conversation_id: str) -> None:
    if not conversation_id:
        raise HTTPException(status_code=422, detail="conversation_id_required")
    case_id, capability_hash = _validate_capability_payload(capability)
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT case_id,conversation_id,expires_at FROM call_contexts WHERE capability_hash=?",
            (capability_hash,),
        ).fetchone()
        if not row or row["case_id"] != case_id:
            raise HTTPException(status_code=403, detail="case_capability_not_registered")
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="case_capability_expired")
        if row["conversation_id"] and row["conversation_id"] != conversation_id:
            raise HTTPException(status_code=403, detail="conversation_binding_mismatch")
        if not row["conversation_id"]:
            try:
                conn.execute(
                    "UPDATE call_contexts SET conversation_id=? WHERE capability_hash=? AND conversation_id IS NULL",
                    (conversation_id, capability_hash),
                )
            except Exception as exc:
                raise HTTPException(status_code=403, detail="conversation_binding_conflict") from exc


def resolve_context_from_capability(capability: str, conversation_id: str | None = None) -> dict[str, str | None]:
    case_id, capability_hash = _validate_capability_payload(capability)
    if conversation_id:
        bind_conversation(capability, conversation_id)
    with connection() as conn:
        row = conn.execute(
            "SELECT case_id,conversation_id,expires_at FROM call_contexts WHERE capability_hash=?",
            (capability_hash,),
        ).fetchone()
    if not row or row["case_id"] != case_id:
        raise HTTPException(status_code=403, detail="case_capability_not_registered")
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="case_capability_expired")
    if conversation_id and row["conversation_id"] != conversation_id:
        raise HTTPException(status_code=403, detail="conversation_binding_mismatch")
    return {"case_id": case_id, "conversation_id": row["conversation_id"]}


def resolve_case_from_capability(capability: str) -> str:
    return str(resolve_context_from_capability(capability)["case_id"])


def resolve_case_from_conversation(conversation_id: str) -> str | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT case_id FROM call_contexts WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
    return str(row["case_id"]) if row else None
