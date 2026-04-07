"""Unit tests for the Orchestrator agent with mock LLM responses.

Tests cover:
- All 7 intent modes with mock LLM
- JSON parsing with markdown code blocks
- Retry logic on failures
- Error handling and fallback to clarify
- Context bundle construction
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import (
    DEFAULT_CLARIFICATION,
    DEFAULT_OPTIONS,
    VALID_INTENTS,
    _parse_llm_response,
    _validate_and_normalize_result,
    clarify_node,
    format_messages,
    orchestrator_node,
)


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
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestFormatMessages:
    """Tests for the format_messages helper."""

    def test_empty_messages(self):
        result = format_messages([])
        assert result == "(no messages yet)"

    def test_single_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = format_messages(messages)
        assert "[user]: Hello" in result

    def test_multiple_messages(self):
        messages = [
            {"role": "user", "content": "Research my competitors"},
            {"role": "assistant", "content": "I'll analyze competitors now."},
        ]
        result = format_messages(messages)
        assert "[user]: Research my competitors" in result
        assert "[assistant]: I'll analyze competitors now." in result

    def test_truncates_long_messages(self):
        long_content = "x" * 600
        messages = [{"role": "user", "content": long_content}]
        result = format_messages(messages)
        assert "..." in result
        assert len(result) < len(long_content)


class TestParseResponse:
    """Tests for JSON parsing with various formats."""

    def test_plain_json(self):
        content = '{"current_intent": "research", "reasoning": "test"}'
        result = _parse_llm_response(content)
        assert result["current_intent"] == "research"

    def test_json_with_markdown_code_block(self):
        content = '```json\n{"current_intent": "generate", "reasoning": "test"}\n```'
        result = _parse_llm_response(content)
        assert result["current_intent"] == "generate"

    def test_json_with_plain_code_block(self):
        content = '```\n{"current_intent": "deploy", "reasoning": "test"}\n```'
        result = _parse_llm_response(content)
        assert result["current_intent"] == "deploy"

    def test_json_with_whitespace(self):
        content = '  \n  {"current_intent": "feedback", "reasoning": "test"}  \n  '
        result = _parse_llm_response(content)
        assert result["current_intent"] == "feedback"

    def test_invalid_json_raises(self):
        content = "not valid json"
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_response(content)


class TestValidateAndNormalize:
    """Tests for result validation and normalization."""

    def test_valid_intent_passes_through(self):
        result = {"current_intent": "research", "next_node": "research"}
        normalized = _validate_and_normalize_result(result)
        assert normalized["current_intent"] == "research"
        assert normalized["next_node"] == "research"

    def test_invalid_intent_defaults_to_clarify(self):
        result = {"current_intent": "invalid_mode", "next_node": "invalid"}
        normalized = _validate_and_normalize_result(result)
        assert normalized["current_intent"] == "clarify"

    def test_missing_intent_defaults_to_clarify(self):
        result = {"reasoning": "test"}
        normalized = _validate_and_normalize_result(result)
        assert normalized["current_intent"] == "clarify"

    def test_clarify_gets_default_question(self):
        result = {"current_intent": "clarify"}
        normalized = _validate_and_normalize_result(result)
        assert normalized["clarification_question"] == DEFAULT_CLARIFICATION
        assert normalized["clarification_options"] == DEFAULT_OPTIONS

    def test_clarify_preserves_custom_question(self):
        result = {
            "current_intent": "clarify",
            "clarification_question": "Custom question?",
            "clarification_options": ["A", "B"],
        }
        normalized = _validate_and_normalize_result(result)
        assert normalized["clarification_question"] == "Custom question?"
        assert normalized["clarification_options"] == ["A", "B"]

    def test_all_valid_intents(self):
        for intent in VALID_INTENTS:
            result = {"current_intent": intent}
            normalized = _validate_and_normalize_result(result)
            assert normalized["current_intent"] == intent


# ---------------------------------------------------------------------------
# Orchestrator node tests with mock LLM
# ---------------------------------------------------------------------------


class TestOrchestratorNode:
    """Tests for the orchestrator_node function."""

    @pytest.fixture
    def mock_llm_response(self):
        """Create a mock LLM response."""
        def _create_response(intent: str, **kwargs):
            response_data = {
                "current_intent": intent,
                "reasoning": f"User wants to {intent}",
                "clarification_question": kwargs.get("question"),
                "clarification_options": kwargs.get("options", []),
                "next_node": kwargs.get("next_node", intent if intent != "refined_cycle" else "clarify"),
            }
            mock = MagicMock()
            mock.content = json.dumps(response_data)
            return mock
        return _create_response

    async def test_research_intent(self, mock_llm_response):
        """User message 'research my competitors' → research intent."""
        state = _make_state(
            messages=[{"role": "user", "content": "research my competitors"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("research", next_node="research")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "research"
        assert result["next_node"] == "research"
        assert "research" in result["intent_history"]

    async def test_segment_intent(self, mock_llm_response):
        """User message about prospects → segment intent."""
        state = _make_state(
            messages=[{"role": "user", "content": "let me pick some prospects to target"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("segment", next_node="segment")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "segment"
        assert result["next_node"] == "segment"

    async def test_generate_intent_after_research(self, mock_llm_response):
        """'Write me 3 email variants' after research → generate intent."""
        state = _make_state(
            previous_intent="research",
            messages=[
                {"role": "user", "content": "research competitors"},
                {"role": "assistant", "content": "Here's the research briefing..."},
                {"role": "user", "content": "write me 3 email variants"},
            ],
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("generate", next_node="generate")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "generate"
        assert result["next_node"] == "generate"
        assert result["previous_intent"] == "research"

    async def test_deploy_intent(self, mock_llm_response):
        """User wants to send content → deploy intent."""
        state = _make_state(
            messages=[{"role": "user", "content": "send variant A to all prospects via email"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("deploy", next_node="deploy")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "deploy"
        assert result["next_node"] == "deploy"

    async def test_feedback_intent(self, mock_llm_response):
        """User reporting engagement → feedback intent."""
        state = _make_state(
            messages=[{"role": "user", "content": "variant A got 40% open rate and 5 replies"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("feedback", next_node="feedback")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "feedback"
        assert result["next_node"] == "feedback"

    async def test_refined_cycle_intent(self, mock_llm_response):
        """User wants to restart with learnings → refined_cycle intent."""
        state = _make_state(
            messages=[{"role": "user", "content": "let's start a new cycle with what we learned"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("refined_cycle", next_node="clarify")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "refined_cycle"

    async def test_ambiguous_input_clarify(self, mock_llm_response):
        """Ambiguous input 'go' → clarify with question."""
        state = _make_state(
            messages=[{"role": "user", "content": "go"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response(
            "clarify",
            next_node="clarify",
            question="What would you like to do? Research, generate content, or deploy?",
            options=["Research", "Generate", "Deploy"],
        )

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["current_intent"] == "clarify"
        assert result["next_node"] == "clarify"
        assert result["clarification_question"] is not None
        assert len(result["clarification_question"]) > 0

    async def test_malformed_response_retries_and_falls_back(self):
        """Malformed Gemini response → retries once, then defaults to clarify."""
        state = _make_state(
            messages=[{"role": "user", "content": "do something"}]
        )

        mock_llm = AsyncMock()
        # Both attempts return malformed JSON
        bad_response = MagicMock()
        bad_response.content = "This is not valid JSON at all!"
        mock_llm.ainvoke.return_value = bad_response

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        # Should have retried twice
        assert mock_llm.ainvoke.call_count == 2
        # Should fall back to clarify
        assert result["current_intent"] == "clarify"
        assert result["next_node"] == "clarify"
        assert result["clarification_question"] == DEFAULT_CLARIFICATION
        # Should log error
        assert len(result.get("error_messages", [])) > 0

    async def test_api_error_retries_and_falls_back(self):
        """Gemini API error → retries once, then defaults to clarify."""
        state = _make_state(
            messages=[{"role": "user", "content": "test"}]
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API rate limit exceeded")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        # Should have retried twice
        assert mock_llm.ainvoke.call_count == 2
        # Should fall back to clarify
        assert result["current_intent"] == "clarify"
        assert result["next_node"] == "clarify"

    async def test_mock_llm_mode(self):
        """USE_MOCK_LLM=true returns default clarify response."""
        state = _make_state(
            messages=[{"role": "user", "content": "research competitors"}]
        )

        with patch("app.agents.orchestrator._get_llm", return_value=None):
            result = await orchestrator_node(state)

        # In mock mode, always returns clarify
        assert result["current_intent"] == "clarify"
        assert result["next_node"] == "clarify"

    async def test_preserves_previous_intent(self, mock_llm_response):
        """Current intent becomes previous intent in next call."""
        state = _make_state(
            current_intent="research",
            messages=[{"role": "user", "content": "now generate content"}],
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("generate", next_node="generate")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["previous_intent"] == "research"
        assert result["current_intent"] == "generate"

    async def test_intent_history_accumulates(self, mock_llm_response):
        """Intent history accumulates across calls."""
        state = _make_state(
            intent_history=["research", "generate"],
            messages=[{"role": "user", "content": "deploy now"}],
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_llm_response("deploy", next_node="deploy")

        with patch("app.agents.orchestrator._get_llm", return_value=mock_llm):
            result = await orchestrator_node(state)

        assert result["intent_history"] == ["research", "generate", "deploy"]


# ---------------------------------------------------------------------------
# Clarify node tests
# ---------------------------------------------------------------------------


class TestClarifyNode:
    """Tests for the clarify_node function."""

    async def test_returns_ui_frame(self):
        """Clarify node returns a UI frame for the frontend."""
        state = _make_state(
            clarification_question="What would you like to do?",
            clarification_options=["Research", "Generate", "Deploy"],
        )

        result = await clarify_node(state)

        assert result["active_stage_summary"] == "awaiting clarification"
        assert result["clarification_question"] == "What would you like to do?"
        assert result["clarification_options"] == ["Research", "Generate", "Deploy"]

    async def test_creates_ui_frame_with_actions(self):
        """Clarify node creates properly structured UI frame."""
        state = _make_state(
            clarification_question="Pick an option",
            clarification_options=["A", "B", "C"],
        )

        result = await clarify_node(state)

        # Check pending UI frames
        frames = result.get("_pending_ui_frames", [])
        assert len(frames) == 1

        frame = frames[0]
        assert frame["type"] == "ui_component"
        assert frame["component"] == "ClarificationPrompt"
        assert frame["props"]["question"] == "Pick an option"
        assert frame["props"]["options"] == ["A", "B", "C"]
        assert len(frame["actions"]) == 3

    async def test_uses_defaults_when_no_question(self):
        """Clarify node uses defaults when no question provided."""
        state = _make_state(
            clarification_question=None,
            clarification_options=[],
        )

        result = await clarify_node(state)

        assert result["clarification_question"] == DEFAULT_CLARIFICATION
        assert result["clarification_options"] == DEFAULT_OPTIONS

    async def test_instance_id_is_unique(self):
        """Each clarify call generates a unique instance_id."""
        state = _make_state()

        result1 = await clarify_node(state)
        result2 = await clarify_node(state)

        frame1 = result1["_pending_ui_frames"][0]
        frame2 = result2["_pending_ui_frames"][0]

        assert frame1["instance_id"] != frame2["instance_id"]
        assert frame1["instance_id"].startswith("clarify_")
        assert frame2["instance_id"].startswith("clarify_")
