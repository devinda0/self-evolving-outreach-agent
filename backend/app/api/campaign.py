"""Campaign API — WebSocket endpoint and REST session management."""

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.agents.graph import get_graph
from app.db.crud import load_campaign_state, save_campaign_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["campaign"])


class _DateSafeEncoder(json.JSONEncoder):
    """Encode datetime/date objects as ISO 8601 strings."""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        return super().default(o)


async def _send_json_safe(websocket: WebSocket, data: Any) -> None:
    """Send JSON via WebSocket using a datetime-safe encoder."""
    text = json.dumps(data, cls=_DateSafeEncoder, separators=(",", ":"), ensure_ascii=False)
    await websocket.send_text(text)


# Cached compiled graph — initialized lazily after the DB connects at startup.
_graph: CompiledStateGraph | None = None

# Progress-emitting node names (used to filter astream_events)
_PROGRESS_NODES = frozenset({
    "orchestrator",
    "research_dispatcher",
    "research_thread",
    "research_synthesizer",
    "segment_agent",
    "content_agent",
    "deployment_agent",
    "feedback_agent",
    "clarify",
})


def _get_or_init_graph() -> CompiledStateGraph:
    """Return the cached compiled graph, building it on first call."""
    global _graph
    if _graph is None:
        _graph = get_graph()
    return _graph


def reset_graph() -> None:
    """Discard the cached graph so the next call rebuilds it with the current DB.

    Used in tests to ensure the checkpointer uses the active Motor client after
    a DB teardown/setup cycle.
    """
    global _graph
    _graph = None


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
        "pending_ui_frames": [],
    }


def _normalize_action_id(action_id: str) -> str:
    """Normalize action IDs: strip ``select-`` prefix for dynamic segment
    selection buttons and convert remaining hyphens to underscores so
    frontend IDs (``confirm-prospects``) match backend keys
    (``confirm_prospects``)."""
    # SegmentSelector buttons arrive as "select-<segment_id>"
    if action_id.startswith("select-") and action_id != "select-all":
        return "select_segment"
    return action_id.replace("-", "_")


def _state_delta_for_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Map a UI action_id to a CampaignState partial update."""
    if action_id == "select_segment":
        return {"selected_segment_id": payload.get("segment_id")}
    if action_id == "confirm_prospects":
        return {"selected_prospect_ids": payload.get("selected_ids", [])}
    if action_id == "navigate":
        return {"next_node": payload.get("target_intent")}
    return {}


# Actions that should update state and then re-run the graph so the
# orchestrator routes to the appropriate specialist agent.
_NAVIGATE_INTENT_MAP: dict[str, str] = {
    "goto_segment": "segment",
    "goto_generate": "generate",
    "drill_deeper": "research",
}


def _graph_rerun_intent(action_id: str, payload: dict[str, Any]) -> str | None:
    """Return a synthetic user message if this action should trigger a graph re-run."""
    # BriefingCard navigation buttons
    intent = _NAVIGATE_INTENT_MAP.get(action_id)
    if intent:
        return _INTENT_TO_USER_MESSAGE.get(intent, intent)

    # VariantGrid confirm → deploy
    if action_id in ("deploy_selected", "confirm_selected", "confirm_variants"):
        return "Deploy the selected variants"

    # DeploymentConfirm approve / cancel
    if action_id in ("confirm_deploy", "confirm_deployment"):
        return "Confirm and send the deployment"
    if action_id in ("cancel_deploy", "cancel_deployment"):
        return "Cancel the deployment"

    # ProspectPicker confirm → generate content
    if action_id == "confirm_prospects":
        return "Generate outreach content for the selected prospects"

    # SegmentSelector pick → acknowledge segment selection
    if action_id == "select_segment":
        return "Use the selected segment and show prospects"

    return None


def _state_delta_before_rerun(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a state patch to apply *before* re-running the graph for this action."""
    if action_id in ("deploy_selected", "confirm_selected", "confirm_variants"):
        return {"selected_variant_ids": payload.get("variant_ids", [])}
    if action_id in ("confirm_deploy", "confirm_deployment"):
        return {"deployment_confirmed": True}
    if action_id in ("cancel_deploy", "cancel_deployment"):
        return {"deployment_confirmed": False}
    if action_id == "confirm_prospects":
        return {"selected_prospect_ids": payload.get("selected_ids", [])}
    if action_id == "select_segment":
        return {"selected_segment_id": payload.get("segment_id")}
    return {}


_INTENT_TO_USER_MESSAGE: dict[str, str] = {
    "segment": "Pick a target segment",
    "generate": "Generate content",
    "research": "Research more",
}


# ---------------------------------------------------------------------------
# Core graph invocation helpers
# ---------------------------------------------------------------------------

async def _run_graph_for_message(
    websocket: WebSocket,
    session_id: str,
    content: str,
    db_state: dict[str, Any],
) -> None:
    """Invoke the LangGraph graph for one user message turn.

    Streams progress events live, then drains pending_ui_frames from the
    final checkpoint state once the graph reaches END.
    """
    try:
        from langgraph.errors import GraphRecursionError
    except ImportError:
        GraphRecursionError = Exception  # type: ignore[misc,assignment]  # noqa: N806

    graph = _get_or_init_graph()
    config: RunnableConfig = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 25,
    }

    # Every new turn: inject product context + new user message, reset
    # session_complete so the graph doesn't exit immediately.
    input_update: dict[str, Any] = {
        "session_id": session_id,
        "product_name": db_state.get("product_name", ""),
        "product_description": db_state.get("product_description", ""),
        "target_market": db_state.get("target_market", ""),
        "messages": [HumanMessage(content=content)],
        "session_complete": False,
        "pending_ui_frames": [],
    }

    try:
        async for event in graph.astream_events(input_update, config, version="v2"):
            event_type = event.get("event", "")

            # Emit a progress frame whenever a key node starts
            if event_type == "on_chain_start":
                node_name = event.get("name", "")
                if node_name in _PROGRESS_NODES:
                    await websocket.send_json({
                        "type": "progress",
                        "stage": node_name,
                        "message": f"Running {node_name}…",
                    })

            # Forward streaming LLM tokens — skip internal nodes (orchestrator, clarify)
            elif event_type == "on_chat_model_stream":
                meta = event.get("metadata", {})
                node = (
                    meta.get("langgraph_node", "")
                    or event.get("tags", [""])[0] if event.get("tags") else ""
                )
                # Skip nodes that produce structured JSON, not user-facing prose
                if node in ("orchestrator", "clarify", "content_agent", "deployment_agent"):
                    continue
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    await websocket.send_json({"type": "token", "content": chunk.content})

    except GraphRecursionError:
        logger.error("Graph recursion limit reached | session=%s", session_id)
        await websocket.send_json({
            "type": "error",
            "message": "Processing limit reached — try a more specific request.",
        })
        return
    except Exception:
        logger.exception("Graph execution error | session=%s", session_id)
        await websocket.send_json({"type": "error", "message": "Agent error — please try again."})
        return

    # Drain UI frames queued by specialist nodes (BriefingCard, SegmentSelector, etc.)
    try:
        state_snap = await graph.aget_state(config)  # type: ignore[arg-type]
        if state_snap and state_snap.values:
            for frame in state_snap.values.get("pending_ui_frames", []):
                await _send_json_safe(websocket, frame)
            # Surface any error messages accumulated by agents
            for err in state_snap.values.get("error_messages", []):
                await websocket.send_json({"type": "error", "message": str(err)})
    except Exception:
        logger.exception("Failed to retrieve pending UI frames | session=%s", session_id)

    await websocket.send_json({"type": "token_end"})


async def _apply_ui_action(
    session_id: str,
    action_id: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply a UI action to the graph state. Returns response frames."""
    delta = _state_delta_for_action(action_id, payload)
    if delta:
        graph = _get_or_init_graph()
        config: RunnableConfig = {"configurable": {"thread_id": session_id}}
        try:
            await graph.aupdate_state(config, delta)  # type: ignore[arg-type]
            logger.info("Applied UI action '%s' to graph state | session=%s", action_id, session_id)
        except Exception:
            logger.warning("Could not update graph state for action '%s'", action_id, exc_info=True)

    return [{
        "type": "progress",
        "stage": "ui_action",
        "message": f"Action applied: {action_id}",
    }]


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

    frames = await _apply_ui_action(session_id, _normalize_action_id(action.action_id), action.payload)
    return {"frames": frames}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/campaign/{session_id}")
async def websocket_campaign(websocket: WebSocket, session_id: str) -> None:
    """Main WebSocket endpoint for real-time campaign communication."""
    await websocket.accept()

    # Load campaign session (product context) — create a bare record if missing.
    db_state = await load_campaign_state(session_id)
    if db_state is None:
        db_state = _new_campaign_state(
            session_id,
            StartCampaignRequest(product_name="", product_description="", target_market=""),
        )
        await save_campaign_state(session_id, db_state)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "user_message")

            if msg_type == "user_message":
                content = str(data.get("content", "")).strip()
                if not content:
                    continue
                await _run_graph_for_message(websocket, session_id, content, db_state)

            elif msg_type == "ui_action":
                raw_action_id = str(data.get("action_id", ""))
                action_id = _normalize_action_id(raw_action_id)
                payload = data.get("payload", {})
                logger.info(
                    "ui_action received | session=%s raw_id=%s normalized_id=%s payload_keys=%s",
                    session_id,
                    raw_action_id,
                    action_id,
                    list(payload.keys()),
                )

                # Clarification responses should re-enter the graph as a user message
                if payload.get("response"):
                    content = str(payload["response"])
                    await _run_graph_for_message(websocket, session_id, content, db_state)
                    continue

                # Actions that require a graph re-run (navigation, deploy, confirm)
                synthetic_msg = _graph_rerun_intent(action_id, payload)
                if synthetic_msg:
                    logger.info(
                        "ui_action path=graph_rerun | session=%s action=%s synthetic_msg=%r",
                        session_id,
                        action_id,
                        synthetic_msg,
                    )
                    # Patch state before re-running (e.g. selected_variant_ids)
                    pre_delta = _state_delta_before_rerun(action_id, payload)
                    if pre_delta:
                        graph = _get_or_init_graph()
                        cfg: RunnableConfig = {"configurable": {"thread_id": session_id}}
                        try:
                            await graph.aupdate_state(cfg, pre_delta)  # type: ignore[arg-type]
                        except Exception:
                            logger.warning("Could not pre-patch state for '%s'", action_id, exc_info=True)
                    await _run_graph_for_message(websocket, session_id, synthetic_msg, db_state)
                else:
                    # Simple state-only updates (segment select, prospect confirm)
                    logger.info(
                        "ui_action path=state_only | session=%s action=%s",
                        session_id,
                        action_id,
                    )
                    frames = await _apply_ui_action(session_id, action_id, payload)
                    for frame in frames:
                        await _send_json_safe(websocket, frame)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected | session=%s", session_id)
    except Exception:
        logger.exception("WebSocket error | session=%s", session_id)
        try:
            await websocket.send_json({"type": "error", "message": "Internal server error"})
            await websocket.close()
        except Exception:
            pass
