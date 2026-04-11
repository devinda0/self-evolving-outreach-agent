"""Content Agent — Advanced two-phase content generation with prospect personalization.

Phase 1 (Strategy): Generates hypothesis-driven content strategies grounded in
research findings, with the user's **last prompt weighted highest** in shaping
the creative direction, tone, and focus.

Phase 2 (Personalization): For each target prospect, produces a deeply
personalized variant that references the prospect's name, role, company,
recommended angle, and any personalization_fields from enrichment.

Visual artifacts: Generates HTML-based visual campaign assets (flyers, banners)
that can be rendered or screenshot'd into images.

Every variant carries:
- source_finding_ids: IDs of the research findings that motivate this content
- hypothesis: "Leading with [angle] will increase [metric] for [segment]"
- success_metric: measurable target (e.g. "reply_rate > 8%")
- angle_label: concise descriptor (e.g. "competitor-gap", "roi-first", "pain-led")
- personalized_for: prospect ID this variant was tailored for (if personalized)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.llm import get_llm
from app.db.crud import save_content_variant
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.intelligence import ContentVariant
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts — two-phase system
# ---------------------------------------------------------------------------

# Phase 1: Strategy generation — last prompt is the PRIMARY DIRECTIVE
STRATEGY_PROMPT = """\
You are a world-class B2B outreach strategist and copywriter.

╔══════════════════════════════════════════════════════════════════╗
║  PRIMARY DIRECTIVE (from the user's latest message — this is   ║
║  your #1 priority and MUST shape every variant you produce):   ║
║                                                                ║
║  {last_user_message}                                           ║
╚══════════════════════════════════════════════════════════════════╝

The above directive takes HIGHEST PRIORITY. If it conflicts with any background
context below, the directive wins. Shape your tone, angle, focus, and
messaging strategy around what the user just asked for.

--- BACKGROUND CONTEXT (use to inform, but do NOT override the directive) ---

Product: {product_name}
Product description: {product_description}
Target segment: {segment_label}
Segment description: {segment_description}
Selected channels: {selected_channels}
Prior winning angles: {winning_angle_memory}

Research briefing (condensed):
{briefing_summary}

Top research findings (cite by ID in source_finding_ids):
{formatted_findings}

--- TARGET PROSPECTS (personalise content for EACH person) ---
{formatted_prospects}

--- INSTRUCTIONS ---

Generate exactly {variant_count} outreach variants.

For EACH variant:
1. It MUST be deeply personalised for a specific target prospect listed above.
   - Reference their actual name, title, company, and industry context.
   - Use the prospect's recommended angle ({prospect_angles}) to shape the message.
   - Incorporate any personalization_fields (recent posts, company news, etc.).
2. The subject line (email) or opening (LinkedIn) must feel hand-written for THAT person.
3. The body must connect the prospect's specific situation to the product's value.
4. Each variant must test a DIFFERENT strategic hypothesis — not stylistic rewording.

Rules:
- Do NOT use generic template tokens like {{{{first_name}}}} or {{{{company}}}}.
  Write the actual prospect's name and company directly into the content.
- subject_line is required for email, null for linkedin.
- source_finding_ids must reference IDs from the findings above.
- hypothesis format: "Leading with [angle] will increase [metric] for [prospect_name] at [company]"
- success_metric format: "<metric_name> > <threshold>%"

Output ONLY a valid JSON array of {variant_count} objects. No prose, no markdown fences.
Each object:
{{
  "intended_channel": "email" | "linkedin",
  "hypothesis": "...",
  "success_metric": "...",
  "source_finding_ids": ["..."],
  "subject_line": "..." | null,
  "body": "...",
  "cta": "...",
  "angle_label": "...",
  "personalized_for": "prospect_id"
}}
"""

# Visual artifact prompt — generates an HTML flyer/banner
VISUAL_ARTIFACT_PROMPT = """\
You are a visual campaign designer. Create an HTML email-safe visual asset
based on the campaign context below.

╔══════════════════════════════════════════════════════════════════╗
║  USER'S CREATIVE DIRECTION:                                    ║
║  {last_user_message}                                           ║
╚══════════════════════════════════════════════════════════════════╝

Product: {product_name}
Key value proposition: {value_prop}
Target audience: {segment_label}
Campaign tone: derived from the user's directive above

Generate a single self-contained HTML snippet (max 600px wide) for a campaign
visual asset. The HTML must:
- Be a complete, self-contained snippet using only inline CSS (no external assets)
- Use a modern, professional design with gradients, shadows, and clean typography
- Include: headline, 2-3 bullet points of value, a CTA button, and brand name
- Use a compelling color scheme that matches a professional B2B aesthetic
- Be email-client safe (table-based layout, inline styles)

Output ONLY the raw HTML. No markdown fences, no explanation.
"""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _get_llm(temperature: float = 0.4):
    return get_llm(temperature=temperature)


def _parse_json_response(content: str) -> list[dict]:
    """Strip optional markdown fences and parse JSON array from LLM output."""
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1 :]
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


def _format_prospects_for_prompt(prospects: list[dict], max_prospects: int = 5) -> str:
    """Format prospect cards into a structured block for the generation prompt."""
    if not prospects:
        return "(no prospects available — use generic {{first_name}} and {{company}} tokens)"

    lines = []
    for p in prospects[:max_prospects]:
        p_fields = p.get("personalization_fields", {})
        extras = ""
        if p_fields:
            extras = "\n    ".join(f"{k}: {v}" for k, v in p_fields.items())
            extras = f"\n    Personalization context:\n    {extras}"

        entry = (
            f"Prospect ID: {p.get('id', 'unknown')}\n"
            f"  Name: {p.get('name', 'Unknown')}\n"
            f"  Title: {p.get('title', 'Unknown')}\n"
            f"  Company: {p.get('company', 'Unknown')}\n"
            f"  Email: {p.get('email', 'N/A')}\n"
            f"  Recommended angle: {p.get('angle_recommendation', 'value-proposition')}\n"
            f"  Recommended channel: {p.get('channel_recommendation', 'email')}\n"
            f"  Fit score: {p.get('fit_score', 0.5):.2f}"
            f"{extras}"
        )
        lines.append(entry)
    return "\n\n".join(lines)


def _extract_last_user_message(messages: list[Any]) -> str:
    """Extract the most recent user/human message from the conversation.

    This is the highest-priority signal for content direction.
    """
    for msg in reversed(messages):
        # LangChain BaseMessage
        if hasattr(msg, "type") and hasattr(msg, "content"):
            if msg.type == "human":
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                return content[:1000]
        # Plain dict
        elif isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", ""))[:1000]
    return ""


def _get_selected_prospects(state: CampaignState) -> list[dict]:
    """Get the target prospects for personalized content generation.

    Priority: selected_prospect_ids → all prospect_cards → empty list.
    """
    all_prospects = state.get("prospect_cards", [])
    selected_ids = set(state.get("selected_prospect_ids", []))

    if selected_ids:
        selected = [p for p in all_prospects if p.get("id") in selected_ids]
        if selected:
            return selected

    # Fall back to all scored prospects (limit to top 5 by fit_score)
    if all_prospects:
        sorted_prospects = sorted(
            all_prospects, key=lambda p: p.get("fit_score", 0.0), reverse=True
        )
        return sorted_prospects[:5]

    return []


def _mock_variants(
    session_id: str,
    cycle_number: int,
    finding_ids: list[str],
    segment_id: str,
    prospects: list[dict] | None = None,
) -> list[ContentVariant]:
    """Return deterministic mock variants when USE_MOCK_LLM=True.

    If prospects are provided, generates personalized mock variants.
    """
    now = datetime.now(timezone.utc)
    ref_ids = finding_ids[:2] if finding_ids else ["finding-mock-1"]
    variants: list[ContentVariant] = []

    if prospects:
        # Generate one personalized variant per prospect (up to 3)
        angles = [
            ("pain-led", "email", "reply_rate > 8%"),
            ("roi-first", "email", "reply_rate > 6%"),
            ("social-proof", "linkedin", "acceptance_rate > 30%"),
        ]
        for i, prospect in enumerate(prospects[:3]):
            angle_label, channel, metric = angles[i % len(angles)]
            name = prospect.get("name", "there")
            first_name = name.split()[0] if name else "there"
            company = prospect.get("company", "your company")
            title = prospect.get("title", "")

            if channel == "email":
                subject = f"Cutting through the noise at {company}"
                body = (
                    f"Hi {first_name},\n\n"
                    f"As {title} at {company}, you're likely juggling multiple priorities "
                    f"that demand clearer data and faster decisions.\n\n"
                    f"We've helped teams in similar positions cut their operational overhead "
                    f"by 30% — and I'd love to show you how it could work for {company}.\n\n"
                    f"Worth a quick 15-minute look?"
                )
            else:
                subject = None
                body = (
                    f"Hi {first_name}, I've been following {company}'s growth and noticed "
                    f"some interesting parallels with teams we've helped as {title}. "
                    f"Would love to share what's working — happy to connect."
                )

            variants.append(
                ContentVariant(
                    id=f"var-{uuid4().hex[:8]}",
                    session_id=session_id,
                    cycle_number=cycle_number,
                    source_finding_ids=ref_ids[:2] if ref_ids else [],
                    target_segment_id=segment_id,
                    intended_channel=channel,
                    hypothesis=f"Leading with {angle_label} will increase {metric.split('>')[0].strip()} for {first_name} at {company}",
                    success_metric=metric,
                    subject_line=subject,
                    body=body,
                    cta="Book a 15-min demo" if channel == "email" else "Connect and share insights",
                    angle_label=angle_label,
                    personalized_for=prospect.get("id"),
                    created_at=now,
                )
            )
    else:
        # Fallback: generic tokenized variants
        variants = [
            ContentVariant(
                id=f"var-{uuid4().hex[:8]}",
                session_id=session_id,
                cycle_number=cycle_number,
                source_finding_ids=ref_ids,
                target_segment_id=segment_id,
                intended_channel="email",
                hypothesis="Leading with competitor-gap will increase reply_rate for target segment",
                success_metric="reply_rate > 8%",
                subject_line="Still losing deals to [Competitor]?",
                body=(
                    "Hi {{first_name}},\n\n"
                    "I noticed {{company}} is in a space where competitors still dominate — "
                    "but their approach has a blind spot that costs teams like yours pipeline.\n\n"
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
                source_finding_ids=ref_ids[:1] if ref_ids else [],
                target_segment_id=segment_id,
                intended_channel="email",
                hypothesis="Leading with ROI-first framing will increase reply_rate for revenue leaders",
                success_metric="reply_rate > 6%",
                subject_line="{{company}}'s outbound ROI this quarter",
                body=(
                    "Hi {{first_name}},\n\n"
                    "Teams similar to {{company}} are seeing 3× pipeline from the same headcount. "
                    "The difference is one process change.\n\n"
                    "I can show you the benchmarks if you have 15 minutes."
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
                hypothesis="Leading with social proof will increase acceptance for growth leaders",
                success_metric="acceptance_rate > 30%",
                subject_line=None,
                body=(
                    "Hi {{first_name}}, "
                    "I've been working with teams like {{company}} on fixing the signal-to-outreach gap. "
                    "Thought this might resonate — happy to share what's working."
                ),
                cta="Connect and share insights",
                angle_label="social-proof",
                created_at=now,
            ),
        ]

    return variants


def _mock_visual_artifact(product_name: str, segment_label: str) -> dict:
    """Return a mock visual artifact when USE_MOCK_LLM=True."""
    return {
        "id": f"visual-{uuid4().hex[:8]}",
        "type": "campaign_flyer",
        "format": "html",
        "content": (
            f'<div style="max-width:600px;margin:0 auto;background:linear-gradient(135deg,#0f172a,#1e293b);'
            f'border-radius:16px;padding:40px;font-family:Arial,sans-serif;color:#e2e8f0;">'
            f'<h1 style="color:#22d3ee;margin:0 0 16px;font-size:28px;">{product_name}</h1>'
            f'<p style="font-size:16px;line-height:1.6;margin:0 0 24px;color:#94a3b8;">'
            f'Empowering {segment_label} with actionable intelligence</p>'
            f'<ul style="list-style:none;padding:0;margin:0 0 24px;">'
            f'<li style="padding:8px 0;border-bottom:1px solid #334155;">✓ Data-driven insights</li>'
            f'<li style="padding:8px 0;border-bottom:1px solid #334155;">✓ Automated compliance</li>'
            f'<li style="padding:8px 0;">✓ Real-time dashboards</li></ul>'
            f'<a href="#" style="display:inline-block;background:#22d3ee;color:#0f172a;'
            f'padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;">'
            f'Get Started →</a></div>'
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Phase 1: Strategy-driven variant generation
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
    last_user_message: str = "",
    prospects: list[dict] | None = None,
) -> list[ContentVariant]:
    """Generate personalized content variants using a two-phase approach.

    Phase 1: LLM generates strategy+content with last_user_message as the
    primary directive and prospect data for deep personalization.

    Falls back to mock variants when USE_MOCK_LLM=True.
    """
    segment_id = selected_segment.get("id", "seg-unknown") if selected_segment else "seg-unknown"
    segment_label = (
        selected_segment.get("label", "Primary ICP") if selected_segment else "Primary ICP"
    )
    segment_description = (
        selected_segment.get("description", "") if selected_segment else ""
    )
    finding_ids = [f.get("id", "") for f in top_findings if f.get("id")]

    llm = _get_llm()
    if llm is None:
        logger.info("generate_variants: USE_MOCK_LLM=True — returning mock variants")
        return _mock_variants(session_id, cycle_number, finding_ids, segment_id, prospects)

    # Determine variant count based on prospects and channels
    effective_prospects = prospects or []
    if effective_prospects:
        variant_count = min(len(effective_prospects), 5)
    else:
        variant_count = min(len(selected_channels) + 1, 3)

    # Build the prospect angles summary
    prospect_angles = set()
    for p in effective_prospects:
        angle = p.get("angle_recommendation", "")
        if angle:
            prospect_angles.add(angle)
    prospect_angles_str = ", ".join(prospect_angles) if prospect_angles else "value-proposition"

    formatted_findings = _format_findings_for_prompt(top_findings)
    formatted_prospects = _format_prospects_for_prompt(effective_prospects)

    # Use content_request as last_user_message fallback
    effective_directive = last_user_message or content_request or "Generate compelling outreach content"

    prompt = STRATEGY_PROMPT.format(
        last_user_message=effective_directive,
        product_name=product_name,
        product_description=product_description or "(not provided)",
        segment_label=segment_label,
        segment_description=segment_description[:500] if segment_description else "(none)",
        selected_channels=", ".join(selected_channels) if selected_channels else "email",
        winning_angle_memory=winning_angle_memory or "none yet",
        briefing_summary=briefing_summary[:2000] if briefing_summary else "(no briefing)",
        formatted_findings=formatted_findings,
        formatted_prospects=formatted_prospects,
        variant_count=variant_count,
        prospect_angles=prospect_angles_str,
    )

    try:
        response = await llm.ainvoke(prompt)
        raw = str(response.content) if hasattr(response, "content") else str(response)
        parsed: list[dict] = _parse_json_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("generate_variants: LLM parse failed (%s) — falling back to mock", exc)
        return _mock_variants(session_id, cycle_number, finding_ids, segment_id, prospects)
    except Exception as exc:
        logger.error("generate_variants: LLM call failed (%s) — falling back to mock", exc)
        return _mock_variants(session_id, cycle_number, finding_ids, segment_id, prospects)

    now = datetime.now(timezone.utc)
    variants: list[ContentVariant] = []
    for raw_var in parsed:
        src_ids = [fid for fid in raw_var.get("source_finding_ids", []) if fid in finding_ids]
        if not src_ids:
            src_ids = finding_ids[:2] if finding_ids else []

        variants.append(
            ContentVariant(
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
                personalized_for=raw_var.get("personalized_for"),
                created_at=now,
            )
        )

    return variants


# ---------------------------------------------------------------------------
# Phase 2: Visual artifact generation
# ---------------------------------------------------------------------------


async def generate_visual_artifact(
    product_name: str,
    segment_label: str,
    briefing_summary: str,
    last_user_message: str,
) -> dict:
    """Generate an HTML visual campaign asset (flyer/banner).

    Returns a dict with id, type, format, content (HTML), and created_at.
    """
    llm = _get_llm(temperature=0.6)
    if llm is None:
        return _mock_visual_artifact(product_name, segment_label)

    # Extract a short value proposition from the briefing
    value_prop = briefing_summary[:300] if briefing_summary else product_name

    prompt = VISUAL_ARTIFACT_PROMPT.format(
        last_user_message=last_user_message or "Create a professional campaign visual",
        product_name=product_name,
        value_prop=value_prop,
        segment_label=segment_label,
    )

    try:
        response = await llm.ainvoke(prompt)
        html_content = str(response.content) if hasattr(response, "content") else str(response)
        # Strip markdown fences if present
        html_content = html_content.strip()
        if html_content.startswith("```"):
            first_newline = html_content.find("\n")
            if first_newline != -1:
                html_content = html_content[first_newline + 1:]
            if html_content.endswith("```"):
                html_content = html_content[:-3]
            html_content = html_content.strip()
    except Exception as exc:
        logger.error("generate_visual_artifact: LLM failed (%s) — returning mock", exc)
        return _mock_visual_artifact(product_name, segment_label)

    return {
        "id": f"visual-{uuid4().hex[:8]}",
        "type": "campaign_flyer",
        "format": "html",
        "content": html_content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


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
    logger.info(
        "get_segment_by_id: no match for '%s' — using first candidate as default", segment_id
    )
    return segment_candidates[0]


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_variant_grid_frame(variants: list[ContentVariant], instance_id: str) -> dict[str, Any]:
    """Build a VariantGrid UI frame for the WebSocket stream."""
    return UIFrame(
        type="ui_component",
        component="VariantGrid",
        instance_id=instance_id,
        props={
            "variants": [v.model_dump(mode="json") for v in variants],
        },
        actions=[
            UIAction(
                id=f"select-{v.id}",
                label=f"Select: {v.angle_label or v.intended_channel} variant",
                action_type="select_variant",
                payload={"variant_id": v.id},
            )
            for v in variants
        ]
        + [
            UIAction(
                id="deploy-selected",
                label="Deploy selected variants",
                action_type="deploy_variants",
                payload={},
            )
        ],
    ).model_dump()


def build_visual_artifact_frame(artifact: dict, instance_id: str) -> dict[str, Any]:
    """Build a VisualArtifact UI frame for the WebSocket stream."""
    return UIFrame(
        type="ui_component",
        component="VisualArtifact",
        instance_id=instance_id,
        props={
            "artifact": artifact,
        },
        actions=[
            UIAction(
                id=f"approve-{artifact.get('id', 'unknown')}",
                label="Approve visual",
                action_type="approve_visual",
                payload={"artifact_id": artifact.get("id")},
            ),
            UIAction(
                id=f"regenerate-{artifact.get('id', 'unknown')}",
                label="Regenerate visual",
                action_type="regenerate_visual",
                payload={"artifact_id": artifact.get("id")},
            ),
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Main agent node
# ---------------------------------------------------------------------------


async def content_agent_node(state: CampaignState) -> dict:
    """Generate personalized A/B content variants and visual artifacts.

    Two-phase generation:
    1. Extract last user message as primary creative directive
    2. Generate prospect-personalized variants with research grounding
    3. Generate a visual campaign artifact (HTML flyer)

    Prerequisites:
    - briefing_summary: must be present (run research first)
    - segment_candidates: used to resolve selected_segment_id

    Produces:
    - Personalized variants per prospect (or fallback tokenized variants)
    - Visual campaign artifact (HTML)
    - Persisted to MongoDB
    - VariantGrid + VisualArtifact UI frames for WebSocket
    """
    session_id = state.get("session_id", "")
    briefing = state.get("briefing_summary")
    findings_count = len(state.get("research_findings", []))
    segment_id = state.get("selected_segment_id")
    segment_candidates_count = len(state.get("segment_candidates", []))
    logger.info(
        "content_agent_node called | session=%s briefing=%s briefing_len=%d "
        "findings=%d segment_id=%s candidates=%d",
        session_id,
        bool(briefing),
        len(briefing) if briefing else 0,
        findings_count,
        segment_id,
        segment_candidates_count,
    )

    # -- Prerequisite: briefing_summary --
    if not state.get("briefing_summary"):
        logger.warning("content_agent_node: no briefing_summary | session=%s", session_id)
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "error_messages": [
                "No research briefing found. Please run research first before generating content."
            ],
        }

    # -- Extract last user message (PRIMARY DIRECTIVE) --
    last_user_message = _extract_last_user_message(state.get("messages", []))
    logger.info(
        "content_agent_node: last_user_message=%s | session=%s",
        last_user_message[:100] if last_user_message else "(empty)",
        session_id,
    )

    # -- Build scoped context bundle via memory manager --
    bundle = await memory_manager.build_context_bundle(state, "content")

    # -- Resolve segment from bundle (falls back to first candidate) --
    selected_segment = bundle.get("selected_segment") or get_segment_by_id(
        state.get("selected_segment_id"),
        state.get("segment_candidates", []),
    )

    # -- Top research findings from bundle (already scoped and sorted) --
    top_findings = bundle.get("source_findings") or state.get("research_findings", [])[:5]

    # -- Winning angle memory from bundle --
    winning_angle_memory = bundle.get("winning_angle_memory") or state.get("prior_cycle_summary")

    # -- Get target prospects for personalization --
    prospects = _get_selected_prospects(state)
    logger.info(
        "content_agent_node: prospects=%d for personalization | session=%s",
        len(prospects),
        session_id,
    )

    # -- Phase 1: Generate personalized content variants --
    variants = await generate_variants(
        product_name=state.get("product_name", "Unknown Product"),
        product_description=state.get("product_description", ""),
        briefing_summary=state.get("briefing_summary") or "",
        top_findings=top_findings,
        selected_segment=selected_segment,
        selected_channels=state.get("selected_channels", ["email"]),
        content_request=state.get("content_request"),
        winning_angle_memory=winning_angle_memory,
        session_id=session_id,
        cycle_number=state.get("cycle_number", 1),
        last_user_message=last_user_message,
        prospects=prospects,
    )

    # -- Phase 2: Generate visual artifact --
    segment_label = (
        selected_segment.get("label", "Target Audience") if selected_segment else "Target Audience"
    )
    visual_artifact = await generate_visual_artifact(
        product_name=state.get("product_name", "Unknown Product"),
        segment_label=segment_label,
        briefing_summary=state.get("briefing_summary") or "",
        last_user_message=last_user_message,
    )

    # -- Persist each variant to MongoDB --
    for variant in variants:
        variant_dict = variant.model_dump()
        variant_dict["created_at"] = variant.created_at
        await save_content_variant(variant_dict)

    # -- Build UI frames --
    ui_frames: list[dict] = []
    grid_frame = build_variant_grid_frame(variants, f"variant-grid-{session_id[:8]}")
    ui_frames.append(grid_frame)

    visual_frame = build_visual_artifact_frame(
        visual_artifact, f"visual-artifact-{session_id[:8]}"
    )
    ui_frames.append(visual_frame)

    # Build response message summarizing what was generated
    user_directive = state.get("user_directive")
    channels_used = list({v.intended_channel for v in variants})
    angles_used = [v.angle_label for v in variants if v.angle_label]
    personalized_count = sum(1 for v in variants if v.personalized_for)

    directive_note = ""
    if user_directive:
        directive_note = f" based on your direction: \"{user_directive}\""

    personalization_note = ""
    if personalized_count > 0:
        personalization_note = f", each personalized for a specific prospect"

    response_message = (
        f"Content generation complete{directive_note}. "
        f"Created {len(variants)} variant(s) across {', '.join(channels_used)}{personalization_note}. "
        f"Angles: {', '.join(angles_used) if angles_used else 'various'}. "
        "Review and select the variants you'd like to deploy below."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"content_response_{uuid4().hex[:8]}",
        props={"content": response_message, "role": "assistant"},
        actions=[],
    ).model_dump()
    ui_frames.insert(0, response_frame)

    logger.info(
        "content_agent_node completed | session=%s variants=%d visual=%s",
        session_id,
        len(variants),
        visual_artifact.get("id"),
    )

    return {
        "content_variants": [v.model_dump(mode="json") for v in variants],
        "visual_artifacts": [visual_artifact],
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }
