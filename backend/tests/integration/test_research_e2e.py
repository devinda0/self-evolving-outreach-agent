"""End-to-end integration test for the Research Subgraph.

Tests the full flow against real MongoDB:
1. Start a campaign session via REST API
2. Seed state with research intent
3. Run the research subgraph (dispatcher → fan-out 4 threads → synthesizer)
4. Verify findings persisted in MongoDB research_findings collection
5. Verify BriefingCard UI frame emitted
6. Verify campaign state updated with briefing_summary
7. Verify failed thread graceful degradation

External APIs (Tavily search, Gemini LLM) are mocked — only MongoDB is real.

Run with:
    pytest -m integration tests/integration/test_research_e2e.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.graph import research_fan_out
from app.agents.research import (
    research_dispatcher_node,
    research_synthesizer_node,
    research_thread_node,
)
from app.db.client import close_db, connect_db, get_db
from app.db.crud import (
    create_indexes,
    get_top_findings,
    load_campaign_state,
    save_campaign_state,
)
from app.main import app

TEST_DB = "signal_to_action_test_research_e2e"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _setup_teardown():
    """Connect to a dedicated test database, create indexes, and clean up after."""
    from app.core.config import settings

    settings.DB_NAME = TEST_DB
    await connect_db()
    await create_indexes()
    yield
    db = get_db()
    await db.client.drop_database(TEST_DB)
    await close_db()


def _mock_search_results(thread_type: str) -> list[dict]:
    """Return realistic search results per thread type."""
    results_by_type = {
        "competitor": [
            {
                "title": "Competitor X launches AI-powered CRM module",
                "url": "https://techcrunch.com/competitor-x-crm",
                "content": "Competitor X today announced a new AI module for their CRM platform, targeting SMBs with pricing starting at $29/mo.",
                "score": 0.85,
            },
            {
                "title": "Top 5 CRM tools for small businesses in 2026",
                "url": "https://forbes.com/crm-tools-2026",
                "content": "Our review of the top CRM tools shows increasing competition in the SMB segment. Key players include Competitor X, Y, and Z.",
                "score": 0.78,
            },
            {
                "title": "Competitor Y raises $50M Series C",
                "url": "https://venturebeat.com/competitor-y-series-c",
                "content": "Competitor Y closed a $50M Series C round to expand their sales intelligence platform into new markets.",
                "score": 0.72,
            },
        ],
        "audience": [
            {
                "title": "Reddit: What CRM do you use for your startup?",
                "url": "https://reddit.com/r/startups/crm-thread",
                "content": "We've been struggling with data quality in our CRM. Every tool we try has the same problem — garbage in, garbage out.",
                "score": 0.82,
            },
            {
                "title": "HackerNews: The CRM problem nobody talks about",
                "url": "https://news.ycombinator.com/crm-problem",
                "content": "The real issue with CRMs is not features but adoption. Sales reps hate updating records manually.",
                "score": 0.75,
            },
        ],
        "channel": [
            {
                "title": "LinkedIn InMail benchmarks for B2B SaaS 2026",
                "url": "https://linkedin.com/business/benchmarks",
                "content": "LinkedIn InMail open rates for B2B SaaS average 38%. Cold email open rates have dropped to 22%.",
                "score": 0.80,
            },
            {
                "title": "Best channels for SaaS outreach in 2026",
                "url": "https://saasgrowth.com/channels-2026",
                "content": "Multi-channel approaches combining LinkedIn and email outperform single-channel by 3x.",
                "score": 0.70,
            },
        ],
        "market": [
            {
                "title": "Gartner: Sales intelligence market to grow 30% in 2026",
                "url": "https://gartner.com/sales-intelligence-2026",
                "content": "Gartner predicts the sales intelligence market will reach $5B by end of 2026, driven by AI adoption.",
                "score": 0.88,
            },
            {
                "title": "EU AI Act implications for sales automation tools",
                "url": "https://euai.org/sales-automation",
                "content": "New EU regulations on AI in sales automation may require transparency reports from tool vendors.",
                "score": 0.65,
            },
        ],
    }
    return results_by_type.get(thread_type, results_by_type["competitor"])


def _make_campaign_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "product_name": "Acme CRM",
        "product_description": "AI-powered CRM for small businesses",
        "target_market": "SMB founders and sales teams",
        "messages": [
            {"role": "user", "content": "research my competitors in the CRM space"},
        ],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": ["research"],
        "current_intent": "research",
        "previous_intent": None,
        "next_node": "research",
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


# ---------------------------------------------------------------------------
# 1. Full research subgraph e2e: dispatcher → fan-out → threads → synthesizer
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_research_e2e_full_pipeline():
    """Start session → run all research nodes → verify findings persisted + BriefingCard emitted."""
    session_id = "e2e-research-001"
    state = _make_campaign_state(session_id)
    await save_campaign_state(session_id, state)

    # --- Step 1: Dispatcher ---
    dispatcher_result = await research_dispatcher_node(state)
    assert set(dispatcher_result["active_thread_types"]) == {
        "competitor",
        "audience",
        "channel",
        "market",
    }
    state.update(dispatcher_result)

    # --- Step 2: Fan-out sends ---
    sends = research_fan_out(state)
    assert len(sends) == 4
    thread_types_dispatched = {s.arg["thread_type"] for s in sends}
    assert thread_types_dispatched == {"competitor", "audience", "channel", "market"}

    # --- Step 3: Run each thread (mock Tavily + Gemini, real MongoDB for caching) ---
    all_findings = []
    for send in sends:
        thread_type = send.arg["thread_type"]
        mock_results = _mock_search_results(thread_type)

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
                return_value="Extracted page content for testing.",
            ),
        ):
            thread_result = await research_thread_node(send.arg)

        findings = thread_result["research_findings"]
        assert len(findings) >= 2, f"{thread_type} thread returned < 2 findings"

        for f in findings:
            assert f["session_id"] == session_id
            assert f["cycle_number"] == 1
            assert f["thread_type"] == thread_type
            assert f["id"].startswith("rf-")
            assert 0.0 <= f["confidence"] <= 1.0
            assert f["claim"]  # non-empty
            assert "created_at" in f

        all_findings.extend(findings)

    assert len(all_findings) >= 8  # 4 threads × ≥2 findings each

    # --- Step 4: Synthesizer (real MongoDB persist) ---
    synth_state = {**state, "research_findings": all_findings}

    with patch("app.agents.research.synthesizer._get_llm", return_value=None):
        synth_result = await research_synthesizer_node(synth_state)

    # Verify briefing
    assert synth_result["briefing_summary"]
    assert len(synth_result["briefing_summary"]) > 0
    assert isinstance(synth_result["research_gaps"], list)

    # Verify BriefingCard UI frame
    assert "pending_ui_frames" in synth_result
    frames = synth_result["pending_ui_frames"]
    assert len(frames) >= 2
    assert frames[0]["component"] == "MessageRenderer"  # response message
    briefing_frame = frames[1]
    assert briefing_frame["component"] == "BriefingCard"
    assert briefing_frame["type"] == "ui_component"
    assert briefing_frame["props"]["finding_count"] >= 4  # After dedup
    assert "thread_summary" in briefing_frame["props"]
    assert len(briefing_frame["actions"]) == 3

    # Verify action IDs on BriefingCard
    action_ids = {a["id"] for a in briefing_frame["actions"]}
    assert action_ids == {"goto_segment", "goto_generate", "drill_deeper"}

    # --- Step 5: Verify findings persisted in MongoDB ---
    db_findings = await get_top_findings(session_id, k=50)
    assert len(db_findings) >= 4  # After dedup, at least one per thread type

    # Check all thread types are represented in DB
    db_thread_types = {f.get("thread_type", f.get("signal_type", "")) for f in db_findings}
    assert db_thread_types == {"competitor", "audience", "channel", "market"}

    # Check findings have required fields
    for f in db_findings:
        assert f["session_id"] == session_id
        assert "claim" in f
        assert "confidence" in f
        assert "source_url" in f


# ---------------------------------------------------------------------------
# 2. Campaign state round-trip with research results
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_research_state_persistence():
    """Verify campaign state is correctly updated after research completes."""
    session_id = "e2e-research-002"
    state = _make_campaign_state(session_id)
    await save_campaign_state(session_id, state)

    # Run dispatcher
    dispatcher_result = await research_dispatcher_node(state)
    state.update(dispatcher_result)

    # Run a single thread (competitor) — enough to prove state flow
    sends = research_fan_out(state)
    competitor_send = [s for s in sends if s.arg["thread_type"] == "competitor"][0]

    with (
        patch("app.agents.research.thread._get_llm", return_value=None),
        patch(
            "app.agents.research.thread.search_web",
            new_callable=AsyncMock,
            return_value=_mock_search_results("competitor"),
        ),
        patch(
            "app.agents.research.thread.extract_page",
            new_callable=AsyncMock,
            return_value="Page text",
        ),
    ):
        thread_result = await research_thread_node(competitor_send.arg)

    # Run synthesizer
    synth_state = {**state, "research_findings": thread_result["research_findings"]}
    with patch("app.agents.research.synthesizer._get_llm", return_value=None):
        synth_result = await research_synthesizer_node(synth_state)

    # Persist updated state
    state["briefing_summary"] = synth_result["briefing_summary"]
    state["research_gaps"] = synth_result["research_gaps"]
    state["research_findings"] = thread_result["research_findings"]
    await save_campaign_state(session_id, state)

    # Reload and verify
    loaded = await load_campaign_state(session_id)
    assert loaded is not None
    assert loaded["briefing_summary"] == synth_result["briefing_summary"]
    assert loaded["research_gaps"] == synth_result["research_gaps"]
    assert len(loaded["research_findings"]) >= 2


# ---------------------------------------------------------------------------
# 3. Failed thread graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_research_e2e_failed_thread_continues():
    """One thread fails with network error, rest continue and produce findings."""
    session_id = "e2e-research-003"
    state = _make_campaign_state(session_id)
    await save_campaign_state(session_id, state)

    dispatcher_result = await research_dispatcher_node(state)
    state.update(dispatcher_result)
    sends = research_fan_out(state)

    all_findings = []
    failed_threads = []

    for send in sends:
        thread_type = send.arg["thread_type"]

        if thread_type == "channel":
            # Simulate network failure for the channel thread
            with (
                patch("app.agents.research.thread._get_llm", return_value=None),
                patch(
                    "app.agents.research.thread.search_web",
                    new_callable=AsyncMock,
                    side_effect=Exception("Network timeout"),
                ),
            ):
                thread_result = await research_thread_node(send.arg)
        else:
            with (
                patch("app.agents.research.thread._get_llm", return_value=None),
                patch(
                    "app.agents.research.thread.search_web",
                    new_callable=AsyncMock,
                    return_value=_mock_search_results(thread_type),
                ),
                patch(
                    "app.agents.research.thread.extract_page",
                    new_callable=AsyncMock,
                    return_value="text",
                ),
            ):
                thread_result = await research_thread_node(send.arg)

        all_findings.extend(thread_result.get("research_findings", []))
        failed_threads.extend(thread_result.get("failed_threads", []))

    # Channel thread failed
    assert "channel" in failed_threads

    # Other 3 threads produced findings
    succeeded_types = {f["thread_type"] for f in all_findings}
    assert "competitor" in succeeded_types
    assert "audience" in succeeded_types
    assert "market" in succeeded_types
    assert "channel" not in succeeded_types

    assert len(all_findings) >= 6  # 3 threads × ≥2 findings

    # Synthesizer still works with partial results
    synth_state = {**state, "research_findings": all_findings, "failed_threads": failed_threads}
    with patch("app.agents.research.synthesizer._get_llm", return_value=None):
        synth_result = await research_synthesizer_node(synth_state)

    assert synth_result["briefing_summary"]
    # Index 0 is the MessageRenderer response, index 1 is the BriefingCard
    briefing_frame = synth_result["pending_ui_frames"][1]
    assert briefing_frame["props"]["failed_threads"] == ["channel"]


# ---------------------------------------------------------------------------
# 4. REST API → research subgraph: start session, verify state
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_api_start_then_research():
    """Start a campaign via REST API, then run research and verify DB state."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Start campaign
        resp = await client.post(
            "/campaign/start",
            json={
                "product_name": "Acme CRM",
                "product_description": "AI-powered CRM for SMBs",
                "target_market": "SMB founders",
            },
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # Verify initial state
        state_resp = await client.get(f"/campaign/{session_id}/state")
        assert state_resp.status_code == 200
        initial_state = state_resp.json()
        assert initial_state["product_name"] == "Acme CRM"
        assert initial_state["research_findings"] == []

    # Load state and run research
    state = await load_campaign_state(session_id)
    state["current_intent"] = "research"
    state["next_node"] = "research"

    dispatcher_result = await research_dispatcher_node(state)
    state.update(dispatcher_result)
    sends = research_fan_out(state)

    all_findings = []
    for send in sends:
        thread_type = send.arg["thread_type"]
        with (
            patch("app.agents.research.thread._get_llm", return_value=None),
            patch(
                "app.agents.research.thread.search_web",
                new_callable=AsyncMock,
                return_value=_mock_search_results(thread_type),
            ),
            patch(
                "app.agents.research.thread.extract_page",
                new_callable=AsyncMock,
                return_value="text",
            ),
        ):
            thread_result = await research_thread_node(send.arg)
        all_findings.extend(thread_result["research_findings"])

    synth_state = {**state, "research_findings": all_findings}
    with patch("app.agents.research.synthesizer._get_llm", return_value=None):
        synth_result = await research_synthesizer_node(synth_state)

    # Persist updated state
    state["briefing_summary"] = synth_result["briefing_summary"]
    state["research_findings"] = all_findings
    state["active_stage_summary"] = synth_result["active_stage_summary"]
    await save_campaign_state(session_id, state)

    # Verify via REST API that state is updated
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        state_resp = await client.get(f"/campaign/{session_id}/state")
        assert state_resp.status_code == 200
        final_state = state_resp.json()

    assert final_state["briefing_summary"]
    assert len(final_state["research_findings"]) >= 8
    assert final_state["active_stage_summary"] == "research complete — briefing ready"

    # Verify findings in dedicated collection
    db_findings = await get_top_findings(session_id, k=50)
    assert len(db_findings) >= 4


# ---------------------------------------------------------------------------
# 5. Policy enforcement: max_pages_to_extract respected end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_research_e2e_policy_enforcement():
    """Verify the max_pages_to_extract policy is respected across full pipeline."""
    session_id = "e2e-research-005"
    strict_policy = {
        "enabled_threads": ["competitor"],
        "max_search_results_per_query": 3,
        "max_pages_to_extract": 1,
        "max_branch_depth": 1,
        "max_subinvestigations_per_thread": 1,
        "recency_days": 14,
        "allowed_tool_groups": ["search_discovery"],
        "evidence_threshold": 0.8,
    }
    state = _make_campaign_state(session_id)
    state["research_policy"] = strict_policy
    await save_campaign_state(session_id, state)

    # Dispatcher should only dispatch competitor thread
    dispatcher_result = await research_dispatcher_node(state)
    assert dispatcher_result["active_thread_types"] == ["competitor"]
    state.update(dispatcher_result)

    sends = research_fan_out(state)
    assert len(sends) == 1

    extract_mock = AsyncMock(return_value="Extracted content")
    with (
        patch("app.agents.research.thread._get_llm", return_value=None),
        patch(
            "app.agents.research.thread.search_web",
            new_callable=AsyncMock,
            return_value=_mock_search_results("competitor"),
        ),
        patch("app.agents.research.thread.extract_page", extract_mock),
    ):
        thread_result = await research_thread_node(sends[0].arg)

    # Only 1 page should have been extracted (policy limit)
    assert extract_mock.call_count <= 1
    assert len(thread_result["research_findings"]) >= 2


# ---------------------------------------------------------------------------
# 6. Deduplication across threads
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_research_e2e_deduplication():
    """Verify that duplicate findings across threads are deduplicated by synthesizer."""
    session_id = "e2e-research-006"
    state = _make_campaign_state(session_id)

    # Create findings with duplicate claims across threads
    findings = [
        {
            "claim": "AI CRM market growing rapidly",
            "confidence": 0.85,
            "thread_type": "competitor",
            "evidence": "TechCrunch report",
            "source_url": "https://tc.com/1",
            "actionable_implication": "Act fast",
            "id": "rf-dup-1",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "competitor",
            "created_at": "2026-04-08T00:00:00Z",
        },
        {
            "claim": "AI CRM market growing rapidly",  # Same claim, different thread
            "confidence": 0.70,
            "thread_type": "market",
            "evidence": "Gartner forecast",
            "source_url": "https://gartner.com/1",
            "actionable_implication": "Market validation",
            "id": "rf-dup-2",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "market",
            "created_at": "2026-04-08T00:00:00Z",
        },
        {
            "claim": "Sales reps hate manual CRM updates",
            "confidence": 0.78,
            "thread_type": "audience",
            "evidence": "Reddit threads",
            "source_url": "https://reddit.com/r/sales",
            "actionable_implication": "Lead with automation angle",
            "id": "rf-dup-3",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "audience",
            "created_at": "2026-04-08T00:00:00Z",
        },
    ]

    synth_state = {**state, "research_findings": findings}
    with patch("app.agents.research.synthesizer._get_llm", return_value=None):
        synth_result = await research_synthesizer_node(synth_state)

    # Should have 2 unique findings (duplicate "AI CRM market..." kept with higher confidence)
    # Index 0 is the MessageRenderer response, index 1 is the BriefingCard
    assert synth_result["pending_ui_frames"][1]["props"]["finding_count"] == 2

    # The kept duplicate should be the one with 0.85 (higher confidence)
    db_findings = await get_top_findings(session_id, k=50)
    ai_crm_findings = [f for f in db_findings if "AI CRM" in f.get("claim", "")]
    assert len(ai_crm_findings) == 1
    assert ai_crm_findings[0]["confidence"] == 0.85
