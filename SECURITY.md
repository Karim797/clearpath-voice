# Security Notes

This repository is a challenge prototype. Do not use seeded OTPs, demo secrets, synthetic phone numbers or the SQLite persistence layer as a production identity/security design.

## Production requirements before any institutional pilot

- replace demo OTP verification with the institution's approved identity challenge;
- use a managed database with transactional idempotency and encryption controls;
- store secrets in a managed secret store, not `.env` on a shared host;
- enable ElevenLabs webhook HMAC validation and network/IP allowlisting;
- enforce service-to-service authentication for authority APIs;
- define retention/deletion rules for recordings, transcripts and audit data;
- complete privacy, data-classification, threat-model and penetration-test review;
- require business/legal owner sign-off on the correction-code → permitted-action catalogue;
- remove or protect demo/admin endpoints before production;
- prohibit real applicant data until the institution authorises the environment.

## Reporting

For a real repository, configure a private security contact before making the project public. Do not open public issues containing credentials or personal data.
