from __future__ import annotations

import hashlib
import hmac
import sqlite3
from typing import Any

from .config import settings
from .db import connection, json_dump, utcnow
from .security import random_id


def _checkpoint_digest(count: int, head_hash: str) -> str:
    canonical = f"{count}|{head_hash}"
    return hmac.new(settings.audit_signing_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def append_audit(case_id: str | None, event_type: str, outcome: str, actor: str, details: dict[str, Any], conn: sqlite3.Connection | None = None) -> str:
    owns_conn = conn is None
    ctx = connection() if owns_conn else None
    db = ctx.__enter__() if ctx else conn
    try:
        if owns_conn:
            db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = previous[0] if previous else "GENESIS"
        event_id = random_id("evt")
        timestamp = utcnow()
        details_json = json_dump(details)
        canonical = "|".join([event_id, timestamp, case_id or "", event_type, outcome, actor, details_json, prev_hash])
        digest = hmac.new(settings.audit_signing_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        db.execute(
            """INSERT INTO audit_events(event_id,timestamp,case_id,event_type,outcome,actor,details_json,prev_hash,event_hash)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (event_id, timestamp, case_id, event_type, outcome, actor, details_json, prev_hash, digest),
        )
        count = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        checkpoint_hash = _checkpoint_digest(count, digest)
        db.execute(
            """INSERT INTO audit_checkpoints(id,event_count,head_hash,checkpoint_hash,updated_at)
               VALUES(1,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET event_count=excluded.event_count,head_hash=excluded.head_hash,
               checkpoint_hash=excluded.checkpoint_hash,updated_at=excluded.updated_at""",
            (count, digest, checkpoint_hash, timestamp),
        )
        if ctx:
            ctx.__exit__(None, None, None)
        return event_id
    except Exception as exc:
        if ctx:
            ctx.__exit__(type(exc), exc, exc.__traceback__)
        raise


def verify_audit_chain() -> tuple[bool, int]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
        checkpoint = conn.execute("SELECT * FROM audit_checkpoints WHERE id=1").fetchone()
    if rows and checkpoint is None:
        return False, len(rows)
    prev = "GENESIS"
    for index, row in enumerate(rows, start=1):
        if row["prev_hash"] != prev:
            return False, index
        canonical = "|".join([
            row["event_id"], row["timestamp"], row["case_id"] or "", row["event_type"], row["outcome"],
            row["actor"], row["details_json"], row["prev_hash"],
        ])
        expected = hmac.new(settings.audit_signing_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, row["event_hash"]):
            return False, index
        prev = row["event_hash"]
    if checkpoint:
        expected_cp = _checkpoint_digest(int(checkpoint["event_count"]), checkpoint["head_hash"])
        if not hmac.compare_digest(expected_cp, checkpoint["checkpoint_hash"]):
            return False, len(rows)
        if int(checkpoint["event_count"]) != len(rows) or checkpoint["head_hash"] != prev:
            return False, len(rows)
    return True, len(rows)


def audit_head() -> dict[str, Any]:
    with connection() as conn:
        cp = conn.execute("SELECT event_count,head_hash,updated_at FROM audit_checkpoints WHERE id=1").fetchone()
    if not cp:
        return {"event_count": 0, "head_hash": "GENESIS", "updated_at": None}
    return dict(cp)
