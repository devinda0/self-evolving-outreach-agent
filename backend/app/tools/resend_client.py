"""Resend email API client.

Thin async wrapper around the Resend REST API.  Returns the raw response dict
on success (which always contains ``"id"`` — the provider_message_id used for
webhook correlation).

Raises ``httpx.HTTPStatusError`` on 4xx/5xx responses so the caller can
decide how to handle failures (e.g. mark a deployment record as failed).
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_TIMEOUT = 15  # seconds


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    from_email: str | None = None,
    tags: dict | None = None,
) -> dict:
    """Send an email via the Resend API.

    Args:
        to_email: Recipient email address.
        to_name: Recipient display name (used in the ``To`` header).
        subject: Email subject line.
        html_body: HTML body of the email.
        from_email: Sender address; falls back to ``settings.RESEND_FROM_EMAIL``.
        tags: Optional key/value tags attached to the message for reporting.

    Returns:
        The JSON response from Resend, which includes ``"id"`` — the
        ``provider_message_id`` needed for later webhook correlation.

    Raises:
        httpx.HTTPStatusError: When Resend returns a 4xx or 5xx status code.
    """
    from_addr = from_email or settings.RESEND_FROM_EMAIL

    payload: dict = {
        "from": from_addr,
        "to": [f"{to_name} <{to_email}>" if to_name else to_email],
        "subject": subject,
        "html": html_body,
    }
    if tags:
        payload["tags"] = [{"name": k, "value": v} for k, v in tags.items()]

    logger.debug("resend_client.send_email to=%s subject=%r", to_email, subject)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()

    result = response.json()
    logger.info(
        "resend_client.send_email success to=%s provider_message_id=%s",
        to_email,
        result.get("id"),
    )
    return result
