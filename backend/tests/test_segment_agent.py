"""Tests for the segment agent — segment derivation, prospect loading, scoring, and UI frames."""

from app.agents.segment_agent import (
    DEMO_SEED_PROSPECTS,
    build_prospect_card,
    build_prospect_picker_frame,
    build_segment_selector_frame,
    calculate_fit_score,
    calculate_urgency_score,
    derive_segments,
    load_prospects,
    load_prospects_from_csv_bytes,
    recommend_angle,
    recommend_channel,
    score_prospects,
)
from app.models.prospect import Segment

# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

def _make_segment(**overrides) -> Segment:
    defaults = {
        "id": "seg-test-1",
        "session_id": "test-session",
        "label": "Test segment",
        "description": "A test segment",
        "criteria": {"derived_from": "briefing_summary", "signal_types": ["competitor"]},
        "prospect_count": 0,
    }
    defaults.update(overrides)
    return Segment(**defaults)


def _make_findings(count: int = 3, signal_type: str = "competitor") -> list[dict]:
    return [
        {
            "claim": f"Finding {i}",
            "confidence": 0.5 + i * 0.1,
            "signal_type": signal_type,
        }
        for i in range(count)
    ]


def _make_prospect(**overrides) -> dict:
    base = {
        "name": "Test Person",
        "email": "test@example.com",
        "linkedin_url": "https://linkedin.com/in/testperson",
        "title": "VP Sales",
        "company": "TestCorp",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Segment derivation
# ---------------------------------------------------------------------------

class TestDeriveSegments:
    async def test_derives_at_least_2_segments(self):
        segments = await derive_segments(
            briefing_summary="Market is growing. Competitors are slow.",
            research_findings=_make_findings(3, "competitor"),
            product_name="TestProd",
        )
        assert len(segments) >= 2
        assert all(isinstance(s, Segment) for s in segments)

    async def test_derives_segments_with_empty_findings(self):
        segments = await derive_segments(
            briefing_summary=None,
            research_findings=[],
            product_name="TestProd",
        )
        assert len(segments) >= 2

    async def test_audience_signal_creates_pain_segment(self):
        findings = _make_findings(2, "audience")
        segments = await derive_segments(
            briefing_summary="Users complain about X",
            research_findings=findings,
            product_name="TestProd",
        )
        labels = [s.label for s in segments]
        assert any("pain" in lbl.lower() or "Pain" in lbl for lbl in labels)

    async def test_competitor_signal_creates_displacement_segment(self):
        findings = _make_findings(2, "competitor")
        segments = await derive_segments(
            briefing_summary="Competitor launched new feature",
            research_findings=findings,
            product_name="TestProd",
        )
        labels = [s.label for s in segments]
        assert any("competitive" in lbl.lower() or "displacement" in lbl.lower() for lbl in labels)

    async def test_mixed_signals(self):
        findings = [
            {"claim": "Audience pain", "confidence": 0.8, "signal_type": "audience"},
            {"claim": "Competitor weakness", "confidence": 0.7, "signal_type": "competitor"},
            {"claim": "Market trend", "confidence": 0.6, "signal_type": "market"},
        ]
        segments = await derive_segments(
            briefing_summary="Mixed signals",
            research_findings=findings,
            product_name="TestProd",
        )
        # Should get primary + audience pain + competitor displacement = 3
        assert len(segments) >= 3


# ---------------------------------------------------------------------------
# Prospect loading
# ---------------------------------------------------------------------------

class TestLoadProspects:
    async def test_no_ref_loads_demo_seed(self):
        prospects = await load_prospects(None)
        assert len(prospects) == len(DEMO_SEED_PROSPECTS)
        assert prospects[0]["name"] == "Alice Chen"

    async def test_invalid_ref_falls_back_to_seed(self):
        prospects = await load_prospects("nonexistent.csv")
        assert len(prospects) == len(DEMO_SEED_PROSPECTS)

    async def test_csv_bytes_parsing(self):
        csv_content = b"name,email,linkedin_url,title,company\nJane Doe,jane@co.io,,CTO,TechCo\n"
        prospects = await load_prospects_from_csv_bytes(csv_content)
        assert len(prospects) == 1
        assert prospects[0]["name"] == "Jane Doe"
        assert prospects[0]["title"] == "CTO"
        assert prospects[0]["email"] == "jane@co.io"
        assert prospects[0]["linkedin_url"] is None

    async def test_csv_bytes_multiple_rows(self):
        csv_content = (
            b"name,email,linkedin_url,title,company\n"
            b"Alice,alice@a.com,https://li.com/alice,VP Sales,AcmeCo\n"
            b"Bob,bob@b.com,,Head of Growth,BobCorp\n"
            b"Carol,,https://li.com/carol,CRO,CarolInc\n"
        )
        prospects = await load_prospects_from_csv_bytes(csv_content)
        assert len(prospects) == 3
        assert prospects[2]["email"] is None
        assert prospects[1]["linkedin_url"] is None

    async def test_csv_bytes_empty(self):
        prospects = await load_prospects_from_csv_bytes(b"name,email,linkedin_url,title,company\n")
        assert len(prospects) == 0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestFitScore:
    def test_leadership_title_boosts_score(self):
        seg = _make_segment()
        vp = _make_prospect(title="VP Sales")
        analyst = _make_prospect(title="Junior Analyst")
        assert calculate_fit_score(vp, seg) > calculate_fit_score(analyst, seg)

    def test_audience_segment_boosts_sales_titles(self):
        seg = _make_segment(criteria={"derived_from": "audience_research"})
        sales = _make_prospect(title="Head of Growth")
        engineer = _make_prospect(title="Software Engineer")
        assert calculate_fit_score(sales, seg) > calculate_fit_score(engineer, seg)

    def test_competitor_segment_boosts_decision_makers(self):
        seg = _make_segment(criteria={"derived_from": "competitor_research"})
        director = _make_prospect(title="Director of Sales")
        intern = _make_prospect(title="Intern")
        assert calculate_fit_score(director, seg) > calculate_fit_score(intern, seg)

    def test_score_in_range(self):
        seg = _make_segment()
        prospect = _make_prospect(title="CEO and Founder")
        score = calculate_fit_score(prospect, seg)
        assert 0.0 <= score <= 1.0


class TestUrgencyScore:
    def test_no_findings_returns_base(self):
        score = calculate_urgency_score(_make_prospect(), [])
        assert score == 0.3

    def test_high_confidence_boosts_urgency(self):
        high = [{"confidence": 0.9, "signal_type": "competitor"}]
        low = [{"confidence": 0.3, "signal_type": "competitor"}]
        assert calculate_urgency_score(_make_prospect(), high) > calculate_urgency_score(
            _make_prospect(), low
        )

    def test_temporal_signal_boosts_urgency(self):
        without_temporal = [{"confidence": 0.7, "signal_type": "competitor"}]
        with_temporal = [
            {"confidence": 0.7, "signal_type": "competitor"},
            {"confidence": 0.7, "signal_type": "temporal"},
        ]
        assert calculate_urgency_score(_make_prospect(), with_temporal) > calculate_urgency_score(
            _make_prospect(), without_temporal
        )

    def test_score_in_range(self):
        findings = _make_findings(5, "market")
        score = calculate_urgency_score(_make_prospect(), findings)
        assert 0.0 <= score <= 1.0


class TestRecommendAngle:
    def test_sales_title(self):
        assert recommend_angle({"title": "VP Sales"}, []) == "pipeline-acceleration"

    def test_marketing_title(self):
        assert recommend_angle({"title": "CMO"}, []) == "demand-generation"

    def test_ceo_title(self):
        assert recommend_angle({"title": "CEO"}, []) == "strategic-vision"

    def test_technical_title(self):
        assert recommend_angle({"title": "CTO"}, []) == "technical-differentiation"

    def test_unknown_title(self):
        assert recommend_angle({"title": "Office Manager"}, []) == "value-proposition"


class TestRecommendChannel:
    def test_prefers_linkedin_when_available(self):
        seg = _make_segment()
        p = _make_prospect(linkedin_url="https://linkedin.com/in/test")
        assert recommend_channel(p, seg) == "linkedin"

    def test_falls_back_to_email(self):
        seg = _make_segment()
        p = _make_prospect(linkedin_url=None, email="test@test.com")
        assert recommend_channel(p, seg) == "email"

    def test_default_email(self):
        seg = _make_segment()
        p = _make_prospect(linkedin_url=None, email=None)
        assert recommend_channel(p, seg) == "email"


class TestScoreProspects:
    async def test_returns_scored_with_all_fields(self):
        segments = [_make_segment()]
        prospects = [_make_prospect()]
        findings = _make_findings(3)

        scored = await score_prospects(prospects, segments, findings)

        assert len(scored) == 1
        p = scored[0]
        assert "id" in p
        assert "fit_score" in p
        assert "urgency_score" in p
        assert "angle_recommendation" in p
        assert "channel_recommendation" in p
        assert 0.0 <= p["fit_score"] <= 1.0
        assert 0.0 <= p["urgency_score"] <= 1.0

    async def test_sorted_by_combined_score(self):
        segments = [_make_segment()]
        prospects = [
            _make_prospect(name="Junior", title="Junior Analyst"),
            _make_prospect(name="VP", title="VP Sales"),
        ]
        findings = _make_findings(3)

        scored = await score_prospects(prospects, segments, findings)

        # VP Sales should score higher and appear first
        assert scored[0]["name"] == "VP"

    async def test_demo_seed_all_scored(self):
        segments = [_make_segment()]
        findings = _make_findings(3)

        scored = await score_prospects(DEMO_SEED_PROSPECTS, segments, findings)

        assert len(scored) == len(DEMO_SEED_PROSPECTS)
        for p in scored:
            assert 0.0 <= p["fit_score"] <= 1.0
            assert 0.0 <= p["urgency_score"] <= 1.0


# ---------------------------------------------------------------------------
# Prospect cards
# ---------------------------------------------------------------------------

class TestBuildProspectCard:
    def test_card_has_required_fields(self):
        scored = {
            "id": "p-1",
            "name": "Alice",
            "title": "VP Sales",
            "company": "Acme",
            "fit_score": 0.8,
            "urgency_score": 0.6,
            "angle_recommendation": "pipeline-acceleration",
            "channel_recommendation": "email",
        }
        card = build_prospect_card(scored)
        assert card["id"] == "p-1"
        assert card["name"] == "Alice"
        assert card["fit_score"] == 0.8
        assert card["angle_recommendation"] == "pipeline-acceleration"

    def test_card_is_compact(self):
        """Card should not contain email/linkedin — those are full prospect fields."""
        scored = {
            "id": "p-1",
            "name": "Alice",
            "email": "alice@test.com",
            "linkedin_url": "https://li.com/alice",
            "title": "VP",
            "company": "Corp",
            "fit_score": 0.7,
            "urgency_score": 0.5,
            "angle_recommendation": "value-proposition",
            "channel_recommendation": "email",
            "personalization_fields": {},
        }
        card = build_prospect_card(scored)
        assert "email" not in card
        assert "linkedin_url" not in card
        assert "personalization_fields" not in card


# ---------------------------------------------------------------------------
# UI frames
# ---------------------------------------------------------------------------

class TestUIFrames:
    def test_segment_selector_frame(self):
        segments = [
            _make_segment(id="seg-1", label="Segment A"),
            _make_segment(id="seg-2", label="Segment B"),
        ]
        frame = build_segment_selector_frame(segments, "inst-1")
        assert frame["type"] == "ui_component"
        assert frame["component"] == "SegmentSelector"
        assert len(frame["props"]["segments"]) == 2
        assert len(frame["actions"]) == 2
        assert frame["actions"][0]["action_type"] == "select_segment"

    def test_prospect_picker_frame(self):
        cards = [{"id": "p-1", "name": "Alice", "fit_score": 0.8}]
        frame = build_prospect_picker_frame(cards, "inst-2")
        assert frame["type"] == "ui_component"
        assert frame["component"] == "ProspectPicker"
        assert len(frame["props"]["prospects"]) == 1
        assert any(a["action_type"] == "confirm_prospects" for a in frame["actions"])
        assert any(a["action_type"] == "select_all_prospects" for a in frame["actions"])


# ---------------------------------------------------------------------------
# Integration: full agent node (without DB)
# ---------------------------------------------------------------------------

class TestSegmentAgentNodeUnit:
    """Test the full segment_agent_node function by mocking DB calls."""

    async def test_segment_agent_node_returns_expected_keys(self):
        """Verify the node returns segment_candidates, prospect_cards, and next_node."""
        from unittest.mock import AsyncMock, patch

        from app.agents.segment_agent import segment_agent_node

        state = {
            "session_id": "test-session",
            "product_name": "TestProd",
            "product_description": "A test product",
            "target_market": "Developers",
            "briefing_summary": "Market is growing",
            "research_findings": _make_findings(4, "competitor")
            + _make_findings(2, "audience"),
            "prospect_pool_ref": None,
        }

        with (
            patch("app.agents.segment_agent.save_segments", new_callable=AsyncMock),
            patch("app.agents.segment_agent.save_prospect_cards", new_callable=AsyncMock),
        ):
            result = await segment_agent_node(state)

        assert "segment_candidates" in result
        assert "prospect_cards" in result
        assert result["next_node"] == "orchestrator"
        assert len(result["segment_candidates"]) >= 2
        assert len(result["prospect_cards"]) == len(DEMO_SEED_PROSPECTS)

    async def test_segment_agent_node_all_cards_have_scores(self):
        from unittest.mock import AsyncMock, patch

        from app.agents.segment_agent import segment_agent_node

        state = {
            "session_id": "test-session",
            "product_name": "TestProd",
            "product_description": "A test product",
            "target_market": "Developers",
            "briefing_summary": "Test briefing",
            "research_findings": _make_findings(3, "competitor"),
            "prospect_pool_ref": None,
        }

        with (
            patch("app.agents.segment_agent.save_segments", new_callable=AsyncMock),
            patch("app.agents.segment_agent.save_prospect_cards", new_callable=AsyncMock),
        ):
            result = await segment_agent_node(state)

        for card in result["prospect_cards"]:
            assert "fit_score" in card
            assert "urgency_score" in card
            assert "angle_recommendation" in card
            assert "channel_recommendation" in card
