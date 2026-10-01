# ClearPath Voice — Reference Policy

This directory is a human-readable mirror of the deterministic policy implemented in `app/policy.py`. The backend code remains the enforcement layer.

| Return code | Allowed voice action | Sensitive field source | Human gate |
|---|---|---|---|
| `PASSPORT_EXPIRY_MISMATCH` | Preview + submit passport-expiry correction | Versioned passport document of record | Officer decides the application |
| `PASSPORT_NUMBER_TYPO` | Preview + submit passport-number correction | Versioned passport document of record | Officer decides the application |
| `MISSING_PASSPORT_COPY` | Create bounded secure-upload route for requested passport copy | Caller uploads through approved route; voice does not invent document content | Back-office review |
| `MISSING_PHOTO` | Create bounded secure-upload route for requested photo | Caller uploads through approved route | Back-office review |
| `BIOMETRIC_REQUIRED` | Book approved demo attendance slot | Case state + bounded location/time rules | In-person authority process |
| `LEGAL_OR_DISPUTED` | Human escalation only | No voice mutation | Qualified human review |

## Global rules

- Voice is not the source of truth for sensitive identity fields.
- Tool calls resolve case identity from a short-lived capability; the model does not supply a writable `case_id`.
- Privileged mutation requires a verified session bound to the conversation.
- Field correction uses backend preview → explicit confirmation → server-issued action token → commit.
- The commit rechecks case state, correction envelope, document ID/version/hash, extracted value, and deadline.
- Verification locks after three failed OTP attempts.
- No-consent cases are blocked before outbound dispatch.
- Disputed, legal, vulnerable, stale-document, and integrity-failure conditions do not mutate the case.
- A correction commit means `CORRECTION_SUBMITTED`; it never means the government application is approved.

This is challenge-prototype policy over synthetic data. It is not an official policy document of any UAE authority.
