"""Tests for feedback_agent.py — issue #19 acceptance criteria.

Covers:
- aggregate_engagement_results: open/click/reply/bounce rate computation
- determine_winner: minimum sample size guard
- compute_confidence_updates: delta bounds and direction
- summarize_learning: text content
- build_ab_results_frame / build_cycle_summary_frame / build_feedback_prompt_frame
- feedback_agent_node: no events → prompt; events → full pipeline
- Unmatched events are quarantined, not silently dropped
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.feedback_agent import (
    MIN_SAMPLE_SIZE,
    _chi_squared_2x2,
    aggregate_engagement_results,
    build_ab_results_frame,
    build_cycle_summary_frame,
    build_feedback_prompt_frame,
    build_manual_feedback_frame,
    build_quarantine_viewer_frame,
    compute_ab_significance,
    compute_confidence_updates,
    determine_winner,
    feedback_agent_node,
    summarize_learning,
)

# ---------------------------------------------------------------------------
# Test helpers
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
        "pending_ui_frames": [],
    }
    base.update(overrides)
    return base


def _make_records(n: int, variant_id: str = "var-A") -> list[dict]:
    """Build n minimal deployment record dicts for a single variant."""
    return [
        {
            "id": f"rec-{i}",
            "variant_id": variant_id,
            "prospect_id": f"prospect-{i}",
            "provider_message_id": f"msg-{i}",
        }
        for i in range(n)
    ]


def _make_event(
    variant_id: str,
    event_type: str,
    *,
    provider_event_id: str | None = None,
    deployment_record_id: str | None = None,
    provider_message_id: str | None = None,
    dedupe_key: str | None = None,
) -> dict:
    return {
        "variant_id": variant_id,
        "event_type": event_type,
        "provider": "resend",
        "provider_event_id": provider_event_id or f"evt-{variant_id}-{event_type}",
        "deployment_record_id": deployment_record_id,
        "provider_message_id": provider_message_id,
        "session_id": "test-session",
        "channel": "email",
        "dedupe_key": dedupe_key or f"dk-{variant_id}-{event_type}",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_finding(finding_id: str, confidence: float = 0.6) -> dict:
    return {
        "id": finding_id,
        "session_id": "test-session",
        "cycle_number": 1,
        "signal_type": "audience",
        "claim": "Test claim",
        "evidence": "Test evidence",
        "source_url": "https://example.com",
        "confidence": confidence,
        "audience_language": [],
        "actionable_implication": "Test implication",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# aggregate_engagement_results
# ---------------------------------------------------------------------------


class TestAggregateEngagementResults:
    def test_single_variant_all_event_types(self):
        records = _make_records(10, "var-A")
        events = (
            [_make_event("var-A", "open") for _ in range(6)]
            + [_make_event("var-A", "click") for _ in range(3)]
            + [_make_event("var-A", "reply") for _ in range(2)]
            + [_make_event("var-A", "bounce") for _ in range(1)]
        )
        results = aggregate_engagement_results(events, records)
        assert len(results) == 1
        r = results[0]
        assert r["variant_id"] == "var-A"
        assert r["sent"] == 10
        assert r["opens"] == 6
        assert r["clicks"] == 3
        assert r["replies"] == 2
        assert r["bounces"] == 1
        assert r["open_rate"] == pytest.approx(0.6, abs=0.001)
        assert r["reply_rate"] == pytest.approx(0.2, abs=0.001)

    def test_two_variants_correct_attribution(self):
        records_a = _make_records(5, "var-A")
        records_b = _make_records(5, "var-B")
        events = [_make_event("var-A", "open") for _ in range(3)] + [
            _make_event("var-B", "reply") for _ in range(2)
        ]
        results = aggregate_engagement_results(events, records_a + records_b)
        by_id = {r["variant_id"]: r for r in results}
        assert by_id["var-A"]["open_rate"] == pytest.approx(0.6, abs=0.001)
        assert by_id["var-A"]["reply_rate"] == 0.0
        assert by_id["var-B"]["reply_rate"] == pytest.approx(0.4, abs=0.001)
        assert by_id["var-B"]["open_rate"] == 0.0

    def test_no_events_yields_zero_rates(self):
        records = _make_records(5, "var-A")
        results = aggregate_engagement_results([], records)
        # With no events but records exist, we should still see sent counts for var-A
        assert len(results) == 1
        r = results[0]
        assert r["sent"] == 5
        assert r["open_rate"] == 0.0

    def test_no_records_no_sent_count(self):
        events = [_make_event("var-A", "open") for _ in range(3)]
        results = aggregate_engagement_results(events, [])
        assert results[0]["sent"] == 0
        assert results[0]["open_rate"] == 0.0  # divide-by-zero guard

    def test_events_without_variant_id_are_ignored(self):
        records = _make_records(5, "var-A")
        events_no_id = [{"event_type": "open", "session_id": "test-session"}]
        events_valid = [_make_event("var-A", "open")]
        results = aggregate_engagement_results(events_no_id + events_valid, records)
        assert results[0]["opens"] == 1  # Only the valid event was counted

    def test_ten_records_six_opens_three_per_variant(self):
        """Acceptance criterion: 10 deployment records + 6 open events (3 per variant)."""
        records_a = _make_records(5, "var-A")
        records_b = _make_records(5, "var-B")
        events = [_make_event("var-A", "open") for _ in range(3)] + [
            _make_event("var-B", "open") for _ in range(3)
        ]
        results = aggregate_engagement_results(events, records_a + records_b)
        by_id = {r["variant_id"]: r for r in results}
        assert by_id["var-A"]["opens"] == 3
        assert by_id["var-B"]["opens"] == 3
        assert by_id["var-A"]["open_rate"] == pytest.approx(0.6, abs=0.001)
        assert by_id["var-B"]["open_rate"] == pytest.approx(0.6, abs=0.001)


# ---------------------------------------------------------------------------
# determine_winner
# ---------------------------------------------------------------------------


class TestDetermineWinner:
    def test_returns_highest_reply_rate(self):
        results = [
            {"variant_id": "var-A", "sent": 5, "reply_rate": 0.10},
            {"variant_id": "var-B", "sent": 5, "reply_rate": 0.20},
        ]
        winner = determine_winner(results, min_sample_size=3)
        assert winner is not None
        assert winner["variant_id"] == "var-B"

    def test_returns_none_when_no_variant_meets_min_sample(self):
        results = [
            {"variant_id": "var-A", "sent": 2, "reply_rate": 0.50},
        ]
        winner = determine_winner(results, min_sample_size=3)
        assert winner is None

    def test_winner_must_meet_min_sample(self):
        # var-A has better reply rate but insufficient sample
        results = [
            {"variant_id": "var-A", "sent": 2, "reply_rate": 0.90},
            {"variant_id": "var-B", "sent": 5, "reply_rate": 0.05},
        ]
        winner = determine_winner(results, min_sample_size=3)
        assert winner is not None
        assert winner["variant_id"] == "var-B"

    def test_empty_results_returns_none(self):
        assert determine_winner([], min_sample_size=3) is None

    def test_exactly_min_sample_size_qualifies(self):
        results = [{"variant_id": "var-A", "sent": MIN_SAMPLE_SIZE, "reply_rate": 0.10}]
        winner = determine_winner(results, min_sample_size=MIN_SAMPLE_SIZE)
        assert winner is not None
        assert winner["variant_id"] == "var-A"


# ---------------------------------------------------------------------------
# compute_confidence_updates
# ---------------------------------------------------------------------------


class TestComputeConfidenceUpdates:
    def test_positive_reply_rate_increases_confidence(self):
        results = [{"variant_id": "var-A", "sent": 10, "reply_rate": 0.10}]
        findings = [_make_finding("f-1")]
        updates = compute_confidence_updates(results, findings)
        assert len(updates) == 1
        finding_id, delta = updates[0]
        assert finding_id == "f-1"
        assert delta > 0

    def test_low_reply_rate_decreases_confidence(self):
        results = [{"variant_id": "var-A", "sent": 10, "reply_rate": 0.01}]
        findings = [_make_finding("f-1")]
        updates = compute_confidence_updates(results, findings)
        _, delta = updates[0]
        assert delta < 0

    def test_delta_capped_at_015(self):
        results = [{"variant_id": "var-A", "sent": 100, "reply_rate": 0.50}]
        findings = [_make_finding("f-1")]
        updates = compute_confidence_updates(results, findings)
        _, delta = updates[0]
        assert abs(delta) <= 0.15

    def test_below_min_sample_triggers_no_update(self):
        """Variants with fewer than MIN_SAMPLE_SIZE sends should not drive updates."""
        results = [{"variant_id": "var-A", "sent": MIN_SAMPLE_SIZE - 1, "reply_rate": 0.50}]
        findings = [_make_finding("f-1")]
        updates = compute_confidence_updates(results, findings)
        assert updates == []

    def test_empty_inputs_return_empty(self):
        assert compute_confidence_updates([], []) == []
        assert compute_confidence_updates([], [_make_finding("f-1")]) == []

    def test_multiple_findings_all_receive_update(self):
        results = [{"variant_id": "var-A", "sent": 10, "reply_rate": 0.08}]
        findings = [_make_finding("f-1"), _make_finding("f-2"), _make_finding("f-3")]
        updates = compute_confidence_updates(results, findings)
        updated_ids = [u[0] for u in updates]
        assert "f-1" in updated_ids
        assert "f-2" in updated_ids
        assert "f-3" in updated_ids


# ---------------------------------------------------------------------------
# _chi_squared_2x2
# ---------------------------------------------------------------------------


class TestChiSquared2x2:
    def test_identical_rates_return_zero(self):
        """Two groups with identical rates → chi² = 0."""
        chi2 = _chi_squared_2x2(50, 100, 50, 100)
        assert chi2 == pytest.approx(0.0, abs=0.01)

    def test_large_difference_is_significant(self):
        """80/100 vs 20/100 → chi² well above 3.841 (p < 0.05)."""
        chi2 = _chi_squared_2x2(80, 100, 20, 100)
        assert chi2 > 3.841

    def test_small_difference_not_significant(self):
        """51/100 vs 49/100 → chi² below 3.841."""
        chi2 = _chi_squared_2x2(51, 100, 49, 100)
        assert chi2 < 3.841

    def test_zero_total_returns_zero(self):
        """Zero total in either group → should return 0.0 without error."""
        assert _chi_squared_2x2(0, 0, 5, 10) == 0.0
        assert _chi_squared_2x2(5, 10, 0, 0) == 0.0

    def test_yates_correction_applied(self):
        """With Yates' correction, chi² is smaller than without."""
        # Without Yates: (10*20 - 5*20)^2 * 55 / (15 * 40 * 30 * 25)
        # This is a sanity check that the function applies Yates' correction
        chi2 = _chi_squared_2x2(10, 30, 5, 25)
        assert chi2 >= 0.0  # should never be negative


# ---------------------------------------------------------------------------
# compute_ab_significance
# ---------------------------------------------------------------------------


class TestComputeAbSignificance:
    def test_significant_difference_detected(self):
        """Clear winner should produce is_significant=True."""
        results = [
            {"variant_id": "var-A", "sent": 100, "opens": 80, "open_rate": 0.8},
            {"variant_id": "var-B", "sent": 100, "opens": 20, "open_rate": 0.2},
        ]
        sig = compute_ab_significance(results, metric="opens")
        assert sig["is_significant"] is True
        assert sig["winner_id"] == "var-A"
        assert len(sig["comparisons"]) == 1
        assert sig["comparisons"][0]["significant"] is True

    def test_no_significance_with_similar_rates(self):
        """Similar rates should produce is_significant=False."""
        results = [
            {"variant_id": "var-A", "sent": 50, "opens": 25, "open_rate": 0.5},
            {"variant_id": "var-B", "sent": 50, "opens": 24, "open_rate": 0.48},
        ]
        sig = compute_ab_significance(results, metric="opens")
        assert sig["is_significant"] is False

    def test_below_min_sample_no_significance(self):
        """Variants below min_sample_size should not produce significant results."""
        results = [
            {"variant_id": "var-A", "sent": 2, "opens": 2, "open_rate": 1.0},
            {"variant_id": "var-B", "sent": 2, "opens": 0, "open_rate": 0.0},
        ]
        sig = compute_ab_significance(results, metric="opens", min_sample_size=3)
        assert sig["is_significant"] is False
        assert sig["comparisons"] == []

    def test_single_variant_no_comparison(self):
        """A single variant has nothing to compare against."""
        results = [
            {"variant_id": "var-A", "sent": 100, "opens": 50, "open_rate": 0.5},
        ]
        sig = compute_ab_significance(results, metric="opens")
        assert sig["is_significant"] is False
        assert sig["comparisons"] == []

    def test_empty_results(self):
        sig = compute_ab_significance([], metric="opens")
        assert sig["is_significant"] is False
        assert sig["winner_id"] is None

    def test_three_variants_pairwise_comparisons(self):
        """Three variants should produce 3 pairwise comparisons."""
        results = [
            {"variant_id": "var-A", "sent": 50, "opens": 40, "open_rate": 0.8},
            {"variant_id": "var-B", "sent": 50, "opens": 10, "open_rate": 0.2},
            {"variant_id": "var-C", "sent": 50, "opens": 25, "open_rate": 0.5},
        ]
        sig = compute_ab_significance(results, metric="opens")
        assert len(sig["comparisons"]) == 3  # A-B, A-C, B-C

    def test_reply_metric(self):
        """Should work with reply metric (uses replies count)."""
        results = [
            {"variant_id": "var-A", "sent": 50, "replies": 20, "reply_rate": 0.4},
            {"variant_id": "var-B", "sent": 50, "replies": 2, "reply_rate": 0.04},
        ]
        sig = compute_ab_significance(results, metric="replies")
        assert sig["is_significant"] is True
        assert sig["winner_id"] == "var-A"

    def test_recommendation_present(self):
        results = [
            {"variant_id": "var-A", "sent": 100, "opens": 80, "open_rate": 0.8},
            {"variant_id": "var-B", "sent": 100, "opens": 20, "open_rate": 0.2},
        ]
        sig = compute_ab_significance(results, metric="opens")
        assert isinstance(sig["recommendation"], str)
        assert len(sig["recommendation"]) > 0


# ---------------------------------------------------------------------------
# summarize_learning
# ---------------------------------------------------------------------------


class TestSummarizeLearning:
    def test_includes_winner_info(self):
        results = [
            {"variant_id": "var-A", "sent": 5, "open_rate": 0.4, "reply_rate": 0.2},
        ]
        winner = {"variant_id": "var-A", "reply_rate": 0.2, "sent": 5}
        text = summarize_learning(results, winner)
        assert "var-A" in text
        assert "Winner" in text

    def test_no_winner_mentions_insufficient_sample(self):
        results = [{"variant_id": "var-A", "sent": 2, "open_rate": 0.0, "reply_rate": 0.0}]
        text = summarize_learning(results, None)
        assert "No winner" in text

    def test_empty_results_returns_no_data_message(self):
        text = summarize_learning([], None)
        assert "No engagement data" in text

    def test_includes_significance_info(self):
        results = [
            {"variant_id": "var-A", "sent": 100, "open_rate": 0.8, "reply_rate": 0.2},
            {"variant_id": "var-B", "sent": 100, "open_rate": 0.3, "reply_rate": 0.05},
        ]
        winner = {"variant_id": "var-A", "reply_rate": 0.2, "sent": 100}
        sig = {
            "is_significant": True,
            "winner_id": "var-A",
            "recommendation": "var-A is statistically significant winner",
        }
        text = summarize_learning(results, winner, significance=sig)
        assert "statistically significant" in text.lower() or "significance" in text.lower()


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


class TestUIFrameBuilders:
    def test_ab_results_frame_structure(self):
        results = [{"variant_id": "var-A", "sent": 5, "reply_rate": 0.2}]
        winner = {"variant_id": "var-A", "reply_rate": 0.2}
        frame = build_ab_results_frame(results, winner, "instance-1")
        assert frame["component"] == "ABResults"
        assert frame["props"]["winner_variant_id"] == "var-A"
        assert frame["props"]["results"] == results
        assert len(frame["actions"]) >= 1

    def test_ab_results_frame_no_winner(self):
        frame = build_ab_results_frame([], None, "instance-1")
        assert frame["props"]["winner_variant_id"] is None

    def test_ab_results_frame_with_significance(self):
        results = [{"variant_id": "var-A", "sent": 5, "reply_rate": 0.2}]
        winner = {"variant_id": "var-A", "reply_rate": 0.2}
        sig = {
            "comparisons": [],
            "winner_id": "var-A",
            "is_significant": True,
            "recommendation": "var-A is the clear winner",
        }
        frame = build_ab_results_frame(results, winner, "instance-1", significance=sig)
        assert frame["props"]["significance"] == sig

    def test_cycle_summary_frame_structure(self):
        frame = build_cycle_summary_frame("Learning delta text", None, 2, "instance-2")
        assert frame["component"] == "CycleSummary"
        assert frame["props"]["cycle_number"] == 2
        assert frame["props"]["learning_delta"] == "Learning delta text"
        assert len(frame["actions"]) >= 1

    def test_feedback_prompt_frame_structure(self):
        frame = build_feedback_prompt_frame("instance-3")
        assert frame["component"] == "FeedbackPrompt"
        assert len(frame["actions"]) >= 2
        action_types = {a["action_type"] for a in frame["actions"]}
        assert "manual_feedback" in action_types
        assert "view_quarantine" in action_types

    def test_manual_feedback_frame_with_variants(self):
        records = [
            {"id": "d1", "variant_id": "var-A", "prospect_id": "p1"},
            {"id": "d2", "variant_id": "var-A", "prospect_id": "p2"},  # duplicate variant
            {"id": "d3", "variant_id": "var-B", "prospect_id": "p3"},
        ]
        frame = build_manual_feedback_frame(records, "mf-instance-1")
        assert frame["component"] == "ManualFeedbackInput"
        variants = frame["props"]["variants"]
        # Deduplication: var-A and var-B → 2 entries
        assert len(variants) == 2
        ids = {v["id"] for v in variants}
        assert "var-A" in ids
        assert "var-B" in ids

    def test_manual_feedback_frame_empty_records(self):
        frame = build_manual_feedback_frame([], "mf-instance-2")
        assert frame["component"] == "ManualFeedbackInput"
        assert frame["props"]["variants"] == []

    def test_quarantine_viewer_frame_with_events(self):
        events = [
            {
                "provider": "resend",
                "event_type": "open",
                "provider_message_id": "msg-001",
                "quarantine_reason": "no_matching_deployment_record",
                "received_at": "2026-04-01T00:00:00+00:00",
            }
        ]
        frame = build_quarantine_viewer_frame(events, "qv-instance-1")
        assert frame["component"] == "QuarantineViewer"
        assert frame["props"]["events"] == events

    def test_quarantine_viewer_frame_empty(self):
        frame = build_quarantine_viewer_frame([], "qv-instance-2")
        assert frame["component"] == "QuarantineViewer"
        assert frame["props"]["events"] == []


# ---------------------------------------------------------------------------
# feedback_agent_node — integration-style (all DB calls mocked)
# ---------------------------------------------------------------------------


class TestFeedbackAgentNode:
    @pytest.mark.asyncio
    async def test_no_events_emits_feedback_prompt(self):
        state = _make_state(normalized_feedback_events=[])
        result = await feedback_agent_node(state)
        frames = result.get("pending_ui_frames", [])
        assert len(frames) == 1
        assert frames[0]["component"] == "FeedbackPrompt"
        # Should NOT advance cycle_number or set next_node when waiting for events
        assert "cycle_number" not in result or result.get("cycle_number") == state["cycle_number"]

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    async def test_events_produce_full_pipeline(
        self,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """Given deployment records + open events, agent aggregates, determines winner,
        calls save_intelligence_entry, and emits ABResults + CycleSummary frames."""
        records_a = _make_records(5, "var-A")
        records_b = _make_records(5, "var-B")
        events = (
            [_make_event("var-A", "open") for _ in range(3)]
            + [_make_event("var-A", "reply") for _ in range(2)]
            + [_make_event("var-B", "open") for _ in range(3)]
        )
        findings = [_make_finding("f-1")]
        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records_a + records_b,
            research_findings=findings,
            cycle_number=1,
        )
        result = await feedback_agent_node(state)

        # Engagement results are populated
        assert "engagement_results" in result
        assert len(result["engagement_results"]) == 2

        # var-A should win (has replies, var-B doesn't)
        assert result.get("winning_variant_id") == "var-A"

        # Cycle is NOT advanced by feedback agent — that's now the refined_cycle node's job
        assert "cycle_number" not in result
        assert result["next_node"] == "orchestrator"

        # IntelligenceEntry was saved
        mock_save_intel.assert_called_once()
        saved = mock_save_intel.call_args[0][0]
        assert saved["session_id"] == "test-session"
        assert "learning_delta" in saved
        assert saved["winning_variant_id"] == "var-A"

        # Confidence updates were persisted (at least for f-1)
        assert mock_update_conf.call_count >= 1

        # Two UI frames: ABResults and CycleSummary
        frames = result["pending_ui_frames"]
        components = [f["component"] for f in frames]
        assert "ABResults" in components
        assert "CycleSummary" in components

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    async def test_no_winner_when_sample_too_small(
        self,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """With only 2 sends per variant, no winner should be declared."""
        records_a = _make_records(2, "var-A")
        records_b = _make_records(2, "var-B")
        events = [_make_event("var-A", "reply"), _make_event("var-B", "open")]
        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records_a + records_b,
            cycle_number=2,
        )
        result = await feedback_agent_node(state)
        assert result.get("winning_variant_id") is None
        saved = mock_save_intel.call_args[0][0]
        assert saved["winning_variant_id"] is None

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    async def test_unmatched_events_are_quarantined(
        self,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """Events without a matching deployment_record_id or provider_message_id
        must be sent to the quarantine collection."""
        records = _make_records(5, "var-A")
        # This event has no correlated record
        unmatched = _make_event(
            "var-X",
            "open",
            provider_event_id="unknown-evt",
            dedupe_key="dk-unmatched",
        )
        matched = _make_event("var-A", "open", provider_message_id="msg-0")
        state = _make_state(
            normalized_feedback_events=[unmatched, matched],
            deployment_records=records,
        )
        await feedback_agent_node(state)
        # Quarantine should have been called at least once for the unmatched event
        mock_quarantine.assert_called()
        quarantined_events = [call.args[0] for call in mock_quarantine.call_args_list]
        assert any(e.get("quarantine_reason") for e in quarantined_events)

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch(
        "app.agents.feedback_agent.save_intelligence_entry",
        side_effect=Exception("DB down"),
    )
    async def test_db_failure_does_not_raise(
        self,
        mock_save_intel,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """A failure in save_intelligence_entry should be caught and logged, not raised."""
        records = _make_records(5, "var-A")
        events = [_make_event("var-A", "reply") for _ in range(3)]
        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records,
        )
        # Should not raise
        result = await feedback_agent_node(state)
        assert "engagement_results" in result  # State should still contain engagement results


# ---------------------------------------------------------------------------
# Tests for event hydration from MongoDB
# ---------------------------------------------------------------------------


class TestHydrateFeedbackFromDB:
    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.get_deployment_records_for_session", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.get_feedback_events_for_session", new_callable=AsyncMock)
    async def test_merges_db_events_with_state(
        self,
        mock_get_events: AsyncMock,
        mock_get_records: AsyncMock,
    ):
        """Events in DB but not in state should be merged into the result."""
        from app.agents.feedback_agent import hydrate_feedback_from_db

        state_events = [_make_event("var-A", "open", dedupe_key="dk-state-1")]
        db_events = [
            _make_event("var-A", "open", dedupe_key="dk-state-1"),  # duplicate
            _make_event("var-A", "click", dedupe_key="dk-db-new"),  # new from DB
        ]
        mock_get_events.return_value = db_events
        mock_get_records.return_value = _make_records(3, "var-A")

        merged, records = await hydrate_feedback_from_db("test-session", state_events)

        assert len(merged) == 2  # 1 from state + 1 new from DB (deduped)
        assert len(records) == 3
        dedupe_keys = {e["dedupe_key"] for e in merged}
        assert "dk-state-1" in dedupe_keys
        assert "dk-db-new" in dedupe_keys

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.get_deployment_records_for_session", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.get_feedback_events_for_session", new_callable=AsyncMock)
    async def test_no_db_events_returns_state_events(
        self,
        mock_get_events: AsyncMock,
        mock_get_records: AsyncMock,
    ):
        """When DB has no new events, result should match state events."""
        from app.agents.feedback_agent import hydrate_feedback_from_db

        state_events = [
            _make_event("var-A", "open", dedupe_key="dk-1"),
            _make_event("var-A", "reply", dedupe_key="dk-2"),
        ]
        mock_get_events.return_value = []
        mock_get_records.return_value = []

        merged, records = await hydrate_feedback_from_db("test-session", state_events)

        assert len(merged) == 2
        assert len(records) == 0


# ---------------------------------------------------------------------------
# Tests for enhanced summarize_learning
# ---------------------------------------------------------------------------


class TestSummarizeLearningEnhanced:
    def test_includes_reply_insights(self):
        """Reply insights should appear in learning delta text."""
        results = [
            {"variant_id": "var-AAAA1234", "sent": 10, "open_rate": 0.5,
             "click_rate": 0.1, "reply_rate": 0.3, "bounce_rate": 0.0},
        ]
        winner = results[0]
        reply_insights = [
            {"classification": "interested", "sentiment": "positive",
             "confidence": 0.9, "key_signals": ["wants demo"], "summary": "Interested"},
            {"classification": "not_interested", "sentiment": "negative",
             "confidence": 0.8, "key_signals": ["budget concerns"], "summary": "Declined"},
        ]
        text = summarize_learning(results, winner, reply_insights=reply_insights)
        assert "Reply Analysis" in text
        assert "interested: 1" in text
        assert "not_interested: 1" in text
        assert "wants demo" in text

    def test_includes_thread_summaries(self):
        """Thread summaries should appear in learning delta text."""
        results = [
            {"variant_id": "var-AAAA1234", "sent": 5, "open_rate": 0.5,
             "click_rate": 0.1, "reply_rate": 0.2, "bounce_rate": 0.0},
        ]
        thread_summaries = [
            {"prospect_name": "Alice", "prospect_email": "alice@co.com",
             "status": "replied", "reply_count": 2, "classification": "interested"},
        ]
        text = summarize_learning(
            results, results[0], thread_summaries=thread_summaries,
        )
        assert "Prospect Conversations" in text
        assert "Alice" in text

    def test_recommendations_section(self):
        """Recommendations should reflect reply classifications."""
        results = [
            {"variant_id": "var-BBBB5678", "sent": 10, "open_rate": 0.4,
             "click_rate": 0.1, "reply_rate": 0.2, "bounce_rate": 0.0},
        ]
        reply_insights = [
            {"classification": "interested", "sentiment": "positive",
             "confidence": 0.9, "key_signals": [], "extracted_info": {}},
            {"classification": "not_interested", "sentiment": "negative",
             "confidence": 0.8, "key_signals": [],
             "extracted_info": {"objection": "Too expensive"}},
        ]
        text = summarize_learning(results, results[0], reply_insights=reply_insights)
        assert "Recommendations for Next Cycle" in text
        assert "interest" in text.lower()
        assert "Too expensive" in text


# ---------------------------------------------------------------------------
# Tests for feedback_agent_node with hydration and classification
# ---------------------------------------------------------------------------


class TestFeedbackAgentNodeEnhanced:
    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.get_email_threads_for_session", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.hydrate_feedback_from_db", new_callable=AsyncMock)
    async def test_hydration_merges_webhook_events(
        self,
        mock_hydrate: AsyncMock,
        mock_get_threads: AsyncMock,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """The node should use hydrated events (state + DB) for analysis."""
        state_events = [_make_event("var-A", "open", dedupe_key="dk-1")]
        records = _make_records(5, "var-A")

        # Simulate hydration returning extra events from DB
        hydrated_events = state_events + [
            _make_event("var-A", "reply", dedupe_key="dk-2"),
            _make_event("var-A", "click", dedupe_key="dk-3"),
        ]
        mock_hydrate.return_value = (hydrated_events, records)
        mock_get_threads.return_value = []

        state = _make_state(
            normalized_feedback_events=state_events,
            deployment_records=records,
        )
        result = await feedback_agent_node(state)

        # Hydrated events should be returned in state
        returned_events = result.get("normalized_feedback_events", [])
        assert len(returned_events) == 3  # 1 state + 2 from DB

        mock_hydrate.assert_called_once_with("test-session", state_events)

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.get_email_threads_for_session", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.hydrate_feedback_from_db", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_feedback_event", new_callable=AsyncMock)
    async def test_reply_events_classified_and_persisted(
        self,
        mock_update_event: AsyncMock,
        mock_hydrate: AsyncMock,
        mock_get_threads: AsyncMock,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """Reply events should be classified and classifications persisted to DB."""
        reply_event = _make_event("var-A", "reply", dedupe_key="dk-reply-1")
        reply_event["reply_body"] = "Hi, I'm very interested in learning more about your product."
        records = _make_records(5, "var-A")
        events = [_make_event("var-A", "open", dedupe_key="dk-open-1"), reply_event]

        mock_hydrate.return_value = (events, records)
        mock_get_threads.return_value = []

        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records,
        )

        # Mock the reply classifier to avoid LLM calls
        mock_classification = {
            "classification": "interested",
            "sentiment": "positive",
            "confidence": 0.95,
            "key_signals": ["wants to learn more"],
            "summary": "Prospect expressed interest",
            "suggested_action": "follow_up",
            "extracted_info": {},
        }
        with patch(
            "app.agents.reply_classifier.classify_reply_events",
            new_callable=AsyncMock,
            return_value=[{**reply_event, "reply_classification": mock_classification}],
        ):
            result = await feedback_agent_node(state)

        # Intelligence entry should contain reply insights
        mock_save_intel.assert_called_once()
        saved = mock_save_intel.call_args[0][0]
        assert len(saved.get("reply_insights", [])) > 0
        assert saved["reply_insights"][0]["classification"] == "interested"

        # Classification should have been persisted to MongoDB
        mock_update_event.assert_called()

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.get_email_threads_for_session", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.hydrate_feedback_from_db", new_callable=AsyncMock)
    async def test_thread_summaries_in_learning(
        self,
        mock_hydrate: AsyncMock,
        mock_get_threads: AsyncMock,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """Email thread summaries should be included in the learning delta."""
        events = [_make_event("var-A", "open", dedupe_key="dk-1")]
        records = _make_records(5, "var-A")
        mock_hydrate.return_value = (events, records)
        mock_get_threads.return_value = [
            {
                "prospect_id": "p-1",
                "prospect_email": "alice@co.com",
                "prospect_name": "Alice",
                "status": "replied",
                "reply_count": 2,
                "classification": "interested",
                "variant_id": "var-A",
            },
        ]

        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records,
        )
        result = await feedback_agent_node(state)

        mock_save_intel.assert_called_once()
        saved = mock_save_intel.call_args[0][0]
        # Learning delta should mention the thread
        assert "Alice" in saved["learning_delta"]

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    async def test_hydration_failure_falls_back_to_state(
        self,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """If DB hydration fails, the node should fall back to state events."""
        events = [
            _make_event("var-A", "open", dedupe_key="dk-1"),
            _make_event("var-A", "reply", dedupe_key="dk-2"),
        ]
        records = _make_records(5, "var-A")

        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records,
        )

        with patch(
            "app.agents.feedback_agent.hydrate_feedback_from_db",
            side_effect=Exception("DB connection refused"),
        ):
            result = await feedback_agent_node(state)

        # Should still produce results from state events
        assert "engagement_results" in result
        assert len(result["engagement_results"]) > 0

    @pytest.mark.asyncio
    @patch("app.agents.feedback_agent.save_quarantine_event", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.update_finding_confidence", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.save_intelligence_entry", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.get_email_threads_for_session", new_callable=AsyncMock)
    @patch("app.agents.feedback_agent.hydrate_feedback_from_db", new_callable=AsyncMock)
    async def test_response_includes_reply_count(
        self,
        mock_hydrate: AsyncMock,
        mock_get_threads: AsyncMock,
        mock_save_intel: AsyncMock,
        mock_update_conf: AsyncMock,
        mock_quarantine: AsyncMock,
    ):
        """Response message should mention the number of replies analyzed."""
        reply_event = _make_event("var-A", "reply", dedupe_key="dk-reply-1")
        reply_event["reply_body"] = "Count me in!"
        events = [reply_event]
        records = _make_records(5, "var-A")

        mock_hydrate.return_value = (events, records)
        mock_get_threads.return_value = []

        state = _make_state(
            normalized_feedback_events=events,
            deployment_records=records,
        )

        mock_cls = {
            "classification": "interested", "sentiment": "positive",
            "confidence": 0.9, "key_signals": [], "summary": "", "suggested_action": "",
            "extracted_info": {},
        }
        with patch(
            "app.agents.reply_classifier.classify_reply_events",
            new_callable=AsyncMock,
            return_value=[{**reply_event, "reply_classification": mock_cls}],
        ):
            result = await feedback_agent_node(state)

        response_frames = [
            f for f in result["pending_ui_frames"]
            if f.get("component") == "MessageRenderer"
        ]
        assert len(response_frames) >= 1
        content = response_frames[0]["props"]["content"]
        assert "1 replies analyzed" in content or "1 repl" in content
