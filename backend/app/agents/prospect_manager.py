"""Prospect Manager Agent — intelligent prospect management via chat.

Handles all prospect operations through natural language:
- View current prospects and selections
- Add manual prospects by name/email/company
- Remove prospects from the list or selection
- Select specific prospects for outreach
- Clear all prospects or selections
- Trigger CSV upload UI
- Edit prospect details
- Bulk operations (select all, select top N, etc.)

Emits UI frames: ProspectManager (enhanced picker with management controls)
"""

import json
import logging
import re
import uuid
from typing import Any

from app.core.llm import get_llm
from app.db.crud import get_prospect_cards, save_prospect_cards
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM prompt for understanding prospect management intent
# ---------------------------------------------------------------------------

PROSPECT_MANAGE_SYSTEM_PROMPT = """You are the Prospect Manager for Signal to Action, a growth intelligence system.

Your job: interpret the user's message about prospect management and return a structured action.

## Available Actions
- view_prospects: user wants to see the current prospect list or selected prospects
- add_prospect: user wants to add one or more prospects manually (by name, email, company, title)
- remove_prospect: user wants to remove one or more prospects from the list
- select_prospect: user wants to select specific prospects for outreach (by name, email, or index)
- deselect_prospect: user wants to deselect specific prospects (keep in list but don't send to them)
- select_all: user wants to select all prospects
- clear_selection: user wants to deselect all prospects
- clear_all: user wants to remove all prospects entirely
- upload_csv: user wants to upload a CSV file with prospects
- edit_prospect: user wants to change details of an existing prospect

## Current Prospect List
{prospect_list}

## Currently Selected IDs
{selected_ids}

## Rules
- Extract names, emails, companies, and titles from the user's message
- For "add" operations, extract as much info as possible (name is required, rest optional)
- For "remove" or "select" operations, match against the current prospect list by name or email (fuzzy ok)
- For "select" with a name like "send only to John", match the best candidate
- If the user says "send to X" or "only X", treat as: clear_selection + select_prospect for X
- If adding and selecting in one message (e.g. "add john@acme.com and send to him"), return both actions
- Return a confirmation message to show the user

## Output format (strict JSON, no markdown, no prose)
{{
  "actions": [
    {{
      "type": "<action_type>",
      "prospects": [
        {{
          "name": "Full Name",
          "email": "email@example.com or null",
          "title": "Job Title or null",
          "company": "Company Name or null",
          "linkedin_url": "URL or null"
        }}
      ],
      "prospect_ids": ["id1", "id2"],
      "match_names": ["name to match against existing list"]
    }}
  ],
  "message": "Confirmation message to show the user",
  "show_prospect_list": true
}}"""


def _format_prospect_list(cards: list[dict[str, Any]]) -> str:
    """Format prospect cards for the LLM prompt."""
    if not cards:
        return "(no prospects in the list)"
    lines = []
    for i, p in enumerate(cards, 1):
        email = p.get("email") or "no email"
        lines.append(
            f"  {i}. [{p.get('id', '')}] {p.get('name', 'Unknown')} — "
            f"{p.get('title', '')} at {p.get('company', '')} ({email})"
        )
    return "\n".join(lines)


def _match_prospect_by_name(
    name: str, prospects: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find a prospect by fuzzy name match."""
    name_lower = name.lower().strip()
    name_parts = set(name_lower.split())

    # Exact match first
    for p in prospects:
        if p.get("name", "").lower().strip() == name_lower:
            return p

    # Partial match (first name or last name)
    for p in prospects:
        p_parts = set(p.get("name", "").lower().split())
        if name_parts & p_parts and len(name_parts & p_parts) >= 1:
            return p

    # Substring match
    for p in prospects:
        if name_lower in p.get("name", "").lower():
            return p

    return None


def _match_prospect_by_email(
    email: str, prospects: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find a prospect by email match."""
    email_lower = email.lower().strip()
    if not email_lower:
        return None
    for p in prospects:
        if (p.get("email") or "").lower().strip() == email_lower:
            return p
    return None


def _create_manual_prospect(data: dict[str, Any]) -> dict[str, Any]:
    """Create a scored prospect dict from manual input."""
    prospect_id = f"prospect-{uuid.uuid4().hex[:8]}"
    return {
        "id": prospect_id,
        "name": (data.get("name") or "").strip(),
        "email": (data.get("email") or "").strip() or None,
        "linkedin_url": (data.get("linkedin_url") or "").strip() or None,
        "title": (data.get("title") or "").strip(),
        "company": (data.get("company") or "").strip(),
        "fit_score": 0.75,  # Manual additions get a decent default score
        "urgency_score": 0.60,
        "angle_recommendation": "value-proposition",
        "channel_recommendation": "email" if data.get("email") else "linkedin",
        "personalization_fields": {},
        "source": "manual",
        "discovery_query": None,
        "role_seniority": None,
        "company_fit": None,
        "signal_recency": None,
    }


def _build_prospect_card(prospect: dict[str, Any]) -> dict[str, Any]:
    """Build a compact prospect card for UI display."""
    return {
        "id": prospect["id"],
        "name": prospect["name"],
        "email": prospect.get("email"),
        "title": prospect.get("title", ""),
        "company": prospect.get("company", ""),
        "fit_score": prospect.get("fit_score", 0.5),
        "urgency_score": prospect.get("urgency_score", 0.5),
        "angle_recommendation": prospect.get("angle_recommendation", "value-proposition"),
        "channel_recommendation": prospect.get("channel_recommendation", "email"),
        "source": prospect.get("source", "manual"),
    }


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


def _execute_actions(
    actions: list[dict[str, Any]],
    current_cards: list[dict[str, Any]],
    selected_ids: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Execute parsed prospect management actions.

    Returns (updated_cards, updated_selected_ids, log_messages).
    """
    cards = list(current_cards)
    sel_ids = list(selected_ids)
    logs: list[str] = []

    for action in actions:
        action_type = action.get("type", "")

        if action_type == "add_prospect":
            for p_data in action.get("prospects", []):
                if not p_data.get("name"):
                    continue
                new_prospect = _create_manual_prospect(p_data)
                cards.append(new_prospect)
                sel_ids.append(new_prospect["id"])
                logs.append(f"Added {new_prospect['name']}")

        elif action_type == "remove_prospect":
            for name in action.get("match_names", []):
                match = _match_prospect_by_name(name, cards)
                if match:
                    cards = [c for c in cards if c["id"] != match["id"]]
                    sel_ids = [s for s in sel_ids if s != match["id"]]
                    logs.append(f"Removed {match['name']}")
                else:
                    logs.append(f"Could not find '{name}' in the prospect list")
            for pid in action.get("prospect_ids", []):
                removed = [c for c in cards if c["id"] == pid]
                if removed:
                    cards = [c for c in cards if c["id"] != pid]
                    sel_ids = [s for s in sel_ids if s != pid]
                    logs.append(f"Removed {removed[0].get('name', pid)}")

        elif action_type == "select_prospect":
            for name in action.get("match_names", []):
                match = _match_prospect_by_name(name, cards)
                if match and match["id"] not in sel_ids:
                    sel_ids.append(match["id"])
                    logs.append(f"Selected {match['name']}")
                elif not match:
                    logs.append(f"Could not find '{name}' in the prospect list")
            for pid in action.get("prospect_ids", []):
                if pid not in sel_ids and any(c["id"] == pid for c in cards):
                    sel_ids.append(pid)

        elif action_type == "deselect_prospect":
            for name in action.get("match_names", []):
                match = _match_prospect_by_name(name, cards)
                if match and match["id"] in sel_ids:
                    sel_ids.remove(match["id"])
                    logs.append(f"Deselected {match['name']}")
            for pid in action.get("prospect_ids", []):
                if pid in sel_ids:
                    sel_ids.remove(pid)

        elif action_type == "select_all":
            sel_ids = [c["id"] for c in cards]
            logs.append(f"Selected all {len(cards)} prospects")

        elif action_type == "clear_selection":
            sel_ids = []
            logs.append("Cleared selection")

        elif action_type == "clear_all":
            cards = []
            sel_ids = []
            logs.append("Cleared all prospects")

        elif action_type == "upload_csv":
            logs.append("CSV upload requested")

        elif action_type == "view_prospects":
            logs.append("Showing current prospects")

    return cards, sel_ids, logs


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_prospect_manager_frame(
    cards: list[dict[str, Any]],
    selected_ids: list[str],
    message: str,
    show_csv_upload: bool,
    instance_id: str,
) -> dict[str, Any]:
    """Build a ProspectManager UI frame with full management capabilities."""
    return UIFrame(
        type="ui_component",
        component="ProspectManager",
        instance_id=instance_id,
        props={
            "prospects": [_build_prospect_card(c) for c in cards],
            "selected_ids": selected_ids,
            "message": message,
            "show_csv_upload": show_csv_upload,
            "total_count": len(cards),
            "selected_count": len(selected_ids),
        },
        actions=[
            UIAction(
                id="confirm-prospects",
                label="Confirm selected prospects",
                action_type="confirm_prospects",
                payload={},
            ),
            UIAction(
                id="csv-upload",
                label="Upload CSV",
                action_type="csv_upload",
                payload={},
            ),
            UIAction(
                id="add-prospect-manual",
                label="Add prospect manually",
                action_type="add_prospect_manual",
                payload={},
            ),
            UIAction(
                id="select-all",
                label="Select all",
                action_type="select_all_prospects",
                payload={},
            ),
            UIAction(
                id="clear-selection",
                label="Clear selection",
                action_type="clear_selection",
                payload={},
            ),
            UIAction(
                id="remove-selected",
                label="Remove selected",
                action_type="remove_selected",
                payload={},
            ),
        ],
    ).model_dump()


def build_prospect_list_frame(
    cards: list[dict[str, Any]],
    selected_ids: list[str],
    message: str,
    instance_id: str,
) -> dict[str, Any]:
    """Build a compact prospect list view frame (for 'show me prospects' queries)."""
    return UIFrame(
        type="ui_component",
        component="ProspectManager",
        instance_id=instance_id,
        props={
            "prospects": [_build_prospect_card(c) for c in cards],
            "selected_ids": selected_ids,
            "message": message,
            "show_csv_upload": False,
            "total_count": len(cards),
            "selected_count": len(selected_ids),
        },
        actions=[
            UIAction(
                id="confirm-prospects",
                label="Confirm selected prospects",
                action_type="confirm_prospects",
                payload={},
            ),
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Main agent node — plugs into the LangGraph graph
# ---------------------------------------------------------------------------


async def prospect_manage_node(state: CampaignState) -> dict:
    """Handle prospect management operations via chat.

    This node is called when the orchestrator classifies intent as 'prospect_manage'.
    It uses the LLM to parse the user's request and execute prospect operations.
    """
    session_id = state.get("session_id", "")
    logger.info("prospect_manage_node called | session=%s", session_id)

    # Load current prospects from state
    current_cards = state.get("prospect_cards", [])
    selected_ids = state.get("selected_prospect_ids", [])

    # Also try loading from DB for most up-to-date data
    try:
        db_cards = await get_prospect_cards(session_id)
        if db_cards and len(db_cards) >= len(current_cards):
            current_cards = db_cards
    except Exception as exc:
        logger.warning("Could not load prospect cards from DB: %s", exc)

    # Build context from recent messages (future use)
    try:
        await memory_manager.build_context_bundle(state, "segment")
    except Exception:
        pass

    # Get the user's latest message
    messages = state.get("messages", [])
    latest_msg = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            latest_msg = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            latest_msg = msg.get("content", "")
            break

    llm = get_llm(temperature=0)
    show_csv_upload = False
    response_message = ""

    if llm is None:
        # Mock mode — try to parse simple commands
        actions, response_message, show_csv_upload = _parse_mock_commands(
            latest_msg, current_cards, selected_ids
        )
    else:
        prompt = PROSPECT_MANAGE_SYSTEM_PROMPT.format(
            prospect_list=_format_prospect_list(current_cards),
            selected_ids=json.dumps(selected_ids),
        )

        try:
            response = await llm.ainvoke(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": latest_msg},
                ]
            )
            result = _parse_json_response(str(response.content))
            actions = result.get("actions", [])
            response_message = result.get("message", "Done.")
            show_csv_upload = any(a.get("type") == "upload_csv" for a in actions)
        except Exception as e:
            logger.warning("Prospect management LLM error: %s", e)
            actions, response_message, show_csv_upload = _parse_mock_commands(
                latest_msg, current_cards, selected_ids
            )

    # Execute the actions
    updated_cards, updated_selected, logs = _execute_actions(
        actions, current_cards, selected_ids
    )

    # Persist updated prospects
    if updated_cards != current_cards:
        try:
            await save_prospect_cards(session_id, updated_cards)
        except Exception as exc:
            logger.warning("Could not persist prospect cards: %s", exc)

    # Build the UI frame
    instance_id = f"prospect-mgr-{session_id[:8]}-{uuid.uuid4().hex[:4]}"

    if not response_message and logs:
        response_message = " | ".join(logs)
    elif not response_message:
        response_message = "Here are your current prospects."

    # Build appropriate frame based on operation
    show_list = bool(updated_cards) or any(
        a.get("type") == "view_prospects" for a in actions
    )

    if show_list:
        ui_frame = build_prospect_manager_frame(
            cards=updated_cards,
            selected_ids=updated_selected,
            message=response_message,
            show_csv_upload=show_csv_upload,
            instance_id=instance_id,
        )
    else:
        # Text-only response when no prospects to show
        ui_frame = UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=instance_id,
            props={
                "content": response_message,
                "role": "assistant",
            },
            actions=[],
        ).model_dump()

    logger.info(
        "prospect_manage_node completed | session=%s cards=%d selected=%d actions=%s",
        session_id,
        len(updated_cards),
        len(updated_selected),
        [a.get("type") for a in actions],
    )

    return {
        "prospect_cards": [_build_prospect_card(c) for c in updated_cards],
        "selected_prospect_ids": updated_selected,
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": [ui_frame],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response, stripping markdown fences."""
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def _parse_mock_commands(
    message: str,
    current_cards: list[dict[str, Any]],
    selected_ids: list[str],
) -> tuple[list[dict[str, Any]], str, bool]:
    """Parse simple prospect commands in mock mode (no LLM)."""
    msg_lower = message.lower().strip()
    actions: list[dict[str, Any]] = []
    show_csv = False

    if any(kw in msg_lower for kw in ("show", "view", "list", "who", "current")):
        actions.append({"type": "view_prospects"})
        return actions, f"Showing {len(current_cards)} prospects ({len(selected_ids)} selected).", show_csv

    if "upload" in msg_lower or "csv" in msg_lower:
        actions.append({"type": "upload_csv"})
        show_csv = True
        return actions, "You can upload a CSV file with prospect data.", show_csv

    if "clear all" in msg_lower or "remove all" in msg_lower:
        actions.append({"type": "clear_all"})
        return actions, "Cleared all prospects.", show_csv

    if "clear" in msg_lower or "deselect all" in msg_lower:
        actions.append({"type": "clear_selection"})
        return actions, "Cleared selection.", show_csv

    if "select all" in msg_lower:
        actions.append({"type": "select_all"})
        return actions, f"Selected all {len(current_cards)} prospects.", show_csv

    # Try to extract "add <name>" pattern
    add_match = re.search(r"add\s+(.+?)(?:\s*$|\s+to\b)", msg_lower)
    if add_match:
        name = add_match.group(1).strip()
        # Try to extract email
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
        email = email_match.group(0) if email_match else None
        actions.append({
            "type": "add_prospect",
            "prospects": [{"name": name.title(), "email": email}],
        })
        return actions, f"Added {name.title()} to the prospect list.", show_csv

    # Try "remove <name>" or "delete <name>"
    remove_match = re.search(r"(?:remove|delete)\s+(.+?)(?:\s*$)", msg_lower)
    if remove_match:
        name = remove_match.group(1).strip()
        actions.append({"type": "remove_prospect", "match_names": [name]})
        return actions, f"Removed {name} from the prospect list.", show_csv

    # "send only to <name>" or "only <name>"
    only_match = re.search(r"(?:only|send\s+(?:only\s+)?to)\s+(.+?)(?:\s*$)", msg_lower)
    if only_match:
        name = only_match.group(1).strip()
        actions.append({"type": "clear_selection"})
        actions.append({"type": "select_prospect", "match_names": [name]})
        return actions, f"Selected only {name} for outreach.", show_csv

    # Default: view
    actions.append({"type": "view_prospects"})
    return actions, f"Showing {len(current_cards)} prospects.", show_csv
