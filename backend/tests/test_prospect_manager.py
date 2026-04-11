"""Tests for the Prospect Manager agent.

Tests cover:
- Helper functions (matching, card building, manual prospect creation)
- Action execution for all action types
- Mock command parsing (no LLM)
- UI frame building
- Graph routing includes prospect_manage
"""

import pytest

from app.agents.prospect_manager import (
    _build_prospect_card,
    _create_manual_prospect,
    _execute_actions,
    _format_prospect_list,
    _match_prospect_by_email,
    _match_prospect_by_name,
    _parse_json_response,
    _parse_mock_commands,
    build_prospect_list_frame,
    build_prospect_manager_frame,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CARDS = [
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
    {
        "id": "p-003",
        "name": "Carol Chen",
        "email": None,
        "title": "Director of Product",
        "company": "TechStart",
        "fit_score": 0.60,
        "urgency_score": 0.50,
        "angle_recommendation": "social-proof",
        "channel_recommendation": "linkedin",
        "source": "manual",
    },
]


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


class TestMatchProspectByName:
    def test_exact_match(self):
        match = _match_prospect_by_name("Alice Johnson", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-001"

    def test_case_insensitive(self):
        match = _match_prospect_by_name("alice johnson", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-001"

    def test_first_name_match(self):
        match = _match_prospect_by_name("Bob", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-002"

    def test_last_name_match(self):
        match = _match_prospect_by_name("Chen", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-003"

    def test_substring_match(self):
        match = _match_prospect_by_name("arol", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-003"

    def test_no_match(self):
        match = _match_prospect_by_name("Zach Williams", SAMPLE_CARDS)
        assert match is None


class TestMatchProspectByEmail:
    def test_exact_match(self):
        match = _match_prospect_by_email("alice@acme.com", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-001"

    def test_case_insensitive(self):
        match = _match_prospect_by_email("BOB@WIDGETS.IO", SAMPLE_CARDS)
        assert match is not None
        assert match["id"] == "p-002"

    def test_no_match(self):
        match = _match_prospect_by_email("nobody@example.com", SAMPLE_CARDS)
        assert match is None

    def test_none_email_skipped(self):
        match = _match_prospect_by_email("nonexistent@nowhere.com", SAMPLE_CARDS)
        assert match is None


# ---------------------------------------------------------------------------
# Create manual prospect
# ---------------------------------------------------------------------------


class TestCreateManualProspect:
    def test_basic_creation(self):
        p = _create_manual_prospect({"name": "Jane Doe", "email": "jane@test.com"})
        assert p["name"] == "Jane Doe"
        assert p["email"] == "jane@test.com"
        assert p["source"] == "manual"
        assert p["fit_score"] == 0.75
        assert p["channel_recommendation"] == "email"
        assert p["id"].startswith("prospect-")

    def test_no_email_gets_linkedin_channel(self):
        p = _create_manual_prospect({"name": "John Doe"})
        assert p["email"] is None
        assert p["channel_recommendation"] == "linkedin"

    def test_empty_fields_normalized(self):
        p = _create_manual_prospect({"name": "  Test  ", "email": "", "title": ""})
        assert p["name"] == "Test"
        assert p["email"] is None
        assert p["title"] == ""


# ---------------------------------------------------------------------------
# Build prospect card
# ---------------------------------------------------------------------------


class TestBuildProspectCard:
    def test_includes_required_fields(self):
        card = _build_prospect_card(SAMPLE_CARDS[0])
        assert card["id"] == "p-001"
        assert card["name"] == "Alice Johnson"
        assert card["email"] == "alice@acme.com"
        assert card["fit_score"] == 0.92
        assert card["source"] == "discovery"

    def test_defaults_for_missing_fields(self):
        card = _build_prospect_card({"id": "x", "name": "Minimal"})
        assert card["fit_score"] == 0.5
        assert card["source"] == "manual"


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


class TestExecuteActions:
    def test_add_prospect(self):
        actions = [
            {
                "type": "add_prospect",
                "prospects": [{"name": "New Person", "email": "new@test.com"}],
            }
        ]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), ["p-001"])
        assert len(cards) == 4
        assert cards[-1]["name"] == "New Person"
        assert cards[-1]["id"] in sel  # Auto-selected
        assert any("Added" in log for log in logs)

    def test_add_prospect_without_name_skipped(self):
        actions = [
            {"type": "add_prospect", "prospects": [{"email": "no-name@test.com"}]}
        ]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), [])
        assert len(cards) == 3  # Unchanged

    def test_remove_by_name(self):
        actions = [{"type": "remove_prospect", "match_names": ["Alice"]}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), ["p-001", "p-002"])
        assert len(cards) == 2
        assert all(c["id"] != "p-001" for c in cards)
        assert "p-001" not in sel

    def test_remove_by_id(self):
        actions = [{"type": "remove_prospect", "prospect_ids": ["p-002"]}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), ["p-002"])
        assert len(cards) == 2
        assert "p-002" not in sel

    def test_remove_nonexistent(self):
        actions = [{"type": "remove_prospect", "match_names": ["Nobody"]}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), [])
        assert len(cards) == 3
        assert any("Could not find" in log for log in logs)

    def test_select_by_name(self):
        actions = [{"type": "select_prospect", "match_names": ["Bob"]}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), [])
        assert "p-002" in sel

    def test_select_by_id(self):
        actions = [{"type": "select_prospect", "prospect_ids": ["p-003"]}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), [])
        assert "p-003" in sel

    def test_select_already_selected(self):
        actions = [{"type": "select_prospect", "match_names": ["Alice"]}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), ["p-001"])
        assert sel.count("p-001") == 1  # Not duplicated

    def test_deselect_by_name(self):
        actions = [{"type": "deselect_prospect", "match_names": ["Alice"]}]
        cards, sel, logs = _execute_actions(
            actions, list(SAMPLE_CARDS), ["p-001", "p-002"]
        )
        assert "p-001" not in sel
        assert "p-002" in sel

    def test_deselect_by_id(self):
        actions = [{"type": "deselect_prospect", "prospect_ids": ["p-001"]}]
        cards, sel, logs = _execute_actions(
            actions, list(SAMPLE_CARDS), ["p-001", "p-002"]
        )
        assert "p-001" not in sel

    def test_select_all(self):
        actions = [{"type": "select_all"}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), [])
        assert set(sel) == {"p-001", "p-002", "p-003"}

    def test_clear_selection(self):
        actions = [{"type": "clear_selection"}]
        cards, sel, logs = _execute_actions(
            actions, list(SAMPLE_CARDS), ["p-001", "p-002"]
        )
        assert sel == []
        assert len(cards) == 3  # Cards preserved

    def test_clear_all(self):
        actions = [{"type": "clear_all"}]
        cards, sel, logs = _execute_actions(
            actions, list(SAMPLE_CARDS), ["p-001"]
        )
        assert cards == []
        assert sel == []

    def test_compound_clear_then_select(self):
        """'send only to Bob' → clear_selection + select_prospect."""
        actions = [
            {"type": "clear_selection"},
            {"type": "select_prospect", "match_names": ["Bob"]},
        ]
        cards, sel, logs = _execute_actions(
            actions, list(SAMPLE_CARDS), ["p-001", "p-003"]
        )
        assert sel == ["p-002"]

    def test_view_prospects_is_noop(self):
        actions = [{"type": "view_prospects"}]
        cards, sel, logs = _execute_actions(actions, list(SAMPLE_CARDS), ["p-001"])
        assert len(cards) == 3
        assert sel == ["p-001"]


# ---------------------------------------------------------------------------
# Mock command parsing
# ---------------------------------------------------------------------------


class TestParseMockCommands:
    def test_view_command(self):
        actions, msg, csv = _parse_mock_commands("show me the prospects", SAMPLE_CARDS, ["p-001"])
        assert actions[0]["type"] == "view_prospects"
        assert "3" in msg

    def test_csv_upload(self):
        actions, msg, csv = _parse_mock_commands("upload a CSV", SAMPLE_CARDS, [])
        assert actions[0]["type"] == "upload_csv"
        assert csv is True

    def test_clear_all(self):
        actions, msg, csv = _parse_mock_commands("clear all prospects", SAMPLE_CARDS, [])
        assert actions[0]["type"] == "clear_all"

    def test_clear_selection(self):
        actions, msg, csv = _parse_mock_commands("clear selection", SAMPLE_CARDS, ["p-001"])
        assert actions[0]["type"] == "clear_selection"

    def test_select_all(self):
        actions, msg, csv = _parse_mock_commands("select all", SAMPLE_CARDS, [])
        assert actions[0]["type"] == "select_all"

    def test_add_prospect(self):
        actions, msg, csv = _parse_mock_commands("add John Doe", SAMPLE_CARDS, [])
        assert actions[0]["type"] == "add_prospect"
        assert actions[0]["prospects"][0]["name"] == "John Doe"

    def test_add_with_email(self):
        actions, msg, csv = _parse_mock_commands(
            "add Jane at jane@test.com", SAMPLE_CARDS, []
        )
        assert actions[0]["type"] == "add_prospect"
        assert actions[0]["prospects"][0]["email"] == "jane@test.com"

    def test_remove_prospect(self):
        actions, msg, csv = _parse_mock_commands("remove Alice", SAMPLE_CARDS, [])
        assert actions[0]["type"] == "remove_prospect"
        assert "alice" in actions[0]["match_names"][0].lower()

    def test_send_only_to(self):
        actions, msg, csv = _parse_mock_commands("send only to Bob", SAMPLE_CARDS, ["p-001"])
        assert actions[0]["type"] == "clear_selection"
        assert actions[1]["type"] == "select_prospect"
        assert "bob" in actions[1]["match_names"][0]

    def test_default_is_view(self):
        actions, msg, csv = _parse_mock_commands("what about prospects?", SAMPLE_CARDS, [])
        assert actions[0]["type"] == "view_prospects"


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_plain_json(self):
        result = _parse_json_response('{"actions": [], "message": "OK"}')
        assert result["message"] == "OK"

    def test_markdown_fenced(self):
        result = _parse_json_response('```json\n{"actions": [], "message": "OK"}\n```')
        assert result["message"] == "OK"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_json_response("not json")


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


class TestBuildFrames:
    def test_prospect_manager_frame(self):
        frame = build_prospect_manager_frame(
            cards=SAMPLE_CARDS,
            selected_ids=["p-001"],
            message="Ready",
            show_csv_upload=True,
            instance_id="test-123",
        )
        assert frame["component"] == "ProspectManager"
        assert frame["instance_id"] == "test-123"
        assert frame["props"]["total_count"] == 3
        assert frame["props"]["selected_count"] == 1
        assert frame["props"]["show_csv_upload"] is True
        assert len(frame["actions"]) == 6  # All management actions

    def test_prospect_list_frame(self):
        frame = build_prospect_list_frame(
            cards=SAMPLE_CARDS,
            selected_ids=["p-001", "p-002"],
            message="Showing list",
            instance_id="test-456",
        )
        assert frame["component"] == "ProspectManager"
        assert frame["props"]["show_csv_upload"] is False
        assert len(frame["actions"]) == 1  # Just confirm

    def test_frame_prospects_are_cards(self):
        frame = build_prospect_manager_frame(
            cards=SAMPLE_CARDS,
            selected_ids=[],
            message="",
            show_csv_upload=False,
            instance_id="test-789",
        )
        p = frame["props"]["prospects"][0]
        assert "id" in p
        assert "name" in p
        assert "fit_score" in p
        assert "source" in p


# ---------------------------------------------------------------------------
# Format prospect list for LLM prompt
# ---------------------------------------------------------------------------


class TestFormatProspectList:
    def test_empty(self):
        result = _format_prospect_list([])
        assert "no prospects" in result.lower()

    def test_formats_cards(self):
        result = _format_prospect_list(SAMPLE_CARDS)
        assert "Alice Johnson" in result
        assert "alice@acme.com" in result
        assert "p-001" in result


# ---------------------------------------------------------------------------
# Graph routing includes prospect_manage
# ---------------------------------------------------------------------------


def test_route_includes_prospect_manage():
    from app.agents.graph import route_from_orchestrator

    state = {
        "next_node": "prospect_manage",
        "session_complete": False,
    }
    assert route_from_orchestrator(state) == "prospect_manage"


def test_valid_intents_includes_prospect_manage():
    from app.agents.orchestrator import VALID_INTENTS

    assert "prospect_manage" in VALID_INTENTS
