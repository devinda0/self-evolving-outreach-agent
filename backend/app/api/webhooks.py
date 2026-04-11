"""Webhook endpoints for external provider event ingestion."""

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.db.crud import (
    get_deployment_by_provider_message_id,
    get_feedback_event_by_dedupe_key,
    get_feedback_events_for_session,
    get_quarantine_events_for_session,
    save_dlq_event,
    save_feedback_event,
    save_quarantine_event,
    update_dlq_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# Resend webhook HMAC verification (svix signing scheme)
# ---------------------------------------------------------------------------

_MAX_TIMESTAMP_SKEW_SECONDS = 300  # 5 minutes


def _verify_resend_signature(
    raw_body: bytes,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    secret: str,
) -> bool:
    """Verify the svix signature on a Resend webhook.

    Args:
        raw_body: The unmodified raw request body bytes.
        svix_id: Value of the ``svix-id`` header.
        svix_timestamp: Value of the ``svix-timestamp`` header.
        svix_signature: Value of the ``svix-signature`` header
            (space-separated list of ``v1,<base64>`` items).
        secret: The webhook signing secret in ``whsec_<base64>`` format.

    Returns:
        ``True`` when at least one provided signature matches the expected
        HMAC and the timestamp is within the allowed skew window.
    """
    # Reject stale or future timestamps to mitigate replay attacks
    try:
        ts = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > _MAX_TIMESTAMP_SKEW_SECONDS:
        return False

    # Decode the webhook secret (strip optional "whsec_" prefix then base64-decode)
    try:
        secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
    except Exception:  # noqa: BLE001
        logger.error("_verify_resend_signature: unable to decode webhook secret")
        return False

    # Build the signed content exactly as Resend/svix does
    signed_content = f"{svix_id}.{svix_timestamp}.{raw_body.decode()}"

    # Compute HMAC-SHA256 and base64-encode
    expected_sig = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()
    ).decode()

    # svix_signature may contain multiple space-separated "v1,<sig>" entries
    provided_sigs = [part.split(",", 1)[1] for part in svix_signature.split() if "," in part]

    return any(hmac.compare_digest(expected_sig, sig) for sig in provided_sigs)


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
    """Ingest a Resend webhook event and normalize it.

    When ``RESEND_WEBHOOK_SECRET`` is configured, the svix HMAC signature is
    verified before the payload is processed.  Requests with an invalid
    signature are rejected with HTTP 401.
    """
    raw_body = await request.body()

    # -- Optional HMAC verification --
    if settings.RESEND_WEBHOOK_SECRET:
        svix_id = request.headers.get("svix-id", "")
        svix_timestamp = request.headers.get("svix-timestamp", "")
        svix_signature = request.headers.get("svix-signature", "")

        if not _verify_resend_signature(
            raw_body=raw_body,
            svix_id=svix_id,
            svix_timestamp=svix_timestamp,
            svix_signature=svix_signature,
            secret=settings.RESEND_WEBHOOK_SECRET,
        ):
            logger.warning("webhook_resend: invalid svix signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json as _json  # avoid shadowing top-level json if any

    payload: dict[str, Any] = _json.loads(raw_body)

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
# Engagement dashboard
# ---------------------------------------------------------------------------


@router.get("/campaign/{session_id}/engagement")
async def get_engagement_dashboard(session_id: str) -> dict[str, Any]:
    """Return a comprehensive engagement dashboard for a campaign session.

    Includes:
    - Per-variant metrics (open/click/reply/bounce rates)
    - Statistical significance testing results
    - Winner determination
    - Deployment summary
    """
    from app.agents.feedback_agent import (
        aggregate_engagement_results,
        compute_ab_significance,
        determine_winner,
    )
    from app.db.crud import get_deployment_records_for_session

    events = await get_feedback_events_for_session(session_id)
    records = await get_deployment_records_for_session(session_id)

    if not records:
        return {
            "session_id": session_id,
            "total_sent": 0,
            "total_failed": 0,
            "variant_metrics": [],
            "winner": None,
            "significance": None,
            "deployment_summary": {"channels": {}},
        }

    # Compute metrics
    results = aggregate_engagement_results(events, records)
    winner = determine_winner(results)
    significance = compute_ab_significance(results, metric="replies")

    # Deployment summary
    total_sent = sum(1 for r in records if r.get("status") == "sent")
    total_failed = sum(1 for r in records if r.get("status") == "failed")
    channels: dict[str, dict] = {}
    for r in records:
        ch = r.get("channel", "unknown")
        if ch not in channels:
            channels[ch] = {"sent": 0, "failed": 0}
        if r.get("status") == "sent":
            channels[ch]["sent"] += 1
        else:
            channels[ch]["failed"] += 1

    return {
        "session_id": session_id,
        "total_sent": total_sent,
        "total_failed": total_failed,
        "total_events": len(events),
        "variant_metrics": results,
        "winner": {
            "variant_id": winner["variant_id"],
            "reply_rate": winner["reply_rate"],
            "open_rate": winner["open_rate"],
            "sent": winner["sent"],
        } if winner else None,
        "significance": significance,
        "deployment_summary": {"channels": channels},
    }


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
    Processing failures are sent to the dead-letter queue for retry.
    """
    # 1. Deduplicate
    existing = await get_feedback_event_by_dedupe_key(dedupe_key)
    if existing:
        logger.debug("Duplicate event skipped: %s", dedupe_key)
        return

    now = datetime.now(tz=timezone.utc)

    try:
        # 2. Correlate to deployment record
        deployment: dict[str, Any] | None = None
        if provider_message_id:
            deployment = await get_deployment_by_provider_message_id(provider_message_id)

        normalized: dict[str, Any] = {
            "provider": provider,
            "provider_event_id": provider_event_id or None,
            "provider_message_id": provider_message_id,
            "deployment_record_id": deployment.get("id") if deployment else None,
            "session_id": (deployment.get("session_id") if deployment else extra.get("session_id")),
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
    except Exception as exc:
        logger.error("_ingest_event failed for %s: %s — sending to DLQ", dedupe_key, exc)
        await save_dlq_event({
            "dedupe_key": dedupe_key,
            "provider": provider,
            "provider_message_id": provider_message_id,
            "provider_event_id": provider_event_id,
            "event_type": event_type,
            "channel": channel,
            "raw_payload": extra,
            "error": str(exc),
            "retry_count": 0,
            "max_retries": settings.WEBHOOK_DLQ_MAX_RETRIES,
            "status": "pending",
            "created_at": now.isoformat(),
        })


# ---------------------------------------------------------------------------
# Manual feedback submission
# ---------------------------------------------------------------------------


class ManualFeedbackRequest(BaseModel):
    """Body schema for manual feedback reports submitted from the UI."""

    variant_id: str | None = None
    prospect_id: str | None = None
    event_type: str  # "open" | "click" | "reply" | "bounce"
    qualitative_signal: str | None = None


@router.post("/campaign/{session_id}/feedback/manual")
async def submit_manual_feedback(
    session_id: str,
    body: ManualFeedbackRequest,
) -> dict[str, str]:
    """Accept a manual feedback report for a session from the UI.

    Validates the event_type, constructs a NormalizedFeedbackEvent with
    ``provider="manual"``, and stores it directly in feedback_events (not
    quarantine) because the user is the authoritative source.
    """
    allowed_types = {"open", "click", "reply", "bounce"}
    if body.event_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"event_type must be one of {sorted(allowed_types)}",
        )

    now = datetime.now(tz=timezone.utc)
    dedupe_key = f"manual:{session_id}:{body.variant_id or ''}:{body.event_type}:{uuid4().hex}"

    normalized: dict[str, Any] = {
        "provider": "manual",
        "provider_event_id": None,
        "provider_message_id": None,
        "deployment_record_id": None,
        "session_id": session_id,
        "variant_id": body.variant_id,
        "prospect_id": body.prospect_id,
        "channel": "manual",
        "event_type": body.event_type,
        "event_value": None,
        "qualitative_signal": body.qualitative_signal,
        "received_at": now.isoformat(),
        "dedupe_key": dedupe_key,
    }

    await save_feedback_event(normalized)
    logger.info(
        "submit_manual_feedback: stored manual event | session=%s variant=%s type=%s",
        session_id,
        body.variant_id,
        body.event_type,
    )
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Quarantine viewer endpoint
# ---------------------------------------------------------------------------


@router.get("/campaign/{session_id}/quarantine")
async def get_quarantine_events(session_id: str) -> list[dict[str, Any]]:
    """Return all quarantined events for a session, ordered by received_at."""
    events = await get_quarantine_events_for_session(session_id)
    return events


# ---------------------------------------------------------------------------
# Dead-letter queue management
# ---------------------------------------------------------------------------


@router.post("/webhooks/dlq/retry")
async def retry_dlq_events() -> dict[str, Any]:
    """Retry all pending dead-letter queue events.

    For each pending DLQ event, re-attempts ingestion. On success, marks the
    event as ``resolved``. On repeated failure, increments retry_count and
    marks as ``failed`` once max_retries is exceeded.
    """
    from app.db.crud import get_dlq_events

    pending = await get_dlq_events(status="pending")
    retried = 0
    resolved = 0
    failed = 0

    for dlq_event in pending:
        dedupe_key = dlq_event.get("dedupe_key", "")
        retry_count = dlq_event.get("retry_count", 0)
        max_retries = dlq_event.get("max_retries", settings.WEBHOOK_DLQ_MAX_RETRIES)

        try:
            await _ingest_event(
                provider=dlq_event.get("provider", "unknown"),
                provider_message_id=dlq_event.get("provider_message_id"),
                provider_event_id=dlq_event.get("provider_event_id"),
                event_type=dlq_event.get("event_type", "sent"),
                dedupe_key=dedupe_key,
                channel=dlq_event.get("channel", "unknown"),
                extra=dlq_event.get("raw_payload", {}),
            )
            await update_dlq_event(dedupe_key, {
                "status": "resolved",
                "resolved_at": datetime.now(tz=timezone.utc).isoformat(),
            })
            resolved += 1
        except Exception as exc:
            new_count = retry_count + 1
            new_status = "failed" if new_count >= max_retries else "pending"
            await update_dlq_event(dedupe_key, {
                "retry_count": new_count,
                "status": new_status,
                "last_error": str(exc),
                "last_retry_at": datetime.now(tz=timezone.utc).isoformat(),
            })
            if new_status == "failed":
                failed += 1
            logger.warning("DLQ retry failed for %s (attempt %d/%d): %s",
                           dedupe_key, new_count, max_retries, exc)
        retried += 1

    return {"retried": retried, "resolved": resolved, "failed": failed}
