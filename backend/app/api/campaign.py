"""Campaign API — WebSocket endpoint and REST session management."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.db.crud import load_campaign_state, save_campaign_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["campaign"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class StartCampaignRequest(BaseModel):
    product_name: str
    product_description: str
    target_market: str


class StartCampaignResponse(BaseModel):
    session_id: str


class UIActionRequest(BaseModel):
    instance_id: str
    action_id: str
    payload: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_campaign_state(session_id: str, req: StartCampaignRequest) -> dict[str, Any]:
    """Return a fresh CampaignState dict for a new session."""
    return {
        "session_id": session_id,
        "product_name": req.product_name,
        "product_description": req.product_description,
        "target_market": req.target_market,
        # Conversation
        "messages": [],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": [],
        # Orchestrator routing
        "current_intent": None,
        "previous_intent": None,
        "next_node": None,
        "clarification_question": None,
        "clarification_options": [],
        "session_complete": False,
        # Cycle tracking
        "cycle_number": 1,
        "prior_cycle_summary": None,
        "active_stage_summary": None,
        # Research
        "research_query": None,
        "active_thread_types": [],
        "research_findings": [],
        "briefing_summary": None,
        "research_gaps": [],
        "failed_threads": [],
        # Segment / prospect
        "selected_segment_id": None,
        "segment_candidates": [],
        "selected_prospect_ids": [],
        "prospect_pool_ref": None,
        "prospect_cards": [],
        # Content
        "content_request": None,
        "content_variants": [],
        "selected_variant_ids": [],
        "visual_artifacts": [],
        # Deployment
        "selected_channels": [],
        "ab_split_plan": None,
        "deployment_confirmed": False,
        "deployment_records": [],
        # Feedback
        "normalized_feedback_events": [],
        "engagement_results": [],
        "winning_variant_id": None,
        # Meta
        "memory_refs": {},
        "error_messages": [],
    }


async def _process_ws_message(
    session_id: str,
    state: dict[str, Any],
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Process an incoming WS message and return response frames.

    This is a stub that echoes back and returns a progress frame.
    Once LangGraph is wired (issue #27), this will invoke the graph.
    """
    msg_type = data.get("type", "user_message")
    frames: list[dict[str, Any]] = []

    if msg_type == "user_message":
        content = data.get("content", "")
        # Append to messages in state
        state.setdefault("messages", []).append(
            {
                "role": "user",
                "content": content,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        frames.append({"type": "progress", "stage": "orchestrator", "message": "Processing..."})
        # Stub echo reply — will be replaced by LangGraph astream_events
        frames.append({"type": "token", "content": f"Echo: {content}"})

    elif msg_type == "ui_action":
        frames.append({
            "type": "progress",
            "stage": "ui_action",
            "message": f"Received action: {data.get('action_id', 'unknown')}",
        })

    return frames


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.post("/campaign/start", response_model=StartCampaignResponse)
async def start_campaign(req: StartCampaignRequest) -> StartCampaignResponse:
    """Create a new campaign session and return its ID."""
    session_id = str(uuid.uuid4())
    state = _new_campaign_state(session_id, req)
    await save_campaign_state(session_id, state)
    return StartCampaignResponse(session_id=session_id)


@router.get("/campaign/{session_id}/state")
async def get_campaign_state(session_id: str) -> dict[str, Any]:
    """Return the current CampaignState for debugging / reconnection."""
    state = await load_campaign_state(session_id)
    if state is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found")
    return state


@router.post("/campaign/{session_id}/ui-action")
async def post_ui_action(session_id: str, action: UIActionRequest) -> dict[str, Any]:
    """Process a UI action via REST (fallback for clients that can't maintain WS)."""
    state = await load_campaign_state(session_id)
    if state is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found")

    data = {
        "type": "ui_action",
        "instance_id": action.instance_id,
        "action_id": action.action_id,
        "payload": action.payload,
    }
    frames = await _process_ws_message(session_id, state, data)
    await save_campaign_state(session_id, state)
    return {"frames": frames}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/campaign/{session_id}")
async def websocket_campaign(websocket: WebSocket, session_id: str) -> None:
    """Main WebSocket endpoint for real-time campaign communication."""
    await websocket.accept()

    # Load or create session state
    state = await load_campaign_state(session_id)
    if state is None:
        state = _new_campaign_state(
            session_id,
            StartCampaignRequest(
                product_name="",
                product_description="",
                target_market="",
            ),
        )
        await save_campaign_state(session_id, state)

    try:
        while True:
            data = await websocket.receive_json()
            frames = await _process_ws_message(session_id, state, data)

            # Persist updated state
            await save_campaign_state(session_id, state)

            # Stream frames back to client
            for frame in frames:
                await websocket.send_json(frame)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception:
        logger.exception("WebSocket error for session %s", session_id)
        try:
            await websocket.send_json({"type": "error", "message": "Internal server error"})
            await websocket.close()
        except Exception:
            pass
