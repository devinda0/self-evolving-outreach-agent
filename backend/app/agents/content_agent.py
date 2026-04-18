"""Content Agent — Multi-phase intelligent content generation with disambiguation,
A/B testing, and iterative refinement.

Architecture:
  Phase 1 (Clarify): Analyses context for ambiguity and gaps, asks targeted questions
      to fully understand sender identity, recipient context, tone, goals, and constraints.
      Questions are asked in a single bounded batch (max 5 questions).

  Phase 2 (Generate): With fully resolved context, generates hypothesis-driven A/B
      content variants grounded in research findings, prospect personalization, and
      prior learnings. Each variant tests a distinct strategic angle.

  Phase 3 (Refine): User can iteratively refine generated content via free-text prompts.
      The agent applies targeted edits while preserving traceability and variant structure.

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
# Prompts
# ---------------------------------------------------------------------------

CLARIFICATION_ANALYSIS_PROMPT = """\
You are a world-class B2B outreach strategist preparing to create hyper-personalized
outreach content. Before generating ANYTHING, you must identify critical gaps
in your understanding.

You have access to the following context:

--- PRODUCT ---
Name: {product_name}
Description: {product_description}

--- TARGET ---
Segment: {segment_label}
Segment description: {segment_description}

--- CHANNELS ---
{selected_channels}

--- RESEARCH BRIEFING ---
{briefing_summary}

--- TOP FINDINGS ---
{formatted_findings}

--- PROSPECTS ---
{formatted_prospects}

--- USER'S REQUEST ---
{last_user_message}

--- PRIOR WINNING ANGLES ---
{winning_angle_memory}

--- PREVIOUS CLARIFICATIONS (already resolved) ---
{prior_clarifications}

--- INSTRUCTIONS ---

Analyse ALL the context above and determine whether you have enough information
to create truly exceptional, human-quality outreach content.

Think about:
1. SENDER IDENTITY — Do you know who is sending this? Their role, company positioning, credibility signals?
2. VALUE PROPOSITION CLARITY — Is the specific value prop for THIS audience crystal-clear, or vague?
3. TONE & VOICE — Has the user specified any tone preferences (formal, casual, provocative, consultative)?
4. GOAL SPECIFICITY — Do you know the exact desired outcome (book a demo, start a trial, get a reply)?
5. CONSTRAINTS — Any compliance requirements, words to avoid, length limits, or brand guidelines?
6. DIFFERENTIATORS — Do you understand what makes this product different from alternatives the prospects know?
7. RELATIONSHIP CONTEXT — Is this cold outreach, warm follow-up, existing relationship?
8. TIMING/URGENCY — Any time-sensitive hooks (events, announcements, seasonal relevance)?

If the context is SUFFICIENT to generate great content, return:
{{"needs_clarification": false, "questions": []}}

If there are genuine gaps that would significantly improve content quality, return
at most 5 targeted questions. Each question should:
- Be specific and actionable (not generic)
- Include 2-4 suggested options where appropriate
- Explain briefly WHY it matters for content quality

Output ONLY valid JSON. No prose, no markdown fences.
{{
  "needs_clarification": true | false,
  "confidence_score": <0.0-1.0 how confident you are about generating great content now>,
  "questions": [
    {{
      "id": "q1",
      "question": "...",
      "why_it_matters": "...",
      "suggested_options": ["option1", "option2", "option3"],
      "category": "sender_identity | value_prop | tone | goal | constraints | differentiator | relationship | timing"
    }}
  ]
}}
"""

STRATEGY_PROMPT = """\
You are a world-class B2B outreach strategist and copywriter with 20 years of experience
writing outreach that gets responses from busy executives.

╔══════════════════════════════════════════════════════════════════╗
║  PRIMARY DIRECTIVE (from the user's latest message — this is   ║
║  your #1 priority and MUST shape every variant you produce):   ║
║                                                                ║
║  {last_user_message}                                           ║
╚══════════════════════════════════════════════════════════════════╝

The above directive takes HIGHEST PRIORITY. If it conflicts with any background
context below, the directive wins.

--- CLARIFIED CONTEXT (resolved from user Q&A — treat as ground truth) ---
{clarification_context}

--- BACKGROUND CONTEXT ---
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

--- A/B TESTING STRATEGY ---
You are generating {variant_count} variants that MUST test genuinely different
strategic hypotheses — not just stylistic rewording. Each variant should differ in:
- The core angle (pain point, benefit, social proof, authority, curiosity)
- The opening hook strategy
- The CTA framing
Think like a growth scientist running split tests.

--- INSTRUCTIONS ---

For EACH variant:
1. It MUST be deeply personalised for a specific target prospect listed above.
   - Reference their actual name, title, company, and industry context.
   - Use the prospect's recommended angle ({prospect_angles}) to shape the message.
   - Incorporate any personalization_fields (recent posts, company news, etc.).
2. The subject line (email) or opening (LinkedIn) must feel hand-written for THAT person.
3. The body must connect the prospect's specific situation to the product's value.
4. Each variant must test a DIFFERENT strategic hypothesis — not stylistic rewording.
5. Write like a thoughtful human — no marketing jargon, no filler, no generic phrasing.
6. Every sentence must earn its place. If it doesn't add value, cut it.

Rules:
- PERSONALISATION TOKENS: If the prospect Name is shown as {{{{first_name}}}} and Company
  as {{{{company}}}}, this is a multi-recipient campaign. You MUST write {{{{first_name}}}}
  and {{{{company}}}} verbatim in your content — they will be swapped for each recipient's
  real details at send time. Otherwise (actual name provided), write the name directly.
- Do NOT start the body with a greeting like "Hi {{{{first_name}}}}", "Hello", or "Dear".
  A greeting is added automatically by the system — begin the body with the first content
  sentence.
- subject_line is required for email, null for linkedin.
- source_finding_ids must reference IDs from the findings above.
- hypothesis format: "Leading with [angle] will increase [metric] for [prospect_name] at [company]"
- success_metric format: "<metric_name> > <threshold>%"
- ab_group: assign each variant a letter starting from "A" (A, B, C...)

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
  "personalized_for": "prospect_id",
  "ab_group": "A" | "B" | "C" | ...
}}
"""

REFINEMENT_PROMPT = """\
You are a world-class copywriting editor. The user wants to refine the existing
outreach content below based on their specific feedback.

--- USER'S REFINEMENT REQUEST ---
{refinement_prompt}

--- CURRENT VARIANTS ---
{current_variants_json}

--- CLARIFIED CONTEXT (established ground truth) ---
{clarification_context}

--- INSTRUCTIONS ---

Apply the user's refinement to ALL variants while:
1. Preserving the distinct strategic hypothesis of each variant
2. Maintaining personalization for each prospect
3. Keeping source_finding_ids and traceability intact
4. Respecting the A/B testing structure

If the user's request applies to only some variants, only modify those.
If the user wants a new variant added, create it with a new hypothesis.

Output ONLY a valid JSON array of the updated variants. Same structure as input.
No prose, no markdown fences.
"""

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


def _parse_json_response(content: str) -> list[dict[str, Any]] | dict[str, Any]:
    """Strip optional markdown fences and parse JSON from LLM output."""
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


def _format_prospects_for_prompt(prospects: list[dict], max_prospects: int = 5) -> str:
    """Format prospect cards into a structured block for the generation prompt."""
    if not prospects:
        return "(no prospects available — use generic {{first_name}} and {{company}} tokens)"

    # Detect multi-recipient (generalized) mode
    if len(prospects) == 1 and prospects[0].get("id") == "generalized":
        return (
            "MULTI-RECIPIENT CAMPAIGN — content will be sent to multiple different prospects.\n"
            "  Name: {{first_name}}  ← write this token verbatim in your content\n"
            "  Company: {{company}}  ← write this token verbatim in your content\n"
            "Do NOT reference a specific title, role, or company. Keep the message broadly\n"
            "relevant. Use {{first_name}} and {{company}} wherever you'd normally write a\n"
            "person's name or company name.\n"
            "Recommended channel: email\n"
            "Recommended angle: value-proposition"
        )

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


def _format_clarifications(clarifications: list[dict]) -> str:
    """Format resolved Q&A pairs for prompt injection."""
    if not clarifications:
        return "(none — no clarifications resolved yet)"
    lines = []
    for qa in clarifications:
        lines.append(f"Q: {qa.get('question', '?')}\nA: {qa.get('answer', '(no answer)')}")
    return "\n\n".join(lines)


def _extract_last_user_message(messages: list[Any]) -> str:
    """Extract the most recent user/human message from the conversation."""
    for msg in reversed(messages):
        if hasattr(msg, "type") and hasattr(msg, "content"):
            if msg.type == "human":
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                return content[:1000]
        elif isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", ""))[:1000]
    return ""


_GENERALIZED_PROSPECT = {
    "id": "generalized",
    "name": "{{first_name}}",
    "company": "{{company}}",
    "title": "",  # no specific title — keep content role-agnostic
    "email": "",
    "fit_score": 0.5,
    "urgency_score": 0.5,
    "angle_recommendation": "value-proposition",
    "channel_recommendation": "email",
}


def _get_selected_prospects(state: CampaignState) -> list[dict]:
    """Get the target prospects for content generation.

    Single prospect → return it directly for fully personalized content.
    Multiple prospects → return a generalized placeholder (with {{first_name}} /
    {{company}} tokens) so the LLM writes one campaign-wide template that the
    deployment layer personalizes per recipient.
    """
    all_prospects = state.get("prospect_cards", [])
    selected_ids = set(state.get("selected_prospect_ids", []))

    if selected_ids:
        selected = [p for p in all_prospects if p.get("id") in selected_ids]
        if selected:
            if len(selected) == 1:
                return selected
            # Multiple selected → generalized template content
            return [_GENERALIZED_PROSPECT]

    if all_prospects:
        sorted_prospects = sorted(
            all_prospects, key=lambda p: p.get("fit_score", 0.0), reverse=True
        )
        if len(sorted_prospects) == 1:
            return sorted_prospects[:1]
        # Multiple available → generalized template content
        return [_GENERALIZED_PROSPECT]

    return []


def _has_real_prospect_targets(prospects: list[dict] | None) -> bool:
    """Return True when the target list includes actual recipients."""
    if not prospects:
        return False

    return any(prospect.get("id") != _GENERALIZED_PROSPECT["id"] for prospect in prospects)


# ---------------------------------------------------------------------------
# Phase 1: Clarification analysis
# ---------------------------------------------------------------------------


async def _analyse_clarification_needs(
    product_name: str,
    product_description: str,
    segment_label: str,
    segment_description: str,
    selected_channels: list[str],
    briefing_summary: str,
    top_findings: list[dict],
    prospects: list[dict],
    last_user_message: str,
    winning_angle_memory: str | None,
    prior_clarifications: list[dict],
) -> dict:
    """Ask the LLM to decide if clarification is needed before generating content."""
    llm = _get_llm(temperature=0.2)
    if llm is None:
        # Mock mode — skip clarification
        return {"needs_clarification": False, "confidence_score": 0.9, "questions": []}

    formatted_findings = _format_findings_for_prompt(top_findings)
    formatted_prospects = _format_prospects_for_prompt(prospects)
    prior_qa = _format_clarifications(prior_clarifications)

    prompt = CLARIFICATION_ANALYSIS_PROMPT.format(
        product_name=product_name,
        product_description=product_description or "(not provided)",
        segment_label=segment_label,
        segment_description=segment_description[:500] if segment_description else "(none)",
        selected_channels=", ".join(selected_channels) if selected_channels else "email",
        briefing_summary=briefing_summary[:2000] if briefing_summary else "(no briefing)",
        formatted_findings=formatted_findings,
        formatted_prospects=formatted_prospects,
        last_user_message=last_user_message or "(no specific request)",
        winning_angle_memory=winning_angle_memory or "none yet",
        prior_clarifications=prior_qa,
    )

    try:
        response = await llm.ainvoke(prompt)
        raw = str(response.content) if hasattr(response, "content") else str(response)
        result = _parse_json_response(raw)
        if isinstance(result, list):
            result = result[0] if result else {"needs_clarification": False, "questions": []}
        return result
    except Exception as exc:
        logger.warning("_analyse_clarification_needs failed (%s) — skipping clarification", exc)
        return {"needs_clarification": False, "confidence_score": 0.5, "questions": []}


# ---------------------------------------------------------------------------
# Phase 2: Strategy-driven variant generation
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
    clarification_context: list[dict] | None = None,
) -> list[ContentVariant]:
    """Generate personalized A/B content variants using resolved context.

    This is Phase 2 — called only after clarification is resolved or skipped.
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
    if _has_real_prospect_targets(effective_prospects):
        variant_count = min(len(effective_prospects), 5)
    else:
        variant_count = min(len(selected_channels) + 1, 3)

    # Ensure at least 2 variants for A/B testing
    variant_count = max(variant_count, 2)

    # Build the prospect angles summary
    prospect_angles = set()
    for p in effective_prospects:
        angle = p.get("angle_recommendation", "")
        if angle:
            prospect_angles.add(angle)
    prospect_angles_str = ", ".join(prospect_angles) if prospect_angles else "value-proposition"

    formatted_findings = _format_findings_for_prompt(top_findings)
    formatted_prospects = _format_prospects_for_prompt(effective_prospects)
    clarification_text = _format_clarifications(clarification_context or [])

    effective_directive = last_user_message or content_request or "Generate compelling outreach content"

    prompt = STRATEGY_PROMPT.format(
        last_user_message=effective_directive,
        clarification_context=clarification_text,
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
        parsed_raw = _parse_json_response(raw)
        parsed: list[dict[str, Any]] = parsed_raw if isinstance(parsed_raw, list) else [parsed_raw]
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
# Phase 3: Refinement
# ---------------------------------------------------------------------------


async def refine_variants(
    current_variants: list[dict],
    refinement_prompt: str,
    clarification_context: list[dict] | None = None,
    session_id: str = "",
    cycle_number: int = 1,
) -> list[ContentVariant]:
    """Refine existing variants based on user feedback prompt."""
    llm = _get_llm(temperature=0.3)
    if llm is None:
        logger.info("refine_variants: USE_MOCK_LLM=True — returning variants unchanged")
        now = datetime.now(timezone.utc)
        return [
            ContentVariant(**{**v, "created_at": now}) for v in current_variants
        ]

    clarification_text = _format_clarifications(clarification_context or [])
    current_json = json.dumps(current_variants, indent=2, default=str)

    prompt = REFINEMENT_PROMPT.format(
        refinement_prompt=refinement_prompt,
        current_variants_json=current_json,
        clarification_context=clarification_text,
    )

    try:
        response = await llm.ainvoke(prompt)
        raw = str(response.content) if hasattr(response, "content") else str(response)
        parsed_raw = _parse_json_response(raw)
        parsed: list[dict[str, Any]] = parsed_raw if isinstance(parsed_raw, list) else [parsed_raw]
    except Exception as exc:
        logger.warning("refine_variants: LLM failed (%s) — returning originals", exc)
        now = datetime.now(timezone.utc)
        return [
            ContentVariant(**{**v, "created_at": now}) for v in current_variants
        ]

    now = datetime.now(timezone.utc)
    variants: list[ContentVariant] = []
    for raw_var in parsed:
        variants.append(
            ContentVariant(
                id=raw_var.get("id", f"var-{uuid4().hex[:8]}"),
                session_id=session_id,
                cycle_number=cycle_number,
                source_finding_ids=raw_var.get("source_finding_ids", []),
                target_segment_id=raw_var.get("target_segment_id", "seg-unknown"),
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
# Visual artifact generation
# ---------------------------------------------------------------------------


async def generate_visual_artifact(
    product_name: str,
    segment_label: str,
    briefing_summary: str,
    last_user_message: str,
) -> dict:
    """Generate an HTML visual campaign asset (flyer/banner)."""
    llm = _get_llm(temperature=0.6)
    if llm is None:
        return _mock_visual_artifact(product_name, segment_label)

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
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_variants(
    session_id: str,
    cycle_number: int,
    finding_ids: list[str],
    segment_id: str,
    prospects: list[dict] | None = None,
) -> list[ContentVariant]:
    """Return deterministic mock variants when USE_MOCK_LLM=True."""
    now = datetime.now(timezone.utc)
    ref_ids = finding_ids[:2] if finding_ids else ["finding-mock-1"]
    variants: list[ContentVariant] = []
    effective_prospects = prospects or []

    if _has_real_prospect_targets(effective_prospects):
        angles = [
            ("pain-led", "email", "reply_rate > 8%"),
            ("roi-first", "email", "reply_rate > 6%"),
            ("social-proof", "linkedin", "acceptance_rate > 30%"),
        ]
        for i, prospect in enumerate(effective_prospects[:3]):
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
                    "Teams similar to {{company}} are seeing 3x pipeline from the same headcount. "
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
            f'<li style="padding:8px 0;border-bottom:1px solid #334155;">&#10003; Data-driven insights</li>'
            f'<li style="padding:8px 0;border-bottom:1px solid #334155;">&#10003; Automated compliance</li>'
            f'<li style="padding:8px 0;">&#10003; Real-time dashboards</li></ul>'
            f'<a href="#" style="display:inline-block;background:#22d3ee;color:#0f172a;'
            f'padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;">'
            f'Get Started &#8594;</a></div>'
        ),
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
        "get_segment_by_id: no match for '%s' -- using first candidate as default", segment_id
    )
    return segment_candidates[0]


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_clarification_frame(
    questions: list[dict], confidence_score: float, instance_id: str
) -> dict[str, Any]:
    """Build a ContentClarification UI frame for the WebSocket stream."""
    actions: list[UIAction] = []
    for q in questions:
        q_id = q.get("id", f"q{len(actions)}")
        for opt in q.get("suggested_options", []):
            actions.append(
                UIAction(
                    id=f"clarify-{q_id}-{opt[:20].replace(' ', '_')}",
                    label=opt,
                    action_type="content_clarify_answer",
                    payload={"question_id": q_id, "answer": opt},
                )
            )

    # Add a "skip and generate" action
    actions.append(
        UIAction(
            id="content-skip-clarification",
            label="Skip -- generate with current context",
            action_type="content_skip_clarification",
            payload={},
        )
    )

    return UIFrame(
        type="ui_component",
        component="ContentClarification",
        instance_id=instance_id,
        props={
            "questions": questions,
            "confidence_score": confidence_score,
            "phase": "clarify",
        },
        actions=actions,
    ).model_dump()


def build_variant_grid_frame(variants: list[ContentVariant], instance_id: str) -> dict[str, Any]:
    """Build a VariantGrid UI frame for the WebSocket stream."""
    return UIFrame(
        type="ui_component",
        component="VariantGrid",
        instance_id=instance_id,
        props={
            "variants": [v.model_dump(mode="json") for v in variants],
            "refinement_enabled": True,
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
                id="refine-content",
                label="Refine content",
                action_type="content_refine",
                payload={},
            ),
            UIAction(
                id="deploy-selected",
                label="Deploy selected variants",
                action_type="deploy_variants",
                payload={},
            ),
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
# Node: Clarification phase
# ---------------------------------------------------------------------------


async def content_clarify_node(state: CampaignState) -> dict:
    """Phase 1 -- Analyse context and ask clarification questions if needed.

    If the agent determines it has sufficient context (confidence >= 0.8), it
    skips directly to generation. Otherwise sends a ContentClarification UI frame.

    Safeguards:
    - If clarification answers already exist, skip to generation.
    - If we already asked questions (content_pending_questions non-empty),
      skip to generation to prevent infinite clarification loops.
    - Maximum 1 round of clarification questions.
    """
    session_id = state.get("session_id", "")
    logger.info("content_clarify_node called | session=%s", session_id)

    existing_clarifications = list(state.get("content_clarifications", []))
    pending_questions = list(state.get("content_pending_questions", []))

    # Safeguard: if user has already provided clarification answers, skip to generation
    if existing_clarifications:
        logger.info(
            "content_clarify_node: %d clarification(s) already answered, routing to generate | session=%s",
            len(existing_clarifications),
            session_id,
        )
        bundle = await memory_manager.build_context_bundle(state, "content")
        selected_segment = bundle.get("selected_segment") or get_segment_by_id(
            state.get("selected_segment_id"),
            state.get("segment_candidates", []),
        )
        top_findings = bundle.get("source_findings") or state.get("research_findings", [])[:5]
        winning_angle_memory = bundle.get("winning_angle_memory") or state.get("prior_cycle_summary")
        prospects = _get_selected_prospects(state)
        last_user_message = _extract_last_user_message(state.get("messages", []))
        gen_context = {
            "segment": selected_segment,
            "findings": top_findings,
            "prospects": [p for p in prospects],
            "winning_angle_memory": winning_angle_memory,
            "last_user_message": last_user_message,
            "clarifications": existing_clarifications,
        }
        return {
            "content_phase": "generate",
            "content_generation_context": gen_context,
            "content_pending_questions": [],
            "next_node": "content_generate",
        }

    # Safeguard: if we already asked questions once (pending_questions non-empty),
    # the user has been through a clarification round — don't loop. Proceed to generate.
    if pending_questions:
        logger.info(
            "content_clarify_node: already asked %d question(s) (pending), forcing generation | session=%s",
            len(pending_questions),
            session_id,
        )
        return {"content_phase": "generate", "content_pending_questions": [], "next_node": "content_generate"}

    # If we already have a generation context (user answered questions), skip to generate
    if state.get("content_generation_context"):
        logger.info(
            "content_clarify_node: generation context present, routing to generate | session=%s",
            session_id,
        )
        return {"content_phase": "generate", "next_node": "content_generate"}

    # Prerequisite: briefing_summary
    if not state.get("briefing_summary"):
        logger.warning("content_clarify_node: no briefing_summary | session=%s", session_id)
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "error_messages": [
                "No research briefing found. Please run research first before generating content."
            ],
        }

    last_user_message = _extract_last_user_message(state.get("messages", []))
    bundle = await memory_manager.build_context_bundle(state, "content")

    selected_segment = bundle.get("selected_segment") or get_segment_by_id(
        state.get("selected_segment_id"),
        state.get("segment_candidates", []),
    )
    top_findings = bundle.get("source_findings") or state.get("research_findings", [])[:5]
    winning_angle_memory = bundle.get("winning_angle_memory") or state.get("prior_cycle_summary")
    prospects = _get_selected_prospects(state)

    segment_label = (
        selected_segment.get("label", "Primary ICP") if selected_segment else "Primary ICP"
    )
    segment_description = selected_segment.get("description", "") if selected_segment else ""

    # Run clarification analysis
    analysis = await _analyse_clarification_needs(
        product_name=state.get("product_name", "Unknown Product"),
        product_description=state.get("product_description", ""),
        segment_label=segment_label,
        segment_description=segment_description,
        selected_channels=state.get("selected_channels", ["email"]),
        briefing_summary=state.get("briefing_summary") or "",
        top_findings=top_findings,
        prospects=prospects,
        last_user_message=last_user_message,
        winning_angle_memory=winning_angle_memory,
        prior_clarifications=existing_clarifications,
    )

    confidence = analysis.get("confidence_score", 0.5)
    questions = analysis.get("questions", [])
    needs_clarification = analysis.get("needs_clarification", False)

    # If confident enough or no questions, skip to generation
    if not needs_clarification or not questions or confidence >= 0.8:
        logger.info(
            "content_clarify_node: sufficient context (confidence=%.2f), skipping to generate | session=%s",
            confidence,
            session_id,
        )
        # Build generation context snapshot
        gen_context = {
            "segment": selected_segment,
            "findings": top_findings,
            "prospects": [p for p in prospects],
            "winning_angle_memory": winning_angle_memory,
            "last_user_message": last_user_message,
            "clarifications": existing_clarifications,
        }
        return {
            "content_phase": "generate",
            "content_generation_context": gen_context,
            "next_node": "content_generate",
        }

    # Needs clarification -- build and send UI frame
    logger.info(
        "content_clarify_node: needs clarification (confidence=%.2f, questions=%d) | session=%s",
        confidence,
        len(questions),
        session_id,
    )

    ui_frames: list[dict] = []

    # Intro message
    intro = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"content_clarify_intro_{uuid4().hex[:8]}",
        props={
            "content": (
                f"Before I generate your outreach content, I want to make sure I get it exactly right. "
                f"I have a few quick questions (confidence: {confidence:.0%} -- "
                f"{'almost' if confidence > 0.6 else 'need more context to'} ready to generate)."
            ),
            "role": "assistant",
        },
        actions=[],
    ).model_dump()
    ui_frames.append(intro)

    # Clarification UI
    clarify_frame = build_clarification_frame(
        questions, confidence, f"content-clarify-{session_id[:8]}"
    )
    ui_frames.append(clarify_frame)

    return {
        "content_phase": "clarify",
        "content_pending_questions": questions,
        "pending_ui_frames": ui_frames,
        "next_node": "orchestrator",
        "session_complete": True,
    }


# ---------------------------------------------------------------------------
# Node: Generation phase
# ---------------------------------------------------------------------------


async def content_generate_node(state: CampaignState) -> dict:
    """Phase 2 -- Generate A/B content variants with fully resolved context.

    Uses the generation context built during clarification (or built fresh
    if clarification was skipped).
    """
    session_id = state.get("session_id", "")
    logger.info("content_generate_node called | session=%s", session_id)

    # Build or recover generation context
    gen_ctx = state.get("content_generation_context")
    if not gen_ctx:
        # Build fresh context (clarification was skipped or direct entry)
        bundle = await memory_manager.build_context_bundle(state, "content")
        selected_segment = bundle.get("selected_segment") or get_segment_by_id(
            state.get("selected_segment_id"),
            state.get("segment_candidates", []),
        )
        top_findings = bundle.get("source_findings") or state.get("research_findings", [])[:5]
        winning_angle_memory = bundle.get("winning_angle_memory") or state.get(
            "prior_cycle_summary"
        )
        prospects = _get_selected_prospects(state)
        last_user_message = _extract_last_user_message(state.get("messages", []))
        clarifications = list(state.get("content_clarifications", []) or [])

        # If no stored clarifications but questions were previously asked, the user
        # may have replied with free-text answers rather than clicking buttons.
        # Extract Q&A pairs from the latest user message as a fallback.
        if not clarifications and state.get("content_pending_questions"):
            raw_answer = last_user_message or ""
            if raw_answer and raw_answer != "Generate outreach content using my clarification answers":
                for line in raw_answer.replace("\\n", "\n").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if ": " in line:
                        q, _, a = line.partition(": ")
                        clarifications.append({"question": q.rstrip("?").strip(), "answer": a.strip()})
                    else:
                        clarifications.append({"question": "(context)", "answer": line})
                if clarifications:
                    logger.info(
                        "content_generate_node: extracted %d clarification(s) from user message | session=%s",
                        len(clarifications), session_id,
                    )
    else:
        selected_segment = gen_ctx.get("segment")
        top_findings = gen_ctx.get("findings", [])
        winning_angle_memory = gen_ctx.get("winning_angle_memory")
        prospects = gen_ctx.get("prospects", [])
        last_user_message = gen_ctx.get("last_user_message", "")
        clarifications = gen_ctx.get("clarifications", [])

    # Generate variants
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
        clarification_context=clarifications,
    )

    # Generate visual artifact
    segment_label = (
        selected_segment.get("label", "Target Audience") if selected_segment else "Target Audience"
    )
    visual_artifact = await generate_visual_artifact(
        product_name=state.get("product_name", "Unknown Product"),
        segment_label=segment_label,
        briefing_summary=state.get("briefing_summary") or "",
        last_user_message=last_user_message,
    )

    # Persist each variant to MongoDB
    for variant in variants:
        variant_dict = variant.model_dump()
        variant_dict["created_at"] = variant.created_at
        await save_content_variant(variant_dict)

    # Build UI frames
    ui_frames: list[dict] = []

    channels_used = list({v.intended_channel for v in variants})
    angles_used = [v.angle_label for v in variants if v.angle_label]
    personalized_count = sum(1 for v in variants if v.personalized_for)
    user_directive = state.get("user_directive")

    directive_note = ""
    if user_directive:
        directive_note = f' based on your direction: "{user_directive}"'

    personalization_note = ""
    if personalized_count > 0:
        personalization_note = ", each personalized for a specific prospect"

    clarification_note = ""
    if clarifications:
        clarification_note = f" Incorporated {len(clarifications)} clarification(s) you provided."

    response_message = (
        f"Content generation complete{directive_note}. "
        f"Created {len(variants)} A/B variant(s) across {', '.join(channels_used)}{personalization_note}. "
        f"Angles: {', '.join(angles_used) if angles_used else 'various'}.{clarification_note} "
        "Review the variants below -- you can refine them with additional prompts or deploy directly."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"content_response_{uuid4().hex[:8]}",
        props={"content": response_message, "role": "assistant"},
        actions=[],
    ).model_dump()
    ui_frames.append(response_frame)

    grid_frame = build_variant_grid_frame(variants, f"variant-grid-{session_id[:8]}")
    ui_frames.append(grid_frame)

    visual_frame = build_visual_artifact_frame(
        visual_artifact, f"visual-artifact-{session_id[:8]}"
    )
    ui_frames.append(visual_frame)

    logger.info(
        "content_generate_node completed | session=%s variants=%d visual=%s",
        session_id,
        len(variants),
        visual_artifact.get("id"),
    )

    return {
        "content_variants": [v.model_dump(mode="json") for v in variants],
        "visual_artifacts": [visual_artifact],
        "content_phase": "generated",
        "content_generation_context": None,  # Clear after generation
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


# ---------------------------------------------------------------------------
# Node: Refinement phase
# ---------------------------------------------------------------------------


async def content_refine_node(state: CampaignState) -> dict:
    """Phase 3 -- Refine existing content variants based on user feedback.

    Reads the latest user message as the refinement prompt and applies it
    to the current content_variants.
    """
    session_id = state.get("session_id", "")
    logger.info("content_refine_node called | session=%s", session_id)

    current_variants = state.get("content_variants", [])
    if not current_variants:
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "error_messages": ["No content variants to refine. Please generate content first."],
        }

    refinement_prompt = _extract_last_user_message(state.get("messages", []))
    clarifications = state.get("content_clarifications", [])

    refined = await refine_variants(
        current_variants=current_variants,
        refinement_prompt=refinement_prompt,
        clarification_context=clarifications,
        session_id=session_id,
        cycle_number=state.get("cycle_number", 1),
    )

    # Persist refined variants
    for variant in refined:
        variant_dict = variant.model_dump()
        variant_dict["created_at"] = variant.created_at
        await save_content_variant(variant_dict)

    # Track refinement history
    refinement_record = {
        "prompt": refinement_prompt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "variant_count": len(refined),
    }

    # Build UI frames
    ui_frames: list[dict] = []

    response_message = (
        f"Content refined based on your feedback. "
        f"Updated {len(refined)} variant(s). "
        "Review the updated versions below -- you can continue refining or deploy."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"content_refine_response_{uuid4().hex[:8]}",
        props={"content": response_message, "role": "assistant"},
        actions=[],
    ).model_dump()
    ui_frames.append(response_frame)

    grid_frame = build_variant_grid_frame(refined, f"variant-grid-refined-{session_id[:8]}")
    ui_frames.append(grid_frame)

    logger.info(
        "content_refine_node completed | session=%s variants=%d",
        session_id,
        len(refined),
    )

    return {
        "content_variants": [v.model_dump(mode="json") for v in refined],
        "content_phase": "generated",
        "content_refinement_history": [refinement_record],
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


# ---------------------------------------------------------------------------
# Main agent node (routes to sub-phases)
# ---------------------------------------------------------------------------


async def content_agent_node(state: CampaignState) -> dict:
    """Content agent entry point -- routes to the appropriate sub-phase.

    Sub-phase routing:
    - If content_phase == "generate": skip clarification, go to generation
    - If content_phase == "generated": already done, go to generation (re-generate)
    - If content_phase == "refine": apply refinement
    - If clarification answers already exist: skip to generation
    - Otherwise: start with clarification analysis
    """
    phase = state.get("content_phase")

    if phase == "generate":
        return await content_generate_node(state)
    elif phase == "generated":
        # Re-entering after generation — treat as new generation request
        return await content_generate_node(state)
    elif phase == "refine":
        return await content_refine_node(state)
    else:
        # Default: clarification phase.
        # But if answers already exist, skip directly to generation.
        if state.get("content_clarifications"):
            logger.info(
                "content_agent_node: clarifications already exist (phase=%s), routing to generate",
                phase,
            )
            return await content_generate_node(state)
        clarify_result = await content_clarify_node(state)
        if clarify_result.get("content_phase") == "generate":
            return await content_generate_node({**state, **clarify_result})
        return clarify_result
