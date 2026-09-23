from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import connection, init_db, json_dump, utcnow
from app.mrz import build_synthetic_td3_line2, extract_passport_fields
from app.security import hash_secret


def _document_for_case(record: dict) -> tuple[str | None, dict]:
    authoritative = dict(record.get("authoritative_data", {}))
    if not authoritative:
        return None, authoritative
    doc_id = f"doc_{record['id'].lower().replace('-', '_')}_v1"
    method = "SYNTHETIC_VERIFIED_RECORD"
    raw_reference = json_dump(authoritative)
    extracted = authoritative
    if authoritative.get("passport_number") and authoritative.get("passport_expiry"):
        raw_reference = record.get("synthetic_mrz_line2") or build_synthetic_td3_line2(authoritative["passport_number"], authoritative["passport_expiry"])
        extracted = extract_passport_fields(raw_reference)
        if extracted != {
            "passport_number": authoritative["passport_number"],
            "passport_expiry": authoritative["passport_expiry"],
        }:
            raise ValueError(f"Seed MRZ for {record['id']} does not match declared synthetic authority data")
        method = "ICAO9303_MRZ"
    return doc_id, {"method": method, "raw_reference": raw_reference, "extracted_fields": extracted}


def main(reset: bool = False) -> None:
    init_db()
    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / "data" / "seed_cases.json").read_text(encoding="utf-8"))
    with connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        if existing and not reset:
            print(f"Database already contains {existing} cases; seed skipped")
            return
        if reset:
            for table in (
                "pending_actions", "verification_sessions", "appointments", "idempotency_keys",
                "post_call_reports", "call_contexts", "documents", "audit_events", "audit_checkpoints", "cases",
            ):
                conn.execute(f"DELETE FROM {table}")
        today_dubai = datetime.now(ZoneInfo("Asia/Dubai")).date()
        for r in records:
            now = utcnow()
            deadline = (today_dubai + timedelta(days=int(r.get("deadline_days", 30)))).isoformat()
            doc_id, doc = _document_for_case(r)
            conn.execute(
                """INSERT INTO cases(
                    id,applicant_name,phone,preferred_language,status,rejection_code,rejection_message,
                    correction_deadline,contact_consent,contact_window_start,contact_window_end,
                    allowed_fields_json,required_documents_json,current_data_json,authoritative_data_json,requires_attendance,
                    demo_otp_hash,contact_role,authoritative_document_id,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["id"], r["applicant_name"], r["phone"], r["preferred_language"], r["status"],
                    r["rejection_code"], r["rejection_message"], deadline, int(r["contact_consent"]),
                    r["contact_window_start"], r["contact_window_end"], json_dump(r["allowed_fields"]),
                    json_dump(r["required_documents"]), json_dump(r["current_data"]), json_dump(r.get("authoritative_data", {})),
                    int(r["requires_attendance"]), hash_secret(r["demo_otp"]), r.get("contact_role", "applicant"),
                    doc_id, now, now,
                ),
            )
            if doc_id:
                raw = doc["raw_reference"]
                conn.execute(
                    """INSERT INTO documents(id,case_id,version,sha256,method,raw_reference,extracted_fields_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (doc_id, r["id"], 1, hashlib.sha256(raw.encode()).hexdigest(), doc["method"], raw, json_dump(doc["extracted_fields"]), now),
                )
    print(f"Seeded {len(records)} demo cases with relative Dubai deadlines")
    print("Demo OTPs are in data/seed_cases.json and must never be used outside local demo mode.")


if __name__ == "__main__":
    main()
