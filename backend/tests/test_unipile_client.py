from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router as health_router
from app.tools.unipile_client import (
    extract_linkedin_identifier,
    get_unipile_base_url,
    get_unipile_connection_health,
    send_linkedin_message,
)


def test_get_unipile_base_url_adds_https():
    with patch("app.tools.unipile_client.settings") as mock_settings:
        mock_settings.UNIPILE_DSN = "api34.unipile.com:16477"
        assert get_unipile_base_url() == "https://api34.unipile.com:16477"


def test_extract_linkedin_identifier_from_public_url():
    identifier = extract_linkedin_identifier("https://www.linkedin.com/in/satyanadella/")
    assert identifier == "satyanadella"


async def test_get_unipile_connection_health_uses_get_only_calls():
    with patch(
        "app.tools.unipile_client._request",
        new_callable=AsyncMock,
        side_effect=[
            {
                "items": [
                    {
                        "id": "acc-1",
                        "type": "LINKEDIN",
                        "name": "Test Account",
                    }
                ]
            },
            {
                "id": "acc-1",
                "type": "LINKEDIN",
                "name": "Test Account",
                "sources": [{"id": "src-1", "status": "OK"}],
            },
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "public_identifier": "jane-doe",
            },
            {"items": []},
            {"items": []},
        ],
    ) as request_mock, patch("app.tools.unipile_client.settings") as mock_settings:
        mock_settings.UNIPILE_DSN = "api34.unipile.com:16477"
        mock_settings.UNIPILE_API_KEY = "secret"
        mock_settings.UNIPILE_LINKEDIN_ACCOUNT_ID = "acc-1"

        result = await get_unipile_connection_health()

    assert result["status"] == "connected"
    assert result["connected"] is True
    assert result["account_id"] == "acc-1"
    methods = [call.args[0] for call in request_mock.await_args_list]
    assert methods == ["GET", "GET", "GET", "GET", "GET"]


async def test_send_linkedin_message_resolves_profile_before_starting_chat():
    with patch(
        "app.tools.unipile_client._request",
        new_callable=AsyncMock,
        side_effect=[
            {"provider_id": "ACo123", "public_identifier": "jane-doe"},
            {"object": "Chat", "id": "chat-1"},
            {"items": [{"message_id": "msg-1"}]},
        ],
    ) as request_mock, patch("app.tools.unipile_client.settings") as mock_settings:
        mock_settings.UNIPILE_DSN = "api34.unipile.com:16477"
        mock_settings.UNIPILE_API_KEY = "secret"
        mock_settings.UNIPILE_LINKEDIN_ACCOUNT_ID = "acc-1"

        result = await send_linkedin_message(
            "https://www.linkedin.com/in/jane-doe/",
            "Hello world",
        )

    assert result["provider_message_id"] == "msg-1"
    assert request_mock.await_args_list[0].args[:2] == ("GET", "/api/v1/users/jane-doe")
    assert request_mock.await_args_list[1].args[:2] == ("POST", "/api/v1/chats")


def test_health_unipile_route_returns_probe_result():
    app = FastAPI()
    app.include_router(health_router)

    with patch(
        "app.api.health.get_unipile_connection_health",
        new_callable=AsyncMock,
        return_value={"status": "connected", "connected": True},
    ):
        client = TestClient(app)
        response = client.get("/health/unipile")

    assert response.status_code == 200
    assert response.json()["status"] == "connected"
