"""Research thread node — Gemini-powered parallel research across dimensions.

Each thread type (competitor, audience, channel, market) generates targeted queries,
runs web searches, optionally extracts pages, and synthesizes structured ResearchFinding
objects using Gemini.
"""

import json
import logging
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4


from app.core.config import settings
from app.core.llm import get_llm
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.tools.research_policy import DEFAULT_RESEARCH_POLICY
from app.tools.search import extract_page, search_web

logger = logging.getLogger(__name__)

THREAD_PROMPTS = {
    "competitor": (
        "Search for how direct and adjacent competitors position their product, "
        "what messaging they use, pricing signals, recent launches, and any gaps "
        "in their offering that create opportunity."
    ),
    "audience": (
        "Find where the target audience talks about this problem in their own words. "
        "Look for pain points, objections, language patterns, community discussions, "
        "and unmet needs that could inform outreach messaging."
    ),
    "channel": (
        "Research which channels are performing for this category right now. "
        "Look for platform trends, engagement benchmarks, emerging channels, "
        "and distribution strategies that competitors or adjacent players are using."
    ),
    "market": (
        "Research PESTEL signals relevant to this product and market. Look for "
        "regulatory changes, funding events, macroeconomic shifts, technology trends, "
        "and timing factors that create urgency or opportunity."
    ),
}

QUERY_GENERATION_PROMPT = """You are a research query generator for a growth intelligence system.

Product: {product_name}
Target Market: {target_market}
Research Dimension: {thread_type}
Research Focus: {thread_prompt}

Generate exactly {num_queries} distinct, specific search queries to investigate this dimension.
Each query should target a different angle or sub-topic.

Output strict JSON array of strings, no markdown, no prose:
["query 1", "query 2", ...]"""

SYNTHESIS_PROMPT = """You are a research analyst synthesizing raw search results into structured findings.

Product: {product_name}
Target Market: {target_market}
Research Dimension: {thread_type}
{prior_intelligence_section}

Raw search results:
{raw_results_text}

Analyze the results and produce exactly {num_findings} research findings.
Each finding must be a concrete, evidence-backed claim with a clear actionable implication.
Assign a confidence score (0.0-1.0) based on source quality and corroboration.
Extract audience language — exact phrases the target audience uses.

Output strict JSON array, no markdown, no prose:
[
  {{
    "claim": "A specific, evidence-backed claim",
    "evidence": "Supporting evidence from the search results",
    "source_url": "The most relevant source URL",
    "confidence": 0.75,
    "audience_language": ["phrase 1", "phrase 2"],
    "actionable_implication": "How this finding should inform outreach strategy"
  }}
]"""


def _get_llm():
    return get_llm(temperature=0.2)


def _parse_json_response(content: str) -> list | dict:
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1 :]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


async def generate_queries(
    product_name: str,
    target_market: str,
    thread_type: str,
    num_queries: int = 3,
) -> list[str]:
    """Generate search queries for a research thread using Gemini."""
    llm = _get_llm()
    if llm is None:
        # Mock mode fallback
        return [
            f"{product_name} {thread_type} {target_market}",
            f"{thread_type} trends {target_market} 2026",
            f"{product_name} {thread_type} analysis",
        ]

    prompt = QUERY_GENERATION_PROMPT.format(
        product_name=product_name,
        target_market=target_market,
        thread_type=thread_type,
        thread_prompt=THREAD_PROMPTS.get(thread_type, "General research"),
        num_queries=num_queries,
    )

    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        queries = _parse_json_response(response.content)
        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
            return queries[:num_queries]
    except Exception as e:
        logger.warning("Query generation failed for %s: %s", thread_type, e)

    # Fallback queries
    return [
        f"{product_name} {thread_type} {target_market}",
        f"{thread_type} trends {target_market} 2026",
    ]


async def synthesize_thread_findings(
    thread_type: str,
    product_name: str,
    target_market: str,
    raw_results: list[dict],
    prior_intelligence: str | None = None,
    num_findings: int = 3,
) -> list[dict]:
    """Synthesize raw search results into structured ResearchFinding dicts using Gemini."""
    if not raw_results:
        return []

    llm = _get_llm()
    if llm is None:
        # Mock mode — return structured findings from raw results
        return _mock_findings(thread_type, raw_results)

    # Build compressed text from raw results
    raw_results_text = _format_raw_results(raw_results)

    prior_section = ""
    if prior_intelligence:
        prior_section = f"Prior intelligence from earlier cycles:\n{prior_intelligence}\n"

    prompt = SYNTHESIS_PROMPT.format(
        product_name=product_name,
        target_market=target_market,
        thread_type=thread_type,
        prior_intelligence_section=prior_section,
        raw_results_text=raw_results_text,
        num_findings=num_findings,
    )

    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        findings = _parse_json_response(response.content)
        if isinstance(findings, list):
            return [_normalize_finding(f, thread_type) for f in findings[:num_findings]]
    except Exception as e:
        logger.warning("Synthesis failed for %s: %s", thread_type, e)

    return _mock_findings(thread_type, raw_results)


def _format_raw_results(results: list[dict], max_chars: int = 8000) -> str:
    lines = []
    total = 0
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "") or r.get("full_content", "")
        # Truncate individual content
        if len(content) > 1000:
            content = content[:1000] + "..."
        entry = f"- [{title}]({url})\n  {content}"
        if total + len(entry) > max_chars:
            break
        lines.append(entry)
        total += len(entry)
    return "\n".join(lines) or "(no results)"


def _normalize_finding(raw: dict, thread_type: str) -> dict:
    return {
        "claim": raw.get("claim", ""),
        "evidence": raw.get("evidence", ""),
        "source_url": raw.get("source_url", ""),
        "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0.5)))),
        "audience_language": raw.get("audience_language", []),
        "actionable_implication": raw.get("actionable_implication", ""),
        "thread_type": thread_type,
    }


def _mock_findings(thread_type: str, raw_results: list[dict]) -> list[dict]:
    findings = []
    for i, r in enumerate(raw_results[:2]):
        findings.append(
            {
                "claim": r.get("title", f"Finding from {thread_type} thread"),
                "evidence": (r.get("content", "") or "")[:200],
                "source_url": r.get("url", ""),
                "confidence": round(max(0.3, min(0.8, r.get("score", 0.5))), 2),
                "audience_language": [],
                "actionable_implication": f"Review {thread_type} signal for outreach angle",
                "thread_type": thread_type,
            }
        )
    # Ensure at least 2 findings
    while len(findings) < 2:
        findings.append(
            {
                "claim": f"Placeholder finding from {thread_type} thread",
                "evidence": "Insufficient search results for deeper analysis",
                "source_url": "",
                "confidence": 0.3,
                "audience_language": [],
                "actionable_implication": f"Requires deeper {thread_type} research",
                "thread_type": thread_type,
            }
        )
    return findings


def should_branch(lead: dict, policy: dict, current_depth: int) -> bool:
    """Determine whether a sub-investigation should be spawned."""
    return (
        lead.get("confidence", 0) >= policy.get("evidence_threshold", 0.6)
        and lead.get("branch_type", "") in policy.get("allowed_tool_groups", [])
        and current_depth < policy.get("max_branch_depth", 2)
    )


async def research_dispatcher_node(state: CampaignState) -> dict:
    """Prepare the thread list for fan-out based on policy."""
    policy: dict = cast(dict, state.get("research_policy") or DEFAULT_RESEARCH_POLICY)
    thread_types = policy.get("enabled_threads", ["competitor", "audience", "channel", "market"])
    logger.info(
        "research_dispatcher_node | session=%s threads=%s",
        state.get("session_id"),
        thread_types,
    )
    return {"active_thread_types": thread_types}


async def research_thread_node(state: CampaignState) -> dict:
    """Execute a single research thread — search, extract, synthesize.

    This node is invoked in parallel via Send for each thread type.
    On failure, records the thread in failed_threads and returns empty findings.
    """
    thread_type: str = state.get("thread_type") or "unknown"
    session_id = state.get("session_id", "unknown")
    product_name = state.get("product_name", "")
    target_market = state.get("target_market", "")
    policy: dict = cast(dict, state.get("research_policy") or DEFAULT_RESEARCH_POLICY)

    logger.info("research_thread_node | session=%s thread=%s", session_id, thread_type)

    # Build scoped context bundle to pull prior long-term intelligence
    try:
        bundle = await memory_manager.build_context_bundle(state, "research")
        prior_findings = bundle.get("top_long_term_findings", [])
        prior_intelligence: str | None = None
        if prior_findings:
            summaries = [f.get("claim", "") for f in prior_findings if f.get("claim")]
            prior_intelligence = "Prior intelligence:\n" + "\n".join(f"- {s}" for s in summaries)
    except Exception as exc:
        logger.warning(
            "research_thread_node: memory bundle failed (%s) — continuing without prior intelligence",
            exc,
        )
        prior_intelligence = state.get("briefing_summary")

    try:
        # Step 1: Generate targeted queries
        queries = await generate_queries(product_name, target_market, thread_type)

        # Step 2: Run searches
        all_results = []
        max_results = policy.get("max_search_results_per_query", 5)
        recency_days = policy.get("recency_days", 30)

        for query in queries:
            results = await search_web(query, max_results=max_results, recency_days=recency_days)
            all_results.extend(results)

        # Step 3: Extract pages for top results (respecting policy limit)
        max_pages = policy.get("max_pages_to_extract", 5)
        pages_extracted = 0
        for result in all_results:
            if pages_extracted >= max_pages:
                break
            url = result.get("url", "")
            if url:
                try:
                    result["full_content"] = await extract_page(url)
                    pages_extracted += 1
                except Exception as e:
                    logger.warning("Page extract failed for %s: %s", url, e)

        # Step 4: Synthesize findings with Gemini (pass prior intelligence from memory manager)
        findings = await synthesize_thread_findings(
            thread_type=thread_type,
            product_name=product_name,
            target_market=target_market,
            raw_results=all_results,
            prior_intelligence=prior_intelligence,
        )

        # Enrich findings with session metadata
        now = datetime.now(timezone.utc).isoformat()
        for finding in findings:
            finding["id"] = f"rf-{uuid4().hex[:12]}"
            finding["session_id"] = session_id
            finding["cycle_number"] = state.get("cycle_number", 1)
            finding["signal_type"] = thread_type
            finding["created_at"] = now

        logger.info(
            "research_thread_node completed | session=%s thread=%s findings=%d",
            session_id,
            thread_type,
            len(findings),
        )
        return {"research_findings": findings}

    except Exception as e:
        logger.error(
            "research_thread_node failed | session=%s thread=%s error=%s",
            session_id,
            thread_type,
            e,
        )
        return {
            "research_findings": [],
            "failed_threads": [thread_type],
        }
