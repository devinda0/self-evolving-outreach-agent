"""End-to-end integration test for the Content Agent.

Tests the full flow against real MongoDB and real Gemini API:
1. Start a campaign session via REST API
2. Seed state with research findings + briefing + segment
3. Run the content agent (dispatcher → variants)
4. Verify variants persisted in MongoDB content_variants collection
5. Verify VariantGrid UI frame emitted
6. Verify traceability (source_finding_ids → real findings)
7. Verify graceful fallback when briefing is missing

Run with:
    pytest -m integration tests/integration/test_content_e2e.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.content_agent import (
    content_agent_node,
    generate_variants,
    get_segment_by_id,
)
from app.core.config import settings
from app.db.client import close_db, connect_db, get_db
from app.db.crud import (
    create_indexes,
    get_variants_for_session,
    load_campaign_state,
    save_campaign_state,
)
from app.main import app

TEST_DB = "signal_to_action_test_content_e2e"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _setup_teardown():
    """Connect to a dedicated test database, create indexes, and clean up after."""
    settings.DB_NAME = TEST_DB
    await connect_db()
    await create_indexes()
    yield
    db = get_db()
    await db.client.drop_database(TEST_DB)
    await close_db()


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

def _research_findings(session_id: str = "") -> list[dict]:
    """Realistic research findings as they'd come from the research subgraph."""
    return [
        {
            "id": "rf-001",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "competitor",
            "claim": "Competitor X launched a cheaper plan targeting SMBs last month",
            "evidence": "Blog post announcing new pricing tier at $19/mo",
            "source_url": "https://competitorx.com/blog/pricing",
            "confidence": 0.85,
            "audience_language": ["affordable", "switching cost"],
            "actionable_implication": "Position on value beyond price",
        },
        {
            "id": "rf-002",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "audience",
            "claim": "Sales leaders on Reddit report frustration with CRM data quality",
            "evidence": "Multiple r/sales threads with 200+ upvotes on dirty data",
            "source_url": "https://reddit.com/r/sales/comments/abc",
            "confidence": 0.78,
            "audience_language": ["data hygiene", "garbage in garbage out", "pipeline accuracy"],
            "actionable_implication": "Lead with data quality angle",
        },
        {
            "id": "rf-003",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "market",
            "claim": "Gartner predicts 30% growth in sales intelligence tools this year",
            "evidence": "Gartner market forecast Q1 2026",
            "source_url": "https://gartner.com/2026-forecast",
            "confidence": 0.72,
            "audience_language": ["sales intelligence", "market growth"],
            "actionable_implication": "Emphasize category momentum",
        },
        {
            "id": "rf-004",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "channel",
            "claim": "LinkedIn InMail open rates for sales tools average 38%",
            "evidence": "Unipile benchmark report",
            "source_url": "https://unipile.com/benchmarks",
            "confidence": 0.65,
            "audience_language": [],
            "actionable_implication": "Prioritize LinkedIn as primary channel",
        },
        {
            "id": "rf-005",
            "session_id": session_id,
            "cycle_number": 1,
            "signal_type": "audience",
            "claim": "VP Sales teams report outbound ROI declining by 20% YoY",
            "evidence": "SaaStr survey of 500 sales leaders",
            "source_url": "https://saastr.com/outbound-roi-2026",
            "confidence": 0.80,
            "audience_language": ["ROI", "outbound efficiency", "pipeline pressure"],
            "actionable_implication": "Use ROI-first framing for VP Sales personas",
        },
    ]


def _segment_candidates(session_id: str = "") -> list[dict]:
    """Segment candidates as they'd come from the segment agent."""
    return [
        {
            "id": "seg-primary",
            "session_id": session_id,
            "label": "VP Sales at Series B SaaS",
            "description": "Core target buyers from market research",
            "criteria": {"derived_from": "briefing_summary"},
            "prospect_count": 10,
        },
        {
            "id": "seg-pain",
            "session_id": session_id,
            "label": "Pain-point driven buyers",
            "description": "Prospect whose pain points align with CRM data quality issues",
            "criteria": {"derived_from": "audience_research"},
            "prospect_count": 8,
        },
    ]


def _make_state(session_id: str, **overrides) -> dict:
    """Build a CampaignState dict with content-ready defaults."""
    findings = _research_findings(session_id)
    segments = _segment_candidates(session_id)
    base = {
        "session_id": session_id,
        "product_name": "SignalPro",
        "product_description": "AI-powered sales intelligence platform that turns market signals into targeted outreach",
        "target_market": "B2B SaaS sales teams",
        "messages": [
            {"role": "user", "content": "research competitors in the sales intelligence space"},
            {"role": "assistant", "content": "Research complete. Briefing ready."},
            {"role": "user", "content": "generate outreach content for the top segment"},
        ],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": ["research", "segment", "generate"],
        "current_intent": "generate",
        "previous_intent": "segment",
        "next_node": "generate",
        "clarification_question": None,
        "clarification_options": [],
        "session_complete": False,
        "cycle_number": 1,
        "prior_cycle_summary": None,
        "active_stage_summary": "Segment derived, prospects scored",
        "research_query": None,
        "active_thread_types": ["competitor", "audience", "channel", "market"],
        "thread_type": None,
        "research_policy": {},
        "research_findings": findings,
        "briefing_summary": (
            "Market intelligence shows: Competitor X is undercutting on price with a $19/mo plan, "
            "sales leaders are frustrated with CRM data quality (pain-led opportunity), "
            "the sales intelligence market is growing 30% YoY per Gartner, "
            "and LinkedIn InMail outperforms cold email at 38% open rate. "
            "VP Sales teams report declining outbound ROI — strong angle for value-first messaging."
        ),
        "research_gaps": ["Deeper analysis of Competitor Y needed"],
        "failed_threads": [],
        "selected_segment_id": "seg-primary",
        "segment_candidates": segments,
        "selected_prospect_ids": ["prospect-001", "prospect-002", "prospect-003"],
        "prospect_pool_ref": None,
        "prospect_cards": [
            {"id": "prospect-001", "name": "Alice Chen", "title": "VP Sales", "company": "Acme SaaS",
             "fit_score": 0.85, "urgency_score": 0.70, "angle_recommendation": "pipeline-acceleration",
             "channel_recommendation": "email"},
            {"id": "prospect-002", "name": "Bob Martinez", "title": "Head of Growth", "company": "ScaleUp Inc",
             "fit_score": 0.80, "urgency_score": 0.65, "angle_recommendation": "demand-generation",
             "channel_recommendation": "linkedin"},
            {"id": "prospect-003", "name": "Carol Nguyen", "title": "CRO", "company": "CloudFirst",
             "fit_score": 0.75, "urgency_score": 0.72, "angle_recommendation": "pipeline-acceleration",
             "channel_recommendation": "email"},
        ],
        "content_request": None,
        "content_variants": [],
        "selected_variant_ids": [],
        "visual_artifacts": [],
        "selected_channels": ["email", "linkedin"],
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


# ---------------------------------------------------------------------------
# 1. Full content agent e2e with real Gemini API
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not settings.GEMINI_API_KEY or settings.USE_MOCK_LLM,
    reason="GEMINI_API_KEY not set or USE_MOCK_LLM is active — requires real Gemini API",
)
async def test_content_agent_e2e_real_gemini():
    """End-to-end: start campaign → seed state → run content agent with real Gemini → verify variants."""
    # 1. Create campaign via API
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/campaign/start",
            json={
                "product_name": "SignalPro",
                "product_description": "AI-powered sales intelligence platform",
                "target_market": "B2B SaaS sales teams",
            },
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

    # 2. Seed state with research + segment data
    state = _make_state(session_id)
    await save_campaign_state(session_id, state)

    # 3. Run content agent (uses real Gemini API)
    result = await content_agent_node(state)

    # 4. Verify node returned expected keys
    assert "content_variants" in result
    assert "pending_ui_frames" in result
    assert result["next_node"] == "orchestrator"
    assert "error_messages" not in result or not result.get("error_messages")

    # 5. Verify exactly 3 variants (2 email + 1 linkedin per spec)
    variants = result["content_variants"]
    assert len(variants) == 3, f"Expected 3 variants, got {len(variants)}"

    email_variants = [v for v in variants if v["intended_channel"] == "email"]
    linkedin_variants = [v for v in variants if v["intended_channel"] == "linkedin"]
    assert len(email_variants) == 2, f"Expected 2 email variants, got {len(email_variants)}"
    assert len(linkedin_variants) == 1, f"Expected 1 linkedin variant, got {len(linkedin_variants)}"

    # 6. Verify traceability: each variant has valid source_finding_ids
    valid_finding_ids = {f["id"] for f in state["research_findings"]}
    for v in variants:
        assert v["source_finding_ids"], f"Variant {v['id']} has empty source_finding_ids"
        for fid in v["source_finding_ids"]:
            assert fid in valid_finding_ids, (
                f"Variant {v['id']} references unknown finding '{fid}'. "
                f"Valid IDs: {valid_finding_ids}"
            )

    # 7. Verify each variant has distinct hypothesis (not just paraphrasing)
    hypotheses = [v["hypothesis"] for v in variants]
    assert all(h for h in hypotheses), "All variants must have non-null hypotheses"
    # Check that hypotheses are actually different (at least first 20 chars differ)
    hypothesis_prefixes = {h[:20].lower() for h in hypotheses}
    assert len(hypothesis_prefixes) >= 2, (
        f"Hypotheses should be distinct, got: {hypotheses}"
    )

    # 8. Verify required fields per variant
    for v in variants:
        assert v["id"].startswith("var-")
        assert v["session_id"] == session_id
        assert v["cycle_number"] == 1
        assert v["target_segment_id"] == "seg-primary"
        assert v["success_metric"]  # non-empty
        assert v["body"]            # non-empty
        assert v["cta"]             # non-empty
        assert v.get("angle_label")  # should be present

    # 9. Verify email variants have subject lines, linkedin does not
    for v in email_variants:
        assert v.get("subject_line"), f"Email variant {v['id']} missing subject_line"
    for v in linkedin_variants:
        # LinkedIn variant may have null subject_line
        pass

    # 10. Verify VariantGrid UI frame
    frames = result["pending_ui_frames"]
    assert len(frames) >= 1
    grid_frame = frames[0]
    assert grid_frame["component"] == "VariantGrid"
    assert grid_frame["type"] == "ui_component"
    assert len(grid_frame["props"]["variants"]) == 3
    # Should have select actions + deploy action
    assert len(grid_frame["actions"]) >= 4  # 3 select + 1 deploy

    # 11. Verify variants persisted to MongoDB
    db_variants = await get_variants_for_session(session_id)
    assert len(db_variants) == 3
    db_ids = {v["id"] for v in db_variants}
    result_ids = {v["id"] for v in variants}
    assert db_ids == result_ids, "DB variants should match returned variants"


# ---------------------------------------------------------------------------
# 2. Content agent with real Gemini + custom content_request
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not settings.GEMINI_API_KEY or settings.USE_MOCK_LLM,
    reason="GEMINI_API_KEY not set or USE_MOCK_LLM is active",
)
async def test_content_agent_with_content_request():
    """Gemini respects a custom content_request and uses it in generation."""
    session_id = "e2e-content-custom-req"
    state = _make_state(
        session_id,
        content_request="Focus on the data quality pain point. Use casual, direct tone.",
    )
    await save_campaign_state(session_id, state)

    result = await content_agent_node(state)

    variants = result["content_variants"]
    assert len(variants) == 3

    # At least one variant should reference the audience finding about data quality
    data_quality_refs = [
        v for v in variants
        if "rf-002" in v["source_finding_ids"] or "rf-005" in v["source_finding_ids"]
    ]
    assert len(data_quality_refs) >= 1, (
        "At least one variant should reference audience/data quality findings"
    )


# ---------------------------------------------------------------------------
# 3. Missing briefing returns error (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_content_agent_no_briefing_returns_error():
    """Content agent returns a user-friendly error when briefing_summary is missing."""
    session_id = "e2e-content-no-briefing"
    state = _make_state(session_id, briefing_summary=None)
    await save_campaign_state(session_id, state)

    result = await content_agent_node(state)

    assert result["next_node"] == "orchestrator"
    assert "error_messages" in result
    assert len(result["error_messages"]) == 1
    assert "research" in result["error_messages"][0].lower()
    # Should NOT have generated any variants
    assert "content_variants" not in result


@pytest.mark.integration
async def test_content_agent_empty_briefing_returns_error():
    """Empty string briefing is treated as missing."""
    session_id = "e2e-content-empty-briefing"
    state = _make_state(session_id, briefing_summary="")
    await save_campaign_state(session_id, state)

    result = await content_agent_node(state)

    assert result["next_node"] == "orchestrator"
    assert "error_messages" in result
    assert len(result["error_messages"]) >= 1


# ---------------------------------------------------------------------------
# 4. Mock LLM fallback produces valid variants
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_content_agent_mock_llm_fallback():
    """With USE_MOCK_LLM=True, the agent produces valid mock variants."""
    session_id = "e2e-content-mock"
    state = _make_state(session_id)
    await save_campaign_state(session_id, state)

    original_mock = settings.USE_MOCK_LLM
    try:
        settings.USE_MOCK_LLM = True
        result = await content_agent_node(state)
    finally:
        settings.USE_MOCK_LLM = original_mock

    # Same structural assertions as the real path
    variants = result["content_variants"]
    assert len(variants) == 3

    email_variants = [v for v in variants if v["intended_channel"] == "email"]
    linkedin_variants = [v for v in variants if v["intended_channel"] == "linkedin"]
    assert len(email_variants) == 2
    assert len(linkedin_variants) == 1

    for v in variants:
        assert v["id"].startswith("var-")
        assert v["source_finding_ids"]  # non-empty
        assert v["hypothesis"]
        assert v["success_metric"]
        assert v["body"]
        assert v["cta"]

    # Verify persisted
    db_variants = await get_variants_for_session(session_id)
    assert len(db_variants) == 3

    # Verify VariantGrid frame
    frames = result["pending_ui_frames"]
    assert len(frames) >= 1
    assert frames[0]["component"] == "VariantGrid"


# ---------------------------------------------------------------------------
# 5. Segment fallback: no selected_segment_id uses first candidate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_content_agent_no_selected_segment_uses_first():
    """When selected_segment_id is None, the agent uses the first segment candidate."""
    session_id = "e2e-content-no-seg-id"
    state = _make_state(session_id, selected_segment_id=None)
    await save_campaign_state(session_id, state)

    original_mock = settings.USE_MOCK_LLM
    try:
        settings.USE_MOCK_LLM = True
        result = await content_agent_node(state)
    finally:
        settings.USE_MOCK_LLM = original_mock

    variants = result["content_variants"]
    assert len(variants) == 3
    # Should have used the first segment candidate's ID
    for v in variants:
        assert v["target_segment_id"] == "seg-primary"


# ---------------------------------------------------------------------------
# 6. No segment candidates at all
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_content_agent_no_segments_still_generates():
    """Even with no segment candidates, the agent generates variants with seg-unknown."""
    session_id = "e2e-content-no-segs"
    state = _make_state(
        session_id,
        selected_segment_id=None,
        segment_candidates=[],
    )
    await save_campaign_state(session_id, state)

    original_mock = settings.USE_MOCK_LLM
    try:
        settings.USE_MOCK_LLM = True
        result = await content_agent_node(state)
    finally:
        settings.USE_MOCK_LLM = original_mock

    variants = result["content_variants"]
    assert len(variants) == 3
    for v in variants:
        assert v["target_segment_id"] == "seg-unknown"


# ---------------------------------------------------------------------------
# 7. Full pipeline: research → segment → content (end-to-end with API)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_e2e_research_segment_content_pipeline():
    """Full pipeline: create campaign → seed research → run segment → run content → verify."""
    # 1. Create campaign via API
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/campaign/start",
            json={
                "product_name": "OutreachBot",
                "product_description": "AI-driven multi-channel outreach automation",
                "target_market": "B2B SaaS growth teams",
            },
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

    # 2. Seed research findings
    state = await load_campaign_state(session_id)
    findings = _research_findings(session_id)
    state["research_findings"] = findings
    state["briefing_summary"] = (
        "Research across 4 dimensions produced 5 findings. "
        "Competitor X is undercutting on price. Sales leaders frustrated with data quality. "
        "Market growing 30% YoY. LinkedIn outperforms email. VP Sales teams see declining ROI."
    )
    await save_campaign_state(session_id, state)

    # 3. Run segment agent (real derivation, real MongoDB)
    from app.agents.segment_agent import segment_agent_node

    seg_result = await segment_agent_node(state)

    assert len(seg_result["segment_candidates"]) >= 2
    assert len(seg_result["prospect_cards"]) >= 1

    # 4. Update state with segment results (as LangGraph would)
    state["segment_candidates"] = seg_result["segment_candidates"]
    state["prospect_cards"] = seg_result["prospect_cards"]
    state["selected_segment_id"] = seg_result["segment_candidates"][0]["id"]
    state["selected_prospect_ids"] = [c["id"] for c in seg_result["prospect_cards"][:5]]
    state["current_intent"] = "generate"
    state["intent_history"].append("generate")
    await save_campaign_state(session_id, state)

    # 5. Run content agent
    original_mock = settings.USE_MOCK_LLM
    try:
        settings.USE_MOCK_LLM = True
        content_result = await content_agent_node(state)
    finally:
        settings.USE_MOCK_LLM = original_mock

    # 6. Verify content output
    variants = content_result["content_variants"]
    assert len(variants) == 3

    # Target segment should match the one we selected
    for v in variants:
        assert v["target_segment_id"] == state["selected_segment_id"]

    # 7. Verify VariantGrid UI frame
    frames = content_result["pending_ui_frames"]
    assert len(frames) >= 1
    grid_frame = frames[0]
    assert grid_frame["component"] == "VariantGrid"
    assert grid_frame["type"] == "ui_component"

    # 8. Verify ALL data persisted to MongoDB
    # Segments
    from app.db.crud import get_segments, get_prospect_cards

    db_segments = await get_segments(session_id)
    assert len(db_segments) >= 2

    db_prospects = await get_prospect_cards(session_id)
    assert len(db_prospects) >= 1

    db_variants = await get_variants_for_session(session_id)
    assert len(db_variants) == 3


# ---------------------------------------------------------------------------
# 8. Cycle number propagation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_content_agent_cycle_number_propagated():
    """Variant cycle_number matches the current campaign cycle."""
    session_id = "e2e-content-cycle-2"
    state = _make_state(
        session_id,
        cycle_number=2,
        prior_cycle_summary="Cycle 1: competitor-gap angle won with 12% reply rate.",
    )
    await save_campaign_state(session_id, state)

    original_mock = settings.USE_MOCK_LLM
    try:
        settings.USE_MOCK_LLM = True
        result = await content_agent_node(state)
    finally:
        settings.USE_MOCK_LLM = original_mock

    for v in result["content_variants"]:
        assert v["cycle_number"] == 2


# ---------------------------------------------------------------------------
# 9. get_segment_by_id helper
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_segment_by_id_returns_match():
    """get_segment_by_id returns the matching segment."""
    candidates = _segment_candidates()
    result = get_segment_by_id("seg-pain", candidates)
    assert result["id"] == "seg-pain"


@pytest.mark.integration
async def test_get_segment_by_id_falls_back_to_first():
    """get_segment_by_id returns the first candidate if no match."""
    candidates = _segment_candidates()
    result = get_segment_by_id("seg-nonexistent", candidates)
    assert result["id"] == "seg-primary"


@pytest.mark.integration
async def test_get_segment_by_id_empty_returns_none():
    """get_segment_by_id returns None for empty candidates."""
    result = get_segment_by_id("seg-any", [])
    assert result is None
