"""Feedback Agent — engagement event aggregation, confidence updates, and learning delta.

Handles:
- Aggregating normalized engagement events by variant/segment/channel
- Determining the winning variant (minimum sample size guard)
- Statistical significance testing (chi-squared) for A/B variant comparison
- Automatic winner declaration when significance threshold is met
- Updating research finding confidence scores in MongoDB
- Writing an IntelligenceEntry (learning_delta) to close the feedback loop
- Quarantining unmatched events that cannot be correlated to a deployment record
- Emitting ABResults and CycleSummary UI frames
- Emitting a feedback prompt UI when no events are present yet
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from app.db.crud import (
    save_intelligence_entry,
    save_quarantine_event,
    update_finding_confidence,
)
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.intelligence import IntelligenceEntry
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)

# Minimum number of events per variant required before a winner is declared.
MIN_SAMPLE_SIZE = 3


# ---------------------------------------------------------------------------
# Engagement aggregation
# ---------------------------------------------------------------------------


def aggregate_engagement_results(
    events: list[dict],
    records: list[dict],
) -> list[dict]:
    """Group normalized feedback events by variant_id and compute engagement rates.

    Args:
        events: List of NormalizedFeedbackEvent dicts.
        records: List of DeploymentRecord dicts (used to count sends per variant).

    Returns:
        List of dicts, one per variant_id, containing raw counts and computed rates.
    """
    # Accumulate raw event counts per variant
    by_variant: dict[str, dict] = defaultdict(
        lambda: {"sent": 0, "opens": 0, "clicks": 0, "replies": 0, "bounces": 0}
    )

    for event in events:
        v_id = event.get("variant_id")
        if not v_id:
            continue
        event_type = event.get("event_type", "")
        if event_type == "open":
            by_variant[v_id]["opens"] += 1
        elif event_type == "click":
            by_variant[v_id]["clicks"] += 1
        elif event_type == "reply":
            by_variant[v_id]["replies"] += 1
        elif event_type == "bounce":
            by_variant[v_id]["bounces"] += 1

    # Populate sent counts from deployment records
    for record in records:
        v_id = record.get("variant_id")
        if v_id:
            by_variant[v_id]["sent"] += 1

    return [{"variant_id": k, **_compute_rates(v)} for k, v in by_variant.items()]


def _compute_rates(counts: dict) -> dict:
    """Compute open_rate, click_rate, reply_rate, bounce_rate from raw counts."""
    sent = counts.get("sent", 0)
    opens = counts.get("opens", 0)
    clicks = counts.get("clicks", 0)
    replies = counts.get("replies", 0)
    bounces = counts.get("bounces", 0)

    def _rate(numerator: int) -> float:
        return round(numerator / sent, 4) if sent > 0 else 0.0

    return {
        "sent": sent,
        "opens": opens,
        "clicks": clicks,
        "replies": replies,
        "bounces": bounces,
        "open_rate": _rate(opens),
        "click_rate": _rate(clicks),
        "reply_rate": _rate(replies),
        "bounce_rate": _rate(bounces),
    }


# ---------------------------------------------------------------------------
# Winner determination
# ---------------------------------------------------------------------------


def determine_winner(
    results: list[dict],
    min_sample_size: int = MIN_SAMPLE_SIZE,
) -> dict | None:
    """Return the variant with the highest reply_rate, provided it has enough sends.

    Returns None if no variant meets the minimum sample size.
    """
    qualified = [r for r in results if r.get("sent", 0) >= min_sample_size]
    if not qualified:
        logger.info(
            "determine_winner: no variant meets min_sample_size=%d — winner is None",
            min_sample_size,
        )
        return None
    return max(qualified, key=lambda r: r.get("reply_rate", 0.0))


# ---------------------------------------------------------------------------
# Statistical significance testing (chi-squared)
# ---------------------------------------------------------------------------

# Critical value for chi-squared with 1 degree of freedom at p < 0.05
_CHI2_CRITICAL_005 = 3.841


def _chi_squared_2x2(
    successes_a: int, total_a: int, successes_b: int, total_b: int
) -> float:
    """Compute the chi-squared statistic for a 2×2 contingency table.

    Layout:
        |            | Success | Failure |
        | Variant A  | s_a     | f_a     |
        | Variant B  | s_b     | f_b     |

    Uses Yates' continuity correction to improve accuracy for small samples.
    Returns 0.0 when the expected frequency in any cell is zero.
    """
    f_a = total_a - successes_a
    f_b = total_b - successes_b
    n = total_a + total_b
    if n == 0:
        return 0.0

    # Expected values for each cell
    row_sums = [total_a, total_b]
    col_sums = [successes_a + successes_b, f_a + f_b]

    # Guard against zero expected frequencies
    for rs in row_sums:
        for cs in col_sums:
            if rs * cs == 0:
                return 0.0

    # Yates-corrected chi-squared
    observed = [[successes_a, f_a], [successes_b, f_b]]
    chi2 = 0.0
    for i in range(2):
        for j in range(2):
            expected = row_sums[i] * col_sums[j] / n
            if expected == 0:
                return 0.0
            diff = abs(observed[i][j] - expected) - 0.5  # Yates correction
            if diff < 0:
                diff = 0.0
            chi2 += (diff ** 2) / expected
    return chi2


def compute_ab_significance(
    results: list[dict],
    metric: str = "replies",
    min_sample_size: int = MIN_SAMPLE_SIZE,
) -> dict:
    """Compute pairwise chi-squared significance between variants.

    Args:
        results: Aggregated variant results from ``aggregate_engagement_results``.
        metric: Which metric to test (``"replies"``, ``"opens"``, ``"clicks"``).
        min_sample_size: Minimum sends per variant to be included.

    Returns:
        A dict with:
        - ``comparisons``: List of pairwise comparison dicts with chi2, significant, and effect_size.
        - ``winner_id``: Variant ID of the statistically significant winner, or None.
        - ``is_significant``: Whether any comparison reached significance.
        - ``recommendation``: Human-readable recommendation.
    """
    qualified = [r for r in results if r.get("sent", 0) >= min_sample_size]
    if len(qualified) < 2:
        return {
            "comparisons": [],
            "winner_id": None,
            "is_significant": False,
            "recommendation": (
                "Insufficient data for significance testing. "
                f"Need at least 2 variants with {min_sample_size}+ sends each."
            ),
        }

    comparisons = []
    for i in range(len(qualified)):
        for j in range(i + 1, len(qualified)):
            a = qualified[i]
            b = qualified[j]
            s_a = a.get(metric, 0)
            s_b = b.get(metric, 0)
            t_a = a.get("sent", 0)
            t_b = b.get("sent", 0)

            chi2 = _chi_squared_2x2(s_a, t_a, s_b, t_b)
            is_sig = chi2 >= _CHI2_CRITICAL_005

            # Effect size (difference in rates)
            rate_a = s_a / t_a if t_a else 0.0
            rate_b = s_b / t_b if t_b else 0.0

            comparisons.append({
                "variant_a": a["variant_id"],
                "variant_b": b["variant_id"],
                "metric": metric,
                "rate_a": round(rate_a, 4),
                "rate_b": round(rate_b, 4),
                "chi_squared": round(chi2, 4),
                "significant": is_sig,
                "effect_size": round(abs(rate_a - rate_b), 4),
            })

    any_significant = any(c["significant"] for c in comparisons)

    # Determine winner: variant with best rate among significant comparisons
    winner_id = None
    if any_significant:
        # Find the best performer among all significant comparisons
        best_rate = -1.0
        for comp in comparisons:
            if comp["significant"]:
                if comp["rate_a"] > best_rate:
                    best_rate = comp["rate_a"]
                    winner_id = comp["variant_a"]
                if comp["rate_b"] > best_rate:
                    best_rate = comp["rate_b"]
                    winner_id = comp["variant_b"]

    if winner_id:
        recommendation = (
            f"Variant {winner_id} is the statistically significant winner "
            f"(p < 0.05, chi-squared test). Consider promoting this variant."
        )
    elif any_significant:
        recommendation = "Significant differences detected but no clear single winner."
    else:
        recommendation = (
            "No statistically significant difference between variants yet. "
            "Continue collecting data."
        )

    return {
        "comparisons": comparisons,
        "winner_id": winner_id,
        "is_significant": any_significant,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Confidence updates
# ---------------------------------------------------------------------------


def compute_confidence_updates(
    results: list[dict],
    findings: list[dict],
) -> list[tuple[str, float]]:
    """Compute per-finding confidence deltas based on engagement results.

    Rules:
    - Only update when sample_size (sent) >= MIN_SAMPLE_SIZE.
    - Weight the delta by: sample_size factor, metric quality, recency proxy.
    - Cap delta magnitude at ±0.15 to prevent over-corrections on small samples.
    - A positive reply_rate above 0.05 increases confidence; below 0.02 decreases it.

    Returns:
        List of (finding_id, delta) tuples for every finding referenced in the results.
    """
    if not results or not findings:
        return []

    # Build finding_id → list of variant results that reference the finding
    finding_refs: dict[str, list[dict]] = defaultdict(list)
    for finding in findings:
        finding_id = finding.get("id")
        if not finding_id:
            continue
        # We can't directly know which variant cited this finding unless we look in
        # content_variants. To keep the feedback agent self-contained, we apply a
        # global average across all qualified results as a conservative update.
        finding_refs[finding_id] = [r for r in results if r.get("sent", 0) >= MIN_SAMPLE_SIZE]

    updates: list[tuple[str, float]] = []
    for finding_id, variant_results in finding_refs.items():
        if not variant_results:
            continue

        avg_reply = sum(r.get("reply_rate", 0.0) for r in variant_results) / len(variant_results)
        avg_sent = sum(r.get("sent", 0) for r in variant_results) / len(variant_results)

        # Scale factor: more sends → more trust in the signal (capped at 1.0)
        sample_factor = min(1.0, avg_sent / 20.0)

        # Direction: above 5% reply is good, below 2% is bad
        if avg_reply >= 0.05:
            base_delta = 0.10
        elif avg_reply >= 0.02:
            base_delta = 0.03
        else:
            base_delta = -0.05

        delta = round(base_delta * sample_factor, 4)
        # Clamp to ±0.15
        delta = max(-0.15, min(0.15, delta))
        updates.append((finding_id, delta))

    return updates


# ---------------------------------------------------------------------------
# Learning delta summarizer
# ---------------------------------------------------------------------------


def summarize_learning(
    results: list[dict],
    winner: dict | None,
    significance: dict | None = None,
) -> str:
    """Produce a compact human-readable learning_delta text."""
    if not results:
        return "No engagement data collected this cycle."

    lines: list[str] = []
    for r in results:
        lines.append(
            f"Variant {r['variant_id']}: sent={r['sent']}, "
            f"open_rate={r['open_rate']:.1%}, reply_rate={r['reply_rate']:.1%}"
        )

    summary = "Engagement summary:\n" + "\n".join(lines)
    if winner:
        summary += (
            f"\n\nWinner: variant {winner['variant_id']} with "
            f"reply_rate={winner['reply_rate']:.1%} (n={winner['sent']})"
        )
    else:
        summary += "\n\nNo winner declared — insufficient sample size."

    if significance:
        summary += f"\n\nStatistical significance: {significance['recommendation']}"
        if significance.get("comparisons"):
            for comp in significance["comparisons"]:
                sig_label = "SIGNIFICANT" if comp["significant"] else "not significant"
                summary += (
                    f"\n  {comp['variant_a']} vs {comp['variant_b']}: "
                    f"chi²={comp['chi_squared']:.3f} ({sig_label}), "
                    f"effect_size={comp['effect_size']:.1%}"
                )

    return summary


# ---------------------------------------------------------------------------
# Event quarantine
# ---------------------------------------------------------------------------


async def _quarantine_unmatched_events(
    events: list[dict],
    records: list[dict],
) -> None:
    """Save events that cannot be correlated to any deployment record to quarantine."""
    record_ids = {r.get("id") for r in records} | {r.get("provider_message_id") for r in records}
    for event in events:
        record_id = event.get("deployment_record_id")
        pmid = event.get("provider_message_id")
        if record_id not in record_ids and pmid not in record_ids:
            logger.warning(
                "quarantining unmatched event: provider_event_id=%s dedupe_key=%s",
                event.get("provider_event_id"),
                event.get("dedupe_key"),
            )
            await save_quarantine_event(
                {**event, "quarantine_reason": "no_matching_deployment_record"}
            )


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_ab_results_frame(
    results: list[dict],
    winner: dict | None,
    instance_id: str,
    significance: dict | None = None,
) -> dict:
    """Build an ABResults UI frame showing per-variant engagement metrics."""
    return UIFrame(
        type="ui_component",
        component="ABResults",
        instance_id=instance_id,
        props={
            "results": results,
            "winner_variant_id": winner["variant_id"] if winner else None,
            "significance": significance,
        },
        actions=[
            UIAction(
                id="run-next-cycle",
                label="Run Next Cycle",
                action_type="run_next_cycle",
                payload={},
            ),
        ],
    ).model_dump()


def build_cycle_summary_frame(
    learning_delta: str,
    winner: dict | None,
    cycle_number: int,
    instance_id: str,
) -> dict:
    """Build a CycleSummary UI frame with learning delta and next-step guidance."""
    return UIFrame(
        type="ui_component",
        component="CycleSummary",
        instance_id=instance_id,
        props={
            "cycle_number": cycle_number,
            "learning_delta": learning_delta,
            "winner_variant_id": winner["variant_id"] if winner else None,
            "winner_reply_rate": winner["reply_rate"] if winner else None,
        },
        actions=[
            UIAction(
                id="run-next-cycle",
                label="Run Next Cycle",
                action_type="run_next_cycle",
                payload={},
            ),
            UIAction(
                id="view-findings",
                label="View Updated Findings",
                action_type="view_findings",
                payload={},
            ),
        ],
    ).model_dump()


def build_feedback_prompt_frame(instance_id: str) -> dict:
    """Build a prompt UI frame when no events exist yet — asks for manual feedback."""
    return UIFrame(
        type="ui_component",
        component="FeedbackPrompt",
        instance_id=instance_id,
        props={
            "message": "No engagement events have been received yet. "
            "You can report results manually or wait for webhook events.",
        },
        actions=[
            UIAction(
                id="report-manual",
                label="Report Results Manually",
                action_type="manual_feedback",
                payload={},
            ),
            UIAction(
                id="view-quarantine",
                label="View Quarantine",
                action_type="view_quarantine",
                payload={},
            ),
        ],
    ).model_dump()


def build_manual_feedback_frame(deployment_records: list[dict], instance_id: str) -> dict:
    """Build a ManualFeedbackInput UI frame with distinct variants from deployment records."""
    seen: set[str] = set()
    variants: list[dict] = []
    for rec in deployment_records:
        v_id = rec.get("variant_id")
        if v_id and v_id not in seen:
            seen.add(v_id)
            variants.append({"id": v_id, "label": f"Variant {v_id[:8]}"})

    return UIFrame(
        type="ui_component",
        component="ManualFeedbackInput",
        instance_id=instance_id,
        props={"variants": variants},
        actions=[],
    ).model_dump()


def build_quarantine_viewer_frame(events: list[dict], instance_id: str) -> dict:
    """Build a QuarantineViewer UI frame showing unmatched/quarantined events."""
    return UIFrame(
        type="ui_component",
        component="QuarantineViewer",
        instance_id=instance_id,
        props={"events": events},
        actions=[],
    ).model_dump()


def _emit_feedback_prompt(state: CampaignState) -> dict:
    """Return a state update that emits a feedback prompt UI frame."""
    instance_id = f"feedback-prompt-{uuid4().hex[:8]}"
    frame = build_feedback_prompt_frame(instance_id)
    logger.info(
        "feedback_agent_node: no events — emitting FeedbackPrompt | session=%s",
        state.get("session_id"),
    )
    return {"pending_ui_frames": [frame]}


# ---------------------------------------------------------------------------
# Main agent node
# ---------------------------------------------------------------------------


async def feedback_agent_node(state: CampaignState) -> dict:
    """Aggregate engagement events, update confidence, write learning delta.

    Flow:
    1. If no normalized_feedback_events → emit FeedbackPrompt UI and wait.
    2. Quarantine events that cannot be correlated to any deployment record.
    3. Aggregate events by variant into open/click/reply/bounce rates.
    4. Determine winner (requires MIN_SAMPLE_SIZE sends per variant).
    5. Compute per-finding confidence deltas and persist to MongoDB.
    6. Write IntelligenceEntry (learning_delta) to MongoDB.
    7. Emit ABResults + CycleSummary UI frames.
    8. Advance cycle_number and route back to orchestrator.
    """
    session_id = state.get("session_id", "")
    cycle_number = state.get("cycle_number", 0)
    events: list[dict] = state.get("normalized_feedback_events", [])
    records: list[dict] = state.get("deployment_records", [])
    findings: list[dict] = state.get("research_findings", [])

    logger.info(
        "feedback_agent_node called | session=%s events=%d records=%d findings=%d",
        session_id,
        len(events),
        len(records),
        len(findings),
    )

    # Build scoped context bundle for structured context access
    try:
        bundle = await memory_manager.build_context_bundle(state, "feedback")
        logger.debug(
            "feedback_agent_node: bundle built | deployment_records=%d normalized_metrics=%d",
            len(bundle.get("deployment_records", [])),
            len(bundle.get("normalized_metrics", [])),
        )
    except Exception as exc:
        logger.warning("feedback_agent_node: memory bundle failed (%s) — continuing", exc)

    if not events:
        return _emit_feedback_prompt(state)

    # -- Step 1: Quarantine unmatched events (fire-and-forget; do not block on failure) --
    try:
        await _quarantine_unmatched_events(events, records)
    except Exception as exc:
        logger.error("feedback_agent_node: quarantine step failed: %s", exc)

    # -- Step 2: Aggregate engagement results --
    results = aggregate_engagement_results(events, records)
    logger.info("feedback_agent_node: aggregated %d variant results", len(results))

    # -- Step 3: Determine winner --
    winner = determine_winner(results, min_sample_size=MIN_SAMPLE_SIZE)

    # -- Step 3b: Statistical significance testing --
    significance = compute_ab_significance(results, metric="replies", min_sample_size=MIN_SAMPLE_SIZE)
    if significance.get("is_significant") and significance.get("winner_id"):
        # Override winner with statistically significant winner if different
        sig_winner = next(
            (r for r in results if r["variant_id"] == significance["winner_id"]), None
        )
        if sig_winner:
            winner = sig_winner
            logger.info(
                "feedback_agent_node: statistically significant winner=%s",
                significance["winner_id"],
            )
    logger.info(
        "feedback_agent_node: significance test — significant=%s winner=%s",
        significance.get("is_significant"),
        significance.get("winner_id"),
    )

    # -- Step 4: Compute and persist confidence updates --
    confidence_updates: list[dict] = []
    try:
        updates = compute_confidence_updates(results, findings)
        for finding_id, delta in updates:
            await update_finding_confidence(finding_id, delta)
            confidence_updates.append({"finding_id": finding_id, "delta": delta})
        logger.info("feedback_agent_node: persisted %d confidence updates", len(confidence_updates))
    except Exception as exc:
        logger.error("feedback_agent_node: confidence update step failed: %s", exc)

    # -- Step 5: Build and save learning delta --
    learning_delta = summarize_learning(results, winner, significance)
    entry = IntelligenceEntry(
        id=str(uuid4()),
        session_id=session_id,
        cycle_number=cycle_number,
        learning_delta=learning_delta,
        confidence_updates=confidence_updates,
        winning_variant_id=winner["variant_id"] if winner else None,
        created_at=datetime.now(timezone.utc),
    )
    try:
        await save_intelligence_entry(entry.model_dump(mode="json"))
        logger.info("feedback_agent_node: saved IntelligenceEntry id=%s", entry.id)
    except Exception as exc:
        logger.error("feedback_agent_node: failed to save IntelligenceEntry: %s", exc)

    # -- Step 6: Build UI frames --
    run_id = uuid4().hex[:8]
    ab_frame = build_ab_results_frame(results, winner, f"ab-results-{run_id}", significance)
    summary_frame = build_cycle_summary_frame(
        learning_delta, winner, cycle_number, f"cycle-summary-{run_id}"
    )

    return {
        "engagement_results": results,
        "winning_variant_id": winner["variant_id"] if winner else None,
        "ab_significance": significance,
        "prior_cycle_summary": learning_delta,
        "cycle_number": cycle_number + 1,
        "next_node": "orchestrator",
        "pending_ui_frames": [ab_frame, summary_frame],
    }
