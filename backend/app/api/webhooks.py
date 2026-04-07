"""Webhook endpoints for external provider event ingestion."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from app.db.crud import (
    get_deployment_by_provider_message_id,
    save_feedback_event,
    save_quarantine_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# Provider-specific webhook endpoints
# ---------------------------------------------------------------------------

@router.post("/webhook/resend")
async def webhook_resend(request: Request) -> dict[str, str]:
    """Ingest a Resend webhook event and normalize it."""
    payload: dict[str, Any] = await request.json()
    await _process_provider_event("resend", payload)
    return {"status": "accepted"}


@router.post("/webhook/unipile")
async def webhook_unipile(request: Request) -> dict[str, str]:
    """Ingest a Unipile webhook event and normalize it."""
    payload: dict[str, Any] = await request.json()
    await _process_provider_event("unipile", payload)
    return {"status": "accepted"}


@router.post("/webhook/engagement")
async def webhook_engagement(request: Request) -> dict[str, str]:
    """Generic normalized feedback endpoint (fallback)."""
    payload: dict[str, Any] = await request.json()
    await _process_provider_event(payload.get("provider", "unknown"), payload)
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _process_provider_event(provider: str, payload: dict[str, Any]) -> None:
    """Normalize a provider event, correlate to deployment, and store.

    Events that cannot be correlated are quarantined.
    """
    provider_message_id = payload.get("provider_message_id")
    event_type = payload.get("event_type", payload.get("type", "unknown"))
    now = datetime.now(tz=timezone.utc)

    # Build dedupe key
    provider_event_id = payload.get("provider_event_id", "")
    dedupe_key = f"{provider}:{provider_message_id or ''}:{provider_event_id}:{event_type}"

    # Attempt correlation
    deployment = None
    if provider_message_id:
        deployment = await get_deployment_by_provider_message_id(provider_message_id)

    normalized = {
        "provider": provider,
        "provider_event_id": provider_event_id or None,
        "provider_message_id": provider_message_id,
        "deployment_record_id": deployment.get("id") if deployment else None,
        "session_id": deployment.get("session_id") if deployment else payload.get("session_id"),
        "variant_id": deployment.get("variant_id") if deployment else None,
        "prospect_id": deployment.get("prospect_id") if deployment else None,
        "channel": deployment.get("channel") if deployment else payload.get("channel", "unknown"),
        "event_type": event_type,
        "event_value": payload.get("event_value"),
        "qualitative_signal": payload.get("qualitative_signal"),
        "received_at": now.isoformat(),
        "dedupe_key": dedupe_key,
    }

    if deployment:
        await save_feedback_event(normalized)
        logger.info("Stored feedback event: %s", dedupe_key)
    else:
        await save_quarantine_event(normalized)
        logger.warning("Quarantined unmatched event: %s", dedupe_key)
