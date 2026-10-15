# ClearPath Voice - Stage 2 companion

Karim Dahya | Ignyte x ElevenLabs Future of Voice AI Challenge
Government Services / Proactive Application Resolution

ClearPath resolves correctable application-return issues through a multilingual voice conversation. The backend, rather than the LLM, controls which case, field and action are permitted. The prototype uses synthetic cases and mock authority records.

## Reproduce backend evidence

```bash
pip install -r requirements.txt
python -m pytest -q --junitxml=runtime/backend-tests.xml
python scripts/stage2_evidence.py
```

The scenario runner uses a disposable temporary database. It does not change a deployed database, place calls, or require ElevenLabs credentials. Its JSON contains outcomes and assertions, without verification codes, capability tokens, session IDs or action tokens.

## Evidence available on 15 October 2026

- 27 backend tests passed in a fresh local run (Python 3.12).
- 5/5 local synthetic API scenarios passed: correction + idempotency, disputed-value freeze, verification lockout, consent block, and legal escalation.
- Architecture: `docs/architecture.svg`.
- Voice instruction draft: `elevenlabs/system_prompt.md`.
- Existing demo script and workspace evaluation plan: `docs/demo_script.md`, `docs/stage2_evaluation_plan.md`.

These are backend checks, not ElevenLabs Agent Testing results or recorded voice conversations.

## Live completion requirements

The previously documented Railway `/health` address returned HTTP 404 during this review. Restore hosting and verify `/health` plus an authenticated tool flow. The Docker command now honors Railway's PORT environment variable, retaining 8000 locally; this is a deployment compatibility improvement, not a confirmed explanation for the 404.

Configure the existing ElevenLabs agent against the restored HTTPS API. Verify dynamic variables and headers using `elevenlabs/README.md`; apply and test the instruction draft. Record one primary Arabic path and one disputed-value escalation path, retaining real conversation IDs, redacted transcripts, tool traces and post-call analysis. Run the platform tests repeatedly and attach actual results. Supply a reviewer-accessible live agent link and recording links before sending the submission.

No current live voice recording, workspace pass rate or voice latency is claimed by this companion. Docker could not be built in this review environment because the Docker executable was unavailable.
