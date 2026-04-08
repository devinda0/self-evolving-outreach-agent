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
    aggregate_engagement_results,
    build_ab_results_frame,
    build_cycle_summary_frame,
    build_feedback_prompt_frame,
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
        events = (
            [_make_event("var-A", "open") for _ in range(3)]
            + [_make_event("var-B", "reply") for _ in range(2)]
        )
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
        events = (
            [_make_event("var-A", "open") for _ in range(3)]
            + [_make_event("var-B", "open") for _ in range(3)]
        )
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

    def test_cycle_summary_frame_structure(self):
        frame = build_cycle_summary_frame("Learning delta text", None, 2, "instance-2")
        assert frame["component"] == "CycleSummary"
        assert frame["props"]["cycle_number"] == 2
        assert frame["props"]["learning_delta"] == "Learning delta text"
        assert len(frame["actions"]) >= 1

    def test_feedback_prompt_frame_structure(self):
        frame = build_feedback_prompt_frame("instance-3")
        assert frame["component"] == "FeedbackPrompt"
        assert len(frame["actions"]) >= 1


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

        # Cycle advanced
        assert result["cycle_number"] == 2
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
