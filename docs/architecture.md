# ClearPath Voice — Stage 2 Architecture

> **Safety invariant:** The LLM converses; the backend owns authority.

```mermaid
flowchart LR
    A[Applicant / authorised contact\nArabic + English] -->|speech + OTP| B[ElevenLabs Agent]
    B -->|AI disclosure + questions| A

    B -->|HTTPS tool calls\nsecret tool key + case capability + conversation ID| C[ClearPath Policy API\nFastAPI]
    C -->|structured result + approved wording| B

    C --> D[(Synthetic case DB)]
    C --> E[(Versioned document of record)]
    C --> F[(Integrity-linked audit log)]
    C --> G[Human officer review queue]

    E -->|server-proposed value only| C
    C -->|preview + one-shot action token| B
    B -->|explicit caller confirmation| C
    C -->|bounded correction submission| G

    B -->|post-call transcript + analysis webhook| C
    C -->|redacted evidence| F

    H[Failure / dispute / vulnerability / dependency down] -->|freeze mutation| C
    C -->|refer| G
```

## Trust boundaries

1. **Voice is untrusted input.** Caller speech may explain or dispute a value, but cannot become the writable source of truth for sensitive identity data.
2. **ElevenLabs is the conversation layer.** The agent can invoke only scoped server tools.
3. **ClearPath is the authority layer.** Case identity is derived from a short-lived capability bound to the ElevenLabs conversation ID.
4. **High-stakes mutations are two phase.** Verified session → backend preview from the document of record → explicit confirmation → one-shot commit token.
5. **The human approval gate remains outside the model.** A successful commit means `CORRECTION_SUBMITTED`, not application approval.
6. **Post-call evidence is signed and redacted.** The webhook verifies the ElevenLabs HMAC signature, redacts OTP/phone patterns, and stores evidence idempotently.

## Dependency-down behaviour

No privileged write is attempted when verification fails, the case is disputed, the authoritative document is stale or corrupted, or required infrastructure is unavailable. The safe outcome is defer, freeze, or refer to a qualified human.
