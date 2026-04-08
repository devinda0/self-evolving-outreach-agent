"""Integration tests for webhook endpoints — issue #20 acceptance criteria.

Covers:
- POST /webhook/resend with email.opened creates a NormalizedFeedbackEvent in MongoDB
- Correlation: event with provider_message_id matching a deployment record gets deployment_record_id
- Unmatched event (no matching deployment record) goes to quarantine collection
- Deduplication: sending same event twice results in only one record
- GET /campaign/{session_id}/feedback-events returns all events for that session
- POST /webhook/unipile normalizes LinkedIn DM events
- HMAC signature verification: valid signature passes, invalid is rejected with 401
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.client import get_db
from app.db.collections import DEPLOYMENT_RECORDS, FEEDBACK_EVENTS, QUARANTINE
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_deployment_record(
    session_id: str = "sess-1",
    variant_id: str = "var-A",
    prospect_id: str = "prospect-1",
    provider_message_id: str = "msg-resend-001",
    channel: str = "email",
) -> dict:
    """Insert a deployment record directly into MongoDB for correlation tests."""
    record = {
        "id": "deploy-001",
        "session_id": session_id,
        "variant_id": variant_id,
        "segment_id": "seg-1",
        "prospect_id": prospect_id,
        "channel": channel,
        "provider": "resend",
        "provider_message_id": provider_message_id,
        "ab_cohort": "A",
        "rendered_content_hash": "abc123",
        "sent_at": "2026-04-01T00:00:00+00:00",
    }
    db = get_db()
    await db[DEPLOYMENT_RECORDS].insert_one({**record})
    return record


# ---------------------------------------------------------------------------
# POST /webhook/resend — basic acceptance
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_resend_webhook_creates_feedback_event():
    """POST /webhook/resend with email.opened creates a NormalizedFeedbackEvent."""
    await _seed_deployment_record(provider_message_id="msg-resend-001")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/resend",
            json={
                "type": "email.opened",
                "data": {
                    "message_id": "msg-resend-001",
                    "email_id": "evt-resend-001",
                },
            },
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    db = get_db()
    events = []
    async for doc in db[FEEDBACK_EVENTS].find({"provider": "resend"}):
        doc.pop("_id", None)
        events.append(doc)

    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "open"
    assert event["provider_message_id"] == "msg-resend-001"
    assert event["deployment_record_id"] == "deploy-001"
    assert event["variant_id"] == "var-A"
    assert event["session_id"] == "sess-1"


# ---------------------------------------------------------------------------
# Correlation: matched vs quarantined
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_resend_webhook_correlates_to_deployment():
    """Event with matching provider_message_id gets deployment_record_id filled."""
    await _seed_deployment_record(
        provider_message_id="msg-corr-001",
        variant_id="var-B",
        prospect_id="prospect-2",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/webhook/resend",
            json={
                "type": "email.clicked",
                "data": {
                    "message_id": "msg-corr-001",
                    "email_id": "evt-corr-001",
                },
            },
        )

    db = get_db()
    event = await db[FEEDBACK_EVENTS].find_one({"dedupe_key": "resend:evt-corr-001"})
    assert event is not None
    assert event["deployment_record_id"] == "deploy-001"
    assert event["variant_id"] == "var-B"
    assert event["event_type"] == "click"


@pytest.mark.integration
async def test_unmatched_event_goes_to_quarantine():
    """Event with no matching deployment record is quarantined."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/resend",
            json={
                "type": "email.opened",
                "data": {
                    "message_id": "msg-no-match",
                    "email_id": "evt-no-match-001",
                },
            },
        )

    assert resp.status_code == 200

    db = get_db()
    quarantined = await db[QUARANTINE].find_one({"dedupe_key": "resend:evt-no-match-001"})
    assert quarantined is not None
    assert quarantined["provider_message_id"] == "msg-no-match"

    # Should NOT be in feedback_events
    in_feedback = await db[FEEDBACK_EVENTS].find_one({"dedupe_key": "resend:evt-no-match-001"})
    assert in_feedback is None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_deduplication_prevents_double_insert():
    """Sending the same event twice results in only one record."""
    await _seed_deployment_record(provider_message_id="msg-dup-001")

    payload = {
        "type": "email.opened",
        "data": {
            "message_id": "msg-dup-001",
            "email_id": "evt-dup-001",
        },
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/webhook/resend", json=payload)
        await client.post("/webhook/resend", json=payload)

    db = get_db()
    count = await db[FEEDBACK_EVENTS].count_documents({"dedupe_key": "resend:evt-dup-001"})
    assert count == 1


# ---------------------------------------------------------------------------
# GET /campaign/{session_id}/feedback-events
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_feedback_events_for_session():
    """GET /campaign/{session_id}/feedback-events returns all events for that session."""
    await _seed_deployment_record(
        session_id="sess-fb-list",
        provider_message_id="msg-list-001",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create two events for the session
        await client.post(
            "/webhook/resend",
            json={
                "type": "email.opened",
                "data": {"message_id": "msg-list-001", "email_id": "evt-list-001"},
            },
        )
        await client.post(
            "/webhook/resend",
            json={
                "type": "email.clicked",
                "data": {"message_id": "msg-list-001", "email_id": "evt-list-002"},
            },
        )

        resp = await client.get("/campaign/sess-fb-list/feedback-events")

    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 2
    event_types = {e["event_type"] for e in events}
    assert event_types == {"open", "click"}


# ---------------------------------------------------------------------------
# POST /webhook/unipile — LinkedIn DM events
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_unipile_webhook_normalizes_linkedin_events():
    """POST /webhook/unipile normalizes a LinkedIn DM read event."""
    await _seed_deployment_record(
        provider_message_id="msg-uni-001",
        channel="linkedin",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/unipile",
            json={
                "type": "message.read",
                "data": {
                    "message_id": "msg-uni-001",
                    "event_id": "evt-uni-001",
                },
            },
        )

    assert resp.status_code == 200

    db = get_db()
    event = await db[FEEDBACK_EVENTS].find_one({"dedupe_key": "unipile:evt-uni-001"})
    assert event is not None
    assert event["event_type"] == "open"
    assert event["channel"] == "linkedin"  # from the deployment record


# ---------------------------------------------------------------------------
# POST /webhook/engagement — generic fallback
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_generic_engagement_webhook():
    """POST /webhook/engagement works as a generic fallback."""
    await _seed_deployment_record(provider_message_id="msg-gen-001")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/engagement",
            json={
                "provider": "manual",
                "provider_message_id": "msg-gen-001",
                "provider_event_id": "evt-gen-001",
                "event_type": "reply",
                "channel": "email",
            },
        )

    assert resp.status_code == 200

    db = get_db()
    event = await db[FEEDBACK_EVENTS].find_one({"provider": "manual"})
    assert event is not None
    assert event["event_type"] == "reply"
    assert event["deployment_record_id"] == "deploy-001"


# ---------------------------------------------------------------------------
# HMAC signature verification — unit-level (no MongoDB required)
# ---------------------------------------------------------------------------


class TestVerifyResendSignature:
    """Unit tests for the HMAC svix signature verification helper."""

    def _make_signature(
        self,
        svix_id: str,
        svix_timestamp: str,
        body: bytes,
        secret: str,
    ) -> str:
        import base64
        import hashlib
        import hmac as _hmac

        secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
        signed_content = f"{svix_id}.{svix_timestamp}.{body.decode()}"
        sig = base64.b64encode(
            _hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()
        ).decode()
        return f"v1,{sig}"

    def test_valid_signature_passes(self):
        import time

        from app.api.webhooks import _verify_resend_signature

        secret = "whsec_" + __import__("base64").b64encode(b"test-secret").decode()
        body = b'{"type": "email.opened"}'
        svix_id = "msg_001"
        svix_ts = str(int(time.time()))
        sig = self._make_signature(svix_id, svix_ts, body, secret)

        assert _verify_resend_signature(body, svix_id, svix_ts, sig, secret) is True

    def test_invalid_signature_fails(self):
        import time

        from app.api.webhooks import _verify_resend_signature

        secret = "whsec_" + __import__("base64").b64encode(b"test-secret").decode()
        body = b'{"type": "email.opened"}'
        svix_id = "msg_001"
        svix_ts = str(int(time.time()))

        assert _verify_resend_signature(body, svix_id, svix_ts, "v1,invalidsig", secret) is False

    def test_stale_timestamp_fails(self):
        from app.api.webhooks import _verify_resend_signature

        secret = "whsec_" + __import__("base64").b64encode(b"test-secret").decode()
        body = b'{"type": "email.opened"}'
        svix_id = "msg_001"
        stale_ts = "1000000000"  # way in the past
        sig = self._make_signature(svix_id, stale_ts, body, secret)

        assert _verify_resend_signature(body, svix_id, stale_ts, sig, secret) is False


@pytest.mark.integration
async def test_resend_webhook_rejects_invalid_signature():
    """When RESEND_WEBHOOK_SECRET is set, invalid signatures are rejected with 401."""
    import time
    from unittest.mock import patch

    secret = "whsec_" + __import__("base64").b64encode(b"test-secret").decode()

    with patch("app.api.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = secret

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/webhook/resend",
                content=b'{"type": "email.opened", "data": {}}',
                headers={
                    "Content-Type": "application/json",
                    "svix-id": "msg_test",
                    "svix-timestamp": str(int(time.time())),
                    "svix-signature": "v1,badsignature",
                },
            )

    assert resp.status_code == 401


@pytest.mark.integration
async def test_resend_webhook_accepts_valid_signature():
    """When RESEND_WEBHOOK_SECRET is set, valid svix signatures are accepted."""
    import base64
    import hashlib
    import hmac as _hmac
    import time
    from unittest.mock import patch

    secret = "whsec_" + base64.b64encode(b"test-secret").decode()
    body = b'{"type": "email.opened", "data": {"message_id": "msg-hmac-001", "email_id": "evt-hmac-001"}}'
    svix_id = "msg_hmac_test"
    svix_ts = str(int(time.time()))

    # Build a valid signature
    secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
    signed_content = f"{svix_id}.{svix_ts}.{body.decode()}"
    sig = base64.b64encode(
        _hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()
    ).decode()
    svix_sig = f"v1,{sig}"

    with patch("app.api.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = secret

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/webhook/resend",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "svix-id": svix_id,
                    "svix-timestamp": svix_ts,
                    "svix-signature": svix_sig,
                },
            )

    assert resp.status_code == 200
