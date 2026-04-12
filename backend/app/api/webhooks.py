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
    append_thread_message,
    find_deployment_by_recipient_email,
    get_deployment_by_provider_message_id,
    get_email_thread_by_provider_message_id,
    get_feedback_event_by_dedupe_key,
    get_feedback_events_for_session,
    get_quarantine_events_for_session,
    save_dlq_event,
    save_feedback_event,
    save_quarantine_event,
    update_dlq_event,
    update_feedback_event,
    upsert_email_thread,
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
    "email.delivered": "delivered",
    "email.delivery_delayed": "sent",
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


@router.post("/webhook/resend/inbound")
async def webhook_resend_inbound(request: Request) -> dict[str, str]:
    """Ingest an inbound email from Resend (reply to an outreach email).

    Resend forwards inbound emails to this endpoint. We extract the reply
    content, correlate it to the original outreach email, classify the reply
    intent, and store it as a feedback event + thread message.
    """
    raw_body = await request.body()

    # Optional HMAC verification (same secret as outbound webhooks)
    if settings.RESEND_WEBHOOK_SECRET:
        svix_id = request.headers.get("svix-id", "")
        svix_timestamp = request.headers.get("svix-timestamp", "")
        svix_signature = request.headers.get("svix-signature", "")

        if svix_id and svix_timestamp and svix_signature:
            if not _verify_resend_signature(
                raw_body=raw_body,
                svix_id=svix_id,
                svix_timestamp=svix_timestamp,
                svix_signature=svix_signature,
                secret=settings.RESEND_WEBHOOK_SECRET,
            ):
                logger.warning("webhook_resend_inbound: invalid svix signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json as _json

    payload: dict[str, Any] = _json.loads(raw_body)

    # Extract inbound email fields from Resend's inbound payload
    reply_info = _extract_inbound_reply(payload)
    if not reply_info:
        logger.warning("webhook_resend_inbound: could not extract reply info from payload")
        await save_quarantine_event({
            "provider": "resend_inbound",
            "raw_payload": payload,
            "quarantine_reason": "unparseable_inbound_email",
            "received_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        return {"status": "quarantined"}

    await _ingest_inbound_reply(reply_info, payload)
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
# Inbound email reply extraction
# ---------------------------------------------------------------------------


def _extract_inbound_reply(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract reply information from a Resend inbound email webhook payload.

    Resend inbound email payloads contain fields like:
    - from: sender email
    - to: recipient email (our outreach address)
    - subject: email subject
    - text: plain text body
    - html: HTML body
    - headers: includes In-Reply-To, References, Message-ID

    Returns a structured dict or None if the payload is not parseable.
    """
    # Handle both top-level and nested data structures
    data = payload.get("data", payload)

    from_email = data.get("from") or ""
    # Handle Resend's from field which can be "Name <email>" or just "email"
    if isinstance(from_email, list):
        from_email = from_email[0] if from_email else ""
    if isinstance(from_email, dict):
        from_email = from_email.get("email") or from_email.get("address", "")
    # Extract email from "Name <email>" format
    if "<" in str(from_email) and ">" in str(from_email):
        from_email = str(from_email).split("<")[1].split(">")[0].strip()
    from_email = str(from_email).strip().lower()

    to_email = data.get("to") or ""
    if isinstance(to_email, list):
        to_email = to_email[0] if to_email else ""
    if isinstance(to_email, dict):
        to_email = to_email.get("email") or to_email.get("address", "")
    if "<" in str(to_email) and ">" in str(to_email):
        to_email = str(to_email).split("<")[1].split(">")[0].strip()
    to_email = str(to_email).strip().lower()

    subject = data.get("subject") or ""
    text_body = data.get("text") or data.get("text_body") or ""
    html_body = data.get("html") or data.get("html_body") or ""

    # Extract headers for In-Reply-To correlation
    headers = data.get("headers") or {}
    if isinstance(headers, list):
        headers = {h.get("name", ""): h.get("value", "") for h in headers if isinstance(h, dict)}
    in_reply_to = headers.get("In-Reply-To") or headers.get("in-reply-to") or ""
    references = headers.get("References") or headers.get("references") or ""
    message_id = (
        data.get("message_id")
        or headers.get("Message-ID")
        or headers.get("message-id")
        or str(uuid4())
    )

    # Strip angle brackets from message IDs
    in_reply_to = in_reply_to.strip().strip("<>")
    message_id = message_id.strip().strip("<>")

    if not from_email:
        return None

    return {
        "from_email": from_email,
        "to_email": to_email,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references": references,
    }


async def _ingest_inbound_reply(
    reply_info: dict[str, Any],
    raw_payload: dict[str, Any],
) -> None:
    """Process an inbound email reply — correlate, classify, and store.

    Correlation strategy (ordered by reliability):
    1. In-Reply-To header → match provider_message_id in deployment records
    2. References header → match any provider_message_id in deployment records
    3. From email → match prospect email across active sessions
    4. If no correlation found → quarantine the event

    For each correlated reply:
    - Store a normalized feedback event (event_type="reply") with reply body
    - Update the email thread with the inbound message
    - Trigger async classification (deferred to feedback agent for batch efficiency)
    """
    now = datetime.now(tz=timezone.utc)
    from_email = reply_info["from_email"]
    in_reply_to = reply_info.get("in_reply_to", "")
    references = reply_info.get("references", "")
    text_body = reply_info.get("text_body", "")
    message_id = reply_info.get("message_id", str(uuid4()))

    dedupe_key = f"resend_inbound:{message_id}"

    # Check for duplicate
    existing = await get_feedback_event_by_dedupe_key(dedupe_key)
    if existing:
        logger.debug("Duplicate inbound reply skipped: %s", dedupe_key)
        return

    # --- Correlation strategy ---
    deployment: dict[str, Any] | None = None
    thread: dict[str, Any] | None = None

    # Strategy 1: In-Reply-To header → deployment record
    if in_reply_to:
        deployment = await get_deployment_by_provider_message_id(in_reply_to)
        if deployment:
            logger.info(
                "_ingest_inbound_reply: correlated via In-Reply-To=%s → deployment=%s",
                in_reply_to,
                deployment.get("id"),
            )

    # Strategy 2: References header → deployment record
    if not deployment and references:
        for ref in references.split():
            ref = ref.strip().strip("<>")
            if ref:
                deployment = await get_deployment_by_provider_message_id(ref)
                if deployment:
                    logger.info(
                        "_ingest_inbound_reply: correlated via References ref=%s → deployment=%s",
                        ref,
                        deployment.get("id"),
                    )
                    break

    # Strategy 3: Match thread by provider_message_id in thread messages
    if not deployment and in_reply_to:
        thread = await get_email_thread_by_provider_message_id(in_reply_to)
        if thread:
            deployment = await get_deployment_by_provider_message_id(
                thread.get("messages", [{}])[0].get("message_id", "")
            ) if thread.get("messages") else None
            logger.info(
                "_ingest_inbound_reply: correlated via thread lookup from=%s",
                from_email,
            )

    # Strategy 4: Match by sender email across all sessions
    if not deployment:
        from app.db.crud import list_campaigns

        campaigns = await list_campaigns(limit=20)
        for campaign in campaigns:
            session_id = campaign.get("session_id", "")
            found = await find_deployment_by_recipient_email(session_id, from_email)
            if found:
                deployment = found
                logger.info(
                    "_ingest_inbound_reply: correlated via email match from=%s → session=%s",
                    from_email,
                    session_id,
                )
                break

    if not deployment:
        # Cannot correlate — quarantine
        logger.warning(
            "_ingest_inbound_reply: no correlation found for inbound from=%s — quarantining",
            from_email,
        )
        await save_quarantine_event({
            "provider": "resend_inbound",
            "from_email": from_email,
            "subject": reply_info.get("subject"),
            "text_body": text_body[:500] if text_body else None,
            "message_id": message_id,
            "in_reply_to": in_reply_to,
            "quarantine_reason": "no_matching_deployment_record",
            "received_at": now.isoformat(),
            "raw_payload": raw_payload,
        })
        return

    # --- Store normalized feedback event ---
    session_id = deployment.get("session_id", "")
    variant_id = deployment.get("variant_id")
    prospect_id = deployment.get("prospect_id")

    normalized: dict[str, Any] = {
        "provider": "resend_inbound",
        "provider_event_id": message_id,
        "provider_message_id": deployment.get("provider_message_id"),
        "deployment_record_id": deployment.get("id"),
        "session_id": session_id,
        "variant_id": variant_id,
        "prospect_id": prospect_id,
        "channel": "email",
        "event_type": "reply",
        "event_value": None,
        "qualitative_signal": text_body[:2000] if text_body else None,
        "reply_body": text_body,
        "reply_subject": reply_info.get("subject"),
        "received_at": now.isoformat(),
        "dedupe_key": dedupe_key,
    }

    await save_feedback_event(normalized)
    logger.info(
        "_ingest_inbound_reply: stored reply event | session=%s prospect=%s from=%s",
        session_id,
        prospect_id,
        from_email,
    )

    # --- Update email thread ---
    await _update_thread_with_reply(
        session_id=session_id,
        prospect_id=prospect_id or "",
        prospect_email=from_email,
        deployment=deployment,
        reply_info=reply_info,
        message_id=message_id,
    )


async def _update_thread_with_reply(
    session_id: str,
    prospect_id: str,
    prospect_email: str,
    deployment: dict[str, Any],
    reply_info: dict[str, Any],
    message_id: str,
) -> None:
    """Update or create the email thread with an inbound reply message."""
    now = datetime.now(tz=timezone.utc)

    from app.db.crud import get_email_thread_by_prospect
    thread = await get_email_thread_by_prospect(session_id, prospect_id)

    inbound_message = {
        "message_id": message_id,
        "direction": "inbound",
        "subject": reply_info.get("subject"),
        "body_text": reply_info.get("text_body"),
        "sender_email": prospect_email,
        "recipient_email": reply_info.get("to_email"),
        "timestamp": now.isoformat(),
        "classification": None,
        "sentiment": None,
        "key_signals": [],
    }

    if thread:
        await append_thread_message(
            thread_id=thread["id"],
            message=inbound_message,
            status="replied",
        )
        logger.info(
            "_update_thread_with_reply: appended reply to thread=%s",
            thread["id"],
        )
    else:
        # Create new thread with the reply (outbound message may have been sent
        # before thread tracking was enabled)
        new_thread = {
            "id": str(uuid4()),
            "session_id": session_id,
            "prospect_id": prospect_id,
            "prospect_email": prospect_email,
            "variant_id": deployment.get("variant_id"),
            "deployment_record_id": deployment.get("id"),
            "subject": reply_info.get("subject"),
            "messages": [inbound_message],
            "status": "replied",
            "reply_count": 1,
            "last_activity_at": now.isoformat(),
            "created_at": now.isoformat(),
        }
        await upsert_email_thread(new_thread)
        logger.info(
            "_update_thread_with_reply: created new thread for prospect=%s",
            prospect_id,
        )


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

            # Update email thread status for engagement events
            if event_type in ("open", "click", "bounce", "delivered"):
                await _update_thread_status(deployment, event_type)
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


async def _update_thread_status(deployment: dict[str, Any], event_type: str) -> None:
    """Update the email thread status based on an engagement event.

    Thread status progression: sent → delivered → opened → replied (or bounced).
    Only upgrades status — never downgrades (e.g., opened won't revert to delivered).
    """
    session_id = deployment.get("session_id", "")
    prospect_id = deployment.get("prospect_id", "")
    if not session_id or not prospect_id:
        return

    from app.db.crud import get_email_thread_by_prospect

    thread = await get_email_thread_by_prospect(session_id, prospect_id)
    if not thread:
        return

    current_status = thread.get("status", "sent")
    status_rank = {"sent": 0, "delivered": 1, "opened": 2, "replied": 3, "bounced": 3}

    new_status_map = {
        "delivered": "delivered",
        "open": "opened",
        "click": "opened",  # A click implies it was opened
        "bounce": "bounced",
    }

    new_status = new_status_map.get(event_type)
    if not new_status:
        return

    # Only upgrade status
    if status_rank.get(new_status, 0) <= status_rank.get(current_status, 0):
        return

    from app.db.client import get_db
    from app.db.collections import EMAIL_THREADS

    db = get_db()
    await db[EMAIL_THREADS].update_one(
        {"id": thread["id"]},
        {"$set": {"status": new_status, "last_activity_at": datetime.now(tz=timezone.utc)}},
    )


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


@router.get("/campaign/{session_id}/email-threads")
async def get_session_email_threads(session_id: str) -> list[dict[str, Any]]:
    """Return all email threads for a session, ordered by last activity."""
    from app.db.crud import get_email_threads_for_session
    return await get_email_threads_for_session(session_id)


@router.get("/campaign/{session_id}/email-threads/{prospect_id}")
async def get_prospect_email_thread(
    session_id: str, prospect_id: str
) -> dict[str, Any]:
    """Return the email thread for a specific prospect in a session."""
    from app.db.crud import get_email_thread_by_prospect
    thread = await get_email_thread_by_prospect(session_id, prospect_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Email thread not found")
    return thread


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
