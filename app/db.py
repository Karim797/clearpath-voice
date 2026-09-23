from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    applicant_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    preferred_language TEXT NOT NULL,
    status TEXT NOT NULL,
    rejection_code TEXT NOT NULL,
    rejection_message TEXT NOT NULL,
    correction_deadline TEXT NOT NULL,
    contact_consent INTEGER NOT NULL,
    contact_window_start INTEGER NOT NULL DEFAULT 9,
    contact_window_end INTEGER NOT NULL DEFAULT 20,
    allowed_fields_json TEXT NOT NULL,
    required_documents_json TEXT NOT NULL,
    current_data_json TEXT NOT NULL,
    authoritative_data_json TEXT NOT NULL DEFAULT '{}',
    requires_attendance INTEGER NOT NULL DEFAULT 0,
    demo_otp_hash TEXT NOT NULL,
    failed_verification_attempts INTEGER NOT NULL DEFAULT 0,
    verification_locked INTEGER NOT NULL DEFAULT 0,
    contact_role TEXT NOT NULL DEFAULT 'applicant',
    authoritative_document_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_sessions (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    conversation_id TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);


CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    method TEXT NOT NULL,
    raw_reference TEXT NOT NULL,
    extracted_fields_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id),
    UNIQUE(case_id, version)
);

CREATE TABLE IF NOT EXISTS call_contexts (
    capability_hash TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    conversation_id TEXT UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);
CREATE INDEX IF NOT EXISTS ix_call_contexts_case ON call_contexts(case_id);

CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    spoken_summary TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    committed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id),
    FOREIGN KEY(session_id) REFERENCES verification_sessions(id)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    location TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_appointment_per_case
ON appointments(case_id) WHERE status='BOOKED';

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    timestamp TEXT NOT NULL,
    case_id TEXT,
    event_type TEXT NOT NULL,
    outcome TEXT NOT NULL,
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_checkpoints (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    event_count INTEGER NOT NULL,
    head_hash TEXT NOT NULL,
    checkpoint_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_call_reports (
    conversation_id TEXT PRIMARY KEY,
    case_id TEXT,
    outcome TEXT,
    transcript_redacted TEXT,
    evaluation_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    path = Path(settings.database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
        # Lightweight demo migrations keep older local databases usable.
        case_cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
        if "contact_role" not in case_cols:
            conn.execute("ALTER TABLE cases ADD COLUMN contact_role TEXT NOT NULL DEFAULT 'applicant'")
        if "authoritative_document_id" not in case_cols:
            conn.execute("ALTER TABLE cases ADD COLUMN authoritative_document_id TEXT")
        session_cols = {r[1] for r in conn.execute("PRAGMA table_info(verification_sessions)").fetchall()}
        if "conversation_id" not in session_cols:
            conn.execute("ALTER TABLE verification_sessions ADD COLUMN conversation_id TEXT")


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def execute(query: str, params: tuple[Any, ...] = ()) -> None:
    with connection() as conn:
        conn.execute(query, params)


def json_load(value: str) -> Any:
    return json.loads(value)


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
