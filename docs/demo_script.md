# Stage 2 Demo Scripts

All cases and identity data below are synthetic.

## Demo A — primary Arabic correction

Case: `DXB-R-260901`

1. Agent discloses that it is an AI assistant and that the call may be recorded.
2. Agent confirms it is speaking with the intended person before revealing case detail.
3. Applicant completes the one-time verification challenge.
4. Agent explains that the submitted passport-expiry value does not match the document of record.
5. Backend runs `preview_correction` without accepting a caller-supplied replacement value.
6. Agent reads back the backend-proposed correction from the versioned synthetic passport record.
7. Applicant explicitly confirms.
8. Agent calls `commit_correction`.
9. Final wording: the correction request was **submitted for officer review**; this is **not final application approval**.

### Guardrail moment to emphasize

If the applicant says a different expiry date than the document of record, the system must not write it.

## Demo B — failure / escalation

Use either:

- the primary case with a deliberately conflicting caller-stated value; or
- `DXB-R-260904`, the synthetic legal/disputed case.

Expected behaviour:

1. Agent does not improvise a legal decision or replacement identity value.
2. No correction is committed.
3. The mutation path is frozen where appropriate.
4. The conversation routes to qualified human review.
5. Agent clearly states that the human authority retains the decision.

## Evidence capture checklist

For each recording capture the ElevenLabs conversation page showing:

- conversation ID;
- transcript;
- tool calls;
- success/evaluation fields;
- duration/latency fields if available.

Do not expose workspace secrets, API keys, OTPs outside the explicitly synthetic demo context, or raw capability/action tokens.
