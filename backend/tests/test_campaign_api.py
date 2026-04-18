from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.campaign import _load_active_campaign_state


async def test_load_active_campaign_state_hydrates_saved_variants():
    base_state = {
        "session_id": "sess-1",
        "product_name": "Acme",
        "content_variants": [],
    }
    saved_variants = [
        {
            "id": "var-1",
            "angle_label": "pain-point",
            "body": "Saved body",
        }
    ]
    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = SimpleNamespace(values={})

    with (
        patch("app.api.campaign.load_campaign_state", new=AsyncMock(return_value=base_state)),
        patch(
            "app.api.campaign.get_latest_variants_for_session",
            new=AsyncMock(return_value=saved_variants),
        ),
        patch("app.api.campaign._get_or_init_graph", return_value=mock_graph),
    ):
        state = await _load_active_campaign_state("sess-1")

    assert state is not None
    assert state["session_id"] == "sess-1"
    assert state["content_variants"] == saved_variants


async def test_load_active_campaign_state_prefers_graph_state_when_available():
    base_state = {
        "session_id": "sess-2",
        "product_name": "Base Product",
        "content_variants": [],
    }
    graph_state = {
        "product_name": "Checkpoint Product",
        "content_variants": [{"id": "var-live", "body": "Live body"}],
    }
    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = SimpleNamespace(values=graph_state)

    with (
        patch("app.api.campaign.load_campaign_state", new=AsyncMock(return_value=base_state)),
        patch("app.api.campaign._get_or_init_graph", return_value=mock_graph),
    ):
        state = await _load_active_campaign_state("sess-2")

    assert state is not None
    assert state["product_name"] == "Checkpoint Product"
    assert state["content_variants"] == graph_state["content_variants"]
