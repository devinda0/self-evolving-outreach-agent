"""Tests for the Research Subgraph — thread nodes, synthesizer, and bounded branching.

Covers:
- Query generation (mock LLM / fallback)
- Thread node with mocked search + extract
- Thread node failure handling (records failed_threads)
- Synthesizer fan-in with deduplication and briefing
- BriefingCard UI frame emission
- Bounded branching gate logic
- Research policy enforcement (max_pages_to_extract)
"""

from unittest.mock import AsyncMock, patch

from app.agents.research.synthesizer import (
    _deduplicate_findings,
    _mock_briefing,
    _thread_summary,
    research_synthesizer_node,
)
from app.agents.research.thread import (
    _mock_findings,
    _normalize_finding,
    generate_queries,
    research_dispatcher_node,
    research_thread_node,
    should_branch,
    synthesize_thread_findings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    base = {
        "session_id": "test-session",
        "product_name": "TestProduct",
        "product_description": "A productivity tool for developers",
        "target_market": "Software Engineers",
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
        "thread_type": None,
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


def _make_search_results(n: int = 3) -> list[dict]:
    return [
        {
            "title": f"Result {i}",
            "url": f"https://example.com/{i}",
            "content": f"Content about topic {i} with details",
            "score": 0.8 - i * 0.1,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------


class TestGenerateQueries:
    async def test_mock_mode_returns_fallback_queries(self):
        with patch("app.agents.research.thread._get_llm", return_value=None):
            queries = await generate_queries("MyProduct", "Developers", "competitor")
        assert len(queries) == 3
        assert all(isinstance(q, str) for q in queries)
        assert "MyProduct" in queries[0]

    async def test_llm_failure_returns_fallback_queries(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API error")
        with patch("app.agents.research.thread._get_llm", return_value=mock_llm):
            queries = await generate_queries("MyProduct", "Devs", "audience")
        assert len(queries) >= 2


# ---------------------------------------------------------------------------
# Thread synthesis
# ---------------------------------------------------------------------------


class TestSynthesizeThreadFindings:
    async def test_empty_results_returns_empty(self):
        findings = await synthesize_thread_findings("competitor", "Prod", "Market", raw_results=[])
        assert findings == []

    async def test_mock_mode_returns_structured_findings(self):
        results = _make_search_results(3)
        with patch("app.agents.research.thread._get_llm", return_value=None):
            findings = await synthesize_thread_findings(
                "competitor", "Prod", "Market", raw_results=results
            )
        assert len(findings) >= 2
        for f in findings:
            assert "claim" in f
            assert "confidence" in f
            assert f["thread_type"] == "competitor"


# ---------------------------------------------------------------------------
# Research thread node
# ---------------------------------------------------------------------------


class TestResearchThreadNode:
    async def test_returns_findings_with_metadata(self):
        mock_results = _make_search_results(3)
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
            state = _make_state(thread_type="competitor")
            result = await research_thread_node(state)

        findings = result["research_findings"]
        assert len(findings) >= 2
        for f in findings:
            assert f["thread_type"] == "competitor"
            assert f["session_id"] == "test-session"
            assert f["cycle_number"] == 1
            assert f["id"].startswith("rf-")
            assert "created_at" in f

    async def test_respects_max_pages_to_extract(self):
        mock_results = _make_search_results(10)
        extract_mock = AsyncMock(return_value="page text")

        policy = {
            "enabled_threads": ["competitor"],
            "max_search_results_per_query": 5,
            "max_pages_to_extract": 2,
            "max_branch_depth": 2,
            "max_subinvestigations_per_thread": 2,
            "recency_days": 30,
            "allowed_tool_groups": [],
            "evidence_threshold": 0.6,
        }

        with (
            patch("app.agents.research.thread._get_llm", return_value=None),
            patch(
                "app.agents.research.thread.search_web",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch("app.agents.research.thread.extract_page", extract_mock),
        ):
            state = _make_state(thread_type="market", research_policy=policy)
            await research_thread_node(state)

        assert extract_mock.call_count <= 2

    async def test_failure_records_in_failed_threads(self):
        with (
            patch("app.agents.research.thread._get_llm", return_value=None),
            patch(
                "app.agents.research.thread.search_web",
                new_callable=AsyncMock,
                side_effect=Exception("Network timeout"),
            ),
        ):
            state = _make_state(thread_type="channel")
            result = await research_thread_node(state)

        assert result["research_findings"] == []
        assert "channel" in result["failed_threads"]

    async def test_all_four_thread_types_produce_findings(self):
        mock_results = _make_search_results(2)
        for thread_type in ["competitor", "audience", "channel", "market"]:
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
                    return_value="",
                ),
            ):
                state = _make_state(thread_type=thread_type)
                result = await research_thread_node(state)
            assert len(result["research_findings"]) >= 2, (
                f"{thread_type} thread returned < 2 findings"
            )


# ---------------------------------------------------------------------------
# Research dispatcher
# ---------------------------------------------------------------------------


class TestResearchDispatcher:
    async def test_returns_default_threads(self):
        result = await research_dispatcher_node(_make_state())
        assert set(result["active_thread_types"]) == {"competitor", "audience", "channel", "market"}

    async def test_respects_custom_policy(self):
        policy = {
            "enabled_threads": ["competitor", "market"],
            "max_search_results_per_query": 3,
            "max_pages_to_extract": 1,
            "max_branch_depth": 1,
            "max_subinvestigations_per_thread": 1,
            "recency_days": 14,
            "allowed_tool_groups": [],
            "evidence_threshold": 0.7,
        }
        result = await research_dispatcher_node(_make_state(research_policy=policy))
        assert result["active_thread_types"] == ["competitor", "market"]


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------


class TestResearchSynthesizer:
    async def test_produces_briefing_and_ui_frame(self):
        findings = [
            {
                "claim": "Competitor X raised Series B",
                "confidence": 0.85,
                "thread_type": "competitor",
                "evidence": "TechCrunch report",
                "source_url": "https://tc.com/1",
                "actionable_implication": "Attack before they scale",
                "id": "rf-1",
                "session_id": "test-session",
                "cycle_number": 1,
                "signal_type": "competitor",
                "created_at": "2026-04-08T00:00:00Z",
            },
            {
                "claim": "Devs complain about setup time",
                "confidence": 0.72,
                "thread_type": "audience",
                "evidence": "Reddit threads",
                "source_url": "https://reddit.com/r/dev",
                "actionable_implication": "Lead with ease-of-setup messaging",
                "id": "rf-2",
                "session_id": "test-session",
                "cycle_number": 1,
                "signal_type": "audience",
                "created_at": "2026-04-08T00:00:00Z",
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

        frame = result["pending_ui_frames"][0]
        assert frame["component"] == "BriefingCard"
        assert frame["props"]["finding_count"] == 2
        assert len(frame["actions"]) == 3

    async def test_persists_findings_to_db(self):
        findings = [
            {"claim": "Finding 1", "confidence": 0.9, "thread_type": "competitor"},
            {"claim": "Finding 2", "confidence": 0.7, "thread_type": "audience"},
        ]
        save_mock = AsyncMock()

        with (
            patch("app.agents.research.synthesizer._get_llm", return_value=None),
            patch("app.agents.research.synthesizer.save_research_finding", save_mock),
        ):
            await research_synthesizer_node(_make_state(research_findings=findings))

        assert save_mock.call_count == 2

    async def test_handles_empty_findings(self):
        with (
            patch("app.agents.research.synthesizer._get_llm", return_value=None),
            patch("app.agents.research.synthesizer.save_research_finding", new_callable=AsyncMock),
        ):
            result = await research_synthesizer_node(_make_state(research_findings=[]))

        assert "briefing_summary" in result


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_keeps_highest_confidence(self):
        findings = [
            {"claim": "Same claim", "confidence": 0.6, "thread_type": "competitor"},
            {"claim": "Same claim", "confidence": 0.9, "thread_type": "competitor"},
            {"claim": "Different claim", "confidence": 0.5, "thread_type": "audience"},
        ]
        deduped = _deduplicate_findings(findings)
        assert len(deduped) == 2
        # Highest confidence first
        assert deduped[0]["confidence"] == 0.9

    def test_empty_input(self):
        assert _deduplicate_findings([]) == []


# ---------------------------------------------------------------------------
# Bounded branching
# ---------------------------------------------------------------------------


class TestBoundedBranching:
    def test_should_branch_when_all_conditions_met(self):
        lead = {"confidence": 0.8, "branch_type": "search_discovery"}
        policy = {
            "evidence_threshold": 0.6,
            "allowed_tool_groups": ["search_discovery", "deep_extraction"],
            "max_branch_depth": 3,
        }
        assert should_branch(lead, policy, current_depth=1) is True

    def test_rejects_low_confidence(self):
        lead = {"confidence": 0.4, "branch_type": "search_discovery"}
        policy = {
            "evidence_threshold": 0.6,
            "allowed_tool_groups": ["search_discovery"],
            "max_branch_depth": 3,
        }
        assert should_branch(lead, policy, current_depth=0) is False

    def test_rejects_disallowed_tool_group(self):
        lead = {"confidence": 0.8, "branch_type": "news_events"}
        policy = {
            "evidence_threshold": 0.6,
            "allowed_tool_groups": ["search_discovery"],
            "max_branch_depth": 3,
        }
        assert should_branch(lead, policy, current_depth=0) is False

    def test_rejects_exceeded_depth(self):
        lead = {"confidence": 0.9, "branch_type": "search_discovery"}
        policy = {
            "evidence_threshold": 0.6,
            "allowed_tool_groups": ["search_discovery"],
            "max_branch_depth": 2,
        }
        assert should_branch(lead, policy, current_depth=2) is False

    def test_rejects_at_exact_depth_limit(self):
        lead = {"confidence": 0.9, "branch_type": "search_discovery"}
        policy = {
            "evidence_threshold": 0.6,
            "allowed_tool_groups": ["search_discovery"],
            "max_branch_depth": 1,
        }
        assert should_branch(lead, policy, current_depth=1) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_normalize_finding_clamps_confidence(self):
        raw = {"claim": "x", "confidence": 1.5, "source_url": "http://a.com"}
        result = _normalize_finding(raw, "market")
        assert result["confidence"] == 1.0
        assert result["thread_type"] == "market"

    def test_mock_findings_produces_at_least_two(self):
        results = _mock_findings("audience", [])
        assert len(results) >= 2
        assert all(f["thread_type"] == "audience" for f in results)

    def test_thread_summary_counts_by_type(self):
        findings = [
            {"thread_type": "competitor"},
            {"thread_type": "competitor"},
            {"thread_type": "audience"},
        ]
        summary = _thread_summary(findings)
        assert summary == {"competitor": 2, "audience": 1}

    def test_mock_briefing_structure(self):
        findings = [
            {
                "claim": "A",
                "confidence": 0.8,
                "thread_type": "competitor",
                "actionable_implication": "act",
            },
            {
                "claim": "B",
                "confidence": 0.7,
                "thread_type": "audience",
                "actionable_implication": "act2",
            },
        ]
        briefing = _mock_briefing(findings)
        assert "executive_summary" in briefing
        assert "key_themes" in briefing
        assert "top_opportunities" in briefing
        assert "gaps" in briefing
        assert "recommended_next_steps" in briefing
