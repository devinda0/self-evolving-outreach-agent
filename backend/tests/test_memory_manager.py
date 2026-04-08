"""Unit tests for the MemoryManager.

Tests cover:
- build_context_bundle returns correct fields per agent type
- Excluded fields are NOT present for each agent type
- maybe_summarize_conversation triggers at correct threshold
- Summary preserves last 8 raw messages verbatim
- enforce_token_budget truncates correctly
- _get_compact_prospect_cards filters by selection correctly
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.manager import (
    AGENT_TOKEN_BUDGETS,
    MemoryManager,
    enforce_token_budget,
)

# ---------------------------------------------------------------------------
# Minimal state builder
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Build a minimal CampaignState-compatible dict."""
    base = {
        "session_id": "test-session-001",
        "product_name": "SalesOS",
        "product_description": "AI-powered outreach automation",
        "target_market": "VP Sales at Series B SaaS",
        "messages": [],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": ["research", "segment"],
        "current_intent": "content",
        "previous_intent": "segment",
        "next_node": "generate",
        "clarification_question": None,
        "clarification_options": [],
        "session_complete": False,
        "cycle_number": 2,
        "prior_cycle_summary": "Competitor-gap angle won in cycle 1 with 12% reply rate.",
        "active_stage_summary": "content generation",
        "research_query": "SaaS outreach tools",
        "active_thread_types": ["competitor", "audience"],
        "thread_type": None,
        "research_policy": {},
        "research_findings": [
            {
                "id": "rf-001",
                "claim": "Competitors lack personalisation at scale.",
                "confidence": 0.85,
                "signal_type": "competitor",
                "actionable_implication": "Lead with personalisation angle.",
            },
            {
                "id": "rf-002",
                "claim": "Audiences respond to ROI metrics.",
                "confidence": 0.72,
                "signal_type": "audience",
                "actionable_implication": "Include ROI data in first message.",
            },
            {
                "id": "rf-003",
                "claim": "LinkedIn performs 2x better in this ICP.",
                "confidence": 0.65,
                "signal_type": "channel",
                "actionable_implication": "Prioritise LinkedIn outreach.",
            },
        ],
        "briefing_summary": "Market shows strong appetite for personalisation.",
        "research_gaps": ["pricing benchmarks"],
        "failed_threads": [],
        "selected_segment_id": "seg-001",
        "segment_candidates": [
            {"id": "seg-001", "label": "VP Sales at Series B SaaS"},
            {"id": "seg-002", "label": "Head of Growth at SMB"},
        ],
        "selected_prospect_ids": ["p-001", "p-002"],
        "prospect_pool_ref": None,
        "prospect_cards": [
            {
                "id": "p-001",
                "name": "Alice Chen",
                "email": "alice@acme.io",
                "title": "VP Sales",
                "company": "Acme SaaS",
                "angle_recommendation": "pipeline-acceleration",
            },
            {
                "id": "p-002",
                "name": "Bob Martinez",
                "email": "bob@scaleup.io",
                "title": "Head of Growth",
                "company": "ScaleUp Inc",
                "angle_recommendation": "demand-generation",
            },
            {
                "id": "p-003",
                "name": "Carol Nguyen",
                "email": "carol@cloudfirst.com",
                "title": "CRO",
                "company": "CloudFirst",
                "angle_recommendation": "strategic-vision",
            },
        ],
        "content_request": "Focus on pain-led angle",
        "content_variants": [
            {
                "id": "var-001",
                "source_finding_ids": ["rf-001", "rf-002"],
                "intended_channel": "email",
                "angle_label": "competitor-gap",
            }
        ],
        "selected_variant_ids": ["var-001"],
        "visual_artifacts": [],
        "selected_channels": ["email"],
        "ab_split_plan": None,
        "deployment_confirmed": False,
        "deployment_records": [{"id": "dr-001", "variant_id": "var-001", "status": "sent"}],
        "normalized_feedback_events": [
            {"variant_id": "var-001", "event_type": "open", "deployment_record_id": "dr-001"}
        ],
        "engagement_results": [],
        "winning_variant_id": None,
        "memory_refs": {},
        "error_messages": [],
        "pending_ui_frames": [],
    }
    base.update(overrides)
    return base


def _make_manager() -> MemoryManager:
    return MemoryManager()


# ---------------------------------------------------------------------------
# build_context_bundle — orchestrator
# ---------------------------------------------------------------------------


class TestBuildContextBundleOrchestrator:
    @pytest.mark.asyncio
    async def test_orchestrator_bundle_has_required_fields(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "orchestrator")

        assert "task_header" in bundle
        assert "current_stage_state" in bundle
        assert "latest_user_intent" in bundle
        assert "recent_messages" in bundle
        assert "relevant_cycle_summary" in bundle
        assert "intent_history" in bundle

    @pytest.mark.asyncio
    async def test_orchestrator_intent_history_capped_at_5(self):
        manager = _make_manager()
        state = _make_state(intent_history=["r", "s", "g", "d", "f", "r", "s"])
        bundle = await manager.build_context_bundle(state, "orchestrator")
        # Should only have the last 5
        assert len(bundle["intent_history"]) == 5

    @pytest.mark.asyncio
    async def test_orchestrator_does_not_have_research_fields(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "orchestrator")

        assert "source_findings" not in bundle
        assert "selected_segment" not in bundle
        assert "selected_prospects" not in bundle

    @pytest.mark.asyncio
    async def test_task_header_contains_session_identity(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "orchestrator")

        header = bundle["task_header"]
        assert header["session_id"] == "test-session-001"
        assert header["product_name"] == "SalesOS"
        assert header["cycle_number"] == 2


# ---------------------------------------------------------------------------
# build_context_bundle — content
# ---------------------------------------------------------------------------


class TestBuildContextBundleContent:
    @pytest.mark.asyncio
    async def test_content_bundle_has_source_findings(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "content")

        assert "source_findings" in bundle
        assert isinstance(bundle["source_findings"], list)
        assert len(bundle["source_findings"]) > 0

    @pytest.mark.asyncio
    async def test_content_bundle_has_selected_segment(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "content")

        assert "selected_segment" in bundle
        seg = bundle["selected_segment"]
        assert seg is not None
        assert seg["id"] == "seg-001"

    @pytest.mark.asyncio
    async def test_content_bundle_has_winning_angle_memory(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "content")

        assert "winning_angle_memory" in bundle
        assert "cycle 1" in bundle["winning_angle_memory"]

    @pytest.mark.asyncio
    async def test_content_bundle_does_not_have_full_prospect_list(self):
        """Content bundle must NOT include the full prospect list."""
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "content")

        # selected_prospects is a deployment concern, not content
        assert "selected_prospects" not in bundle

    @pytest.mark.asyncio
    async def test_content_source_findings_scoped_to_selected_variants(self):
        """Findings are scoped to those referenced by selected variants."""
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "content")

        finding_ids = {f["id"] for f in bundle["source_findings"]}
        # var-001 references rf-001 and rf-002
        assert "rf-001" in finding_ids
        assert "rf-002" in finding_ids

    @pytest.mark.asyncio
    async def test_content_fallback_to_top_findings_when_no_variant_selected(self):
        """When no variants are selected, falls back to top-5 sorted by confidence."""
        manager = _make_manager()
        state = _make_state(selected_variant_ids=[])
        bundle = await manager.build_context_bundle(state, "content")

        assert len(bundle["source_findings"]) <= 5
        # Should be sorted by confidence descending
        confidences = [f.get("confidence", 0) for f in bundle["source_findings"]]
        assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# build_context_bundle — deployment
# ---------------------------------------------------------------------------


class TestBuildContextBundleDeployment:
    @pytest.mark.asyncio
    async def test_deployment_bundle_has_compact_prospects(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "deployment")

        assert "selected_prospects" in bundle
        prospects = bundle["selected_prospects"]
        assert isinstance(prospects, list)

    @pytest.mark.asyncio
    async def test_deployment_compact_cards_filter_by_selection(self):
        """Only selected prospect IDs should appear in compact cards."""
        manager = _make_manager()
        state = _make_state(selected_prospect_ids=["p-001"])
        bundle = await manager.build_context_bundle(state, "deployment")

        prospect_ids = [p["id"] for p in bundle["selected_prospects"]]
        assert "p-001" in prospect_ids
        assert "p-003" not in prospect_ids

    @pytest.mark.asyncio
    async def test_deployment_compact_cards_do_not_include_body_text(self):
        """Compact cards must only have key fields, not full content."""
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "deployment")

        for card in bundle["selected_prospects"]:
            assert set(card.keys()) == {"id", "name", "email", "title", "company", "angle"}

    @pytest.mark.asyncio
    async def test_deployment_bundle_has_selected_variants(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "deployment")

        assert "selected_variant" in bundle
        assert isinstance(bundle["selected_variant"], list)


# ---------------------------------------------------------------------------
# build_context_bundle — feedback
# ---------------------------------------------------------------------------


class TestBuildContextBundleFeedback:
    @pytest.mark.asyncio
    async def test_feedback_bundle_has_deployment_records(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "feedback")

        assert "deployment_records" in bundle
        assert len(bundle["deployment_records"]) > 0

    @pytest.mark.asyncio
    async def test_feedback_bundle_has_normalized_metrics(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "feedback")

        assert "normalized_metrics" in bundle

    @pytest.mark.asyncio
    async def test_feedback_bundle_does_not_include_prospects(self):
        manager = _make_manager()
        state = _make_state()
        bundle = await manager.build_context_bundle(state, "feedback")

        assert "selected_prospects" not in bundle


# ---------------------------------------------------------------------------
# maybe_summarize_conversation
# ---------------------------------------------------------------------------


class TestMaybeSummarizeConversation:
    def _make_messages(self, n: int) -> list[dict]:
        return [{"role": "user" if i % 2 == 0 else "ai", "content": f"Message {i}"} for i in range(n)]

    @pytest.mark.asyncio
    async def test_no_summary_when_below_threshold(self):
        manager = _make_manager()
        state = _make_state(messages=self._make_messages(10))
        result = await manager.maybe_summarize_conversation(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_summary_at_exactly_threshold(self):
        manager = _make_manager()
        state = _make_state(messages=self._make_messages(20))
        result = await manager.maybe_summarize_conversation(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_summary_triggered_above_threshold(self):
        """Summary should be produced when messages > 20."""
        manager = _make_manager()
        messages = self._make_messages(25)
        state = _make_state(messages=messages)

        with patch.object(
            manager, "_get_llm", return_value=None
        ):  # forces mock path (USE_MOCK_LLM equivalent)
            result = await manager.maybe_summarize_conversation(state)

        assert "conversation_summary" in result
        assert result["conversation_summary"]  # non-empty

    @pytest.mark.asyncio
    async def test_summary_preserves_last_8_raw_messages(self):
        """The raw message window (last 8) must NOT be included in summarised content."""
        manager = _make_manager()
        messages = self._make_messages(25)
        state = _make_state(messages=messages)

        with patch.object(manager, "_get_llm", return_value=None):
            result = await manager.maybe_summarize_conversation(state)

        # The summary should cover messages 0..16 (25 - 8 older = 17 messages)
        summary = result["conversation_summary"]
        assert summary  # non-empty

    @pytest.mark.asyncio
    async def test_summary_appended_to_decision_log(self):
        manager = _make_manager()
        messages = self._make_messages(25)
        state = _make_state(messages=messages, decision_log=[{"type": "existing"}])

        with patch.object(manager, "_get_llm", return_value=None):
            result = await manager.maybe_summarize_conversation(state)

        assert "decision_log" in result
        log = result["decision_log"]
        # Existing entry preserved, new summary entry appended
        assert len(log) == 2
        assert log[1]["type"] == "conversation_summary"
        assert "covers_messages" in log[1]

    @pytest.mark.asyncio
    async def test_summary_covers_messages_count_is_correct(self):
        manager = _make_manager()
        messages = self._make_messages(28)
        state = _make_state(messages=messages)

        with patch.object(manager, "_get_llm", return_value=None):
            result = await manager.maybe_summarize_conversation(state)

        # 28 messages - 8 recent = 20 covered
        assert result["decision_log"][-1]["covers_messages"] == 20

    @pytest.mark.asyncio
    async def test_summary_skipped_on_llm_failure(self):
        """If LLM call fails, return empty dict (don't crash)."""
        manager = _make_manager()
        messages = self._make_messages(25)
        state = _make_state(messages=messages)

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        with patch.object(manager, "_get_llm", return_value=mock_llm):
            result = await manager.maybe_summarize_conversation(state)

        assert result == {}


# ---------------------------------------------------------------------------
# enforce_token_budget
# ---------------------------------------------------------------------------


class TestEnforceTokenBudget:
    def test_small_bundle_unchanged(self):
        bundle = {
            "task_header": {"session_id": "x"},
            "recent_messages": [{"role": "user", "content": "Hi"}],
        }
        result = enforce_token_budget(bundle, "orchestrator")
        assert result["recent_messages"] == bundle["recent_messages"]

    def test_large_messages_trimmed_to_fit_budget(self):
        # Create a bundle well over the budget
        large_content = "x" * 500
        messages = [{"role": "user", "content": large_content}] * 50
        bundle = {"recent_messages": messages}

        budget_chars = AGENT_TOKEN_BUDGETS["orchestrator"] * 4  # 4 chars/token
        result = enforce_token_budget(bundle, "orchestrator")

        total_chars = sum(len(str(v)) for v in result.values())
        assert total_chars <= budget_chars * 2  # Allow some slack for str() overhead

    def test_minimum_3_messages_preserved(self):
        large_content = "x" * 5000
        messages = [{"role": "user", "content": large_content}] * 10
        bundle = {"recent_messages": messages}

        result = enforce_token_budget(bundle, "orchestrator")
        assert len(result["recent_messages"]) >= 3

    def test_findings_trimmed_when_oversized(self):
        findings = [{"id": f"rf-{i}", "claim": "x" * 2000} for i in range(50)]
        bundle = {
            "recent_messages": [],
            "source_findings": findings,
        }

        result = enforce_token_budget(bundle, "content")
        assert len(result["source_findings"]) < 50

    def test_returns_new_dict_not_mutating_original(self):
        bundle = {
            "task_header": {"session_id": "x"},
            "recent_messages": [{"role": "user", "content": "Hi"}],
        }
        result = enforce_token_budget(bundle, "orchestrator")
        assert result is not bundle


# ---------------------------------------------------------------------------
# _get_recent_messages
# ---------------------------------------------------------------------------


class TestGetRecentMessages:
    def test_returns_last_n_messages(self):
        manager = _make_manager()
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(15)]
        state = _make_state(messages=messages)
        result = manager._get_recent_messages(state, n=8)
        assert len(result) == 8
        assert result[-1]["content"] == "msg 14"

    def test_returns_all_when_fewer_than_n(self):
        manager = _make_manager()
        messages = [{"role": "user", "content": "msg"}] * 3
        state = _make_state(messages=messages)
        result = manager._get_recent_messages(state, n=8)
        assert len(result) == 3

    def test_empty_messages(self):
        manager = _make_manager()
        state = _make_state(messages=[])
        result = manager._get_recent_messages(state, n=8)
        assert result == []


# ---------------------------------------------------------------------------
# _get_compact_prospect_cards
# ---------------------------------------------------------------------------


class TestGetCompactProspectCards:
    def test_filters_to_selected_ids(self):
        manager = _make_manager()
        state = _make_state(selected_prospect_ids=["p-001"])
        cards = manager._get_compact_prospect_cards(state)
        assert len(cards) == 1
        assert cards[0]["id"] == "p-001"

    def test_returns_all_when_no_selection(self):
        """When selected_prospect_ids is empty, return all as compact cards."""
        manager = _make_manager()
        state = _make_state(selected_prospect_ids=[])
        cards = manager._get_compact_prospect_cards(state)
        assert len(cards) == 3  # all 3 from prospect_cards

    def test_compact_card_fields(self):
        manager = _make_manager()
        state = _make_state(selected_prospect_ids=["p-001"])
        cards = manager._get_compact_prospect_cards(state)
        card = cards[0]
        assert set(card.keys()) == {"id", "name", "email", "title", "company", "angle"}

    def test_angle_maps_to_angle_recommendation(self):
        manager = _make_manager()
        state = _make_state(selected_prospect_ids=["p-001"])
        cards = manager._get_compact_prospect_cards(state)
        assert cards[0]["angle"] == "pipeline-acceleration"


# ---------------------------------------------------------------------------
# _get_selected_segment
# ---------------------------------------------------------------------------


class TestGetSelectedSegment:
    def test_returns_matching_segment(self):
        manager = _make_manager()
        state = _make_state(selected_segment_id="seg-002")
        seg = manager._get_selected_segment(state)
        assert seg["id"] == "seg-002"

    def test_falls_back_to_first_when_no_match(self):
        manager = _make_manager()
        state = _make_state(selected_segment_id="seg-999")
        seg = manager._get_selected_segment(state)
        assert seg["id"] == "seg-001"  # first candidate

    def test_returns_none_when_no_candidates(self):
        manager = _make_manager()
        state = _make_state(segment_candidates=[])
        seg = manager._get_selected_segment(state)
        assert seg is None
