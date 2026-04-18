"""Prospect discovery engine — research-powered prospect finding, scoring, and deduplication.

Replaces the static seed-list approach with:
1. LLM-powered prospect discovery from research findings
2. Weighted multi-signal scoring model
3. Fuzzy deduplication across import sources
4. CSV import with flexible column mapping
"""

import csv
import io
import json
import logging
import re
from typing import Any

from app.core.llm import get_llm
from app.tools.mcp_tools import do_search as search_web

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seniority weights for weighted scoring
# ---------------------------------------------------------------------------

SENIORITY_TIERS: dict[str, float] = {
    # C-suite
    "ceo": 1.0, "cto": 1.0, "cfo": 1.0, "coo": 1.0, "cmo": 1.0, "cro": 1.0,
    "chief": 1.0, "co-founder": 1.0, "founder": 1.0,
    # VP level
    "vp": 0.85, "vice president": 0.85, "svp": 0.9, "evp": 0.9,
    # Director level
    "director": 0.7, "senior director": 0.75,
    # Head / Lead
    "head": 0.75, "lead": 0.6, "principal": 0.6,
    # Manager
    "manager": 0.45, "senior manager": 0.55,
}

COMPANY_FIT_KEYWORDS: dict[str, float] = {
    "saas": 0.15, "b2b": 0.15, "enterprise": 0.1, "startup": 0.1,
    "series a": 0.1, "series b": 0.15, "series c": 0.1,
    "growth": 0.1, "scale": 0.1, "platform": 0.05,
}

# Scoring weight configuration
SCORING_WEIGHTS = {
    "role_seniority": 0.30,
    "company_fit": 0.25,
    "signal_recency": 0.20,
    "research_alignment": 0.25,
}


# ---------------------------------------------------------------------------
# Research-powered prospect discovery
# ---------------------------------------------------------------------------

DISCOVERY_PROMPT = """You are a prospect researcher for a B2B growth intelligence platform.

Product: {product_name}
Target Market: {target_market}
Research Context:
{research_context}

Based on the research findings above, identify {num_prospects} specific prospect profiles
that would be ideal targets for outreach. For each prospect, provide realistic but
representative profiles of the type of person who would be a decision-maker.

Focus on:
- Decision-makers at companies matching the research signals
- People whose roles align with the product's value proposition
- Companies showing signals of need (growth, hiring, funding, pain points)

CRITICAL REQUIREMENT:
You MUST provide a realistic email address or a valid LinkedIn profile URL for each prospect.
Without an email or LinkedIn ID, the prospect is useless for outreach. Ensure at least one communication method is present for each prospect.

Output strict JSON array, no markdown, no prose:
[
  {{
    "name": "Full Name",
    "title": "Job Title",
    "company": "Company Name",
    "email": "valid@email.com or null",
    "linkedin_url": "valid URL or null",
    "rationale": "Why this profile is a good target based on research"
  }}
]"""

DISCOVERY_QUERY_PROMPT = """You are generating web search queries to find real prospects for outreach.

Product: {product_name}
Target Market: {target_market}
Research Context:
{research_context}

Generate {num_queries} specific search queries to find decision-makers and companies that match
our ideal customer profile. Queries should target LinkedIn profiles, company pages, industry
directories, and funding announcements.

Output strict JSON array of strings, no markdown:
["query 1", "query 2", ...]"""

PROSPECT_EXTRACTION_PROMPT = """You are extracting prospect information from web search results.

Search results:
{search_results}

Target Market: {target_market}
Product: {product_name}

Extract real prospect profiles from these search results. Only include people who appear to be
real individuals with verifiable information. Do not fabricate details.

CRITICAL REQUIREMENT:
You MUST successfully extract either a valid email address or a valid LinkedIn profile URL for each prospect.
If a prospect does not have an email OR a LinkedIn URL available in the search results, DO NOT include them in the results.
Prospects without a communication method are useless for outreach.

Output strict JSON array, no markdown:
[
  {{
    "name": "Full Name",
    "title": "Job Title",
    "company": "Company Name",
    "email": "valid@email.com or null",
    "linkedin_url": "valid linkedin URL or null",
    "rationale": "Brief explanation of why they match"
  }}
]

If no valid prospects can be extracted, return an empty array: []"""


def _parse_json_response(content: str) -> list | dict:
    """Parse JSON from LLM response, stripping markdown fences."""
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def _format_research_context(findings: list[dict[str, Any]], limit: int = 8) -> str:
    """Build a compact research context string from top findings."""
    lines = []
    for f in findings[:limit]:
        claim = f.get("claim", "")
        signal = f.get("signal_type", f.get("thread_type", "general"))
        confidence = f.get("confidence", 0.0)
        lines.append(f"- [{signal}] {claim} (confidence: {confidence:.2f})")
    return "\n".join(lines) if lines else "(no research findings available)"


async def discover_prospects_via_research(
    product_name: str,
    target_market: str,
    research_findings: list[dict[str, Any]],
    num_prospects: int = 10,
    num_search_queries: int = 3,
) -> list[dict[str, Any]]:
    """Use research findings + web search to discover prospect profiles.

    Flow:
    1. Generate targeted discovery search queries from research
    2. Execute web searches to find real prospects
    3. Extract prospect profiles from search results
    4. Fall back to LLM-generated profiles if search yields insufficient results
    """
    llm = get_llm(temperature=0.3)
    research_context = _format_research_context(research_findings)
    discovered: list[dict[str, Any]] = []

    # Step 1: Search-based discovery
    search_prospects = await _search_based_discovery(
        llm, product_name, target_market, research_context, num_search_queries
    )
    discovered.extend(search_prospects)

    # Step 2: If search didn't find enough, use LLM to generate representative profiles
    if len(discovered) < num_prospects:
        llm_prospects = await _llm_profile_generation(
            llm, product_name, target_market, research_context,
            num_prospects=num_prospects - len(discovered),
        )
        discovered.extend(llm_prospects)

    # Tag all discovered prospects with source
    for p in discovered:
        p["source"] = "discovery"

    return discovered[:num_prospects]


async def _search_based_discovery(
    llm: Any,
    product_name: str,
    target_market: str,
    research_context: str,
    num_queries: int,
) -> list[dict[str, Any]]:
    """Generate search queries and extract prospects from results."""
    prospects: list[dict[str, Any]] = []

    # Generate targeted queries
    queries = await _generate_discovery_queries(
        llm, product_name, target_market, research_context, num_queries
    )

    # Execute searches
    all_results: list[dict] = []
    for query in queries:
        results = await search_web(query, max_results=5, recency_days=90)
        all_results.extend(results)

    if not all_results:
        return []

    # Extract prospects from search results
    if llm is None:
        return _mock_extract_prospects(all_results)

    search_text = "\n".join(
        f"- [{r.get('title', '')}]({r.get('url', '')}): {(r.get('content', '') or '')[:300]}"
        for r in all_results[:15]
    )

    prompt = PROSPECT_EXTRACTION_PROMPT.format(
        search_results=search_text,
        target_market=target_market,
        product_name=product_name,
    )

    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        extracted = _parse_json_response(response.content)
        if isinstance(extracted, list):
            prospects.extend([_normalize_prospect(p) for p in extracted])
    except Exception as e:
        logger.warning("Prospect extraction from search failed: %s", e)

    return [p for p in prospects if p.get("email") or p.get("linkedin_url")]


async def _generate_discovery_queries(
    llm: Any,
    product_name: str,
    target_market: str,
    research_context: str,
    num_queries: int,
) -> list[str]:
    """Generate search queries for prospect discovery."""
    if llm is None:
        return [
            f"{target_market} decision makers {product_name}",
            f"site:linkedin.com {target_market} VP director",
            f"{target_market} companies hiring growth",
        ]

    prompt = DISCOVERY_QUERY_PROMPT.format(
        product_name=product_name,
        target_market=target_market,
        research_context=research_context,
        num_queries=num_queries,
    )

    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        queries = _parse_json_response(response.content)
        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
            return queries[:num_queries]
    except Exception as e:
        logger.warning("Discovery query generation failed: %s", e)

    return [f"{target_market} decision makers {product_name}"]


async def _llm_profile_generation(
    llm: Any,
    product_name: str,
    target_market: str,
    research_context: str,
    num_prospects: int,
) -> list[dict[str, Any]]:
    """Generate representative prospect profiles using the LLM."""
    if llm is None:
        return _mock_discovered_prospects(num_prospects)

    prompt = DISCOVERY_PROMPT.format(
        product_name=product_name,
        target_market=target_market,
        research_context=research_context,
        num_prospects=num_prospects,
    )

    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        profiles = _parse_json_response(response.content)
        if isinstance(profiles, list):
            valid_profiles = [_normalize_prospect(p) for p in profiles]
            return [p for p in valid_profiles if p.get("email") or p.get("linkedin_url")][:num_prospects]
    except Exception as e:
        logger.warning("LLM prospect generation failed: %s", e)

    return _mock_discovered_prospects(num_prospects)


def _normalize_prospect(raw: dict) -> dict[str, Any]:
    """Normalize a raw prospect dict to the expected schema."""
    return {
        "name": (raw.get("name") or "").strip(),
        "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company") or "").strip(),
        "email": (raw.get("email") or "").strip() or None,
        "linkedin_url": (raw.get("linkedin_url") or "").strip() or None,
        "rationale": (raw.get("rationale") or "").strip(),
    }


def _mock_discovered_prospects(count: int) -> list[dict[str, Any]]:
    """Fallback mock prospects for testing / when LLM is unavailable."""
    mock_profiles = [
        {"name": "Sarah Mitchell", "title": "VP of Revenue Operations", "company": "GrowthStack"},
        {"name": "Marcus Chen", "title": "Head of Demand Generation", "company": "PipelinePro"},
        {"name": "Priya Patel", "title": "Director of Growth", "company": "ScaleMetrics"},
        {"name": "Jordan Wells", "title": "CRO", "company": "RevenueOS"},
        {"name": "Nina Kowalski", "title": "VP Business Development", "company": "SignalBase"},
        {"name": "Alex Rivera", "title": "Head of Sales", "company": "DataPulse AI"},
        {"name": "Tanya Okonkwo", "title": "Director of Partnerships", "company": "MotionLead"},
        {"name": "Ryan Choi", "title": "VP Marketing", "company": "InsightLoop"},
        {"name": "Leila Amara", "title": "Growth Lead", "company": "FlowState Inc"},
        {"name": "Derek Volkov", "title": "Head of Revenue", "company": "NexusGrowth"},
    ]
    return [
        {**p, "email": None, "linkedin_url": None, "rationale": "Matched ICP profile", "source": "discovery"}
        for p in mock_profiles[:count]
    ]


def _mock_extract_prospects(results: list[dict]) -> list[dict[str, Any]]:
    """Extract mock prospects from search results in mock mode."""
    prospects = []
    for r in results[:3]:
        title_text = r.get("title", "")
        prospects.append({
            "name": f"Prospect from {title_text[:30]}",
            "title": "Decision Maker",
            "company": "Discovered Co",
            "email": None,
            "linkedin_url": r.get("url"),
            "rationale": f"Found via search: {title_text[:80]}",
            "source": "discovery",
        })
    return prospects


# ---------------------------------------------------------------------------
# Weighted multi-signal scoring model
# ---------------------------------------------------------------------------


def calculate_role_seniority(title: str) -> float:
    """Score role seniority from 0.0 to 1.0 based on title keywords."""
    title_lower = title.lower()
    # Tokenize into words for whole-word matching to avoid substring false positives
    # e.g. "director" should not match "cto" via substring
    title_words = set(re.findall(r"[a-z]+(?:-[a-z]+)*", title_lower))
    best_score = 0.2  # base score for any title

    for keyword, score in SENIORITY_TIERS.items():
        # Check whole-word match: keyword must appear as a complete word
        if keyword in title_words:
            best_score = max(best_score, score)
        # Also handle multi-word keywords like "vice president", "senior director"
        elif " " in keyword and keyword in title_lower:
            best_score = max(best_score, score)

    return best_score


def calculate_company_fit(
    company: str,
    target_market: str,
    research_findings: list[dict[str, Any]],
) -> float:
    """Score company fit based on target market alignment and research signals."""
    score = 0.3  # base score
    company_lower = company.lower()
    market_lower = target_market.lower()

    # Keyword match from company fit dictionary
    for keyword, boost in COMPANY_FIT_KEYWORDS.items():
        if keyword in company_lower or keyword in market_lower:
            score += boost

    # Check if company is mentioned in research findings
    for finding in research_findings[:10]:
        claim = (finding.get("claim") or "").lower()
        evidence = (finding.get("evidence") or "").lower()
        if company_lower in claim or company_lower in evidence:
            score += 0.2
            break

    return min(score, 1.0)


def calculate_signal_recency(
    findings: list[dict[str, Any]],
    prospect: dict[str, Any],
) -> float:
    """Score based on how recent and relevant the signals are.

    Higher scores when research findings are high-confidence and the
    prospect's company/industry aligns with recent signals.
    """
    if not findings:
        return 0.3

    company_lower = (prospect.get("company") or "").lower()
    title_lower = (prospect.get("title") or "").lower()

    relevance_scores: list[float] = []
    for f in findings[:5]:
        confidence = f.get("confidence", 0.5)
        claim_lower = (f.get("claim") or "").lower()

        relevance = confidence * 0.5
        if company_lower and company_lower in claim_lower:
            relevance += 0.3
        if any(kw in claim_lower for kw in title_lower.split() if len(kw) > 3):
            relevance += 0.1

        relevance_scores.append(min(relevance, 1.0))

    return sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0.3


def calculate_weighted_fit_score(
    prospect: dict[str, Any],
    segment: Any,
    research_findings: list[dict[str, Any]],
    target_market: str,
) -> tuple[float, dict[str, float]]:
    """Calculate a weighted composite fit score.

    Returns (composite_score, component_scores) where component_scores
    contains the individual signal scores for transparency.
    """
    title = prospect.get("title") or ""
    company = prospect.get("company") or ""

    role_seniority = calculate_role_seniority(title)
    company_fit = calculate_company_fit(company, target_market, research_findings)
    signal_recency = calculate_signal_recency(research_findings, prospect)

    # Research alignment: how well does this prospect's profile match segment criteria
    research_alignment = _calculate_research_alignment(prospect, segment, research_findings)

    components = {
        "role_seniority": round(role_seniority, 3),
        "company_fit": round(company_fit, 3),
        "signal_recency": round(signal_recency, 3),
        "research_alignment": round(research_alignment, 3),
    }

    composite = (
        SCORING_WEIGHTS["role_seniority"] * role_seniority
        + SCORING_WEIGHTS["company_fit"] * company_fit
        + SCORING_WEIGHTS["signal_recency"] * signal_recency
        + SCORING_WEIGHTS["research_alignment"] * research_alignment
    )

    return round(min(composite, 1.0), 3), components


def _calculate_research_alignment(
    prospect: dict[str, Any],
    segment: Any,
    findings: list[dict[str, Any]],
) -> float:
    """Score how well a prospect aligns with the research-derived segment criteria."""
    if segment is None:
        return 0.4

    score = 0.3
    criteria = getattr(segment, "criteria", {}) if hasattr(segment, "criteria") else {}
    title_lower = (prospect.get("title") or "").lower()

    derived_from = criteria.get("derived_from", "")

    if derived_from == "audience_research":
        sales_keywords = ["sales", "growth", "revenue", "business development", "demand"]
        if any(kw in title_lower for kw in sales_keywords):
            score += 0.3
    elif derived_from == "competitor_research":
        decision_keywords = ["vp", "director", "head", "chief", "lead", "president"]
        if any(kw in title_lower for kw in decision_keywords):
            score += 0.3
    else:
        # Generic alignment with leadership
        if calculate_role_seniority(prospect.get("title", "")) >= 0.6:
            score += 0.2

    # Boost for rationale presence (discovered prospects have context)
    if prospect.get("rationale"):
        score += 0.1

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _normalize_email(email: str | None) -> str | None:
    """Lowercase and strip an email for comparison."""
    if not email:
        return None
    return email.strip().lower()


def _normalize_linkedin_url(url: str | None) -> str | None:
    """Extract the canonical LinkedIn profile path for comparison."""
    if not url:
        return None
    url = url.strip().lower()
    # Extract path like /in/username from various LinkedIn URL formats
    match = re.search(r"linkedin\.com/(in/[a-z0-9_-]+)", url)
    if match:
        return match.group(1)
    return url


def _normalize_name(name: str) -> str:
    """Lowercase and strip extra whitespace for fuzzy matching."""
    return " ".join(name.lower().split())


def _fuzzy_name_match(name_a: str, name_b: str) -> bool:
    """Check if two names are a fuzzy match.

    Handles: exact match, reversed order, subset matching.
    """
    a = _normalize_name(name_a)
    b = _normalize_name(name_b)

    if a == b:
        return True

    # Check if one name is a subset of the other (handles middle names, initials)
    parts_a = set(a.split())
    parts_b = set(b.split())

    if len(parts_a) >= 2 and len(parts_b) >= 2:
        # If both share first and last name parts
        overlap = parts_a & parts_b
        if len(overlap) >= 2:
            return True

    return False


def deduplicate_prospects(prospects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate prospects across import sources.

    Deduplication priority: email > LinkedIn URL > fuzzy name + company match.
    When duplicates are found, the record with more data is kept.
    """
    seen_emails: dict[str, int] = {}
    seen_linkedin: dict[str, int] = {}
    seen_name_company: dict[str, int] = {}
    unique: list[dict[str, Any]] = []
    duplicate_count = 0

    for prospect in prospects:
        email = _normalize_email(prospect.get("email"))
        linkedin = _normalize_linkedin_url(prospect.get("linkedin_url"))
        name = _normalize_name(prospect.get("name", ""))
        company = _normalize_name(prospect.get("company", ""))
        name_company_key = f"{name}|{company}" if name and company else None

        existing_idx: int | None = None

        # Check email match
        if email and email in seen_emails:
            existing_idx = seen_emails[email]
        # Check LinkedIn match
        elif linkedin and linkedin in seen_linkedin:
            existing_idx = seen_linkedin[linkedin]
        # Check fuzzy name + company match
        elif name_company_key:
            for key, idx in seen_name_company.items():
                existing_name, existing_company = key.split("|", 1)
                if existing_company == company and _fuzzy_name_match(name, existing_name):
                    existing_idx = idx
                    break

        if existing_idx is not None:
            duplicate_count += 1
            # Merge: keep the record with more data
            existing = unique[existing_idx]
            merged = _merge_prospect_records(existing, prospect)
            unique[existing_idx] = merged
        else:
            idx = len(unique)
            unique.append(prospect)

            if email:
                seen_emails[email] = idx
            if linkedin:
                seen_linkedin[linkedin] = idx
            if name_company_key:
                seen_name_company[name_company_key] = idx

    if duplicate_count:
        logger.info("Deduplication removed %d duplicate prospects", duplicate_count)

    return unique


def _merge_prospect_records(
    existing: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Merge two prospect records, preferring non-null values from the newer record."""
    merged = {**existing}
    for key in ("email", "linkedin_url", "title", "company", "rationale"):
        if not merged.get(key) and new.get(key):
            merged[key] = new[key]

    # Keep the higher source priority: discovery > csv > seed > manual
    source_priority = {"discovery": 3, "csv": 2, "manual": 1, "seed": 0}
    existing_priority = source_priority.get(merged.get("source", "seed"), 0)
    new_priority = source_priority.get(new.get("source", "seed"), 0)
    if new_priority > existing_priority:
        merged["source"] = new["source"]

    return merged


# ---------------------------------------------------------------------------
# Enhanced CSV import with column mapping
# ---------------------------------------------------------------------------

DEFAULT_COLUMN_MAP = {
    "name": ["name", "full_name", "full name", "contact_name", "contact name"],
    "email": ["email", "email_address", "e-mail", "email address", "work_email"],
    "linkedin_url": ["linkedin_url", "linkedin", "linkedin_profile", "linkedin url", "profile_url"],
    "title": ["title", "job_title", "role", "position", "job title"],
    "company": ["company", "company_name", "organization", "org", "company name"],
}


def _resolve_column_mapping(
    headers: list[str],
    custom_mapping: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """Resolve CSV column headers to our internal field names.

    If custom_mapping is provided, it takes priority.
    Otherwise, auto-detect using DEFAULT_COLUMN_MAP.
    """
    mapping: dict[str, str | None] = {
        "name": None, "email": None, "linkedin_url": None, "title": None, "company": None,
    }
    headers_lower = [h.strip().lower() for h in headers]

    if custom_mapping:
        for field, csv_col in custom_mapping.items():
            if field in mapping and csv_col.strip().lower() in headers_lower:
                idx = headers_lower.index(csv_col.strip().lower())
                mapping[field] = headers[idx]
        return mapping

    # Auto-detect
    for field, aliases in DEFAULT_COLUMN_MAP.items():
        for alias in aliases:
            if alias in headers_lower:
                idx = headers_lower.index(alias)
                mapping[field] = headers[idx]
                break

    return mapping


async def load_prospects_from_csv_with_mapping(
    csv_bytes: bytes,
    column_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Parse CSV content with flexible column mapping.

    Args:
        csv_bytes: Raw CSV file content.
        column_mapping: Optional {field: csv_column_name} mapping.
            If not provided, auto-detects columns from common aliases.

    Returns:
        List of prospect dicts with standardized field names.
    """
    content = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    if not reader.fieldnames:
        return []

    mapping = _resolve_column_mapping(list(reader.fieldnames), column_mapping)

    prospects: list[dict[str, Any]] = []
    for row in reader:
        name = (row.get(mapping["name"] or "name") or "").strip()
        if not name:
            continue  # Skip rows without a name

        prospects.append({
            "name": name,
            "email": (row.get(mapping["email"] or "") or "").strip() or None,
            "linkedin_url": (row.get(mapping["linkedin_url"] or "") or "").strip() or None,
            "title": (row.get(mapping["title"] or "") or "").strip(),
            "company": (row.get(mapping["company"] or "") or "").strip(),
            "source": "csv",
        })

    logger.info("Loaded %d prospects from CSV with column mapping", len(prospects))
    return prospects
