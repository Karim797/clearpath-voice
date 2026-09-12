# ClearPath Voice

**Multilingual, bounded-action voice recovery for government applications held up by correctable errors.**

ClearPath Voice is a competition-grade reference build for the **Ignyte × ElevenLabs Future of Voice AI Challenge — Government Services / Proactive Application Resolution** track.

It is designed around one core principle:

> **The LLM can converse; the backend owns authority.**

V4 adds a second principle: **voice is never the source of truth for sensitive identity fields.** A correction is committable only when it matches the authority's document-of-record value; the caller may confirm or dispute that value, but cannot dictate a replacement that the backend accepts on trust.

The agent can explain a recorded issue, verify the applicant, submit only a case-authorised correction, create a secure document-upload route, book required attendance, or escalate. It cannot approve, reject, cancel, or start an application because those capabilities do not exist in its tool surface.

---

## Why this is different from a generic voice bot

Most agent demos put policy in a system prompt. ClearPath also enforces policy **server-side** through a per-case **Correction Envelope**:

- the rejection code determines the only fields/documents/actions that can be touched;
- voice tools carry no writable case ID; a short-lived `secret__case_capability` derives case identity server-side and is bound to the ElevenLabs conversation ID;
- every sensitive mutation requires a verified, short-lived session;
- field corrections use server-proposed document value → read-back → explicit confirmation → one-shot commit;
- commit tokens are HMAC-signed and bound to case, session, action type, nonce and expiry;
- permissions, Dubai-date deadline, current value, current authoritative-document ID, document version and a recomputed content hash are checked again at commit time;
- mutation retries are idempotent;
- three failed verification attempts lock automation;
- unconsented outbound contact is blocked before ElevenLabs is called;
- legal/disputed/vulnerable cases are escalation-only;
- post-call webhooks can be HMAC-verified and stored with redacted transcripts;
- audit events are integrity-linked and checkpointed; concurrent local appends are serialized. The prototype does not claim external immutability or utterance-level proof of confirmation.

This is intentionally a **bounded correction agent**, not an autonomous government decision-maker.

---

## Architecture

See [`docs/architecture.svg`](docs/architecture.svg) and [`docs/architecture.md`](docs/architecture.md).

High level:

```text
Government case system
        │  rejection event
        ▼
ClearPath orchestrator ── consent/contact-window gate
        │
        ▼
ElevenLabs Agent
Workflow + Eleven v3 + Scribe v2
        │ scoped webhook tools
        ▼
ClearPath Policy API
verification + Correction Envelope + two-phase commit
        │                         │
        ▼                         ▼
Government mock APIs         Human escalation
        │
        ▼
Audit + post-call evidence + Agent Testing
```

---

## Repository map

```text
app/
  main.py                  FastAPI application
  config.py                environment configuration
  db.py                    SQLite demo persistence
  policy.py                deterministic return policies + approved bilingual wording + validators
  security.py              auth, HMAC tokens, capability security, redaction
  audit.py                 integrity-linked audit + checkpoint
  services/
    case_service.py         verification, document-anchored correction, document, appointment flows
    call_context.py         per-call capability + conversation binding
    elevenlabs.py           outbound Twilio/ElevenLabs adapter
  routers/
    tools.py                ElevenLabs webhook tool endpoints
    events.py               return-for-amendment trigger / consent gate
    webhooks.py             ElevenLabs post-call webhook receiver
    admin.py                protected admin evidence + synthetic web-demo capability issuance

data/seed_cases.json       synthetic cases only
reference_policy/           human-readable reference files; not wired to RAG

elevenlabs/
  agent_prompt.md           production-style agent prompt
  workflow_spec.md          workflow graph + node-level tool scoping
  tool_configs/             webhook-tool dashboard field maps

docs/
  threat_model.md
  evaluation_plan.md
  demo_script.md
  architecture.svg
  idea_canvas_content.md

tests/                      deterministic guardrail + happy-path tests
scripts/seed.py             reset synthetic dataset
scripts/demo_flow.py        full local correction walkthrough
```

---

## Quick start

Python 3.13 is used in the supplied Docker image; Python 3.11+ should work for local development.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m scripts.seed
uvicorn app.main:app --reload
```

Open:

- `http://localhost:8000/` — project landing page
- `http://localhost:8000/docs` — interactive API docs
- `http://localhost:8000/demo` — sanitized evidence console
- `protected `/admin/*` — requires `X-ClearPath-Admin-Key`

Run the complete local primary flow:

```bash
python scripts/demo_flow.py
```

Run tests:

```bash
pytest -q
```

Current checked result: **45 passed**.

---

## Demo cases

| Case | Path | Language | Expected outcome |
|---|---|---|---|
| `DXB-R-260901` | passport expiry mismatch | Arabic | verified two-phase field correction |
| `DXB-R-260902` | missing passport copy | English | only requested secure-upload route |
| `DXB-R-260903` | biometric attendance | Arabic | appointment booking only |
| `DXB-R-260904` | legal/disputed issue | English | mandatory human escalation |
| `DXB-R-260905` | correctable typo, no consent | Urdu preference | outbound call blocked before dispatch |

All names, phone numbers and OTPs are synthetic challenge data.

---

## ElevenLabs integration

The competition build plan deliberately selects Agent Workflows, Eleven v3 Conversational, Scribe v2 Realtime, webhook/server tools, Agent Testing, conversation analysis and post-call webhooks. RAG is not core because the demo policy set is small.

### 1. Create the agent

In ElevenAgents, create an agent and apply:

- system prompt: [`elevenlabs/agent_prompt.md`](elevenlabs/agent_prompt.md)
- workflow: [`elevenlabs/workflow_spec.md`](elevenlabs/workflow_spec.md)
- Eleven v3 Conversational for restrained multilingual voice
- Scribe v2 Realtime for realtime listening/turn-taking
- Arabic + English first, with later supported-language QA
- verification as a dispatch-tool gate with success/failure edges

### 2. Configure webhook tools

Deploy this API over HTTPS, then create webhook tools pointing to `/tools/*`.

Use three server-side headers: the workspace-secret tool credential, the per-call capability secret variable, and the ElevenLabs system conversation ID:

```text
X-ClearPath-Tool-Key: {{secret__tool_api_key}}
X-ClearPath-Case-Capability: {{secret__case_capability}}
X-Conversation-Id: {{system__conversation_id}}
```

The agent does not supply `case_id`. The first web-demo tool call lazily binds the short-lived capability to `system__conversation_id`; later mismatches are rejected. Field maps are in [`elevenlabs/tool_configs/`](elevenlabs/tool_configs/).
Initialize `session_id`, `action_token`, and `document_action_token` as empty strings in the dashboard. `verify_applicant` and preview tools then overwrite them through sanitized dynamic-variable assignments. See [`elevenlabs/dashboard_setup.md`](elevenlabs/dashboard_setup.md) for the exact Stage-1 configuration.


**Do not expose every tool on every workflow node.** Follow the node-level scope table in the workflow spec.

### 3. Configure a Stage-1 web demo

For a synthetic talk-to demo, an admin can issue a short-lived call context:

```text
POST /admin/demo-call-context
X-ClearPath-Admin-Key: <ADMIN_API_KEY>
{"case_id": "DXB-R-260901", "ttl_seconds": 1800}
```

Pass the returned `secret__case_capability` as a runtime dynamic variable when starting the ElevenLabs web conversation. Every tool also sends `{{system__conversation_id}}`; the backend binds the capability on first use. This admin path is for synthetic challenge evidence only, not a production issuance design.

### 4. Configure outbound calls

Set:

```env
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_PHONE_NUMBER_ID=...
DEMO_MODE=false
```

When a consented rejection event arrives, the adapter uses ElevenLabs' Twilio outbound endpoint:

```text
POST /v1/convai/twilio/outbound-call
```

Only minimal dynamic variables are passed to the call. Sensitive case details stay behind authenticated tools.

### 5. Configure post-call evidence

Create an ElevenLabs workspace webhook for `post_call_transcription`, copy its HMAC secret into:

```env
ELEVENLABS_WEBHOOK_SECRET=...
```

Point it to:

```text
https://<your-host>/webhooks/elevenlabs/post-call
```

The receiver validates the `ElevenLabs-Signature` timestamp/HMAC in production, redacts obvious OTP/phone patterns, and idempotently stores the call evidence by conversation ID.

### 6. Agent Testing

Build the Stage 2 tests in [`docs/evaluation_plan.md`](docs/evaluation_plan.md):

- simulation tests for full multi-turn outcomes;
- next-reply tests for disclosure, language and policy wording;
- tool-call tests for high-stakes mutations;
- repeated runs for pass-rate evidence.

Critical guardrail failures should block release even if task completion looks good.

---

## Local API walkthrough

The real voice-tool surface is capability-bound, so copy/paste examples with a model-supplied `case_id` are intentionally not provided. Run:

```bash
python scripts/demo_flow.py
```

The script issues a server-side per-call capability, shows pre-verification privacy, verifies the synthetic caller, requests a correction preview **without a proposed value**, commits the one-shot action, and verifies the audit chain.

For `DXB-R-260901`, the preview value comes from a versioned synthetic passport document whose stored synthetic MRZ artifact is content-hashed and validated across all TD3 check digits used by the demo parser.

---

## Stage 1 submission

`docs/idea_canvas_content.md` contains the prepared copy for Boxes A–N. **The official five-page Idea Canvas remains the required submission artifact**, so paste the final copy into the official template and verify each template word limit before submission.

Replace Box N placeholders with a public repository, hosted evidence console, Arabic ElevenLabs recording and workflow screenshot before submission. A live demo can be offered on request; a shared talk-to URL is not required for the Stage-1 proof package.

---

## Stage 2 evidence package already scaffolded

- capability-bound callable-agent integration seam with web/outbound conversation binding;
- primary and failure-path demo script;
- architecture one-pager;
- technical README;
- approved bilingual backend wording + human-readable reference policy files (RAG intentionally non-core);
- webhook tool map;
- deterministic backend tests;
- Agent Testing plan;
- transcript/evaluation receiver;
- audit-chain evidence endpoint.

What cannot be completed without the participant's accounts is intentionally limited to: creating the ElevenLabs workspace/agent, adding real secrets, connecting a test phone number, publishing the GitHub repository, and deploying the HTTPS service.

---

## Public-source basis used in the concept

The demo knowledge set uses published process facts rather than invented institutional operations data. In particular, the GDRFA Dubai residence-data amendment page states that applicants are notified when items are missing and must provide them within 30 days or the application will be cancelled if the missing items are not attached within 30 days. These public facts are used for problem framing, not as a claim that ClearPath is affiliated with or endorsed by any UAE authority.

Useful current platform references:

- ElevenAgents overview: https://elevenlabs.io/docs/eleven-agents/overview
- Workflows: https://elevenlabs.io/docs/eleven-agents/customization/agent-workflows
- Webhook tools: https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools
- Knowledge base: https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base
- Agent Testing: https://elevenlabs.io/docs/eleven-agents/customization/agent-testing
- Post-call webhooks: https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks
- Twilio outbound call API: https://elevenlabs.io/docs/eleven-agents/api-reference/twilio/outbound-call
- GDRFA residence amendment: https://gdrfad.gov.ae/en/services/dff87d9f-b81d-11ed-5210-4cd98f768936

---

## Disclaimer

This is a challenge prototype using synthetic cases. It is not a deployed UAE government service, not legal advice, and not authorised to make government decisions. A real pilot would require the institution's security review, privacy/data-retention controls, approved identity challenge, source/SOP ownership, API contracts, telephony consent rules, accessibility review, and formal sign-off of the rule/action catalogue.
