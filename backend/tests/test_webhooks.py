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
