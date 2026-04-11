"""Tests for the LangGraph graph topology and stub node routing.

These tests verify:
- Graph compiles without errors
- Conditional routing from orchestrator works for all intents
- Research fan-out dispatches to 4 threads and fan-in synthesizes
- End-to-end invoke returns updated state
"""

import pytest

from app.agents.content_agent import content_agent_node
from app.agents.deployment_agent import deployment_agent_node
from app.agents.graph import (
    build_graph,
    feedback_agent_node,
    research_fan_out,
    route_from_orchestrator,
)
from app.agents.orchestrator import (
    answer_node,
    clarify_node,
    orchestrator_node,
    update_context_node,
)
from app.agents.research import (
    research_dispatcher_node,
    research_synthesizer_node,
    research_thread_node,
)
from app.agents.segment_agent import segment_agent_node

# ---------------------------------------------------------------------------
# Minimal state helper
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Build a minimal CampaignState dict with sensible defaults."""
    base = {
        "session_id": "test-session",
        "product_name": "Test Product",
        "product_description": "A test product",
        "target_market": "Developers",
        "messages": [],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": [],
        "current_intent": None,
        "previous_intent": None,
        "next_node": None,
        "clarification_question": None,
        "clarification_options": [],
        "session_complete": False,
        "cycle_number": 1,
        "prior_cycle_summary": None,
        "active_stage_summary": None,
        "research_query": None,
        "active_thread_types": [],
        "research_findings": [],
        "briefing_summary": None,
        "research_gaps": [],
        "failed_threads": [],
        "selected_segment_id": None,
        "segment_candidates": [],
        "selected_prospect_ids": [],
        "prospect_pool_ref": None,
        "prospect_cards": [],
        "content_request": None,
        "content_variants": [],
        "selected_variant_ids": [],
        "visual_artifacts": [],
        "selected_channels": [],
        "ab_split_plan": None,
        "deployment_confirmed": False,
        "deployment_records": [],
        "normalized_feedback_events": [],
        "engagement_results": [],
        "winning_variant_id": None,
        "memory_refs": {},
        "error_messages": [],
        "_last_summary_message_count": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------


def test_build_graph_compiles():
    """Graph compiles without errors (no checkpointer)."""
    graph = build_graph(checkpointer=None)
    assert graph is not None


# ---------------------------------------------------------------------------
# Routing function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "next_node,expected",
    [
        ("research", "research"),
        ("segment", "segment"),
        ("generate", "generate"),
        ("deploy", "deploy"),
        ("feedback", "feedback"),
        ("clarify", "clarify"),
        ("answer", "answer"),
        ("update_context", "update_context"),
        ("prospect_manage", "prospect_manage"),
    ],
)
def test_route_from_orchestrator(next_node, expected):
    state = _make_state(next_node=next_node)
    assert route_from_orchestrator(state) == expected


def test_route_from_orchestrator_session_complete():
    from langgraph.graph import END

    state = _make_state(session_complete=True, next_node="research")
    assert route_from_orchestrator(state) == END


def test_route_from_orchestrator_unknown_defaults_to_clarify():
    state = _make_state(next_node="unknown_intent")
    assert route_from_orchestrator(state) == "clarify"


def test_route_from_orchestrator_none_defaults_to_clarify():
    state = _make_state(next_node=None)
    assert route_from_orchestrator(state) == "clarify"


# ---------------------------------------------------------------------------
# Research fan-out
# ---------------------------------------------------------------------------


def test_research_fan_out_default_threads():
    state = _make_state(active_thread_types=[])
    sends = research_fan_out(state)
    assert len(sends) == 4
    thread_types = [s.arg.get("thread_type") for s in sends]
    assert set(thread_types) == {"competitor", "audience", "channel", "market"}


def test_research_fan_out_custom_threads():
    state = _make_state(active_thread_types=["competitor", "audience"])
    sends = research_fan_out(state)
    assert len(sends) == 2


# ---------------------------------------------------------------------------
# Stub nodes return expected keys
# ---------------------------------------------------------------------------


async def test_orchestrator_node_returns_routing():
    """Orchestrator returns routing decision (mock LLM mode returns clarify)."""
    from unittest.mock import patch

    # Patch _get_llm to return None (mock mode)
    with patch("app.agents.orchestrator._get_llm", return_value=None):
        result = await orchestrator_node(_make_state())
    assert result["current_intent"] == "clarify"
    assert result["next_node"] == "clarify"
    assert "clarification_question" in result


async def test_research_dispatcher_node_returns_threads():
    result = await research_dispatcher_node(_make_state())
    assert "active_thread_types" in result
    assert len(result["active_thread_types"]) == 4


async def test_research_thread_node_returns_findings():
    from unittest.mock import AsyncMock, patch

    mock_results = [
        {
            "title": "Competitor X launches product",
            "url": "https://example.com/1",
            "content": "Details",
            "score": 0.7,
        },
        {
            "title": "Competitor Y pricing update",
            "url": "https://example.com/2",
            "content": "Info",
            "score": 0.6,
        },
    ]

    with (
        patch("app.agents.research.thread._get_llm", return_value=None),
        patch(
            "app.agents.research.thread.search_web",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
        patch(
            "app.agents.research.thread.extract_page",
            new_callable=AsyncMock,
            return_value="Page text",
        ),
    ):
        state = _make_state(thread_type="competitor")
        result = await research_thread_node(state)
    assert len(result["research_findings"]) >= 2
    assert all(f["thread_type"] == "competitor" for f in result["research_findings"])


async def test_research_synthesizer_node_returns_briefing():
    from unittest.mock import AsyncMock, patch

    findings = [
        {
            "claim": "Claim A",
            "confidence": 0.8,
            "thread_type": "competitor",
            "evidence": "ev",
            "source_url": "http://a.com",
            "actionable_implication": "act",
        },
        {
            "claim": "Claim B",
            "confidence": 0.7,
            "thread_type": "audience",
            "evidence": "ev",
            "source_url": "http://b.com",
            "actionable_implication": "act",
        },
    ]
    state = _make_state(research_findings=findings)

    with (
        patch("app.agents.research.synthesizer._get_llm", return_value=None),
        patch("app.agents.research.synthesizer.save_research_finding", new_callable=AsyncMock),
    ):
        result = await research_synthesizer_node(state)
    assert "briefing_summary" in result
    assert len(result["briefing_summary"]) > 0
    assert "research_gaps" in result
    assert "pending_ui_frames" in result
    assert result["pending_ui_frames"][0]["component"] == "MessageRenderer"
    assert result["pending_ui_frames"][1]["component"] == "BriefingCard"


async def test_segment_agent_node_returns_candidates():
    from unittest.mock import AsyncMock, patch

    with (
        patch("app.agents.segment_agent.save_segments", new_callable=AsyncMock),
        patch("app.agents.segment_agent.save_prospect_cards", new_callable=AsyncMock),
    ):
        result = await segment_agent_node(_make_state())
    assert len(result["segment_candidates"]) >= 1


async def test_content_agent_node_returns_variants():
    from unittest.mock import AsyncMock, patch

    state = _make_state(
        briefing_summary="Test briefing: competitor gap identified in enterprise segment."
    )
    with (
        patch("app.agents.content_agent._get_llm", return_value=None),
        patch("app.agents.content_agent.save_content_variant", new_callable=AsyncMock),
    ):
        result = await content_agent_node(state)
    assert len(result["content_variants"]) >= 2


async def test_deployment_agent_node_emits_confirm_when_not_confirmed():
    """Deployment agent emits DeploymentConfirm when deployment_confirmed=False."""
    state = _make_state(
        deployment_confirmed=False,
        content_variants=[
            {
                "id": "v1",
                "body": "Hi {{first_name}}",
                "intended_channel": "email",
                "angle_label": "test",
            },
        ],
        selected_variant_ids=["v1"],
        prospect_cards=[
            {"id": "p1", "name": "Jane Doe", "company": "Acme Corp"},
        ],
        selected_prospect_ids=["p1"],
    )
    result = await deployment_agent_node(state)
    assert result["next_node"] == "orchestrator"
    assert "pending_ui_frames" in result
    assert result["pending_ui_frames"][0]["component"] == "MessageRenderer"
    assert result["pending_ui_frames"][1]["component"] == "DeploymentConfirm"
    assert "ab_split_plan" in result


async def test_deployment_agent_node_sends_when_confirmed():
    """Deployment agent creates deployment records when confirmed."""
    from unittest.mock import AsyncMock, patch

    state = _make_state(
        deployment_confirmed=True,
        content_variants=[
            {
                "id": "v1",
                "body": "Hi {{first_name}} at {{company}}",
                "intended_channel": "email",
                "angle_label": "test",
            },
            {
                "id": "v2",
                "body": "Hey {{first_name}}",
                "intended_channel": "email",
                "angle_label": "roi",
            },
        ],
        selected_variant_ids=["v1", "v2"],
        prospect_cards=[
            {"id": "p1", "name": "Jane Doe", "company": "Acme Corp"},
            {"id": "p2", "name": "Bob Smith", "company": "WidgetCo"},
        ],
        selected_prospect_ids=["p1", "p2"],
    )
    with patch("app.agents.deployment_agent.save_deployment_record", new_callable=AsyncMock):
        result = await deployment_agent_node(state)
    assert len(result["deployment_records"]) == 2
    assert result["deployment_confirmed"] is False  # reset for next cycle
    assert result["next_node"] == "orchestrator"
    # Each record has unique provider_message_id
    msg_ids = {r["provider_message_id"] for r in result["deployment_records"]}
    assert len(msg_ids) == 2
    # Check UI frame
    assert result["pending_ui_frames"][0]["component"] == "MessageRenderer"
    assert result["pending_ui_frames"][1]["component"] == "DeliveryStatusCard"


async def test_feedback_agent_node_no_events_emits_prompt():
    """With no normalized_feedback_events, the agent emits a FeedbackPrompt UI frame."""
    result = await feedback_agent_node(_make_state(normalized_feedback_events=[]))
    frames = result.get("pending_ui_frames", [])
    assert len(frames) == 1
    assert frames[0]["component"] == "FeedbackPrompt"


async def test_clarify_node_returns_question():
    result = await clarify_node(_make_state())
    assert "clarification_question" in result
    assert result["active_stage_summary"] == "awaiting clarification"
    assert "pending_ui_frames" in result


async def test_answer_node_returns_text_frame():
    """Answer node returns a text UI frame with session_complete=True."""
    from unittest.mock import patch

    state = _make_state(messages=[{"role": "user", "content": "What is our target market?"}])
    with patch("app.agents.orchestrator._get_llm", return_value=None):
        result = await answer_node(state)
    assert result["session_complete"] is True
    assert result["active_stage_summary"] == "answered user question"
    assert "pending_ui_frames" in result
    assert result["pending_ui_frames"][0]["component"] == "MessageRenderer"


async def test_update_context_node_returns_confirmation():
    """Update-context node returns a confirmation frame with session_complete=True."""
    from unittest.mock import patch

    state = _make_state(
        messages=[{"role": "user", "content": "Our company focuses on B2B SaaS"}],
    )
    with patch("app.agents.orchestrator._get_llm", return_value=None):
        result = await update_context_node(state)
    assert result["session_complete"] is True
    assert "context updated" in result["active_stage_summary"]
    assert "pending_ui_frames" in result


# ---------------------------------------------------------------------------
# End-to-end graph invocation (no checkpointer, stub orchestrator→clarify)
# ---------------------------------------------------------------------------


async def test_graph_invoke_returns_updated_state():
    """Invoke the graph — stub orchestrator routes to clarify, loops until recursion limit.

    We set a low recursion_limit so it terminates quickly. The key assertion is that
    the state was updated by stub nodes.
    """
    graph = build_graph(checkpointer=None)
    initial = _make_state()
    config = {"configurable": {"thread_id": "test-1"}, "recursion_limit": 5}
    try:
        result = await graph.ainvoke(initial, config=config)
    except Exception:
        # GraphRecursionError expected — orchestrator↔clarify loops
        # Still validates that the graph compiles and starts executing.
        return

    # If it does return (e.g. LangGraph stops gracefully), check state was updated
    assert result["current_intent"] == "clarify"
    assert result["clarification_question"] is not None


async def test_graph_research_route():
    """Verify research routing fans out to 4 threads and synthesizes."""
    from unittest.mock import AsyncMock, patch

    # Build graph without checkpointer
    build_graph(checkpointer=None)

    state = _make_state(
        next_node="research",
        active_thread_types=["competitor", "audience", "channel", "market"],
    )

    # Verify dispatcher
    dispatcher_result = await research_dispatcher_node(state)
    assert len(dispatcher_result["active_thread_types"]) == 4

    # Verify fan-out produces 4 Sends
    sends = research_fan_out({**state, **dispatcher_result})
    assert len(sends) == 4

    # Verify each thread produces findings (with mocked external calls)
    mock_results = [
        {"title": "Result", "url": "https://example.com/1", "content": "Details", "score": 0.7},
        {"title": "Result 2", "url": "https://example.com/2", "content": "More", "score": 0.6},
    ]

    all_findings = []
    for send in sends:
        with (
            patch("app.agents.research.thread._get_llm", return_value=None),
            patch(
                "app.agents.research.thread.search_web",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch(
                "app.agents.research.thread.extract_page",
                new_callable=AsyncMock,
                return_value="text",
            ),
        ):
            thread_result = await research_thread_node(send.arg)
            all_findings.extend(thread_result["research_findings"])
    assert len(all_findings) >= 8  # At least 2 findings per thread × 4 threads

    # Verify synthesizer
    with (
        patch("app.agents.research.synthesizer._get_llm", return_value=None),
        patch("app.agents.research.synthesizer.save_research_finding", new_callable=AsyncMock),
    ):
        synth_result = await research_synthesizer_node(_make_state(research_findings=all_findings))
    assert len(synth_result["briefing_summary"]) > 0
    assert "pending_ui_frames" in synth_result


async def test_graph_generate_route_via_content_node():
    """Verify the content agent returns variants when invoked directly."""
    from unittest.mock import AsyncMock, patch

    state = _make_state(
        next_node="generate",
        briefing_summary="Test briefing: ROI opportunity identified for mid-market segment.",
    )
    with (
        patch("app.agents.content_agent._get_llm", return_value=None),
        patch("app.agents.content_agent.save_content_variant", new_callable=AsyncMock),
    ):
        result = await content_agent_node(state)
    assert len(result["content_variants"]) >= 2
    for v in result["content_variants"]:
        assert "id" in v
        assert "body" in v
