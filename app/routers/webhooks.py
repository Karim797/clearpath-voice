from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..audit import append_audit
from ..config import is_local_development, settings
from ..db import connection, json_dump, utcnow
from ..security import redact_text
from ..services.call_context import resolve_case_from_conversation

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_elevenlabs_signature(raw_body: bytes, header: str | None) -> None:
    if not settings.elevenlabs_webhook_secret:
        if is_local_development():
            return
        raise HTTPException(status_code=503, detail="webhook_secret_not_configured")
    if not header:
        raise HTTPException(status_code=401, detail="missing_elevenlabs_signature")
    try:
        values = dict(part.split("=", 1) for part in header.split(","))
        timestamp = values["t"]
        supplied = values["v0"]
        if abs(time.time() - int(timestamp)) > 30 * 60:
            raise ValueError("stale signature")
        message = timestamp.encode() + b"." + raw_body
        expected = hmac.new(settings.elevenlabs_webhook_secret.encode(), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid signature")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid_elevenlabs_signature") from exc


def _flatten_transcript(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for turn in turns:
        role = str(turn.get("role", "unknown"))
        message = turn.get("message")
        if message:
            lines.append(f"{role}: {message}")
    return "\n".join(lines)


@router.post("/elevenlabs/post-call")
async def post_call(request: Request):
    raw = await request.body()
    _verify_elevenlabs_signature(raw, request.headers.get("elevenlabs-signature"))
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc

    if event.get("type") != "post_call_transcription":
        return {"status": "ignored", "type": event.get("type")}
    data = event.get("data") or {}
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=422, detail="missing_conversation_id")
    case_id = resolve_case_from_conversation(str(conversation_id))
    if not case_id:
        raise HTTPException(status_code=409, detail="unbound_conversation")

    transcript = redact_text(_flatten_transcript(data.get("transcript") or []))
    analysis = data.get("analysis") or {}
    outcome = str(analysis.get("call_successful", data.get("status", "unknown")))
    payload_hash = hashlib.sha256(raw).hexdigest()

    conflict = False
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        inserted = conn.execute(
            """INSERT OR IGNORE INTO post_call_reports(conversation_id,case_id,outcome,transcript_redacted,evaluation_json,payload_hash,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (conversation_id, case_id, outcome, transcript, json_dump(analysis), payload_hash, utcnow()),
        )
        if inserted.rowcount == 0:
            existing = conn.execute("SELECT payload_hash FROM post_call_reports WHERE conversation_id=?", (conversation_id,)).fetchone()
            if existing and existing["payload_hash"] == payload_hash:
                return {"status": "duplicate_ignored"}
            conflict = True
        else:
            append_audit(case_id, "post_call_report", "stored", "elevenlabs_webhook", {
                "conversation_id": conversation_id, "outcome": outcome, "transcript_redacted": True,
                "signature_verified": bool(settings.elevenlabs_webhook_secret),
            }, conn=conn)
    if conflict:
        append_audit(case_id, "post_call_report", "conflict", "elevenlabs_webhook", {"conversation_id": conversation_id, "reason": "payload_hash_mismatch"})
        raise HTTPException(status_code=409, detail="post_call_payload_conflict")
    return {"status": "received"}
