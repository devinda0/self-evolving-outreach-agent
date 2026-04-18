"""Tests for the cycle manager — refined_cycle_node, CycleRecord building, accumulated learnings."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.cycle_manager import (
    _build_accumulated_learnings,
    _build_approach_outcomes,
    _build_cycle_record,
    refined_cycle_node,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Build a minimal CampaignState dict with sensible defaults."""
    base = {
        "session_id": "test-session",
        "product_name": "TestProduct",
        "product_description": "A test product",
        "target_market": "Developers",
        "messages": [],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": ["research", "segment", "generate", "deploy", "feedback"],
        "current_intent": "refined_cycle",
        "previous_intent": "feedback",
        "next_node": "refined_cycle",
        "user_directive": "proceed to next cycle",
        "clarification_question": None,
        "clarification_options": [],
        "session_complete": False,
        "cycle_number": 1,
        "prior_cycle_summary": "Variant A outperformed B with 40% reply rate.",
        "active_stage_summary": "feedback complete",
        "cycle_records": [],
        "accumulated_learnings": None,
        "research_query": None,
        "active_thread_types": [],
        "thread_type": None,
        "research_policy": {},
        "research_findings": [
            {"id": "f-1", "claim": "Competitors lack mobile support", "confidence": 0.8},
        ],
        "briefing_summary": "Market research shows gap in mobile-first solutions",
        "research_gaps": [],
        "failed_threads": [],
        "selected_segment_id": "seg-1",
        "segment_candidates": [{"id": "seg-1", "label": "VP Engineering at Series B"}],
        "selected_prospect_ids": ["p-1"],
        "prospect_pool_ref": None,
        "prospect_cards": [{"id": "p-1", "name": "Jane Doe", "email": "jane@co.com"}],
        "content_request": None,
        "content_variants": [
            {
                "id": "var-A",
                "hypothesis": "ROI-focused pitch with data points",
                "angle_label": "ROI Focus",
                "intended_channel": "email",
            },
            {
                "id": "var-B",
                "hypothesis": "Pain-point narrative with testimonial",
                "angle_label": "Pain Point",
                "intended_channel": "email",
            },
        ],
        "selected_variant_ids": ["var-A", "var-B"],
        "visual_artifacts": [],
        "selected_channels": ["email"],
        "ab_split_plan": None,
        "deployment_confirmed": True,
        "deployment_records": [
            {"id": "d-1", "variant_id": "var-A", "prospect_id": "p-1", "channel": "email"},
            {"id": "d-2", "variant_id": "var-B", "prospect_id": "p-1", "channel": "email"},
        ],
        "normalized_feedback_events": [],
        "engagement_results": [
            {
                "variant_id": "var-A",
                "sent": 5,
                "opens": 3,
                "clicks": 1,
                "replies": 2,
                "bounces": 0,
                "open_rate": 0.6,
                "click_rate": 0.2,
                "reply_rate": 0.4,
                "bounce_rate": 0.0,
            },
            {
                "variant_id": "var-B",
                "sent": 5,
                "opens": 2,
                "clicks": 0,
                "replies": 0,
                "bounces": 1,
                "open_rate": 0.4,
                "click_rate": 0.0,
                "reply_rate": 0.0,
                "bounce_rate": 0.2,
            },
        ],
        "winning_variant_id": "var-A",
        "memory_refs": {},
        "error_messages": [],
        "pending_ui_frames": [],
        "_last_summary_message_count": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test: approach outcome analysis
# ---------------------------------------------------------------------------


class TestApproachOutcomes:
    def test_identifies_effective_and_ineffective(self):
        state = _make_state()
        outcomes = _build_approach_outcomes(state)

        assert len(outcomes) == 2

        # var-A has 40% reply rate → effective
        var_a = next(o for o in outcomes if o.variant_id == "var-A")
        assert var_a.verdict == "effective"
        assert var_a.engagement_rate == 0.4

        # var-B has 0% reply rate → ineffective
        var_b = next(o for o in outcomes if o.variant_id == "var-B")
        assert var_b.verdict == "ineffective"
        assert var_b.engagement_rate == 0.0

    def test_empty_engagement_results(self):
        state = _make_state(engagement_results=[])
        outcomes = _build_approach_outcomes(state)
        assert outcomes == []

    def test_insufficient_data_verdict(self):
        state = _make_state(
            engagement_results=[
                {
                    "variant_id": "var-C",
                    "sent": 0,
                    "opens": 0,
                    "clicks": 0,
                    "replies": 0,
                    "bounces": 0,
                    "reply_rate": 0.0,
                },
            ]
        )
        outcomes = _build_approach_outcomes(state)
        assert outcomes[0].verdict == "insufficient_data"


# ---------------------------------------------------------------------------
# Test: CycleRecord building
# ---------------------------------------------------------------------------


class TestBuildCycleRecord:
    def test_builds_record_from_state(self):
        state = _make_state()
        record = _build_cycle_record(state)

        assert record.session_id == "test-session"
        assert record.cycle_number == 1
        assert record.total_sends == 10  # 5+5
        assert record.total_replies == 2
        assert record.winning_variant_id == "var-A"
        assert len(record.approach_outcomes) == 2
        assert "ROI-focused pitch with data points" in record.approaches_to_amplify
        assert "Pain-point narrative with testimonial" in record.approaches_to_avoid

    def test_preserves_research_summary(self):
        state = _make_state()
        record = _build_cycle_record(state)
        assert "mobile-first" in record.research_summary

    def test_captures_channels_and_segments(self):
        state = _make_state()
        record = _build_cycle_record(state)
        assert "email" in record.channels_used
        assert len(record.segments_used) == 1


# ---------------------------------------------------------------------------
# Test: accumulated learnings
# ---------------------------------------------------------------------------


class TestAccumulatedLearnings:
    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    async def test_builds_from_single_cycle(self, mock_get_cycles, mock_get_intel):
        state = _make_state()
        record = _build_cycle_record(state)
        learnings = await _build_accumulated_learnings("test-session", record)

        assert "1 cycles completed" in learnings
        assert "AMPLIFY" in learnings
        assert "AVOID" in learnings
        assert "ROI-focused pitch" in learnings

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock)
    async def test_builds_from_multiple_cycles(self, mock_get_cycles, mock_get_intel):
        past_record = {
            "cycle_number": 1,
            "research_summary": "Initial market research",
            "content_strategies": ["Price comparison"],
            "total_sends": 10,
            "total_replies": 1,
            "approach_outcomes": [
                {"approach": "Price comparison", "verdict": "ineffective", "engagement_rate": 0.0},
            ],
            "approaches_to_amplify": [],
            "approaches_to_avoid": ["Price comparison"],
            "learning_delta": "Price comparison approach failed",
        }
        mock_get_cycles.return_value = [past_record]

        state = _make_state(cycle_number=2)
        record = _build_cycle_record(state)
        learnings = await _build_accumulated_learnings("test-session", record)

        assert "2 cycles completed" in learnings
        assert "Price comparison" in learnings
        assert "AVOID" in learnings


# ---------------------------------------------------------------------------
# Test: refined_cycle_node
# ---------------------------------------------------------------------------


class TestRefinedCycleNode:
    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_advances_cycle_number(self, mock_save, mock_get_cycles, mock_get_intel):
        state = _make_state(cycle_number=1)
        result = await refined_cycle_node(state)

        assert result["cycle_number"] == 2
        assert result["session_complete"] is True

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_persists_cycle_record(self, mock_save, mock_get_cycles, mock_get_intel):
        state = _make_state(cycle_number=1)
        await refined_cycle_node(state)

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["session_id"] == "test-session"
        assert saved["cycle_number"] == 1

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_resets_transient_state(self, mock_save, mock_get_cycles, mock_get_intel):
        state = _make_state(cycle_number=1)
        result = await refined_cycle_node(state)

        # Transient per-cycle fields should be reset
        assert result["content_variants"] == []
        assert result["deployment_records"] == []
        assert result["normalized_feedback_events"] == []
        assert result["engagement_results"] == []
        assert result["winning_variant_id"] is None
        assert result["deployment_confirmed"] is False

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_builds_accumulated_learnings(self, mock_save, mock_get_cycles, mock_get_intel):
        state = _make_state(cycle_number=1)
        result = await refined_cycle_node(state)

        assert result["accumulated_learnings"] is not None
        assert "AMPLIFY" in result["accumulated_learnings"]

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_emits_ui_frames(self, mock_save, mock_get_cycles, mock_get_intel):
        state = _make_state(cycle_number=1)
        result = await refined_cycle_node(state)

        frames = result["pending_ui_frames"]
        assert len(frames) >= 2
        components = [f["component"] for f in frames]
        assert "MessageRenderer" in components
        assert "CycleSummary" in components

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_appends_to_existing_cycle_records(self, mock_save, mock_get_cycles, mock_get_intel):
        existing = [{"cycle_number": 1, "session_id": "test-session"}]
        state = _make_state(cycle_number=2, cycle_records=existing)
        result = await refined_cycle_node(state)

        assert len(result["cycle_records"]) == 2
        assert result["cycle_records"][0]["cycle_number"] == 1
        assert result["cycle_records"][1]["cycle_number"] == 2

    @pytest.mark.asyncio
    @patch("app.agents.cycle_manager.get_intelligence_entries", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.get_cycle_records", new_callable=AsyncMock, return_value=[])
    @patch("app.agents.cycle_manager.save_cycle_record", new_callable=AsyncMock)
    async def test_prior_cycle_summary_populated(self, mock_save, mock_get_cycles, mock_get_intel):
        state = _make_state(cycle_number=1)
        result = await refined_cycle_node(state)

        # Evolution summary should reference the cycle results
        assert result["prior_cycle_summary"] is not None
        assert len(result["prior_cycle_summary"]) > 0
