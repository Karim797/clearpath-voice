from __future__ import annotations

from typing import Any
import httpx

from ..audit import append_audit
from ..config import settings
from ..security import mask_phone
from .call_context import bind_conversation, issue_case_capability


async def initiate_outbound_call(case: dict[str, Any], force_dry_run: bool = False) -> dict[str, Any]:
    # A per-call capability is the only case locator the voice layer receives.
    # Every tool sends it back in a secret header; the backend resolves case identity.
    capability = issue_case_capability(case["id"], ttl_seconds=1800)
    dynamic_variables = {
        "secret__case_capability": capability,
        "applicant_first_name": case["applicant_name"].split()[0],
        "preferred_language": case["preferred_language"],
        "contact_role": case.get("contact_role", "applicant"),
    }
    payload = {
        "agent_id": settings.elevenlabs_agent_id,
        "agent_phone_number_id": settings.elevenlabs_phone_number_id,
        "to_number": case["phone"],
        "conversation_initiation_client_data": {"dynamic_variables": dynamic_variables},
        "call_recording_enabled": True,
    }
    missing = [
        name for name, value in {
            "ELEVENLABS_API_KEY": settings.elevenlabs_api_key,
            "ELEVENLABS_AGENT_ID": settings.elevenlabs_agent_id,
            "ELEVENLABS_PHONE_NUMBER_ID": settings.elevenlabs_phone_number_id,
        }.items() if not value
    ]
    if force_dry_run or settings.demo_mode or missing:
        append_audit(case["id"], "outbound_call", "dry_run", "orchestrator", {
            "to": mask_phone(case["phone"]), "preverification_detail_disclosed": False, "missing_config": missing,
        })
        preview = {**payload, "to_number": mask_phone(case["phone"])}
        preview["conversation_initiation_client_data"] = {"dynamic_variables": {**dynamic_variables, "secret__case_capability": "[SIGNED_CAPABILITY_REDACTED]"}}
        return {"mode": "dry_run", "payload_preview": preview, "missing_config": missing}

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{settings.elevenlabs_base_url}/v1/convai/twilio/outbound-call",
            headers={"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"}, json=payload,
        )
    response.raise_for_status()
    data = response.json()
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        raise RuntimeError("ElevenLabs outbound call response did not include conversation_id")
    bind_conversation(capability, str(conversation_id))
    append_audit(case["id"], "outbound_call", "dispatched", "orchestrator", {"conversation_id": conversation_id, "to": mask_phone(case["phone"])})
    return data
