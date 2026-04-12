"""Feedback Agent — engagement event aggregation, confidence updates, and learning delta.

Handles:
- Hydrating feedback events from MongoDB (capturing webhook-delivered events)
- Aggregating normalized engagement events by variant/segment/channel
- LLM-powered reply classification (intent, sentiment, actionable signals)
- Per-prospect email thread analysis and summary
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
    get_deployment_records_for_session,
    get_email_threads_for_session,
    get_feedback_events_for_session,
    get_reply_events_for_session,
    save_intelligence_entry,
    save_quarantine_event,
    update_feedback_event,
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
# Event hydration from MongoDB
# ---------------------------------------------------------------------------


async def hydrate_feedback_from_db(
    session_id: str,
    state_events: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Merge feedback events from state with events stored in MongoDB by webhooks.

    Webhooks write directly to MongoDB, bypassing LangGraph state. This function
    ensures the feedback agent sees ALL events — both those already in state and
    those delivered via webhooks since the last graph run.

    Returns:
        (all_events, db_records) — deduplicated merged events and deployment records.
    """
    db_events = await get_feedback_events_for_session(session_id)
    db_records = await get_deployment_records_for_session(session_id)

    # Build dedupe set from state events
    seen_keys: set[str] = set()
    for event in state_events:
        key = event.get("dedupe_key") or f"{event.get('provider_message_id')}:{event.get('event_type')}"
        seen_keys.add(key)

    # Merge DB events not already in state
    merged = list(state_events)
    new_from_db = 0
    for event in db_events:
        key = event.get("dedupe_key") or f"{event.get('provider_message_id')}:{event.get('event_type')}"
        if key not in seen_keys:
            merged.append(event)
            seen_keys.add(key)
            new_from_db += 1

    if new_from_db > 0:
        logger.info(
            "hydrate_feedback_from_db: merged %d new events from DB (total=%d) | session=%s",
            new_from_db,
            len(merged),
            session_id,
        )

    return merged, db_records


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
    reply_insights: list[dict] | None = None,
    thread_summaries: list[dict] | None = None,
) -> str:
    """Produce a comprehensive human-readable learning_delta text."""
    if not results:
        return "No engagement data collected this cycle."

    lines: list[str] = []

    # --- Engagement metrics ---
    lines.append("## Engagement Summary")
    for r in results:
        lines.append(
            f"- Variant {r['variant_id'][:8]}: sent={r.get('sent', 0)}, "
            f"open_rate={r.get('open_rate', 0):.1%}, click_rate={r.get('click_rate', 0):.1%}, "
            f"reply_rate={r.get('reply_rate', 0):.1%}, bounce_rate={r.get('bounce_rate', 0):.1%}"
        )

    if winner:
        lines.append(
            f"\n**Winner: variant {winner['variant_id'][:8]}** with "
            f"reply_rate={winner.get('reply_rate', 0):.1%} (n={winner.get('sent', 0)})"
        )
    else:
        lines.append("\nNo winner declared — insufficient sample size.")

    if significance:
        lines.append(f"\n## Statistical Significance\n{significance['recommendation']}")
        if significance.get("comparisons"):
            for comp in significance["comparisons"]:
                sig_label = "SIGNIFICANT" if comp["significant"] else "not significant"
                lines.append(
                    f"- {comp['variant_a'][:8]} vs {comp['variant_b'][:8]}: "
                    f"chi²={comp['chi_squared']:.3f} ({sig_label}), "
                    f"effect_size={comp['effect_size']:.1%}"
                )

    # --- Reply Intelligence ---
    if reply_insights:
        lines.append("\n## Reply Analysis")
        classification_counts: dict[str, int] = defaultdict(int)
        sentiment_counts: dict[str, int] = defaultdict(int)
        key_signals_all: list[str] = []

        for insight in reply_insights:
            cls = insight.get("classification", "unknown")
            sent = insight.get("sentiment", "unknown")
            classification_counts[cls] += 1
            sentiment_counts[sent] += 1
            key_signals_all.extend(insight.get("key_signals", []))

        lines.append(f"Total replies analyzed: {len(reply_insights)}")
        lines.append("Classification breakdown:")
        for cls, count in sorted(classification_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  - {cls}: {count}")
        lines.append("Sentiment breakdown:")
        for sent, count in sorted(sentiment_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  - {sent}: {count}")

        if key_signals_all:
            # Deduplicate and show top signals
            unique_signals = list(dict.fromkeys(key_signals_all))[:10]
            lines.append("Key signals extracted:")
            for signal in unique_signals:
                lines.append(f"  - {signal}")

    # --- Per-prospect thread summaries ---
    if thread_summaries:
        replied_threads = [t for t in thread_summaries if t.get("status") == "replied"]
        if replied_threads:
            lines.append(f"\n## Prospect Conversations ({len(replied_threads)} active threads)")
            for t in replied_threads[:5]:  # Show top 5
                prospect_name = t.get("prospect_name") or t.get("prospect_email", "Unknown")
                reply_count = t.get("reply_count", 0)
                classification = t.get("classification") or "pending"
                lines.append(
                    f"- {prospect_name}: {reply_count} replies, "
                    f"latest classification: {classification}"
                )

    # --- Actionable recommendations ---
    lines.append("\n## Recommendations for Next Cycle")
    if reply_insights:
        interested_count = sum(
            1 for i in reply_insights if i.get("classification") == "interested"
        )
        not_interested_count = sum(
            1 for i in reply_insights if i.get("classification") == "not_interested"
        )
        if interested_count > 0:
            lines.append(
                f"- {interested_count} prospect(s) expressed interest — prioritize follow-up"
            )
        if not_interested_count > 0:
            lines.append(
                f"- {not_interested_count} prospect(s) declined — analyze objections for content refinement"
            )
        # Extract common objections
        objections = [
            i.get("extracted_info", {}).get("objection")
            for i in reply_insights
            if i.get("extracted_info", {}).get("objection")
        ]
        if objections:
            lines.append("- Common objections:")
            for obj in objections[:3]:
                lines.append(f"    - {obj}")

    return "\n".join(lines)


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
    """Aggregate engagement events, classify replies, analyze threads, write learning delta.

    Flow:
    1. Hydrate events from MongoDB (captures webhook-delivered events missed in state).
    2. If no events at all → emit FeedbackPrompt UI and wait.
    3. Quarantine events that cannot be correlated to any deployment record.
    4. Aggregate events by variant into open/click/reply/bounce rates.
    5. Classify reply events using LLM-powered reply classifier.
    6. Load email threads and build per-prospect conversation summaries.
    7. Determine winner (requires MIN_SAMPLE_SIZE sends per variant).
    8. Compute per-finding confidence deltas and persist to MongoDB.
    9. Write enriched IntelligenceEntry (learning_delta + reply_insights) to MongoDB.
    10. Emit ABResults + CycleSummary UI frames.
    11. Advance cycle_number and route back to orchestrator.
    """
    from app.agents.reply_classifier import classify_reply_events

    session_id = state.get("session_id", "")
    cycle_number = state.get("cycle_number", 0)
    state_events: list[dict] = state.get("normalized_feedback_events", [])
    state_records: list[dict] = state.get("deployment_records", [])
    findings: list[dict] = state.get("research_findings", [])

    logger.info(
        "feedback_agent_node called | session=%s state_events=%d records=%d findings=%d",
        session_id,
        len(state_events),
        len(state_records),
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

    # -- Step 1: Hydrate events from MongoDB --
    # Webhooks write directly to DB, bypassing LangGraph state. Merge to get
    # the full picture of engagement events since deployment.
    try:
        events, records = await hydrate_feedback_from_db(session_id, state_events)
        # Use DB records if state records are empty (common after webhook ingestion)
        if not records and state_records:
            records = state_records
    except Exception as exc:
        logger.error("feedback_agent_node: hydration failed (%s) — falling back to state", exc)
        events = state_events
        records = state_records

    logger.info(
        "feedback_agent_node: after hydration | events=%d records=%d",
        len(events),
        len(records),
    )

    if not events:
        return _emit_feedback_prompt(state)

    # -- Step 2: Quarantine unmatched events --
    try:
        await _quarantine_unmatched_events(events, records)
    except Exception as exc:
        logger.error("feedback_agent_node: quarantine step failed: %s", exc)

    # -- Step 3: Aggregate engagement results --
    results = aggregate_engagement_results(events, records)
    logger.info("feedback_agent_node: aggregated %d variant results", len(results))

    # -- Step 4: Classify reply events with LLM --
    reply_insights: list[dict] = []
    reply_events = [e for e in events if e.get("event_type") == "reply"]
    if reply_events:
        try:
            threads = await get_email_threads_for_session(session_id)
            prospects = state.get("prospect_cards", [])
            variants = state.get("content_variants", [])

            classified_replies = await classify_reply_events(
                events=reply_events,
                threads=threads,
                prospects=prospects,
                variants=variants,
            )

            # Persist classifications back to MongoDB and collect insights
            for event in classified_replies:
                cls_data = event.get("reply_classification", {})
                if cls_data:
                    reply_insights.append(cls_data)
                    dedupe_key = event.get("dedupe_key")
                    if dedupe_key:
                        try:
                            await update_feedback_event(dedupe_key, {
                                "reply_classification": cls_data.get("classification"),
                                "reply_body": event.get("reply_body"),
                            })
                        except Exception as exc:
                            logger.warning(
                                "feedback_agent_node: failed to persist classification for %s: %s",
                                dedupe_key, exc,
                            )

            logger.info(
                "feedback_agent_node: classified %d reply events", len(classified_replies)
            )
        except Exception as exc:
            logger.error("feedback_agent_node: reply classification failed: %s", exc)
    else:
        logger.info("feedback_agent_node: no reply events to classify")

    # -- Step 5: Build per-prospect thread summaries --
    thread_summaries: list[dict] = []
    try:
        threads = await get_email_threads_for_session(session_id)
        for thread in threads:
            thread_summaries.append({
                "prospect_id": thread.get("prospect_id"),
                "prospect_email": thread.get("prospect_email"),
                "prospect_name": thread.get("prospect_name"),
                "status": thread.get("status"),
                "reply_count": thread.get("reply_count", 0),
                "classification": thread.get("classification"),
                "variant_id": thread.get("variant_id"),
            })
        logger.info(
            "feedback_agent_node: built %d thread summaries", len(thread_summaries)
        )
    except Exception as exc:
        logger.error("feedback_agent_node: thread summary step failed: %s", exc)

    # -- Step 6: Determine winner --
    winner = determine_winner(results, min_sample_size=MIN_SAMPLE_SIZE)

    # -- Step 6b: Statistical significance testing --
    significance = compute_ab_significance(
        results, metric="replies", min_sample_size=MIN_SAMPLE_SIZE
    )
    if significance.get("is_significant") and significance.get("winner_id"):
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

    # -- Step 7: Compute and persist confidence updates --
    confidence_updates: list[dict] = []
    try:
        updates = compute_confidence_updates(results, findings)
        for finding_id, delta in updates:
            await update_finding_confidence(finding_id, delta)
            confidence_updates.append({"finding_id": finding_id, "delta": delta})
        logger.info(
            "feedback_agent_node: persisted %d confidence updates", len(confidence_updates)
        )
    except Exception as exc:
        logger.error("feedback_agent_node: confidence update step failed: %s", exc)

    # -- Step 8: Build and save enriched learning delta --
    learning_delta = summarize_learning(
        results, winner, significance,
        reply_insights=reply_insights,
        thread_summaries=thread_summaries,
    )

    # Build prospect sentiment summary from reply classifications
    prospect_sentiment: dict[str, dict] = {}
    for event in reply_events:
        pid = event.get("prospect_id")
        cls_data = event.get("reply_classification", {})
        if pid and cls_data:
            prospect_sentiment[pid] = {
                "classification": cls_data.get("classification"),
                "sentiment": cls_data.get("sentiment"),
                "confidence": cls_data.get("confidence"),
                "key_signals": cls_data.get("key_signals", []),
                "suggested_action": cls_data.get("suggested_action"),
            }

    entry = IntelligenceEntry(
        id=str(uuid4()),
        session_id=session_id,
        cycle_number=cycle_number,
        learning_delta=learning_delta,
        confidence_updates=confidence_updates,
        winning_variant_id=winner["variant_id"] if winner else None,
        reply_insights=reply_insights,
        prospect_sentiment_summary=prospect_sentiment,
        created_at=datetime.now(timezone.utc),
    )
    try:
        await save_intelligence_entry(entry.model_dump(mode="json"))
        logger.info("feedback_agent_node: saved IntelligenceEntry id=%s", entry.id)
    except Exception as exc:
        logger.error("feedback_agent_node: failed to save IntelligenceEntry: %s", exc)

    # -- Step 9: Build UI frames --
    run_id = uuid4().hex[:8]
    ab_frame = build_ab_results_frame(results, winner, f"ab-results-{run_id}", significance)
    summary_frame = build_cycle_summary_frame(
        learning_delta, winner, cycle_number, f"cycle-summary-{run_id}"
    )

    # Build response message summarizing the feedback analysis
    user_directive = state.get("user_directive")
    total_events = len(events)

    if winner:
        winner_summary = (
            f"Variant {winner['variant_id'][:8]} is the winner with "
            f"{winner.get('reply_rate', 0):.1%} reply rate."
        )
    else:
        winner_summary = "No clear winner yet — more data is needed."

    sig_note = ""
    if significance and significance.get("is_significant"):
        sig_note = " Results are statistically significant (p < 0.05)."

    directive_note = ""
    if user_directive:
        directive_note = f" (per your request: {user_directive})"

    # Include reply intelligence in response
    reply_note = ""
    if reply_insights:
        interested = sum(1 for r in reply_insights if r.get("classification") == "interested")
        total_replies = len(reply_insights)
        reply_note = f" {total_replies} replies analyzed"
        if interested > 0:
            reply_note += f" ({interested} expressing interest)"
        reply_note += "."

    response_message = (
        f"Feedback analysis complete{directive_note}. "
        f"Processed {total_events} engagement events across {len(results)} variants. "
        f"{winner_summary}{sig_note}{reply_note} "
        f"Cycle {cycle_number} learning has been captured for the next iteration."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"feedback_response_{run_id}",
        props={"content": response_message, "role": "assistant"},
        actions=[],
    ).model_dump()

    return {
        "normalized_feedback_events": events,
        "engagement_results": results,
        "winning_variant_id": winner["variant_id"] if winner else None,
        "ab_significance": significance,
        "prior_cycle_summary": learning_delta,
        "next_node": "orchestrator",
        "pending_ui_frames": [response_frame, ab_frame, summary_frame],
    }
