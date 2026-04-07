"""Integration tests for the FastAPI campaign API and WebSocket endpoint.

Requires a running MongoDB instance.
Run with: pytest -m integration
"""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.db.client import close_db, connect_db, get_db
from app.db.crud import create_indexes
from app.main import app

TEST_DB = "signal_to_action_test"


@pytest.fixture(autouse=True)
async def _setup_teardown():
    """Connect to a dedicated test database, create indexes, and clean up after."""
    from app.core.config import settings

    settings.DB_NAME = TEST_DB
    await connect_db()
    await create_indexes()
    yield
    db = get_db()
    await db.client.drop_database(TEST_DB)
    await close_db()


# ---------------------------------------------------------------------------
# REST: POST /campaign/start
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_start_campaign():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/campaign/start",
            json={
                "product_name": "Acme Widget",
                "product_description": "Best widget ever",
                "target_market": "SMBs",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert isinstance(body["session_id"], str)


# ---------------------------------------------------------------------------
# REST: GET /campaign/{session_id}/state
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_get_campaign_state():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a session first
        start = await client.post(
            "/campaign/start",
            json={
                "product_name": "Acme Widget",
                "product_description": "A widget",
                "target_market": "SMBs",
            },
        )
        session_id = start.json()["session_id"]

        # Fetch the state
        resp = await client.get(f"/campaign/{session_id}/state")

    assert resp.status_code == 200
    state = resp.json()
    assert state["session_id"] == session_id
    assert state["product_name"] == "Acme Widget"
    assert state["cycle_number"] == 1


@pytest.mark.integration
async def test_get_campaign_state_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/campaign/nonexistent/state")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# REST: POST /campaign/{session_id}/ui-action
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_ui_action_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start = await client.post(
            "/campaign/start",
            json={
                "product_name": "Test",
                "product_description": "Desc",
                "target_market": "Market",
            },
        )
        session_id = start.json()["session_id"]

        resp = await client.post(
            f"/campaign/{session_id}/ui-action",
            json={
                "instance_id": "ui_001",
                "action_id": "select_segment",
                "payload": {"segment_id": "seg-1"},
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "frames" in body
    assert len(body["frames"]) > 0


# ---------------------------------------------------------------------------
# REST: GET /health
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "connected"


# ---------------------------------------------------------------------------
# WebSocket: /ws/campaign/{session_id}
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_websocket_echo():
    """Connect via WS, send a user message, and verify at least one JSON frame returns."""
    client = TestClient(app)

    with client.websocket_connect("/ws/campaign/ws-test-001") as ws:
        ws.send_json({"type": "user_message", "content": "Hello, agent!"})

        # Should receive at least one frame
        frames = []
        for _ in range(2):
            frame = ws.receive_json()
            frames.append(frame)

        assert len(frames) >= 1
        # One should be a progress frame, the other a token echo
        types = {f["type"] for f in frames}
        assert "token" in types or "progress" in types
