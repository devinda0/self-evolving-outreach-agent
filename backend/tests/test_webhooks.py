"""Unit tests for webhook helpers — no MongoDB required."""

import base64
import hashlib
import hmac as _hmac
import time


class TestVerifyResendSignature:
    """Unit tests for the HMAC svix signature verification helper."""

    def _make_signature(
        self,
        svix_id: str,
        svix_timestamp: str,
        body: bytes,
        secret: str,
    ) -> str:
        secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
        signed_content = f"{svix_id}.{svix_timestamp}.{body.decode()}"
        sig = base64.b64encode(
            _hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()
        ).decode()
        return f"v1,{sig}"

    def test_valid_signature_passes(self):
        from app.api.webhooks import _verify_resend_signature

        secret = "whsec_" + base64.b64encode(b"test-secret").decode()
        body = b'{"type": "email.opened"}'
        svix_id = "msg_001"
        svix_ts = str(int(time.time()))
        sig = self._make_signature(svix_id, svix_ts, body, secret)

        assert _verify_resend_signature(body, svix_id, svix_ts, sig, secret) is True

    def test_invalid_signature_fails(self):
        from app.api.webhooks import _verify_resend_signature

        secret = "whsec_" + base64.b64encode(b"test-secret").decode()
        body = b'{"type": "email.opened"}'
        svix_id = "msg_001"
        svix_ts = str(int(time.time()))

        assert _verify_resend_signature(body, svix_id, svix_ts, "v1,invalidsig", secret) is False

    def test_stale_timestamp_fails(self):
        from app.api.webhooks import _verify_resend_signature

        secret = "whsec_" + base64.b64encode(b"test-secret").decode()
        body = b'{"type": "email.opened"}'
        svix_id = "msg_001"
        stale_ts = "1000000000"  # way in the past
        sig = self._make_signature(svix_id, stale_ts, body, secret)

        assert _verify_resend_signature(body, svix_id, stale_ts, sig, secret) is False


# ---------------------------------------------------------------------------
# CAN-SPAM footer injection
# ---------------------------------------------------------------------------


class TestInjectCanSpamFooter:
    def test_appends_footer_with_unsubscribe_and_address(self):
        from unittest.mock import patch

        from app.tools.resend_client import inject_can_spam_footer

        with patch("app.tools.resend_client.settings") as mock_settings:
            mock_settings.UNSUBSCRIBE_URL = "https://example.com/unsub"
            mock_settings.PHYSICAL_ADDRESS = "123 Main St, City, ST 00000"
            html = inject_can_spam_footer("<p>Hello</p>", session_id="sess-1")

        assert "unsubscribe here" in html.lower()
        assert "123 Main St" in html
        assert "sid=sess-1" in html

    def test_inserts_before_body_close_tag(self):
        from unittest.mock import patch

        from app.tools.resend_client import inject_can_spam_footer

        with patch("app.tools.resend_client.settings") as mock_settings:
            mock_settings.UNSUBSCRIBE_URL = "https://example.com/unsub"
            mock_settings.PHYSICAL_ADDRESS = "123 Main St"
            html = inject_can_spam_footer("<html><body><p>Hello</p></body></html>", "s1")

        # Footer should appear before </body>
        body_idx = html.lower().rfind("</body>")
        unsub_idx = html.lower().rfind("unsubscribe")
        assert unsub_idx < body_idx

    def test_no_config_returns_original(self):
        from unittest.mock import patch

        from app.tools.resend_client import inject_can_spam_footer

        with patch("app.tools.resend_client.settings") as mock_settings:
            mock_settings.UNSUBSCRIBE_URL = ""
            mock_settings.PHYSICAL_ADDRESS = ""
            html = inject_can_spam_footer("<p>Hello</p>")

        assert html == "<p>Hello</p>"

    def test_only_physical_address(self):
        from unittest.mock import patch

        from app.tools.resend_client import inject_can_spam_footer

        with patch("app.tools.resend_client.settings") as mock_settings:
            mock_settings.UNSUBSCRIBE_URL = ""
            mock_settings.PHYSICAL_ADDRESS = "456 Oak Ave"
            html = inject_can_spam_footer("<p>Hello</p>")

        assert "456 Oak Ave" in html
        assert "unsubscribe" not in html.lower()


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------


class TestTokenBucket:
    async def test_acquire_does_not_raise(self):
        from app.tools.resend_client import _TokenBucket

        bucket = _TokenBucket(rate=10, interval=1.0)
        # Should complete without error
        await bucket.acquire()

    async def test_multiple_acquires_within_rate(self):
        from app.tools.resend_client import _TokenBucket

        bucket = _TokenBucket(rate=100, interval=1.0)
        for _ in range(50):
            await bucket.acquire()
