from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.campaign import _load_active_campaign_state, _sync_prospect_manager_ui_action


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


async def test_sync_prospect_manager_ui_action_adds_and_selects_manual_prospect():
    base_state = {
        "session_id": "sess-add",
        "prospect_cards": [
            {
                "id": "p-001",
                "name": "Alice Johnson",
                "email": "alice@acme.com",
                "title": "VP Engineering",
                "company": "Acme Corp",
                "fit_score": 0.92,
                "urgency_score": 0.85,
                "angle_recommendation": "pain-point",
                "channel_recommendation": "email",
                "source": "discovery",
            }
        ],
        "selected_prospect_ids": ["p-001"],
    }
    persisted_cards = [
        {
            "id": "p-001",
            "name": "Alice Johnson",
            "email": "alice@acme.com",
            "title": "VP Engineering",
            "company": "Acme Corp",
            "fit_score": 0.92,
            "urgency_score": 0.85,
            "angle_recommendation": "pain-point",
            "channel_recommendation": "email",
            "source": "discovery",
        }
    ]
    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = SimpleNamespace(values={"selected_prospect_ids": ["p-001"]})

    with (
        patch("app.api.campaign.load_campaign_state", new=AsyncMock(return_value=dict(base_state))),
        patch("app.api.campaign.get_prospect_cards", new=AsyncMock(return_value=list(persisted_cards))),
        patch("app.api.campaign.save_prospect_cards", new=AsyncMock()) as save_cards,
        patch("app.api.campaign.save_campaign_state", new=AsyncMock()) as save_state,
        patch("app.api.campaign._get_or_init_graph", return_value=mock_graph),
    ):
        changed = await _sync_prospect_manager_ui_action(
            "sess-add",
            "add_prospect_manual",
            {
                "name": "New Person",
                "email": "new@example.com",
                "title": "Founder",
                "company": "Orbit Labs",
            },
        )

    assert changed is True

    saved_cards = save_cards.await_args.args[1]
    assert len(saved_cards) == 2
    new_card = next(card for card in saved_cards if card["id"] != "p-001")
    assert new_card["name"] == "New Person"
    assert new_card["email"] == "new@example.com"
    assert new_card["source"] == "manual"

    saved_state = save_state.await_args.args[1]
    assert len(saved_state["prospect_cards"]) == 2
    assert new_card["id"] in saved_state["selected_prospect_ids"]
    assert any(card["name"] == "New Person" for card in saved_state["prospect_cards"])

    graph_patch = mock_graph.aupdate_state.await_args.args[1]
    assert new_card["id"] in graph_patch["selected_prospect_ids"]
    assert any(card["name"] == "New Person" for card in graph_patch["prospect_cards"])


async def test_sync_prospect_manager_ui_action_removes_selected_prospects():
    base_state = {
        "session_id": "sess-remove",
        "prospect_cards": [
            {
                "id": "p-001",
                "name": "Alice Johnson",
                "email": "alice@acme.com",
                "title": "VP Engineering",
                "company": "Acme Corp",
                "fit_score": 0.92,
                "urgency_score": 0.85,
                "angle_recommendation": "pain-point",
                "channel_recommendation": "email",
                "source": "discovery",
            },
            {
                "id": "p-002",
                "name": "Bob Smith",
                "email": "bob@widgets.io",
                "title": "CTO",
                "company": "Widgets Inc",
                "fit_score": 0.78,
                "urgency_score": 0.65,
                "angle_recommendation": "value-proposition",
                "channel_recommendation": "linkedin",
                "source": "csv",
            },
        ],
        "selected_prospect_ids": ["p-001", "p-002"],
    }
    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = SimpleNamespace(
        values={"selected_prospect_ids": ["p-001", "p-002"]}
    )

    with (
        patch("app.api.campaign.load_campaign_state", new=AsyncMock(return_value=dict(base_state))),
        patch(
            "app.api.campaign.get_prospect_cards",
            new=AsyncMock(return_value=list(base_state["prospect_cards"])),
        ),
        patch("app.api.campaign.save_prospect_cards", new=AsyncMock()) as save_cards,
        patch("app.api.campaign.save_campaign_state", new=AsyncMock()) as save_state,
        patch("app.api.campaign._get_or_init_graph", return_value=mock_graph),
    ):
        changed = await _sync_prospect_manager_ui_action(
            "sess-remove",
            "remove_selected",
            {"prospect_ids": ["p-002"]},
        )

    assert changed is True

    saved_cards = save_cards.await_args.args[1]
    assert [card["id"] for card in saved_cards] == ["p-001"]

    saved_state = save_state.await_args.args[1]
    assert [card["id"] for card in saved_state["prospect_cards"]] == ["p-001"]
    assert saved_state["selected_prospect_ids"] == ["p-001"]

    graph_patch = mock_graph.aupdate_state.await_args.args[1]
    assert [card["id"] for card in graph_patch["prospect_cards"]] == ["p-001"]
    assert graph_patch["selected_prospect_ids"] == ["p-001"]
