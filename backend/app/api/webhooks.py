"""Webhook endpoints for external provider event ingestion."""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.db.crud import (
    get_deployment_by_provider_message_id,
    get_feedback_event_by_dedupe_key,
    get_feedback_events_for_session,
    save_feedback_event,
    save_quarantine_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# Resend event-type mapping
# ---------------------------------------------------------------------------

_RESEND_EVENT_MAP: dict[str, str] = {
    "email.sent": "sent",
    "email.delivered": "sent",
    "email.opened": "open",
    "email.clicked": "click",
    "email.bounced": "bounce",
    "email.complained": "bounce",
}


def _map_resend_event_type(resend_type: str) -> str:
    return _RESEND_EVENT_MAP.get(resend_type, "sent")


# ---------------------------------------------------------------------------
# Unipile event-type mapping
# ---------------------------------------------------------------------------

_UNIPILE_EVENT_MAP: dict[str, str] = {
    "message.sent": "sent",
    "message.delivered": "sent",
    "message.read": "open",
    "message.replied": "reply",
    "message.failed": "bounce",
}


def _map_unipile_event_type(unipile_type: str) -> str:
    return _UNIPILE_EVENT_MAP.get(unipile_type, "sent")


# ---------------------------------------------------------------------------
# Provider-specific webhook endpoints
# ---------------------------------------------------------------------------


@router.post("/webhook/resend")
async def webhook_resend(request: Request) -> dict[str, str]:
    """Ingest a Resend webhook event and normalize it."""
    payload: dict[str, Any] = await request.json()

    data = payload.get("data", {})
    provider_message_id = data.get("message_id") or payload.get("provider_message_id")
    provider_event_id = data.get("email_id") or payload.get("provider_event_id", "")
    raw_type = payload.get("type", "unknown")
    event_type = _map_resend_event_type(raw_type)

    dedupe_key = f"resend:{provider_event_id or uuid4()}"

    await _ingest_event(
        provider="resend",
        provider_message_id=provider_message_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        dedupe_key=dedupe_key,
        channel="email",
        extra=payload,
    )
    return {"status": "accepted"}


@router.post("/webhook/unipile")
async def webhook_unipile(request: Request) -> dict[str, str]:
    """Ingest a Unipile webhook event and normalize it."""
    payload: dict[str, Any] = await request.json()

    data = payload.get("data", {})
    provider_message_id = data.get("message_id") or payload.get("provider_message_id")
    provider_event_id = data.get("event_id") or payload.get("provider_event_id", "")
    raw_type = payload.get("type", "unknown")
    event_type = _map_unipile_event_type(raw_type)

    dedupe_key = f"unipile:{provider_event_id or uuid4()}"

    await _ingest_event(
        provider="unipile",
        provider_message_id=provider_message_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        dedupe_key=dedupe_key,
        channel="linkedin",
        extra=payload,
    )
    return {"status": "accepted"}


@router.post("/webhook/engagement")
async def webhook_engagement(request: Request) -> dict[str, str]:
    """Generic normalized feedback endpoint (fallback)."""
    payload: dict[str, Any] = await request.json()
    provider = payload.get("provider", "unknown")
    provider_message_id = payload.get("provider_message_id")
    provider_event_id = payload.get("provider_event_id", "")
    event_type = payload.get("event_type", payload.get("type", "sent"))
    channel = payload.get("channel", "unknown")

    dedupe_key = f"{provider}:{provider_message_id or ''}:{provider_event_id}:{event_type}"

    await _ingest_event(
        provider=provider,
        provider_message_id=provider_message_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        dedupe_key=dedupe_key,
        channel=channel,
        extra=payload,
    )
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# GET feedback events
# ---------------------------------------------------------------------------


@router.get("/campaign/{session_id}/feedback-events")
async def get_session_feedback_events(session_id: str) -> list[dict[str, Any]]:
    """Return all normalized feedback events for a session."""
    events = await get_feedback_events_for_session(session_id)
    if events is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return events


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _ingest_event(
    *,
    provider: str,
    provider_message_id: str | None,
    provider_event_id: str | None,
    event_type: str,
    dedupe_key: str,
    channel: str,
    extra: dict[str, Any],
) -> None:
    """Deduplicate, correlate to a deployment record, and store.

    Events that cannot be correlated are quarantined.
    """
    # 1. Deduplicate
    existing = await get_feedback_event_by_dedupe_key(dedupe_key)
    if existing:
        logger.debug("Duplicate event skipped: %s", dedupe_key)
        return

    now = datetime.now(tz=timezone.utc)

    # 2. Correlate to deployment record
    deployment: dict[str, Any] | None = None
    if provider_message_id:
        deployment = await get_deployment_by_provider_message_id(provider_message_id)

    normalized: dict[str, Any] = {
        "provider": provider,
        "provider_event_id": provider_event_id or None,
        "provider_message_id": provider_message_id,
        "deployment_record_id": deployment.get("id") if deployment else None,
        "session_id": (
            deployment.get("session_id") if deployment else extra.get("session_id")
        ),
        "variant_id": deployment.get("variant_id") if deployment else None,
        "prospect_id": deployment.get("prospect_id") if deployment else None,
        "channel": deployment.get("channel") if deployment else channel,
        "event_type": event_type,
        "event_value": extra.get("event_value"),
        "qualitative_signal": extra.get("qualitative_signal"),
        "received_at": now.isoformat(),
        "dedupe_key": dedupe_key,
    }

    if deployment:
        await save_feedback_event(normalized)
        logger.info("Stored feedback event: %s", dedupe_key)
    else:
        await save_quarantine_event(normalized)
        logger.warning("Quarantined unmatched event: %s", dedupe_key)
