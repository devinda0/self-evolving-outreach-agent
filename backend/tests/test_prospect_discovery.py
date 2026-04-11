"""Tests for the prospect discovery engine — discovery, weighted scoring, deduplication, CSV mapping."""

import pytest

from app.agents.prospect_discovery import (
    SCORING_WEIGHTS,
    _fuzzy_name_match,
    _normalize_email,
    _normalize_linkedin_url,
    _normalize_name,
    _resolve_column_mapping,
    calculate_company_fit,
    calculate_role_seniority,
    calculate_signal_recency,
    calculate_weighted_fit_score,
    deduplicate_prospects,
    load_prospects_from_csv_with_mapping,
)
from app.models.prospect import Segment


# ---------------------------------------------------------------------------
# Helpers
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
            "claim": f"Finding {i} about competitor landscape",
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
# Role seniority scoring
# ---------------------------------------------------------------------------


class TestRoleSeniority:
    def test_ceo_scores_highest(self):
        assert calculate_role_seniority("CEO") == 1.0

    def test_vp_scores_high(self):
        assert calculate_role_seniority("VP Sales") == 0.85

    def test_director_scores_mid(self):
        assert calculate_role_seniority("Director of Marketing") == 0.7

    def test_manager_scores_lower(self):
        assert calculate_role_seniority("Manager") == 0.45

    def test_unknown_title_gets_base(self):
        assert calculate_role_seniority("Office Coordinator") == 0.2

    def test_case_insensitive(self):
        assert calculate_role_seniority("cro") == 1.0
        assert calculate_role_seniority("CRO") == 1.0

    def test_compound_title(self):
        # Should pick the highest matching keyword
        score = calculate_role_seniority("VP and Co-Founder")
        assert score >= 0.85


class TestCompanyFit:
    def test_saas_keyword_boosts(self):
        score = calculate_company_fit("Acme SaaS", "B2B SaaS", [])
        assert score > 0.3  # base

    def test_finding_mention_boosts(self):
        findings = [{"claim": "TestCorp is expanding rapidly", "evidence": ""}]
        score = calculate_company_fit("TestCorp", "general", findings)
        assert score >= 0.5

    def test_base_score_for_unknown(self):
        score = calculate_company_fit("Generic LLC", "unrelated", [])
        assert score == 0.3

    def test_capped_at_1(self):
        findings = [{"claim": "SaaS B2B Enterprise startup Series B", "evidence": ""}]
        score = calculate_company_fit("SaaS B2B Enterprise startup", "B2B SaaS Enterprise", findings)
        assert score <= 1.0


class TestSignalRecency:
    def test_no_findings_returns_base(self):
        score = calculate_signal_recency([], _make_prospect())
        assert score == 0.3

    def test_high_confidence_boosts_score(self):
        high = [{"confidence": 0.9, "claim": "important finding"}]
        low = [{"confidence": 0.2, "claim": "vague finding"}]
        assert calculate_signal_recency(high, _make_prospect()) > calculate_signal_recency(
            low, _make_prospect()
        )

    def test_company_mention_boosts(self):
        findings = [{"confidence": 0.7, "claim": "TestCorp is hiring aggressively"}]
        prospect = _make_prospect(company="TestCorp")
        score = calculate_signal_recency(findings, prospect)
        assert score > 0.5


class TestWeightedFitScore:
    def test_returns_score_and_components(self):
        segment = _make_segment()
        findings = _make_findings(3)
        prospect = _make_prospect()

        score, components = calculate_weighted_fit_score(prospect, segment, findings, "B2B SaaS")

        assert 0.0 <= score <= 1.0
        assert "role_seniority" in components
        assert "company_fit" in components
        assert "signal_recency" in components
        assert "research_alignment" in components

    def test_vp_scores_higher_than_analyst(self):
        segment = _make_segment()
        findings = _make_findings(3)

        vp_score, _ = calculate_weighted_fit_score(
            _make_prospect(title="VP Sales"), segment, findings, "B2B SaaS"
        )
        analyst_score, _ = calculate_weighted_fit_score(
            _make_prospect(title="Junior Analyst"), segment, findings, "B2B SaaS"
        )

        assert vp_score > analyst_score

    def test_weights_sum_to_one(self):
        total = sum(SCORING_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_normalize_email(self):
        assert _normalize_email("  Alice@Example.COM  ") == "alice@example.com"
        assert _normalize_email(None) is None
        assert _normalize_email("") is None

    def test_normalize_linkedin_url(self):
        assert _normalize_linkedin_url("https://www.linkedin.com/in/alice-chen") == "in/alice-chen"
        assert _normalize_linkedin_url("https://linkedin.com/in/bob123") == "in/bob123"
        assert _normalize_linkedin_url(None) is None

    def test_normalize_name(self):
        assert _normalize_name("  Alice   Chen  ") == "alice chen"


class TestFuzzyNameMatch:
    def test_exact_match(self):
        assert _fuzzy_name_match("Alice Chen", "Alice Chen") is True

    def test_case_insensitive(self):
        assert _fuzzy_name_match("alice chen", "ALICE CHEN") is True

    def test_extra_whitespace(self):
        assert _fuzzy_name_match("Alice  Chen", "Alice Chen") is True

    def test_shared_first_last(self):
        assert _fuzzy_name_match("Alice M. Chen", "Alice Chen") is True

    def test_no_match(self):
        assert _fuzzy_name_match("Alice Chen", "Bob Martinez") is False

    def test_single_name_no_match(self):
        # Single word names should not fuzzy-match
        assert _fuzzy_name_match("Alice", "Alice Chen") is False


class TestDeduplication:
    def test_email_dedup(self):
        prospects = [
            _make_prospect(name="Alice", email="alice@test.com", source="csv"),
            _make_prospect(name="Alice Chen", email="alice@test.com", source="discovery"),
        ]
        result = deduplicate_prospects(prospects)
        assert len(result) == 1

    def test_linkedin_dedup(self):
        prospects = [
            _make_prospect(name="Bob", linkedin_url="https://linkedin.com/in/bob123"),
            _make_prospect(name="Bob M.", linkedin_url="https://www.linkedin.com/in/bob123"),
        ]
        result = deduplicate_prospects(prospects)
        assert len(result) == 1

    def test_fuzzy_name_company_dedup(self):
        prospects = [
            _make_prospect(name="Carol Nguyen", company="CloudFirst", email=None, linkedin_url=None),
            _make_prospect(name="Carol N. Nguyen", company="CloudFirst", email=None, linkedin_url=None),
        ]
        result = deduplicate_prospects(prospects)
        assert len(result) == 1

    def test_different_people_not_deduped(self):
        prospects = [
            _make_prospect(name="Alice", email="alice@a.com", linkedin_url="https://linkedin.com/in/alice"),
            _make_prospect(name="Bob", email="bob@b.com", linkedin_url="https://linkedin.com/in/bob"),
        ]
        result = deduplicate_prospects(prospects)
        assert len(result) == 2

    def test_merge_fills_missing_fields(self):
        prospects = [
            _make_prospect(name="Alice", email="alice@test.com", linkedin_url=None, source="csv"),
            _make_prospect(
                name="Alice",
                email="alice@test.com",
                linkedin_url="https://linkedin.com/in/alice",
                source="discovery",
            ),
        ]
        result = deduplicate_prospects(prospects)
        assert len(result) == 1
        assert result[0]["linkedin_url"] == "https://linkedin.com/in/alice"

    def test_merge_keeps_higher_source_priority(self):
        prospects = [
            _make_prospect(name="Alice", email="alice@test.com", source="seed"),
            _make_prospect(name="Alice", email="alice@test.com", source="discovery"),
        ]
        result = deduplicate_prospects(prospects)
        assert result[0]["source"] == "discovery"

    def test_empty_list(self):
        assert deduplicate_prospects([]) == []

    def test_single_prospect(self):
        prospects = [_make_prospect()]
        assert len(deduplicate_prospects(prospects)) == 1


# ---------------------------------------------------------------------------
# CSV column mapping
# ---------------------------------------------------------------------------


class TestColumnMapping:
    def test_auto_detect_standard_headers(self):
        headers = ["name", "email", "linkedin_url", "title", "company"]
        mapping = _resolve_column_mapping(headers)
        assert mapping["name"] == "name"
        assert mapping["email"] == "email"

    def test_auto_detect_alternative_headers(self):
        headers = ["Full Name", "E-Mail", "LinkedIn Profile", "Job Title", "Organization"]
        mapping = _resolve_column_mapping(headers)
        assert mapping["name"] is not None
        assert mapping["email"] is not None
        assert mapping["title"] is not None
        assert mapping["company"] is not None

    def test_custom_mapping_overrides(self):
        headers = ["contact", "mail", "li_url", "role", "org"]
        custom = {"name": "contact", "email": "mail", "title": "role", "company": "org"}
        mapping = _resolve_column_mapping(headers, custom)
        assert mapping["name"] == "contact"
        assert mapping["email"] == "mail"

    def test_missing_columns_return_none(self):
        headers = ["name", "company"]
        mapping = _resolve_column_mapping(headers)
        assert mapping["name"] == "name"
        assert mapping["email"] is None


class TestCsvWithMapping:
    async def test_standard_csv(self):
        csv = b"name,email,linkedin_url,title,company\nAlice,alice@a.com,,VP Sales,Acme\n"
        prospects = await load_prospects_from_csv_with_mapping(csv)
        assert len(prospects) == 1
        assert prospects[0]["name"] == "Alice"
        assert prospects[0]["source"] == "csv"

    async def test_alternative_headers(self):
        csv = b"Full Name,E-Mail,LinkedIn,Job Title,Organization\nBob,bob@b.com,,CTO,TechCo\n"
        prospects = await load_prospects_from_csv_with_mapping(csv)
        assert len(prospects) == 1
        assert prospects[0]["name"] == "Bob"

    async def test_custom_mapping(self):
        csv = b"contact,mail,role,org\nCarol,carol@c.com,VP,CorpX\n"
        mapping = {"name": "contact", "email": "mail", "title": "role", "company": "org"}
        prospects = await load_prospects_from_csv_with_mapping(csv, column_mapping=mapping)
        assert len(prospects) == 1
        assert prospects[0]["name"] == "Carol"
        assert prospects[0]["email"] == "carol@c.com"

    async def test_skips_rows_without_name(self):
        csv = b"name,email,title,company\n,alice@a.com,VP,Acme\nBob,bob@b.com,CTO,Corp\n"
        prospects = await load_prospects_from_csv_with_mapping(csv)
        assert len(prospects) == 1
        assert prospects[0]["name"] == "Bob"

    async def test_empty_csv(self):
        prospects = await load_prospects_from_csv_with_mapping(b"name,email\n")
        assert len(prospects) == 0


# ---------------------------------------------------------------------------
# Discovery (mock mode)
# ---------------------------------------------------------------------------


class TestDiscoveryMockMode:
    """Test discovery with LLM in mock mode (USE_MOCK_LLM=True)."""

    async def test_discover_returns_prospects(self):
        from unittest.mock import AsyncMock, patch

        from app.agents.prospect_discovery import discover_prospects_via_research

        with (
            patch("app.agents.prospect_discovery.get_llm", return_value=None),
            patch("app.agents.prospect_discovery.search_web", new_callable=AsyncMock, return_value=[]),
        ):
            prospects = await discover_prospects_via_research(
                product_name="TestProd",
                target_market="B2B SaaS",
                research_findings=_make_findings(3),
                num_prospects=5,
            )

        assert len(prospects) <= 5
        assert all(p.get("source") == "discovery" for p in prospects)
        for p in prospects:
            assert p.get("name")
            assert p.get("title")

    async def test_discover_respects_count(self):
        from unittest.mock import AsyncMock, patch

        from app.agents.prospect_discovery import discover_prospects_via_research

        with (
            patch("app.agents.prospect_discovery.get_llm", return_value=None),
            patch("app.agents.prospect_discovery.search_web", new_callable=AsyncMock, return_value=[]),
        ):
            prospects = await discover_prospects_via_research(
                product_name="TestProd",
                target_market="B2B SaaS",
                research_findings=_make_findings(3),
                num_prospects=3,
            )

        assert len(prospects) <= 3
