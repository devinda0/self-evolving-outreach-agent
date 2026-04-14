"""Segment/Prospect Agent — derives segments from research, loads prospects, scores them.

This agent sits between research and content. It:
1. Derives target segment candidates from the briefing summary and top research findings
2. Discovers prospects via research-powered queries or loads from CSV / manual entry
3. Scores each prospect using a weighted multi-signal model
4. Deduplicates prospects across multiple import sources
5. Builds compact prospect cards for the ProspectPicker UI
6. Emits SegmentSelector + ProspectPicker UI frames
"""

import csv
import io
import logging
import uuid
from pathlib import Path
from typing import Any

from app.agents.prospect_discovery import (
    calculate_weighted_fit_score,
    deduplicate_prospects,
    discover_prospects_via_research,
)
from app.db.crud import save_prospect_cards, save_segments
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.prospect import Segment
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Demo seed list — used when no prospect source is provided
# ---------------------------------------------------------------------------

DEMO_SEED_PROSPECTS: list[dict[str, Any]] = [
    {
        "name": "Alice Chen",
        "title": "VP Sales",
        "company": "Acme SaaS",
        "email": "alice@acme.io",
        "linkedin_url": "https://linkedin.com/in/alicechen",
    },
    {
        "name": "Bob Martinez",
        "title": "Head of Growth",
        "company": "ScaleUp Inc",
        "email": "bob@scaleup.io",
        "linkedin_url": "https://linkedin.com/in/bobmartinez",
    },
    {
        "name": "Carol Nguyen",
        "title": "CRO",
        "company": "CloudFirst",
        "email": "carol@cloudfirst.com",
        "linkedin_url": "https://linkedin.com/in/carolnguyen",
    },
    {
        "name": "David Kim",
        "title": "VP Marketing",
        "company": "DataDriven Co",
        "email": "david@datadriven.co",
        "linkedin_url": "https://linkedin.com/in/davidkim",
    },
    {
        "name": "Emily Ross",
        "title": "Director of Partnerships",
        "company": "NexGen Labs",
        "email": "emily@nexgenlabs.io",
        "linkedin_url": "https://linkedin.com/in/emilyross",
    },
    {
        "name": "Frank Okafor",
        "title": "VP Business Development",
        "company": "Synapse AI",
        "email": "frank@synapseai.com",
        "linkedin_url": "https://linkedin.com/in/frankokafor",
    },
    {
        "name": "Grace Liu",
        "title": "Head of Revenue",
        "company": "FinStack",
        "email": "grace@finstack.io",
        "linkedin_url": "https://linkedin.com/in/graceliu",
    },
    {
        "name": "Hasan Ali",
        "title": "VP Sales",
        "company": "PipelineHQ",
        "email": "hasan@pipelinehq.com",
        "linkedin_url": "https://linkedin.com/in/hasanali",
    },
    {
        "name": "Irene Volkov",
        "title": "Growth Lead",
        "company": "ShipFast Dev",
        "email": "irene@shipfast.dev",
        "linkedin_url": "https://linkedin.com/in/irenevolkov",
    },
    {
        "name": "James Park",
        "title": "Director of Sales",
        "company": "OutboundOS",
        "email": "james@outboundos.io",
        "linkedin_url": "https://linkedin.com/in/jamespark",
    },
]


# ---------------------------------------------------------------------------
# Prospect loading
# ---------------------------------------------------------------------------


async def load_prospects(
    prospect_pool_ref: str | None,
    research_findings: list[dict[str, Any]] | None = None,
    product_name: str = "",
    target_market: str = "",
) -> list[dict[str, Any]]:
    """Load prospects from the referenced source.

    Priority:
    1. CSV file path → load from CSV with auto column mapping
    2. Research-powered discovery → if research findings are available
    3. Demo seed list → fallback when no other source is available
    """
    if prospect_pool_ref:
        ref_path = Path(prospect_pool_ref)
        if ref_path.suffix.lower() == ".csv" and ref_path.is_file():
            prospects = await load_prospects_from_csv(str(ref_path))
            # Filter out prospects without a communication method
            return [p for p in prospects if p.get("email") or p.get("linkedin_url")]
        logger.warning("Unrecognized prospect_pool_ref '%s'", prospect_pool_ref)

    # Try research-powered discovery when findings are available
    if research_findings:
        logger.info("Attempting research-powered prospect discovery")
        try:
            discovered = await discover_prospects_via_research(
                product_name=product_name,
                target_market=target_market,
                research_findings=research_findings,
                num_prospects=10,
            )
            if discovered:
                logger.info("Discovered %d prospects via research", len(discovered))
                # Filter out prospects without a communication method
                return [p for p in discovered if p.get("email") or p.get("linkedin_url")]
        except Exception as exc:
            logger.warning("Prospect discovery failed (%s) — falling back to seed list", exc)

    logger.info("Using demo seed list as fallback")
    # Filter out prospects without a communication method
    return [p for p in DEMO_SEED_PROSPECTS if p.get("email") or p.get("linkedin_url")]


async def load_prospects_from_csv(file_path: str) -> list[dict[str, Any]]:
    """Parse a CSV file with columns: name, email, linkedin_url, title, company.

    Returns a list of raw prospect dicts with an id assigned.
    """
    prospects: list[dict[str, Any]] = []
    path = Path(file_path)
    if not path.is_file():
        logger.error("CSV file not found: %s", file_path)
        return []

    content = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        prospects.append(
            {
                "name": row.get("name", "").strip(),
                "email": row.get("email", "").strip() or None,
                "linkedin_url": row.get("linkedin_url", "").strip() or None,
                "title": row.get("title", "").strip(),
                "company": row.get("company", "").strip(),
            }
        )

    logger.info("Loaded %d prospects from CSV: %s", len(prospects), file_path)
    return prospects


async def load_prospects_from_csv_bytes(csv_bytes: bytes) -> list[dict[str, Any]]:
    """Parse CSV content from uploaded bytes. Used by the import API endpoint."""
    prospects: list[dict[str, Any]] = []
    content = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        prospects.append(
            {
                "name": row.get("name", "").strip(),
                "email": row.get("email", "").strip() or None,
                "linkedin_url": row.get("linkedin_url", "").strip() or None,
                "title": row.get("title", "").strip(),
                "company": row.get("company", "").strip(),
            }
        )
    logger.info("Loaded %d prospects from uploaded CSV", len(prospects))
    return prospects


# ---------------------------------------------------------------------------
# Segment derivation
# ---------------------------------------------------------------------------


def _format_findings(findings: list[dict[str, Any]], limit: int = 5) -> str:
    """Format top research findings into a concise text block for prompting."""
    lines = []
    for i, f in enumerate(findings[:limit], 1):
        claim = f.get("claim", "N/A")
        confidence = f.get("confidence", 0.0)
        signal_type = f.get("signal_type", f.get("thread_type", "unknown"))
        lines.append(f"  {i}. [{signal_type}] {claim} (confidence: {confidence:.2f})")
    return "\n".join(lines) if lines else "  (no findings available)"


async def derive_segments(
    briefing_summary: str | None,
    research_findings: list[dict[str, Any]],
    product_name: str,
) -> list[Segment]:
    """Derive segment candidates from the research briefing.

    Currently uses a rule-based approach. Once the Gemini integration is wired
    (content agent), this can be upgraded to an LLM-driven derivation.
    """
    session_id = ""  # Will be set by the caller in the node

    # Build segments from the research signal types present
    segments: list[Segment] = []
    signal_types = {
        f.get("signal_type", f.get("thread_type", "unknown")) for f in research_findings
    }

    # Segment 1: Always create a primary ICP segment
    segments.append(
        Segment(
            id=f"seg-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            label=f"Primary ICP for {product_name}",
            description=f"Core target buyers identified from market research for {product_name}",
            criteria={
                "derived_from": "briefing_summary",
                "signal_types": list(signal_types),
            },
            prospect_count=0,
        )
    )

    # Segment 2: If audience signals exist, create an audience-pain segment
    if "audience" in signal_types:
        audience_findings = [
            f for f in research_findings if f.get("signal_type", f.get("thread_type")) == "audience"
        ]
        top_claim = audience_findings[0].get("claim", "") if audience_findings else ""
        segments.append(
            Segment(
                id=f"seg-{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                label="Pain-point driven buyers",
                description=f"Prospects whose pain points align with: {top_claim[:120]}",
                criteria={
                    "derived_from": "audience_research",
                    "pain_signal": top_claim[:200],
                },
                prospect_count=0,
            )
        )

    # Segment 3: If competitor signals exist, create a competitive-displacement segment
    if "competitor" in signal_types:
        competitor_findings = [
            f
            for f in research_findings
            if f.get("signal_type", f.get("thread_type")) == "competitor"
        ]
        top_claim = competitor_findings[0].get("claim", "") if competitor_findings else ""
        segments.append(
            Segment(
                id=f"seg-{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                label="Competitive displacement targets",
                description=f"Prospects using competitor solutions vulnerable to: {top_claim[:120]}",
                criteria={
                    "derived_from": "competitor_research",
                    "competitive_signal": top_claim[:200],
                },
                prospect_count=0,
            )
        )

    # Ensure at least 2 segments (issue acceptance criteria)
    if len(segments) < 2:
        segments.append(
            Segment(
                id=f"seg-{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                label=f"Early adopters for {product_name}",
                description="Technology-forward buyers who adopt new solutions quickly",
                criteria={"derived_from": "default", "buyer_type": "early_adopter"},
                prospect_count=0,
            )
        )

    return segments


# ---------------------------------------------------------------------------
# Prospect scoring
# ---------------------------------------------------------------------------


def calculate_fit_score(prospect: dict[str, Any], segment: Segment) -> float:
    """Calculate how well a prospect fits the segment criteria.

    Uses heuristic matching on title, company, and segment criteria.
    Kept for backward compatibility — new code uses calculate_weighted_fit_score.
    """
    score = 0.5  # Base score

    title = (prospect.get("title") or "").lower()
    criteria = segment.criteria

    # Boost for leadership titles
    leadership_keywords = ["vp", "head", "director", "cro", "cmo", "ceo", "founder", "chief"]
    if any(kw in title for kw in leadership_keywords):
        score += 0.2

    # Boost if segment is pain-point driven and prospect has a relevant title
    if criteria.get("derived_from") == "audience_research":
        sales_keywords = ["sales", "growth", "revenue", "business development"]
        if any(kw in title for kw in sales_keywords):
            score += 0.15

    # Boost for competitive displacement if title suggests decision-maker
    if criteria.get("derived_from") == "competitor_research":
        decision_keywords = ["vp", "director", "head", "chief", "lead"]
        if any(kw in title for kw in decision_keywords):
            score += 0.15

    return min(score, 1.0)


def calculate_urgency_score(prospect: dict[str, Any], top_findings: list[dict[str, Any]]) -> float:
    """Estimate urgency based on how strongly top findings create time pressure.

    Higher confidence findings with market/temporal signals boost urgency.
    """
    if not top_findings:
        return 0.3

    # Average confidence of top findings as a base
    avg_confidence = sum(f.get("confidence", 0.5) for f in top_findings) / len(top_findings)
    urgency = avg_confidence * 0.6  # Scale to leave room for signal boosts

    # Boost for temporal / market signals (time-sensitive intelligence)
    temporal_signals = [
        f
        for f in top_findings
        if f.get("signal_type", f.get("thread_type")) in ("temporal", "market")
    ]
    if temporal_signals:
        urgency += 0.2

    return min(urgency, 1.0)


def recommend_angle(prospect: dict[str, Any], top_findings: list[dict[str, Any]]) -> str:
    """Recommend a message angle based on the prospect's profile and research findings."""
    title = (prospect.get("title") or "").lower()

    if any(kw in title for kw in ("sales", "revenue", "growth", "business development")):
        return "pipeline-acceleration"
    if any(kw in title for kw in ("marketing", "cmo", "brand")):
        return "demand-generation"
    if any(kw in title for kw in ("ceo", "founder", "co-founder")):
        return "strategic-vision"
    if any(kw in title for kw in ("cto", "engineering", "technical")):
        return "technical-differentiation"
    return "value-proposition"


def recommend_channel(prospect: dict[str, Any], segment: Segment) -> str:
    """Recommend the best outreach channel for a prospect."""
    if prospect.get("linkedin_url"):
        return "linkedin"
    if prospect.get("email"):
        return "email"
    return "email"


async def score_prospects(
    prospects: list[dict[str, Any]],
    segments: list[Segment],
    top_findings: list[dict[str, Any]],
    target_market: str = "",
) -> list[dict[str, Any]]:
    """Score every prospect using the weighted multi-signal model.

    Returns enriched prospect dicts with scores, component breakdowns, and recommendations.
    """
    primary_segment = segments[0] if segments else None
    scored: list[dict[str, Any]] = []

    for raw in prospects:
        prospect_id = f"prospect-{uuid.uuid4().hex[:8]}"

        # Use weighted scoring model
        fit, components = calculate_weighted_fit_score(
            raw, primary_segment, top_findings, target_market
        )
        urgency = calculate_urgency_score(raw, top_findings)
        angle = recommend_angle(raw, top_findings)
        channel = recommend_channel(raw, primary_segment) if primary_segment else "email"

        scored.append(
            {
                "id": prospect_id,
                "name": raw.get("name", ""),
                "email": raw.get("email"),
                "linkedin_url": raw.get("linkedin_url"),
                "title": raw.get("title", ""),
                "company": raw.get("company", ""),
                "fit_score": round(fit, 2),
                "urgency_score": round(urgency, 2),
                "angle_recommendation": angle,
                "channel_recommendation": channel,
                "personalization_fields": {},
                "source": raw.get("source", "seed"),
                "discovery_query": raw.get("rationale"),
                "role_seniority": components.get("role_seniority"),
                "company_fit": components.get("company_fit"),
                "signal_recency": components.get("signal_recency"),
            }
        )

    # Sort by combined score (fit + urgency) descending
    scored.sort(key=lambda p: p["fit_score"] + p["urgency_score"], reverse=True)

    # Deduplicate after scoring
    scored = deduplicate_prospects(scored)

    return scored


def build_prospect_card(prospect: dict[str, Any]) -> dict[str, Any]:
    """Build a compact prospect card for the ProspectPicker UI.

    Includes email and linkedin_url so the deployment agent can send messages.
    """
    return {
        "id": prospect["id"],
        "name": prospect["name"],
        "title": prospect.get("title", ""),
        "company": prospect.get("company", ""),
        "email": prospect.get("email"),
        "linkedin_url": prospect.get("linkedin_url"),
        "fit_score": prospect["fit_score"],
        "urgency_score": prospect["urgency_score"],
        "angle_recommendation": prospect["angle_recommendation"],
        "channel_recommendation": prospect["channel_recommendation"],
    }


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_segment_selector_frame(segments: list[Segment], instance_id: str) -> dict[str, Any]:
    """Build a SegmentSelector UI frame for the WebSocket stream."""
    return UIFrame(
        type="ui_component",
        component="SegmentSelector",
        instance_id=instance_id,
        props={
            "segments": [s.model_dump() for s in segments],
        },
        actions=[
            UIAction(
                id=f"select-{s.id}",
                label=f"Select: {s.label}",
                action_type="select_segment",
                payload={"segment_id": s.id},
            )
            for s in segments
        ],
    ).model_dump()


def build_prospect_picker_frame(cards: list[dict[str, Any]], instance_id: str) -> dict[str, Any]:
    """Build a ProspectPicker UI frame for the WebSocket stream."""
    return UIFrame(
        type="ui_component",
        component="ProspectPicker",
        instance_id=instance_id,
        props={
            "prospects": cards,
        },
        actions=[
            UIAction(
                id="confirm-prospects",
                label="Confirm selected prospects",
                action_type="confirm_prospects",
                payload={},
            ),
            UIAction(
                id="select-all",
                label="Select all",
                action_type="select_all_prospects",
                payload={},
            ),
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Main agent node — plugs into the LangGraph graph
# ---------------------------------------------------------------------------


async def segment_agent_node(state: CampaignState) -> dict:
    """Derive segments, load and score prospects, emit UI frames.

    This replaces the stub in graph.py.
    """
    session_id = state.get("session_id", "")
    briefing_present = bool(state.get("briefing_summary"))
    findings_count = len(state.get("research_findings", []))
    user_directive = state.get("user_directive")
    logger.info(
        "segment_agent_node called | session=%s briefing=%s findings=%d directive=%s",
        session_id,
        briefing_present,
        findings_count,
        user_directive[:80] if user_directive else None,
    )

    # Build scoped context bundle for structured context access
    try:
        bundle = await memory_manager.build_context_bundle(state, "segment")
        top_findings = bundle.get("top_findings") or state.get("research_findings", [])[:5]
    except Exception as exc:
        logger.warning("segment_agent_node: memory bundle failed (%s) — continuing", exc)
        top_findings = state.get("research_findings", [])[:5]

    # Step 1: Derive segment candidates from briefing
    segments = await derive_segments(
        briefing_summary=state.get("briefing_summary"),
        research_findings=state.get("research_findings", []),
        product_name=state.get("product_name", "Unknown Product"),
    )

    # Assign session_id to all segments
    for seg in segments:
        seg.session_id = session_id

    # Step 2: Load prospects (discovery / CSV / seed list)
    raw_prospects = await load_prospects(
        prospect_pool_ref=state.get("prospect_pool_ref"),
        research_findings=state.get("research_findings", []),
        product_name=state.get("product_name", "Unknown Product"),
        target_market=state.get("target_market", ""),
    )

    # Step 3: Score each prospect using weighted model
    scored = await score_prospects(
        prospects=raw_prospects,
        segments=segments,
        top_findings=top_findings,
        target_market=state.get("target_market", ""),
    )

    # Step 4: Build compact prospect cards
    cards = [build_prospect_card(p) for p in scored]

    # Update prospect counts on segments
    for seg in segments:
        seg.prospect_count = len(cards)

    # Step 5: Persist to session store
    await save_segments(session_id, [s.model_dump() for s in segments])
    await save_prospect_cards(session_id, scored)

    # Step 6: Build UI frames and include in state for the WS handler to drain
    segment_frame = build_segment_selector_frame(segments, f"seg-selector-{session_id[:8]}")
    prospect_frame = build_prospect_picker_frame(cards, f"prospect-picker-{session_id[:8]}")

    logger.info(
        "segment_agent_node completed | session=%s segments=%d prospects=%d",
        session_id,
        len(segments),
        len(cards),
    )

    # Build a response message for the user
    directive_note = ""
    if user_directive:
        directive_note = f" based on your request to {user_directive.lower().rstrip('.')}."
    else:
        directive_note = " from research findings."

    top_prospect_names = [c.get("name", "Unknown") for c in cards[:3]]
    prospect_preview = ", ".join(top_prospect_names)
    response_message = (
        f"Segmentation complete{directive_note} "
        f"Identified {len(segments)} target segments and {len(cards)} prospects. "
        f"Top prospects: {prospect_preview}. "
        "Review and select the prospects you'd like to target below."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"segment_response_{uuid.uuid4().hex[:8]}",
        props={"content": response_message, "role": "assistant"},
        actions=[],
    ).model_dump()

    return {
        "segment_candidates": [s.model_dump() for s in segments],
        "prospect_cards": cards,
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": [response_frame, segment_frame, prospect_frame],
    }
