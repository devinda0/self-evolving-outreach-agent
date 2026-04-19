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
from app.db.crud import (
    get_latest_variants_for_session,
    list_campaigns,
    load_campaign_state,
    save_campaign_state,
)

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


async def _load_active_campaign_state(session_id: str) -> dict[str, Any] | None:
    """Load the most complete campaign snapshot available for a session."""
    base_state = await load_campaign_state(session_id)
    merged_state: dict[str, Any] | None = dict(base_state) if base_state else None

    try:
        graph = _get_or_init_graph()
        config: RunnableConfig = {"configurable": {"thread_id": session_id}}
        state_snap = await graph.aget_state(config)  # type: ignore[arg-type]
        if state_snap and state_snap.values:
            merged_state = {**(merged_state or {}), **state_snap.values}
    except Exception:
        logger.warning(
            "Could not load graph checkpoint state | session=%s",
            session_id,
            exc_info=True,
        )

    if merged_state is None:
        return None

    if not merged_state.get("content_variants"):
        try:
            merged_state["content_variants"] = await get_latest_variants_for_session(session_id)
        except Exception:
            logger.warning(
                "Could not hydrate content variants from DB | session=%s",
                session_id,
                exc_info=True,
            )

    return merged_state


# Cached compiled graph — initialized lazily after the DB connects at startup.
_graph: CompiledStateGraph | None = None

# Progress-emitting node names (used to filter astream_events)
_PROGRESS_NODES = frozenset(
    {
        "orchestrator",
        "research_dispatcher",
        "research_thread",
        "research_synthesizer",
        "segment_agent",
        "prospect_manage",
        "content_agent",
        "content_refine",
        "deployment_agent",
        "feedback_agent",
        "clarify",
        "answer",
        "update_context",
        "mcp_configure",
        "lookup",
    }
)


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
        # Content agent sub-phases
        "content_phase": None,
        "content_clarifications": [],
        "content_pending_questions": [],
        "content_generation_context": None,
        "content_refinement_history": [],
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
    """Normalize action IDs: handle dynamic prefixes and convert hyphens to
    underscores so frontend IDs (``confirm-prospects``) match backend keys
    (``confirm_prospects``).

    Specific prefix rules (evaluated in order):
    - ``select-var-`` → ``select_variant``   (VariantGrid selection)
    - ``select-seg-`` → ``select_segment``   (SegmentSelector)
    - ``select-``     → ``select_segment``   (other legacy segment buttons)
    - anything else   → replace ``-`` with ``_``
    """
    if action_id.startswith("select-var-"):
        return "select_variant"
    if action_id.startswith("select-seg-") or (
        action_id.startswith("select-") and action_id != "select-all"
    ):
        return "select_segment"
    return action_id.replace("-", "_")


def _state_delta_for_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Map a UI action_id to a CampaignState partial update."""
    if action_id == "select_segment":
        return {"selected_segment_id": payload.get("segment_id")}
    if action_id == "confirm_prospects":
        selected = payload.get("selected_ids")
        if selected is not None:
            return {"selected_prospect_ids": selected}
        return {}
    if action_id == "navigate":
        return {"next_node": payload.get("target_intent")}
    return {}


# Actions that should update state and then re-run the graph so the
# orchestrator routes to the appropriate specialist agent.
_NAVIGATE_INTENT_MAP: dict[str, str] = {
    "goto_segment": "segment",
    "goto_generate": "generate",
    "drill_deeper": "research",
    "goto_prospect_manage": "prospect_manage",
}


def _parse_clarification_response(response_text: str) -> list[dict[str, str]]:
    """Parse combined Q&A text into structured clarification pairs.

    Handles formats like:
      "Question text: Answer text\\nAnother question: Another answer"
      "Question text?: Answer text"
    """
    pairs: list[dict[str, str]] = []
    for line in response_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split on first colon that is followed by a space (avoid splitting URLs)
        if ": " in line:
            question, _, answer = line.partition(": ")
            # Handle "Question?:" edge case
            question = question.rstrip("?").rstrip(":").strip()
            answer = answer.strip()
            if question and answer:
                pairs.append({"question": question, "answer": answer})
            elif answer:
                pairs.append({"question": "(context)", "answer": answer})
        else:
            pairs.append({"question": "(context)", "answer": line})
    return pairs


def _graph_rerun_intent(action_id: str, payload: dict[str, Any]) -> str | None:
    """Return a synthetic user message if this action should trigger a graph re-run."""
    # BriefingCard navigation buttons
    intent = _NAVIGATE_INTENT_MAP.get(action_id)
    if intent:
        return _INTENT_TO_USER_MESSAGE.get(intent, intent)

    # Content clarification: user answered individual question — re-enter as generation
    if action_id == "content_clarify_answer":
        return "Generate outreach content using my clarification answers"

    # Content clarification: user skipped — generate with current context
    if action_id == "content_skip_clarification":
        return "Generate outreach content with the current context"

    # Content refinement: re-enter graph for refinement
    if action_id == "content_refine":
        return "Refine the existing content variants"

    # VariantGrid confirm → deploy
    if action_id in ("deploy_selected", "confirm_selected", "confirm_variants"):
        return "Deploy the selected variants"

    # DeploymentConfirm approve / cancel
    if action_id in ("confirm_deploy", "confirm_deployment"):
        return "Confirm and send the deployment"
    if action_id in ("cancel_deploy", "cancel_deployment"):
        return "Cancel the deployment"

    # ProspectPicker / ProspectManager confirm → generate content
    if action_id == "confirm_prospects":
        return "Generate outreach content for the selected prospects"

    # ProspectManager actions that need graph re-run
    if action_id in ("add_prospect_manual", "remove_selected", "clear_selection", "select_all_prospects"):
        return "Show me the current prospect list"

    # SegmentSelector pick → acknowledge segment selection
    if action_id == "select_segment":
        return "Use the selected segment and show prospects"

    # ChannelSelector confirm → generate content for selected channels
    if action_id == "confirm_channels":
        return "Generate outreach content for the selected channels"

    # DeliveryStatusCard post-deployment actions
    if action_id == "view_results":
        return "Show me the campaign results and engagement metrics"
    if action_id == "run_next_cycle":
        return "Process the campaign results and run the next outreach cycle"
    if action_id == "retry_failed":
        return "Retry sending to the failed recipients"

    # CycleSummary / ABResults learnings
    if action_id == "view_findings":
        return "Show me the research findings and key learnings from this cycle"

    # ProspectManager CSV upload completion
    if action_id == "csv_upload_complete":
        return "Show me the current prospect list"

    return None


def _state_delta_before_rerun(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a state patch to apply *before* re-running the graph for this action.

    Note: deployment_confirmed is intentionally excluded here. It is passed
    directly through _run_graph_for_message's input_update so it is applied
    atomically at graph invocation time and never left in a stale True state
    in the checkpoint between turns.
    """
    if action_id in ("deploy_selected", "confirm_selected", "confirm_variants"):
        return {"selected_variant_ids": payload.get("variant_ids", [])}
    if action_id == "confirm_prospects":
        # Only overwrite selected_prospect_ids if the payload explicitly includes them.
        # An empty payload {} (e.g. from lookup's ProspectManager) must NOT clear
        # the IDs that lookup_node already wrote to state.
        selected = payload.get("selected_ids")
        if selected is not None:
            return {"selected_prospect_ids": selected}
        return {}
    if action_id in ("select_all_prospects",):
        return {}  # handled by graph re-run
    if action_id in ("clear_selection",):
        return {"selected_prospect_ids": []}
    if action_id in ("remove_selected",):
        return {}  # handled by graph re-run
    if action_id == "select_segment":
        return {"selected_segment_id": payload.get("segment_id")}
    if action_id == "confirm_channels":
        return {"selected_channels": payload.get("selected_channels", [])}
    # Content clarification: individual answer → store answer and jump to generate
    if action_id == "content_clarify_answer":
        answer = payload.get("answer", "")
        question_id = payload.get("question_id", "")
        return {
            "content_phase": "generate",
            "content_clarifications": [{"question": question_id, "answer": answer}],
            "content_pending_questions": [],
        }
    # Content clarification: skip → jump to generate phase
    if action_id == "content_skip_clarification":
        return {"content_phase": "generate", "content_pending_questions": []}
    # Content refinement: set phase so content_agent routes to refine
    if action_id == "content_refine":
        return {"content_phase": "refine"}
    return {}


_INTENT_TO_USER_MESSAGE: dict[str, str] = {
    "segment": "Pick a target segment",
    "generate": "Generate content",
    "research": "Research more",
}


# ---------------------------------------------------------------------------
# UI-action helpers for feedback features
# ---------------------------------------------------------------------------


async def _handle_manual_feedback_action(websocket: WebSocket, session_id: str) -> None:
    """Emit a ManualFeedbackInput UI frame populated with the session's deployed variants."""
    from app.agents.feedback_agent import build_manual_feedback_frame

    graph = _get_or_init_graph()
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    records: list[dict] = []
    try:
        state_snap = await graph.aget_state(config)  # type: ignore[arg-type]
        if state_snap and state_snap.values:
            records = state_snap.values.get("deployment_records", [])
    except Exception:
        logger.warning("_handle_manual_feedback_action: could not load graph state", exc_info=True)

    instance_id = f"manual-feedback-{uuid.uuid4().hex[:8]}"
    frame = build_manual_feedback_frame(records, instance_id)
    await _send_json_safe(websocket, frame)
    await websocket.send_json({"type": "token_end"})


async def _handle_view_quarantine_action(websocket: WebSocket, session_id: str) -> None:
    """Fetch quarantined events and emit a QuarantineViewer UI frame."""
    from app.agents.feedback_agent import build_quarantine_viewer_frame
    from app.db.crud import get_quarantine_events_for_session

    events: list[dict] = []
    try:
        events = await get_quarantine_events_for_session(session_id)
    except Exception:
        logger.warning("_handle_view_quarantine_action: could not load quarantine", exc_info=True)

    instance_id = f"quarantine-{uuid.uuid4().hex[:8]}"
    frame = build_quarantine_viewer_frame(events, instance_id)
    await _send_json_safe(websocket, frame)
    await websocket.send_json({"type": "token_end"})


# ---------------------------------------------------------------------------
# Core graph invocation helpers
# ---------------------------------------------------------------------------


async def _run_graph_for_message(
    websocket: WebSocket,
    session_id: str,
    content: str,
    db_state: dict[str, Any],
    deployment_confirmed: bool = False,
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

    # Snapshot frame counts before this turn so we only drain *new* frames
    # after the run. pending_ui_frames uses operator.add reducer and accumulates
    # across turns — without this we'd re-send every frame from prior turns.
    prior_frame_count = 0
    prior_error_count = 0
    try:
        pre_snap = await graph.aget_state(config)  # type: ignore[arg-type]
        if pre_snap and pre_snap.values:
            prior_frame_count = len(pre_snap.values.get("pending_ui_frames", []))
            prior_error_count = len(pre_snap.values.get("error_messages", []))
    except Exception:
        pass  # first turn — no checkpoint exists yet

    # Every new turn: inject product context + new user message, reset
    # session_complete so the graph doesn't exit immediately.
    # Always reset deployment_confirmed unless this turn is explicitly a
    # deployment confirmation — prevents stale True flag from sending emails
    # automatically if a prior confirmation run was interrupted.
    input_update: dict[str, Any] = {
        "session_id": session_id,
        "product_name": db_state.get("product_name", ""),
        "product_description": db_state.get("product_description", ""),
        "target_market": db_state.get("target_market", ""),
        "messages": [HumanMessage(content=content)],
        "session_complete": False,
        "deployment_confirmed": deployment_confirmed,
    }

    try:
        async for event in graph.astream_events(input_update, config, version="v2"):
            event_type = event.get("event", "")

            # Emit a progress frame whenever a key node starts
            if event_type == "on_chain_start":
                node_name = event.get("name", "")
                if node_name in _PROGRESS_NODES:
                    await websocket.send_json(
                        {
                            "type": "progress",
                            "stage": node_name,
                            "message": f"Running {node_name}…",
                        }
                    )

            # Forward streaming LLM tokens — skip internal nodes (orchestrator, clarify)
            elif event_type == "on_chat_model_stream":
                meta = event.get("metadata", {})
                node = (
                    meta.get("langgraph_node", "") or event.get("tags", [""])[0]
                    if event.get("tags")
                    else ""
                )
                # Skip nodes that produce structured JSON, not user-facing prose
                if node in ("orchestrator", "clarify", "content_agent", "content_refine", "deployment_agent", "answer", "update_context", "prospect_manage", "mcp_configure", "lookup"):
                    continue
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    await websocket.send_json({"type": "token", "content": chunk.content})

    except GraphRecursionError:
        logger.error("Graph recursion limit reached | session=%s", session_id)
        await websocket.send_json(
            {
                "type": "error",
                "message": "Processing limit reached — try a more specific request.",
            }
        )
        return
    except Exception:
        logger.exception("Graph execution error | session=%s", session_id)
        await websocket.send_json({"type": "error", "message": "Agent error — please try again."})
        return

    # Drain only the UI frames added during *this* turn
    try:
        state_snap = await graph.aget_state(config)  # type: ignore[arg-type]
        if state_snap and state_snap.values:
            all_frames = state_snap.values.get("pending_ui_frames", [])
            for frame in all_frames[prior_frame_count:]:
                await _send_json_safe(websocket, frame)
            # Surface only new error messages from this turn
            all_errors = state_snap.values.get("error_messages", [])
            for err in all_errors[prior_error_count:]:
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

    return [
        {
            "type": "progress",
            "stage": "ui_action",
            "message": f"Action applied: {action_id}",
        }
    ]


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


@router.get("/campaign/list")
async def list_campaign_sessions() -> list[dict[str, Any]]:
    """Return recent campaigns for the history sidebar."""
    return await list_campaigns(limit=50)


@router.get("/campaign/{session_id}/state")
async def get_campaign_state(session_id: str) -> dict[str, Any]:
    """Return the current CampaignState for debugging / reconnection."""
    state = await _load_active_campaign_state(session_id)
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

    frames = await _apply_ui_action(
        session_id, _normalize_action_id(action.action_id), action.payload
    )
    return {"frames": frames}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/campaign/{session_id}")
async def websocket_campaign(websocket: WebSocket, session_id: str) -> None:
    """Main WebSocket endpoint for real-time campaign communication."""
    await websocket.accept()

    # Load campaign session (product context) — create a bare record if missing.
    db_state = await _load_active_campaign_state(session_id)
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

                # If there are pending content clarification questions, treat this
                # message as the user's answers — parse and inject them, then run
                # generation directly rather than relying on the orchestrator to
                # correctly classify what can look like product-context prose.
                _pending_qs: list = []
                try:
                    _g = _get_or_init_graph()
                    _cfg_snap: RunnableConfig = {"configurable": {"thread_id": session_id}}
                    _snap = await _g.aget_state(_cfg_snap)  # type: ignore[arg-type]
                    if _snap and _snap.values:
                        _pending_qs = _snap.values.get("content_pending_questions", []) or []
                except Exception:
                    pass

                if _pending_qs:
                    logger.info(
                        "ws: intercepting free-text clarification answer | session=%s pending_qs=%d",
                        session_id, len(_pending_qs),
                    )
                    clarifications = _parse_clarification_response(content)
                    if not clarifications:
                        # Whole message is one context blob
                        clarifications = [{"question": "(user context)", "answer": content}]
                    try:
                        _g = _get_or_init_graph()
                        _cfg_patch: RunnableConfig = {"configurable": {"thread_id": session_id}}
                        await _g.aupdate_state(_cfg_patch, {  # type: ignore[arg-type]
                            "content_phase": "generate",
                            "content_clarifications": clarifications,
                            "content_pending_questions": [],
                        })
                    except Exception:
                        logger.warning(
                            "ws: could not patch state for free-text clarification",
                            exc_info=True,
                        )
                    await _run_graph_for_message(
                        websocket, session_id,
                        "Generate outreach content using my clarification answers",
                        db_state, deployment_confirmed=False,
                    )
                    continue

                # Normal user message path — let the orchestrator classify intent.
                await _run_graph_for_message(
                    websocket, session_id, content, db_state, deployment_confirmed=False
                )

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

                # Content clarification submission — parse answers and patch state
                # before re-running graph. Must come before generic response handler.
                if action_id == "content_clarify_submit":
                    response_text = str(payload.get("response", ""))
                    if response_text:
                        clarifications = _parse_clarification_response(response_text)
                        graph = _get_or_init_graph()
                        clarify_cfg: RunnableConfig = {"configurable": {"thread_id": session_id}}
                        try:
                            await graph.aupdate_state(clarify_cfg, {
                                "content_phase": "generate",
                                "content_clarifications": clarifications,
                                "content_pending_questions": [],
                            })
                        except Exception:
                            logger.warning(
                                "Could not patch state for content_clarify_submit",
                                exc_info=True,
                            )
                        await _run_graph_for_message(
                            websocket,
                            session_id,
                            "Generate outreach content using my clarification answers",
                            db_state,
                            deployment_confirmed=False,
                        )
                    continue

                # Generic clarification responses should re-enter the graph as a user message
                if payload.get("response"):
                    content = str(payload["response"])
                    await _run_graph_for_message(
                        websocket, session_id, content, db_state, deployment_confirmed=False
                    )
                    continue

                # Manual feedback input — build and emit ManualFeedbackInput frame
                if action_id == "manual_feedback":
                    await _handle_manual_feedback_action(websocket, session_id)
                    continue

                # View quarantine — fetch events and emit QuarantineViewer frame
                if action_id == "view_quarantine":
                    await _handle_view_quarantine_action(websocket, session_id)
                    continue

                # Variant selection toggle — read current state, append/remove, write back
                if action_id == "select_variant":
                    variant_id = payload.get("variant_id", "")
                    if variant_id:
                        _g = _get_or_init_graph()
                        _cfg_v: RunnableConfig = {"configurable": {"thread_id": session_id}}
                        try:
                            _snap_v = await _g.aget_state(_cfg_v)  # type: ignore[arg-type]
                            current_sel: list[str] = []
                            if _snap_v and _snap_v.values:
                                current_sel = list(_snap_v.values.get("selected_variant_ids", []) or [])
                            if variant_id in current_sel:
                                current_sel.remove(variant_id)
                            else:
                                current_sel.append(variant_id)
                            await _g.aupdate_state(_cfg_v, {"selected_variant_ids": current_sel})  # type: ignore[arg-type]
                            logger.info(
                                "select_variant: toggled %s → selected=%s | session=%s",
                                variant_id, current_sel, session_id,
                            )
                        except Exception:
                            logger.warning("select_variant: state update failed", exc_info=True)
                    await _send_json_safe(websocket, {"type": "token_end"})
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
                    # Patch state before re-running (e.g. selected_variant_ids).
                    # Note: deployment_confirmed is intentionally NOT included here —
                    # it is passed directly via _run_graph_for_message to avoid it
                    # persisting in the checkpoint between turns.
                    pre_delta = _state_delta_before_rerun(action_id, payload)
                    if pre_delta:
                        graph = _get_or_init_graph()
                        rerun_cfg: RunnableConfig = {"configurable": {"thread_id": session_id}}
                        try:
                            await graph.aupdate_state(rerun_cfg, pre_delta)  # type: ignore[arg-type]
                        except Exception:
                            logger.warning(
                                "Could not pre-patch state for '%s'", action_id, exc_info=True
                            )
                    # Only pass deployment_confirmed=True for explicit confirmation actions.
                    is_confirm = action_id in ("confirm_deploy", "confirm_deployment")
                    await _run_graph_for_message(
                        websocket, session_id, synthetic_msg, db_state,
                        deployment_confirmed=is_confirm,
                    )
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
                    # Always terminate the action so the frontend clears the
                    # waiting/processing indicator, even for state-only paths.
                    await _send_json_safe(websocket, {"type": "token_end"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected | session=%s", session_id)
    except Exception:
        logger.exception("WebSocket error | session=%s", session_id)
        try:
            await websocket.send_json({"type": "error", "message": "Internal server error"})
            await websocket.close()
        except Exception:
            pass
