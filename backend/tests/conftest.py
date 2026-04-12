"""Root-level pytest configuration for the test suite.

SAFETY GUARANTEE: Real email sending via Resend is unconditionally disabled
in every test, regardless of the USE_MOCK_SEND value in .env or environment
variables.  This prevents accidental quota exhaustion during test runs.

Two defence layers:
  1. settings.USE_MOCK_SEND is forced to True so the deployment agent always
     takes the mock_send path.
  2. app.tools.resend_client.send_email is patched to raise RuntimeError if
     it is somehow reached.  This turns a silent quota drain into a loud,
     immediately visible test failure.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _enforce_mock_send():
    """Force mock email sending for every test in the suite.

    Restores the original value after each test so unit tests that
    explicitly exercise the USE_MOCK_SEND=False code path (by patching
    settings themselves) remain unaffected after they finish.
    """
    original = settings.USE_MOCK_SEND
    settings.USE_MOCK_SEND = True

    # Safety net: if send_email is called despite the flag, fail loudly
    # instead of silently consuming Resend quota.
    with patch(
        "app.tools.resend_client.send_email",
        new_callable=AsyncMock,
        side_effect=RuntimeError(
            "Real Resend send_email was called during a test. "
            "USE_MOCK_SEND must be True in tests.  "
            "Patch send_email explicitly if you need to test the real send path."
        ),
    ):
        yield

    settings.USE_MOCK_SEND = original
