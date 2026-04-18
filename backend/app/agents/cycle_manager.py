"""Cycle Manager — snapshots completed cycles, builds accumulated learnings, advances cycle.

When a user says "proceed to cycle 2" or "start next cycle", this node:
1. Snapshots the current cycle's data into a CycleRecord
2. Builds accumulated learnings from ALL past cycles (self-evolving memory)
3. Resets transient state for the new cycle while preserving persistent knowledge
4. Advances cycle_number
5. Emits a summary UI frame with what was learned and what will change
"""

import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from app.core.llm import get_llm
from app.db.crud import get_cycle_records, get_intelligence_entries, save_cycle_record
from app.models.campaign_state import CampaignState
from app.models.intelligence import ApproachOutcome, CycleRecord
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot builder — captures current cycle state into a CycleRecord
# ---------------------------------------------------------------------------


def _build_approach_outcomes(state: CampaignState) -> list[ApproachOutcome]:
    """Analyze engagement results to determine which approaches worked or failed."""
    results = state.get("engagement_results", [])
    variants = state.get("content_variants", [])

    # Build variant_id → variant metadata lookup
    variant_map = {v.get("id"): v for v in variants if isinstance(v, dict)}

    outcomes: list[ApproachOutcome] = []
    for result in results:
        v_id = result.get("variant_id")
        variant = variant_map.get(v_id, {})
        sent = result.get("sent", 0)
        reply_rate = result.get("reply_rate", 0.0)

        verdict: Literal["effective", "ineffective", "insufficient_data"]
        if sent < 1:
            verdict = "insufficient_data"
        elif reply_rate >= 0.05:
            verdict = "effective"
        elif reply_rate >= 0.02:
            verdict = "insufficient_data"
        else:
            verdict = "ineffective"

        approach_desc = variant.get("hypothesis") or variant.get("angle_label") or f"variant_{v_id}"
        channel = variant.get("intended_channel", "unknown")

        outcomes.append(
            ApproachOutcome(
                approach=approach_desc,
                channel=channel,
                variant_id=v_id,
                engagement_rate=reply_rate,
                sample_size=sent,
                verdict=verdict,
            )
        )
    return outcomes


def _build_cycle_record(state: CampaignState) -> CycleRecord:
    """Build a CycleRecord snapshot from the current campaign state."""
    session_id = state.get("session_id", "")
    cycle_number = state.get("cycle_number", 1)

    # Research summary
    findings = state.get("research_findings", [])
    briefing = state.get("briefing_summary") or ""
    research_summary = briefing or f"{len(findings)} research findings collected"

    # Segments used
    segments_used = [
        seg.get("label", seg.get("id", "unknown"))
        for seg in state.get("segment_candidates", [])
        if isinstance(seg, dict)
    ]

    # Content strategies
    variants = state.get("content_variants", [])
    content_strategies = []
    for v in variants:
        if isinstance(v, dict):
            strategy = v.get("hypothesis") or v.get("angle_label") or "unknown"
            content_strategies.append(strategy)

    # Channels / deployment stats
    records = state.get("deployment_records", [])
    channels_used = list({r.get("channel", "unknown") for r in records if isinstance(r, dict)})
    prospects_contacted = len({r.get("prospect_id") for r in records if isinstance(r, dict) and r.get("prospect_id")})

    # Engagement aggregates
    results = state.get("engagement_results", [])
    total_sends = sum(r.get("sent", 0) for r in results)
    total_opens = sum(r.get("opens", 0) for r in results)
    total_replies = sum(r.get("replies", 0) for r in results)
    total_bounces = sum(r.get("bounces", 0) for r in results)

    # Approach outcomes
    approach_outcomes = _build_approach_outcomes(state)

    # Determine what to avoid / amplify
    approaches_to_avoid = [
        o.approach for o in approach_outcomes if o.verdict == "ineffective"
    ]
    approaches_to_amplify = [
        o.approach for o in approach_outcomes if o.verdict == "effective"
    ]

    # Key decisions from decision log
    key_decisions = [
        d.get("type", "unknown") + ": " + (d.get("label") or d.get("summary") or str(d.get("segment_id", "")))
        for d in state.get("decision_log", [])
        if isinstance(d, dict)\
    ]

    # Interaction count (number of messages in this cycle)
    messages = state.get("messages", [])
    interaction_count = len(messages)

    return CycleRecord(
        id=str(uuid4()),
        session_id=session_id,
        cycle_number=cycle_number,
        research_summary=research_summary,
        segments_used=segments_used,
        content_strategies=content_strategies,
        channels_used=channels_used,
        prospects_contacted=prospects_contacted,
        total_sends=total_sends,
        total_opens=total_opens,
        total_replies=total_replies,
        total_bounces=total_bounces,
        winning_variant_id=state.get("winning_variant_id"),
        winning_strategy=next(
            (o.approach for o in approach_outcomes if o.verdict == "effective"),
            None,
        ),
        approach_outcomes=approach_outcomes,
        learning_delta=state.get("prior_cycle_summary") or "",
        approaches_to_avoid=approaches_to_avoid,
        approaches_to_amplify=approaches_to_amplify,
        interaction_count=interaction_count,
        key_decisions=key_decisions[:20],  # cap to prevent bloat
        completed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Accumulated learnings builder — the self-evolution engine
# ---------------------------------------------------------------------------


async def _build_accumulated_learnings(
    session_id: str,
    current_cycle_record: CycleRecord,
) -> str:
    """Synthesize learnings from ALL completed cycles into actionable guidance.

    This is the core of the self-evolving system. It reads all past cycle records
    and generates a directive that tells future agents what to do differently.
    """
    past_records = await get_cycle_records(session_id)
    all_records = past_records + [current_cycle_record.model_dump(mode="json")]

    if not all_records:
        return ""

    # Also pull intelligence entries for richer context
    intel_entries = await get_intelligence_entries(session_id)

    # Build the learnings synthesis
    lines: list[str] = [
        f"=== Accumulated Campaign Learnings ({len(all_records)} cycles completed) ===\n",
    ]

    # Track effective/ineffective approaches across all cycles
    all_effective: list[str] = []
    all_ineffective: list[str] = []
    all_strategies: list[str] = []

    for rec in all_records:
        cn = rec.get("cycle_number", "?")
        lines.append(f"--- Cycle {cn} ---")

        if rec.get("research_summary"):
            lines.append(f"  Research: {rec['research_summary'][:200]}")

        strategies = rec.get("content_strategies", [])
        if strategies:
            lines.append(f"  Strategies tried: {', '.join(strategies[:5])}")
            all_strategies.extend(strategies)

        sends = rec.get("total_sends", 0)
        replies = rec.get("total_replies", 0)
        reply_rate = f"{replies / sends:.1%}" if sends > 0 else "n/a"
        lines.append(f"  Results: {sends} sends, {replies} replies ({reply_rate} reply rate)")

        for o in rec.get("approach_outcomes", []):
            if o.get("verdict") == "effective":
                all_effective.append(o.get("approach", "unknown"))
            elif o.get("verdict") == "ineffective":
                all_ineffective.append(o.get("approach", "unknown"))

        to_avoid = rec.get("approaches_to_avoid", [])
        to_amplify = rec.get("approaches_to_amplify", [])
        if to_amplify:
            lines.append(f"  Worked well: {', '.join(to_amplify[:3])}")
        if to_avoid:
            lines.append(f"  Did NOT work: {', '.join(to_avoid[:3])}")

        if rec.get("learning_delta"):
            lines.append(f"  Learning: {rec['learning_delta'][:300]}")

        lines.append("")

    # Synthesize directives
    lines.append("=== DIRECTIVES FOR NEXT CYCLE ===")

    if all_effective:
        unique_effective = list(dict.fromkeys(all_effective))  # preserve order, dedupe
        lines.append("AMPLIFY these approaches (they generated engagement):")
        for approach in unique_effective[:5]:
            lines.append(f"  + {approach}")

    if all_ineffective:
        unique_ineffective = list(dict.fromkeys(all_ineffective))
        lines.append("AVOID these approaches (they generated NO engagement):")
        for approach in unique_ineffective[:5]:
            lines.append(f"  - {approach}")

    if not all_effective and not all_ineffective:
        lines.append("No clear signal yet — continue experimenting with diverse approaches.")

    # Add intelligence entry learnings
    for entry in intel_entries[-3:]:
        delta = entry.get("learning_delta", "")
        if delta:
            lines.append(f"\nIntelligence (cycle {entry.get('cycle_number', '?')}): {delta[:200]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main node — refined_cycle handler
# ---------------------------------------------------------------------------


async def refined_cycle_node(state: CampaignState) -> dict[str, Any]:
    """Snapshot the current cycle, build accumulated learnings, advance to next cycle.

    This node is the transition point between cycles. It:
    1. Snapshots everything from the current cycle into a CycleRecord
    2. Persists the record to MongoDB
    3. Builds accumulated learnings from ALL past cycles
    4. Uses LLM to generate an evolution summary (what to change)
    5. Resets transient state while keeping persistent knowledge
    6. Advances cycle_number
    7. Emits a CycleTransition UI frame
    """
    session_id = state.get("session_id", "")
    current_cycle = state.get("cycle_number", 1)
    next_cycle = current_cycle + 1

    logger.info(
        "refined_cycle_node: transitioning from cycle %d to %d | session=%s",
        current_cycle,
        next_cycle,
        session_id,
    )

    # -- Step 1: Snapshot current cycle --
    cycle_record = _build_cycle_record(state)

    # -- Step 2: Persist to MongoDB --
    try:
        await save_cycle_record(cycle_record.model_dump(mode="json"))
        logger.info("refined_cycle_node: saved CycleRecord for cycle %d", current_cycle)
    except Exception as exc:
        logger.error("refined_cycle_node: failed to save CycleRecord: %s", exc)

    # -- Step 3: Build accumulated learnings --
    accumulated = await _build_accumulated_learnings(session_id, cycle_record)

    # -- Step 4: Use LLM to generate evolution summary --
    evolution_summary = await _generate_evolution_summary(state, cycle_record, accumulated)

    # -- Step 5: Build updated cycle_records list for state --
    existing_records = list(state.get("cycle_records", []))
    existing_records.append(cycle_record.model_dump(mode="json"))

    # -- Step 6: Emit UI frame --
    run_id = uuid4().hex[:8]
    transition_frame = _build_cycle_transition_frame(
        current_cycle, next_cycle, cycle_record, evolution_summary, run_id
    )

    response_text = (
        f"Cycle {current_cycle} is complete. Moving to Cycle {next_cycle}.\n\n"
        f"{evolution_summary}\n\n"
        f"All learnings from previous cycles have been captured and will guide the next cycle's strategy."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"cycle_transition_{run_id}",
        props={"content": response_text, "role": "assistant"},
        actions=[],
    ).model_dump()

    # -- Step 7: Return state patch --
    # Reset transient cycle data while preserving persistent knowledge
    return {
        "cycle_number": next_cycle,
        "prior_cycle_summary": evolution_summary,
        "accumulated_learnings": accumulated,
        "cycle_records": existing_records,
        "active_stage_summary": f"starting cycle {next_cycle}",
        # Reset transient per-cycle fields
        "content_variants": [],
        "selected_variant_ids": [],
        "deployment_records": [],
        "deployment_confirmed": False,
        "normalized_feedback_events": [],
        "engagement_results": [],
        "winning_variant_id": None,
        "selected_channels": [],
        "ab_split_plan": None,
        # Keep research findings — they accumulate and evolve via confidence updates
        # Keep prospect_cards — they persist across cycles
        # Keep segment_candidates — they persist across cycles
        "session_complete": True,
        "pending_ui_frames": [response_frame, transition_frame],
    }


async def _generate_evolution_summary(
    state: CampaignState,
    cycle_record: CycleRecord,
    accumulated_learnings: str,
) -> str:
    """Use LLM to generate a concise evolution summary for the cycle transition."""
    llm = get_llm(temperature=0.2)
    if llm is None:
        # Mock mode
        return (
            f"Cycle {cycle_record.cycle_number} complete. "
            f"Sent {cycle_record.total_sends} messages, received {cycle_record.total_replies} replies. "
            f"Approaches to amplify: {', '.join(cycle_record.approaches_to_amplify) or 'none identified yet'}. "
            f"Approaches to avoid: {', '.join(cycle_record.approaches_to_avoid) or 'none identified yet'}."
        )

    prompt = f"""You are analyzing the results of campaign cycle {cycle_record.cycle_number} to guide the next cycle.

Current cycle results:
- Sends: {cycle_record.total_sends}, Opens: {cycle_record.total_opens}, Replies: {cycle_record.total_replies}
- Strategies tried: {', '.join(cycle_record.content_strategies[:5]) or 'none'}
- Winning strategy: {cycle_record.winning_strategy or 'no clear winner'}
- Approaches that worked: {', '.join(cycle_record.approaches_to_amplify) or 'none'}
- Approaches that failed: {', '.join(cycle_record.approaches_to_avoid) or 'none'}

Accumulated learnings from all cycles:
{accumulated_learnings[:2000]}

Generate a concise (3-5 sentence) evolution summary that:
1. States what was learned this cycle
2. Identifies specific tactics to double down on
3. Identifies specific tactics to abandon
4. Recommends the strategic direction for the next cycle

Be specific and actionable. Reference actual strategies and metrics."""

    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": "You are a growth strategy analyst. Be concise and data-driven."},
                {"role": "user", "content": prompt},
            ]
        )
        return response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:
        logger.error("_generate_evolution_summary LLM error: %s", exc)
        return (
            f"Cycle {cycle_record.cycle_number} complete. "
            f"{cycle_record.total_sends} sends, {cycle_record.total_replies} replies."
        )


def _build_cycle_transition_frame(
    current_cycle: int,
    next_cycle: int,
    record: CycleRecord,
    evolution_summary: str,
    run_id: str,
) -> dict:
    """Build a CycleTransition UI frame."""
    return UIFrame(
        type="ui_component",
        component="CycleSummary",
        instance_id=f"cycle-transition-{run_id}",
        props={
            "cycle_number": current_cycle,
            "next_cycle_number": next_cycle,
            "learning_delta": evolution_summary,
            "winner_variant_id": record.winning_variant_id,
            "winner_reply_rate": None,
            "total_sends": record.total_sends,
            "total_replies": record.total_replies,
            "approaches_to_amplify": record.approaches_to_amplify,
            "approaches_to_avoid": record.approaches_to_avoid,
        },
        actions=[
            UIAction(
                id="start-research",
                label="Research for Next Cycle",
                action_type="start_research",
                payload={},
            ),
            UIAction(
                id="generate-content",
                label="Generate New Content",
                action_type="generate_content",
                payload={},
            ),
            UIAction(
                id="reuse-prospects",
                label="Keep Current Prospects",
                action_type="reuse_prospects",
                payload={},
            ),
        ],
    ).model_dump()
