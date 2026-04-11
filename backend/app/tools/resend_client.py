"""Resend email API client.

Thin async wrapper around the Resend REST API.  Returns the raw response dict
on success (which always contains ``"id"`` — the provider_message_id used for
webhook correlation).

Includes CAN-SPAM compliance (unsubscribe link + physical address footer)
and token-bucket rate limiting to protect sender domain reputation.

Raises ``httpx.HTTPStatusError`` on 4xx/5xx responses so the caller can
decide how to handle failures (e.g. mark a deployment record as failed).
"""

import asyncio
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Simple async-safe token-bucket rate limiter.

    Allows ``rate`` sends per ``interval`` seconds.  Callers ``await acquire()``
    which sleeps only when the bucket is empty.
    """

    def __init__(self, rate: int, interval: float) -> None:
        self._rate = max(1, rate)
        self._interval = max(0.1, interval)
        self._tokens = float(self._rate)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * (self._rate / self._interval))
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) * (self._interval / self._rate)
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# Singleton rate limiter — initialized lazily so settings are read at call time.
_limiter: _TokenBucket | None = None


def _get_limiter() -> _TokenBucket:
    global _limiter
    if _limiter is None:
        _limiter = _TokenBucket(
            rate=settings.SEND_RATE_LIMIT,
            interval=settings.SEND_RATE_INTERVAL_SECONDS,
        )
    return _limiter


# ---------------------------------------------------------------------------
# CAN-SPAM footer
# ---------------------------------------------------------------------------


def inject_can_spam_footer(html_body: str, session_id: str = "") -> str:
    """Append a CAN-SPAM-compliant footer to the HTML body.

    Includes:
    - Unsubscribe link (List-Unsubscribe is handled via Resend header)
    - Physical mailing address
    - Optionally the session_id in the unsubscribe URL for tracking

    Returns the original body if no UNSUBSCRIBE_URL or PHYSICAL_ADDRESS is configured.
    """
    parts: list[str] = []

    unsubscribe_url = settings.UNSUBSCRIBE_URL
    physical_address = settings.PHYSICAL_ADDRESS

    if not unsubscribe_url and not physical_address:
        return html_body

    parts.append('<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e5e5e5;'
                 'font-size:11px;color:#999;line-height:1.5;font-family:Arial,sans-serif">')

    if unsubscribe_url:
        unsub_href = f"{unsubscribe_url}?sid={session_id}" if session_id else unsubscribe_url
        parts.append(
            f'<p>If you no longer wish to receive these emails, '
            f'<a href="{unsub_href}" style="color:#999;text-decoration:underline">'
            f'unsubscribe here</a>.</p>'
        )

    if physical_address:
        parts.append(f"<p>{physical_address}</p>")

    parts.append("</div>")

    footer = "\n".join(parts)

    # Insert before </body> if present, otherwise append
    if "</body>" in html_body.lower():
        idx = html_body.lower().rfind("</body>")
        return html_body[:idx] + footer + html_body[idx:]
    return html_body + footer


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    from_email: str | None = None,
    tags: dict | None = None,
    session_id: str = "",
) -> dict:
    """Send an email via the Resend API.

    Args:
        to_email: Recipient email address.
        to_name: Recipient display name (used in the ``To`` header).
        subject: Email subject line.
        html_body: HTML body of the email.
        from_email: Sender address; falls back to ``settings.RESEND_FROM_EMAIL``.
        tags: Optional key/value tags attached to the message for reporting.
        session_id: Campaign session ID (used in CAN-SPAM unsubscribe link).

    Returns:
        The JSON response from Resend, which includes ``"id"`` — the
        ``provider_message_id`` needed for later webhook correlation.

    Raises:
        httpx.HTTPStatusError: When Resend returns a 4xx or 5xx status code.
    """
    # Rate limiting — wait for a token before sending
    await _get_limiter().acquire()

    from_addr = from_email or settings.RESEND_FROM_EMAIL

    # CAN-SPAM: inject footer with unsubscribe link and physical address
    compliant_html = inject_can_spam_footer(html_body, session_id=session_id)

    payload: dict = {
        "from": from_addr,
        "to": [f"{to_name} <{to_email}>" if to_name else to_email],
        "subject": subject,
        "html": compliant_html,
    }
    if tags:
        payload["tags"] = [{"name": k, "value": v} for k, v in tags.items()]

    # CAN-SPAM: List-Unsubscribe header for one-click unsubscribe
    if settings.UNSUBSCRIBE_URL:
        unsub_url = (
            f"{settings.UNSUBSCRIBE_URL}?sid={session_id}" if session_id
            else settings.UNSUBSCRIBE_URL
        )
        payload["headers"] = {
            "List-Unsubscribe": f"<{unsub_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

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
