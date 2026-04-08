"""Research synthesizer node — fan-in merge, briefing generation, persistence.

After all parallel research threads complete, this node:
1. Deduplicates and ranks findings
2. Generates an executive briefing with Gemini
3. Persists all findings to MongoDB
4. Emits a BriefingCard UI frame for the frontend
"""

import json
import logging
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.db.crud import save_research_finding
from app.models.campaign_state import CampaignState
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = """You are a senior research analyst producing an executive briefing.

Product: {product_name}
Target Market: {target_market}
Cycle: {cycle_number}

Research findings from {thread_count} parallel threads ({finding_count} total findings):

{findings_text}

Produce a structured briefing summarizing what was discovered. Include:
1. An executive summary (2-3 sentences capturing the most important insights)
2. Key themes across threads
3. Top opportunities for outreach
4. Research gaps that need further investigation

Output strict JSON, no markdown, no prose:
{{
  "executive_summary": "...",
  "key_themes": ["theme 1", "theme 2", ...],
  "top_opportunities": ["opp 1", "opp 2", ...],
  "gaps": ["gap 1", "gap 2", ...],
  "recommended_next_steps": ["step 1", "step 2", ...]
}}"""


def _get_llm():
    if settings.USE_MOCK_LLM:
        return None
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",
        temperature=0.1,
        api_key=settings.GEMINI_API_KEY,
    )


def _parse_json_response(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def _format_findings_for_prompt(findings: list[dict], max_chars: int = 10000) -> str:
    lines = []
    total = 0
    for f in findings:
        thread = f.get("thread_type", f.get("signal_type", "unknown"))
        claim = f.get("claim", "")
        evidence = f.get("evidence", "")[:300]
        confidence = f.get("confidence", 0)
        source = f.get("source_url", "")
        entry = (
            f"[{thread}] (confidence: {confidence:.2f})\n"
            f"  Claim: {claim}\n"
            f"  Evidence: {evidence}\n"
            f"  Source: {source}"
        )
        if total + len(entry) > max_chars:
            break
        lines.append(entry)
        total += len(entry)
    return "\n\n".join(lines) or "(no findings)"


def _deduplicate_findings(findings: list[dict]) -> list[dict]:
    """Deduplicate by claim similarity, keeping the highest-confidence version."""
    seen_claims: dict[str, dict] = {}
    for f in findings:
        # Normalize claim for dedup
        key = f.get("claim", "").strip().lower()[:100]
        if not key:
            continue
        existing = seen_claims.get(key)
        if existing is None or f.get("confidence", 0) > existing.get("confidence", 0):
            seen_claims[key] = f
    # Return sorted by confidence descending
    return sorted(seen_claims.values(), key=lambda x: x.get("confidence", 0), reverse=True)


def _mock_briefing(findings: list[dict]) -> dict:
    """Produce a mock briefing when LLM is unavailable."""
    thread_types = list({f.get("thread_type", "unknown") for f in findings})
    claims = [f.get("claim", "") for f in findings[:5]]
    return {
        "executive_summary": (
            f"Research across {len(thread_types)} dimensions produced {len(findings)} findings. "
            f"Key signals include: {'; '.join(claims[:3]) or 'pending deeper analysis'}."
        ),
        "key_themes": [f"Theme from {t} analysis" for t in thread_types],
        "top_opportunities": [f.get("actionable_implication", "") for f in findings[:3]],
        "gaps": [f"Deeper {t} research needed" for t in thread_types if t not in
                 {f.get("thread_type") for f in findings if f.get("confidence", 0) > 0.6}],
        "recommended_next_steps": ["Define target segment", "Generate content variants"],
    }


async def synthesize_briefing(
    product_name: str,
    target_market: str,
    findings: list[dict],
    cycle_number: int = 1,
) -> dict:
    """Generate an executive briefing from research findings using Gemini."""
    llm = _get_llm()
    if llm is None:
        return _mock_briefing(findings)

    thread_types = list({f.get("thread_type", "unknown") for f in findings})
    findings_text = _format_findings_for_prompt(findings)

    prompt = BRIEFING_PROMPT.format(
        product_name=product_name,
        target_market=target_market,
        cycle_number=cycle_number,
        thread_count=len(thread_types),
        finding_count=len(findings),
        findings_text=findings_text,
    )

    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        briefing = _parse_json_response(response.content)
        if isinstance(briefing, dict) and "executive_summary" in briefing:
            return briefing
    except Exception as e:
        logger.warning("Briefing synthesis failed: %s", e)

    return _mock_briefing(findings)


async def research_synthesizer_node(state: CampaignState) -> dict:
    """Fan-in: merge all thread findings, generate briefing, persist, emit UI frame."""
    session_id = state.get("session_id", "unknown")
    findings = state.get("research_findings", [])
    failed = state.get("failed_threads", [])

    logger.info(
        "research_synthesizer_node | session=%s findings=%d failed_threads=%s",
        session_id,
        len(findings),
        failed,
    )

    # Deduplicate findings
    deduplicated = _deduplicate_findings(findings)

    # Generate briefing
    briefing = await synthesize_briefing(
        product_name=state.get("product_name", ""),
        target_market=state.get("target_market", ""),
        findings=deduplicated,
        cycle_number=state.get("cycle_number", 1),
    )

    # Persist all findings to MongoDB
    for finding in deduplicated:
        try:
            await save_research_finding(finding)
        except Exception as e:
            logger.error("Failed to persist finding: %s", e)

    # Build BriefingCard UI frame
    instance_id = f"briefing_{uuid4().hex[:8]}"
    ui_frame = UIFrame(
        type="ui_component",
        component="BriefingCard",
        instance_id=instance_id,
        props={
            "briefing": briefing,
            "finding_count": len(deduplicated),
            "thread_summary": _thread_summary(deduplicated),
            "failed_threads": failed,
        },
        actions=[
            UIAction(
                id="goto_segment",
                label="Pick Target Segment",
                action_type="navigate",
                payload={"target_intent": "segment"},
            ),
            UIAction(
                id="goto_generate",
                label="Generate Content",
                action_type="navigate",
                payload={"target_intent": "generate"},
            ),
            UIAction(
                id="drill_deeper",
                label="Research More",
                action_type="navigate",
                payload={"target_intent": "research"},
            ),
        ],
    )

    return {
        "briefing_summary": briefing.get("executive_summary", ""),
        "research_gaps": briefing.get("gaps", []),
        "active_stage_summary": "research complete — briefing ready",
        "session_complete": True,
        "pending_ui_frames": [ui_frame.model_dump()],
    }


def _thread_summary(findings: list[dict]) -> dict[str, int]:
    """Count findings per thread type."""
    summary: dict[str, int] = {}
    for f in findings:
        t = f.get("thread_type", "unknown")
        summary[t] = summary.get(t, 0) + 1
    return summary
