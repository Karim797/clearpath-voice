# ElevenLabs Workspace Verification

The backend is public and reproducible; the live ElevenLabs workspace is configured separately. Before Stage 2 submission, verify the dashboard matches this contract.

## Required dynamic variables

- `secret__case_capability`
- `session_id` — initially empty; assigned from `verify_applicant.session_id`
- `action_token` — initially empty; assigned from correction preview
- `document_action_token` — initially empty when document flow is enabled
- `system__conversation_id` — ElevenLabs system variable

## Required server-tool headers

```text
X-ClearPath-Tool-Key: {{secret__tool_api_key}}
X-ClearPath-Case-Capability: {{secret__case_capability}}
X-Conversation-Id: {{system__conversation_id}}
```

Never place real secret values in this repository.

## Core server tools

- `get_case_context`
- `verify_applicant`
- `preview_correction`
- `commit_correction`
- `freeze_for_review`
- `refer_human`

Optional bounded paths supported by the backend include document-link preview/commit and appointment booking.

## Response assignments

- `verify_applicant.session_id` → `session_id`
- `preview_correction.action_token` → `action_token`

Sanitize assignments in the ElevenLabs dashboard.

## Post-call webhook

Workspace event:

`post_call_transcription`

Endpoint:

```text
https://clearpath-voice-production-36b5.up.railway.app/webhooks/elevenlabs/post-call
```

The matching webhook secret belongs only in the ElevenLabs/Railway secret stores.

## Stage 2 evidence

Use the ElevenLabs **Tests** area for repeat-run simulation and tool-call evidence. The companion plan is in [../docs/stage2_evaluation_plan.md](../docs/stage2_evaluation_plan.md).
