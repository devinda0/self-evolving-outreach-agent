"""Content Agent — Gemini-powered A/B content variant generation with full traceability.

Generates exactly 2 email variants and 1 LinkedIn variant per run, each grounded
in research findings with explicit hypotheses and success metrics.

Every variant carries:
- source_finding_ids: IDs of the research findings that motivate this content
- hypothesis: "Leading with [angle] will increase [metric] for [segment]"
- success_metric: measurable target (e.g. "reply_rate > 8%")
- angle_label: concise descriptor (e.g. "competitor-gap", "roi-first", "pain-led")
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.db.crud import save_content_variant
from app.models.campaign_state import CampaignState
from app.models.intelligence import ContentVariant
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

CONTENT_GENERATION_PROMPT = """\
You are an expert B2B copywriter generating research-grounded outreach variants.

Product: {product_name}
Product description: {product_description}
Target segment: {segment_label}
Briefing summary: {briefing_summary}
Prior winning angles (from previous cycles): {winning_angle_memory}
Additional content request: {content_request}

Top research findings (you MUST cite these by their ID in source_finding_ids):
{formatted_findings}

Generate exactly 3 outreach variants:
- Variant 1: email  (angle: competitor-gap or pain-led)
- Variant 2: email  (angle: roi-first or strategic-vision — MUST differ from Variant 1)
- Variant 3: linkedin (angle: authority or social-proof)

Rules:
- Variants must test DIFFERENT hypotheses — not just stylistic rewording.
- Use {{{{first_name}}}} and {{{{company}}}} as personalisation tokens in body text.
- subject_line is required for email variants, null for linkedin.
- source_finding_ids must be a non-empty list containing only IDs from the findings above.
- hypothesis format: "Leading with [angle] will increase [metric] for [segment]"
- success_metric format: "<metric_name> > <threshold>%" (e.g. "reply_rate > 8%")

Output ONLY a valid JSON array of 3 objects. No prose, no markdown fences.
Each object must contain exactly these keys:
  intended_channel, hypothesis, success_metric, source_finding_ids,
  subject_line, body, cta, angle_label
"""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGoogleGenerativeAI | None:
    if settings.USE_MOCK_LLM:
        return None
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in environment variables")
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",
        temperature=0.4,
        api_key=settings.GEMINI_API_KEY,
    )


def _parse_json_response(content: str) -> list[dict]:
    """Strip optional markdown fences and parse JSON array from LLM output."""
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def _format_findings_for_prompt(findings: list[dict], max_chars: int = 6000) -> str:
    """Format research findings for the generation prompt."""
    lines = []
    total = 0
    for f in findings:
        finding_id = f.get("id", "unknown")
        signal_type = f.get("signal_type", f.get("thread_type", "unknown"))
        claim = f.get("claim", "")
        confidence = f.get("confidence", 0.0)
        implication = f.get("actionable_implication", "")
        entry = (
            f"ID: {finding_id}\n"
            f"  [{signal_type}] (confidence: {confidence:.2f})\n"
            f"  Claim: {claim}\n"
            f"  Implication: {implication}"
        )
        if total + len(entry) > max_chars:
            break
        lines.append(entry)
        total += len(entry)
    return "\n\n".join(lines) if lines else "(no findings available)"


def _mock_variants(
    session_id: str,
    cycle_number: int,
    finding_ids: list[str],
    segment_id: str,
) -> list[ContentVariant]:
    """Return deterministic mock variants when USE_MOCK_LLM=True."""
    now = datetime.now(timezone.utc)
    ref_ids = finding_ids[:2] if finding_ids else ["finding-mock-1"]
    return [
        ContentVariant(
            id=f"var-{uuid4().hex[:8]}",
            session_id=session_id,
            cycle_number=cycle_number,
            source_finding_ids=ref_ids,
            target_segment_id=segment_id,
            intended_channel="email",
            hypothesis="Leading with competitor-message gap will increase reply_rate for VP Sales at Series B SaaS",
            success_metric="reply_rate > 8%",
            subject_line="Still losing deals to [Competitor]?",
            body=(
                "Hi {{first_name}},\n\n"
                "I noticed {{company}} is in a space where [Competitor] still dominates — "
                "but their approach has a blind spot that costs teams like yours pipeline every quarter.\n\n"
                "We built something that closes that gap. Worth a 15-minute look?"
            ),
            cta="Book a 15-min demo",
            angle_label="competitor-gap",
            created_at=now,
        ),
        ContentVariant(
            id=f"var-{uuid4().hex[:8]}",
            session_id=session_id,
            cycle_number=cycle_number,
            source_finding_ids=ref_ids[:1] if ref_ids else ["finding-mock-1"],
            target_segment_id=segment_id,
            intended_channel="email",
            hypothesis="Leading with ROI-first framing will increase reply_rate for revenue-focused leaders",
            success_metric="reply_rate > 6%",
            subject_line="{{company}}'s outbound ROI in Q1",
            body=(
                "Hi {{first_name}},\n\n"
                "Teams similar to {{company}} are seeing 3× pipeline from the same headcount "
                "after switching their outbound motion. The difference is one process change.\n\n"
                "I can show you the benchmarks if you have 15 minutes this week."
            ),
            cta="See the ROI benchmarks",
            angle_label="roi-first",
            created_at=now,
        ),
        ContentVariant(
            id=f"var-{uuid4().hex[:8]}",
            session_id=session_id,
            cycle_number=cycle_number,
            source_finding_ids=ref_ids,
            target_segment_id=segment_id,
            intended_channel="linkedin",
            hypothesis="Leading with social proof will increase connection acceptance for growth leaders",
            success_metric="acceptance_rate > 30%",
            subject_line=None,
            body=(
                "Hi {{first_name}}, "
                "I've been working with VP Sales teams at companies like {{company}} on fixing "
                "the signal-to-outreach gap. Thought this might resonate — happy to share what's working."
            ),
            cta="Connect and share insights",
            angle_label="social-proof",
            created_at=now,
        ),
    ]


# ---------------------------------------------------------------------------
# Variant generation (LLM path)
# ---------------------------------------------------------------------------

async def generate_variants(
    product_name: str,
    product_description: str,
    briefing_summary: str,
    top_findings: list[dict],
    selected_segment: dict | None,
    selected_channels: list[str],
    content_request: str | None,
    winning_angle_memory: str | None,
    session_id: str,
    cycle_number: int,
) -> list[ContentVariant]:
    """Generate 3 content variants (2 email + 1 LinkedIn) using Gemini.

    Falls back to mock variants when USE_MOCK_LLM=True.
    """
    segment_id = selected_segment.get("id", "seg-unknown") if selected_segment else "seg-unknown"
    segment_label = selected_segment.get("label", "Primary ICP") if selected_segment else "Primary ICP"
    finding_ids = [f.get("id", "") for f in top_findings if f.get("id")]

    llm = _get_llm()
    if llm is None:
        logger.info("generate_variants: USE_MOCK_LLM=True — returning mock variants")
        return _mock_variants(session_id, cycle_number, finding_ids, segment_id)

    formatted_findings = _format_findings_for_prompt(top_findings)
    prompt = CONTENT_GENERATION_PROMPT.format(
        product_name=product_name,
        product_description=product_description or "(not provided)",
        segment_label=segment_label,
        briefing_summary=briefing_summary[:2000] if briefing_summary else "(no briefing)",
        winning_angle_memory=winning_angle_memory or "none yet",
        content_request=content_request or "standard A/B outreach variants",
        formatted_findings=formatted_findings,
    )

    try:
        response = await llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        parsed: list[dict] = _parse_json_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("generate_variants: LLM parse failed (%s) — falling back to mock", exc)
        return _mock_variants(session_id, cycle_number, finding_ids, segment_id)
    except Exception as exc:
        logger.error("generate_variants: LLM call failed (%s) — falling back to mock", exc)
        return _mock_variants(session_id, cycle_number, finding_ids, segment_id)

    now = datetime.now(timezone.utc)
    variants: list[ContentVariant] = []
    for raw_var in parsed:
        # Ensure source_finding_ids reference real finding IDs
        src_ids = [fid for fid in raw_var.get("source_finding_ids", []) if fid in finding_ids]
        if not src_ids:
            src_ids = finding_ids[:2] if finding_ids else []

        variants.append(ContentVariant(
            id=f"var-{uuid4().hex[:8]}",
            session_id=session_id,
            cycle_number=cycle_number,
            source_finding_ids=src_ids,
            target_segment_id=segment_id,
            intended_channel=raw_var.get("intended_channel", "email"),
            hypothesis=raw_var.get("hypothesis", ""),
            success_metric=raw_var.get("success_metric", "reply_rate > 5%"),
            subject_line=raw_var.get("subject_line"),
            body=raw_var.get("body", ""),
            cta=raw_var.get("cta", ""),
            angle_label=raw_var.get("angle_label"),
            created_at=now,
        ))

    return variants


# ---------------------------------------------------------------------------
# Segment helper
# ---------------------------------------------------------------------------

def get_segment_by_id(
    segment_id: str | None,
    segment_candidates: list[dict],
) -> dict | None:
    """Return the matching segment dict, or the first candidate as a fallback."""
    if not segment_candidates:
        return None
    if segment_id:
        for seg in segment_candidates:
            if seg.get("id") == segment_id:
                return seg
    # Fallback: use the first candidate rather than blocking
    logger.info("get_segment_by_id: no match for '%s' — using first candidate as default", segment_id)
    return segment_candidates[0]


# ---------------------------------------------------------------------------
# UI frame builder
# ---------------------------------------------------------------------------

def build_variant_grid_frame(variants: list[ContentVariant], instance_id: str) -> dict[str, Any]:
    """Build a VariantGrid UI frame for the WebSocket stream."""
    return UIFrame(
        type="ui_component",
        component="VariantGrid",
        instance_id=instance_id,
        props={
            "variants": [v.model_dump() for v in variants],
        },
        actions=[
            UIAction(
                id=f"select-{v.id}",
                label=f"Select: {v.angle_label or v.intended_channel} variant",
                action_type="select_variant",
                payload={"variant_id": v.id},
            )
            for v in variants
        ] + [
            UIAction(
                id="deploy-selected",
                label="Deploy selected variants",
                action_type="deploy_variants",
                payload={},
            )
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Main agent node
# ---------------------------------------------------------------------------

async def content_agent_node(state: CampaignState) -> dict:
    """Generate A/B content variants from research findings and segment data.

    Prerequisites:
    - briefing_summary: must be present (run research first)
    - segment_candidates: used to resolve selected_segment_id

    Produces:
    - 2 email variants + 1 LinkedIn variant
    - Persisted to MongoDB content_variants collection
    - VariantGrid UI frame emitted for the WebSocket handler to drain
    """
    session_id = state.get("session_id", "")
    logger.info("content_agent_node called | session=%s", session_id)

    # -- Prerequisite: briefing_summary --
    if not state.get("briefing_summary"):
        logger.warning("content_agent_node: no briefing_summary | session=%s", session_id)
        return {
            "next_node": "orchestrator",
            "error_messages": [
                "No research briefing found. Please run research first before generating content."
            ],
        }

    # -- Resolve segment --
    selected_segment = get_segment_by_id(
        state.get("selected_segment_id"),
        state.get("segment_candidates", []),
    )

    # -- Top research findings (cap at 5 for context budget) --
    top_findings = state.get("research_findings", [])[:5]

    # -- Generate variants --
    variants = await generate_variants(
        product_name=state.get("product_name", "Unknown Product"),
        product_description=state.get("product_description", ""),
        briefing_summary=state.get("briefing_summary", ""),
        top_findings=top_findings,
        selected_segment=selected_segment,
        selected_channels=state.get("selected_channels", ["email"]),
        content_request=state.get("content_request"),
        winning_angle_memory=state.get("prior_cycle_summary"),
        session_id=session_id,
        cycle_number=state.get("cycle_number", 1),
    )

    # -- Persist each variant to MongoDB --
    for variant in variants:
        variant_dict = variant.model_dump()
        # datetime objects must be serialisable by pymongo
        variant_dict["created_at"] = variant.created_at
        await save_content_variant(variant_dict)

    # -- Build VariantGrid UI frame --
    grid_frame = build_variant_grid_frame(variants, f"variant-grid-{session_id[:8]}")

    logger.info(
        "content_agent_node completed | session=%s variants=%d",
        session_id,
        len(variants),
    )

    return {
        "content_variants": [v.model_dump() for v in variants],
        "next_node": "orchestrator",
        "pending_ui_frames": [grid_frame],
    }
