"""Integration tests for the Orchestrator agent with real Gemini API calls.

These tests verify that the orchestrator correctly classifies intent using
the actual Gemini 2.5 Pro model. Run with: pytest -m integration

Requires GEMINI_API_KEY to be set in environment or .env file.
"""

import pytest

from app.agents.orchestrator import orchestrator_node
from app.core.config import settings

# Skip all tests in this module if GEMINI_API_KEY is not set
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.GEMINI_API_KEY,
        reason="GEMINI_API_KEY not set in environment",
    ),
]


# ---------------------------------------------------------------------------
# Minimal state helper
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Build a minimal CampaignState dict with sensible defaults."""
    base = {
        "session_id": "integration-test-session",
        "product_name": "Acme CRM",
        "product_description": "AI-powered CRM for small businesses",
        "target_market": "SMB founders and sales teams",
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
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Integration tests with real Gemini API
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_research_intent_real_gemini():
    """Gemini correctly classifies 'research my competitors' as research intent."""
    state = _make_state(
        messages=[
            {"role": "user", "content": "research my competitors in the CRM space"},
        ]
    )

    result = await orchestrator_node(state)

    assert result["current_intent"] == "research"
    assert result["next_node"] == "research"
    assert "research" in result["intent_history"]


@pytest.mark.integration
async def test_generate_intent_real_gemini():
    """Gemini correctly classifies content generation request."""
    state = _make_state(
        previous_intent="research",
        active_stage_summary="research complete - briefing ready",
        messages=[
            {"role": "user", "content": "research competitors"},
            {"role": "assistant", "content": "Research complete. Here's the briefing..."},
            {"role": "user", "content": "write me 3 cold email variants targeting SMB founders"},
        ]
    )

    result = await orchestrator_node(state)

    assert result["current_intent"] == "generate"
    assert result["next_node"] == "generate"


@pytest.mark.integration
async def test_segment_intent_real_gemini():
    """Gemini correctly classifies prospect/segment selection request."""
    state = _make_state(
        messages=[
            {"role": "user", "content": "I want to select prospects from the Series A SaaS segment"},
        ]
    )

    result = await orchestrator_node(state)

    assert result["current_intent"] == "segment"
    assert result["next_node"] == "segment"


@pytest.mark.integration
async def test_deploy_intent_real_gemini():
    """Gemini correctly classifies deployment request."""
    state = _make_state(
        previous_intent="generate",
        active_stage_summary="content variants ready",
        messages=[
            {"role": "user", "content": "generate email variants"},
            {"role": "assistant", "content": "Here are 3 variants: A, B, C..."},
            {"role": "user", "content": "send variant A to all selected prospects via email"},
        ]
    )

    result = await orchestrator_node(state)

    assert result["current_intent"] == "deploy"
    assert result["next_node"] == "deploy"


@pytest.mark.integration
async def test_feedback_intent_real_gemini():
    """Gemini correctly classifies engagement feedback."""
    state = _make_state(
        previous_intent="deploy",
        active_stage_summary="campaign deployed",
        messages=[
            {"role": "user", "content": "deploy campaign"},
            {"role": "assistant", "content": "Campaign sent to 50 prospects..."},
            {"role": "user", "content": "variant A got 45% open rate and 8 replies, variant B got 30% open rate and 2 replies"},
        ]
    )

    result = await orchestrator_node(state)

    assert result["current_intent"] == "feedback"
    assert result["next_node"] == "feedback"


@pytest.mark.integration
async def test_ambiguous_input_clarify_real_gemini():
    """Gemini classifies ambiguous input as clarify with a question."""
    state = _make_state(
        messages=[
            {"role": "user", "content": "go"},
        ]
    )

    result = await orchestrator_node(state)

    assert result["current_intent"] == "clarify"
    assert result["next_node"] == "clarify"
    assert result["clarification_question"] is not None
    assert len(result["clarification_question"]) > 0


@pytest.mark.integration
async def test_context_aware_classification():
    """Gemini uses conversation context for classification."""
    # "Now write some content" after research should be "generate"
    state = _make_state(
        previous_intent="research",
        active_stage_summary="research briefing ready",
        messages=[
            {"role": "user", "content": "research my competitors"},
            {"role": "assistant", "content": "I found 5 key insights about your competitors..."},
            {"role": "user", "content": "now write some content"},
        ]
    )

    result = await orchestrator_node(state)

    # Should understand "write some content" in context means generate
    assert result["current_intent"] == "generate"


@pytest.mark.integration
async def test_intent_override():
    """User can override current mode explicitly."""
    state = _make_state(
        previous_intent="generate",
        current_intent="generate",
        active_stage_summary="generating content",
        messages=[
            {"role": "user", "content": "write email variants"},
            {"role": "assistant", "content": "Generating variants..."},
            {"role": "user", "content": "actually, go back to research mode - I want more competitor data"},
        ]
    )

    result = await orchestrator_node(state)

    # Should override to research
    assert result["current_intent"] == "research"
    assert result["next_node"] == "research"


@pytest.mark.integration
async def test_refined_cycle_intent():
    """Gemini correctly classifies new cycle request."""
    state = _make_state(
        cycle_number=1,
        previous_intent="feedback",
        active_stage_summary="cycle 1 complete",
        messages=[
            {"role": "user", "content": "let's start a new cycle and apply what we learned"},
        ]
    )

    result = await orchestrator_node(state)

    # Should recognize this as starting a new cycle
    assert result["current_intent"] == "refined_cycle"


@pytest.mark.integration
async def test_multiple_intents_batch():
    """Test multiple intent classifications in sequence."""
    test_cases = [
        {
            "messages": [{"role": "user", "content": "analyze my competitors"}],
            "expected_intent": "research",
        },
        {
            "messages": [{"role": "user", "content": "create 3 LinkedIn posts"}],
            "expected_intent": "generate",
        },
        {
            "messages": [{"role": "user", "content": "send the campaign to all prospects"}],
            "expected_intent": "deploy",
        },
        {
            "messages": [{"role": "user", "content": "email A had 50% opens, email B had 20% opens"}],
            "expected_intent": "feedback",
        },
        {
            "messages": [{"role": "user", "content": "pick the top 10 prospects"}],
            "expected_intent": "segment",
        },
    ]

    for case in test_cases:
        state = _make_state(messages=case["messages"])
        result = await orchestrator_node(state)
        assert result["current_intent"] == case["expected_intent"], (
            f"Expected {case['expected_intent']} for message: {case['messages'][0]['content']}"
        )


@pytest.mark.integration
async def test_json_output_format():
    """Gemini returns properly structured output."""
    state = _make_state(
        messages=[{"role": "user", "content": "research competitors"}]
    )

    result = await orchestrator_node(state)

    # Verify all required fields are present
    assert "current_intent" in result
    assert "previous_intent" in result
    assert "next_node" in result
    assert "intent_history" in result
    assert isinstance(result["intent_history"], list)

    # Intent should be valid
    valid_intents = {"research", "segment", "generate", "deploy", "feedback", "refined_cycle", "clarify"}
    assert result["current_intent"] in valid_intents

    # next_node should be valid
    valid_nodes = {"research", "segment", "generate", "deploy", "feedback", "clarify", "orchestrator"}
    assert result["next_node"] in valid_nodes
