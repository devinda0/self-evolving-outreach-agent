"""Memory Manager — context bundle construction and token budgeting.

Constructs scoped context bundles for each agent call so that every agent
receives only the information it needs, not the full raw session state.
Also manages conversation summarisation when the thread grows long.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.llm import get_llm
from app.db.crud import get_top_findings
from app.models.campaign_state import CampaignState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token budget per agent type (approximate token estimates for the bundle)
# ---------------------------------------------------------------------------

AGENT_TOKEN_BUDGETS: dict[str, int] = {
    "orchestrator": 4000,
    "research": 6000,
    "research_synthesis": 8000,
    "segment": 5000,
    "content": 7000,
    "deployment": 3000,
    "feedback": 4000,
}

# Rough chars-per-token estimate for truncation (conservative)
_CHARS_PER_TOKEN = 4

# Number of recent messages preserved verbatim in summaries / context bundles
_RECENT_MESSAGE_WINDOW = 8

# Orchestrator needs a slightly larger window to capture full conversation intent
_ORCHESTRATOR_MESSAGE_WINDOW = 12

# ---------------------------------------------------------------------------
# Summarisation constants (public — imported by tests and graph nodes)
# ---------------------------------------------------------------------------

# Minimum messages before the first summary is generated
SUMMARIZATION_THRESHOLD = 20

# Re-summarise only after this many additional messages accumulate since last summary
RESUMMARIZE_EVERY_N = 10

# Always keep this many recent messages verbatim (never summarised)
VERBATIM_KEEP_LAST_N = 8

# Internal alias used by MemoryManager.maybe_summarize_conversation
_SUMMARISE_THRESHOLD = SUMMARIZATION_THRESHOLD


# ---------------------------------------------------------------------------
# Public helpers re-exported from orchestrator to avoid circular imports
# ---------------------------------------------------------------------------


def _format_message(msg: Any) -> str:
    """Format a single message (dict or LangChain BaseMessage)."""
    if hasattr(msg, "type") and hasattr(msg, "content"):
        role = msg.type
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
    else:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
    if len(content) > 500:
        content = content[:500] + "..."
    return f"[{role}]: {content}"


def _format_messages(messages: list[Any]) -> str:
    if not messages:
        return "(no messages yet)"
    return "\n".join(_format_message(m) for m in messages)


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


def enforce_token_budget(bundle: dict, agent_type: str) -> dict:
    """Truncate bundle fields to fit within the agent's token budget.

    Strategy:
    - Convert the bundle to a rough character count.
    - If it exceeds the budget, shorten ``recent_messages`` first
      (keep at least the last 3), then truncate findings lists.
    """
    budget_chars = AGENT_TOKEN_BUDGETS.get(agent_type, 4000) * _CHARS_PER_TOKEN
    bundle = dict(bundle)  # shallow copy

    def _char_count(obj: Any) -> int:
        return len(str(obj))

    def _total() -> int:
        return sum(_char_count(v) for v in bundle.values())

    # Step 1: trim recent_messages
    messages = bundle.get("recent_messages", [])
    while _total() > budget_chars and len(messages) > 3:
        messages = messages[1:]  # drop oldest
        bundle["recent_messages"] = messages

    # Step 2: trim findings lists
    for key in ("source_findings", "top_findings", "top_long_term_findings"):
        findings = bundle.get(key)
        if findings and isinstance(findings, list):
            while _total() > budget_chars and len(findings) > 1:
                findings = findings[:-1]
            bundle[key] = findings

    return bundle


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------


class MemoryManager:
    """Builds scoped context bundles and manages conversation summarisation."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_context_bundle(self, state: CampaignState, agent_type: str) -> dict:
        """Build a scoped context bundle for the specified agent.

        Each agent gets only what it needs — not the full raw session.
        """
        message_window = (
            _ORCHESTRATOR_MESSAGE_WINDOW if agent_type == "orchestrator" else _RECENT_MESSAGE_WINDOW
        )
        base: dict[str, Any] = {
            "task_header": self._get_task_header(state, agent_type),
            "current_stage_state": self._get_stage_state(state, agent_type),
            "latest_user_intent": state.get("current_intent"),
            "recent_messages": self._get_recent_messages(state, n=message_window),
            "relevant_cycle_summary": state.get("prior_cycle_summary"),
        }

        # Include accumulated learnings for all agents so they can evolve
        accumulated = state.get("accumulated_learnings")
        if accumulated:
            base["accumulated_learnings"] = accumulated

        # Include compact cycle history for context-aware agents
        cycle_records = state.get("cycle_records", [])
        if cycle_records:
            base["cycle_history"] = self._get_compact_cycle_history(cycle_records)

        # Agent-specific additions
        if agent_type == "orchestrator":
            base["intent_history"] = state.get("intent_history", [])[-5:]

        elif agent_type == "research":
            base["top_long_term_findings"] = await self._get_top_findings(state, k=3)

        elif agent_type == "segment":
            base["top_findings"] = self._get_top_findings_from_state(state, k=5)

        elif agent_type == "content":
            base["source_findings"] = self._get_findings_by_ids(state)
            base["selected_segment"] = self._get_selected_segment(state)
            base["winning_angle_memory"] = state.get("prior_cycle_summary")
            base["prospect_cards"] = self._get_prospect_cards_for_content(state)

        elif agent_type == "deployment":
            base["selected_variant"] = self._get_selected_variants(state)
            base["selected_prospects"] = self._get_compact_prospect_cards(state)

        elif agent_type == "feedback":
            base["deployment_records"] = state.get("deployment_records", [])
            base["normalized_metrics"] = state.get("normalized_feedback_events", [])

        bundle = enforce_token_budget(base, agent_type)
        approx_chars = sum(len(str(v)) for v in bundle.values())
        approx_tokens = approx_chars // _CHARS_PER_TOKEN
        logger.debug(
            "build_context_bundle: agent=%s approx_tokens=%d bundle_keys=%s",
            agent_type,
            approx_tokens,
            list(bundle.keys()),
        )
        return bundle

    async def maybe_summarize_conversation(self, state: CampaignState) -> dict:
        """If the conversation exceeds SUMMARIZATION_THRESHOLD messages, generate a rolling summary.

        Tracks ``_last_summary_message_count`` so re-summarisation only occurs
        after RESUMMARIZE_EVERY_N additional messages have accumulated.

        Preserves the raw transcript in state. Keeps verbatim: last VERBATIM_KEEP_LAST_N
        turns, unresolved clarifications, explicit approvals, final selections.

        Returns a (possibly empty) state patch dict.
        """
        messages = state.get("messages", [])
        if len(messages) <= SUMMARIZATION_THRESHOLD:
            return {}

        last_summary_coverage = state.get("_last_summary_message_count", 0)
        if len(messages) - last_summary_coverage < RESUMMARIZE_EVERY_N:
            return {}

        older_messages = messages[last_summary_coverage:-VERBATIM_KEEP_LAST_N]
        summary_prompt = (
            "Summarize this campaign conversation. Preserve:\n"
            "- Key decisions made (segment chosen, variants selected, channels confirmed)\n"
            "- Research insights referenced\n"
            "- Approvals given by user\n"
            "- Current campaign stage\n\n"
            f"Conversation:\n{_format_messages(older_messages)}"
        )

        llm = self._get_llm()
        if llm is None:
            # Mock path — produce a deterministic summary for tests
            summary_text = (
                f"[Mock summary covering {len(older_messages)} messages. "
                f"Session: {state.get('session_id')}]"
            )
        else:
            try:
                response = await llm.ainvoke(summary_prompt)
                raw_content = response.content if hasattr(response, "content") else response
                summary_text = raw_content if isinstance(raw_content, str) else str(raw_content)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "maybe_summarize_conversation: LLM call failed (%s) — skipping summary",
                    exc,
                )
                return {}

        new_coverage = len(messages) - VERBATIM_KEEP_LAST_N
        decision_log = list(state.get("decision_log", []))
        decision_log.append(
            {
                "id": str(uuid4()),
                "type": "conversation_summary",
                "summary": summary_text,
                "covers_messages": new_coverage,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        logger.info(
            "maybe_summarize_conversation: summarised %d messages | session=%s",
            len(older_messages),
            state.get("session_id"),
        )

        return {
            "conversation_summary": summary_text,
            "decision_log": decision_log,
            "_last_summary_message_count": new_coverage,
        }

    # ------------------------------------------------------------------
    # Private helpers — task header and stage state
    # ------------------------------------------------------------------

    def _get_task_header(self, state: CampaignState, agent_type: str) -> dict:
        """Return key session identity fields."""
        return {
            "session_id": state.get("session_id"),
            "product_name": state.get("product_name"),
            "target_market": state.get("target_market"),
            "cycle_number": state.get("cycle_number", 1),
            "agent_type": agent_type,
        }

    def _get_stage_state(self, state: CampaignState, agent_type: str) -> dict:
        """Return the fields most relevant to the current stage."""
        stage_map: dict[str, list[str]] = {
            "orchestrator": [
                "current_intent",
                "next_node",
                "session_complete",
                "active_stage_summary",
                "previous_intent",
            ],
            "research": [
                "research_query",
                "active_thread_types",
                "briefing_summary",
                "research_gaps",
            ],
            "segment": [
                "selected_segment_id",
                "segment_candidates",
                "prospect_pool_ref",
            ],
            "content": [
                "content_request",
                "selected_variant_ids",
                "selected_segment_id",
                "briefing_summary",
            ],
            "deployment": [
                "selected_channels",
                "deployment_confirmed",
                "ab_split_plan",
            ],
            "feedback": [
                "winning_variant_id",
                "engagement_results",
            ],
        }
        keys = stage_map.get(agent_type, [])
        return {k: state.get(k) for k in keys}

    # ------------------------------------------------------------------
    # Private helpers — message windowing
    # ------------------------------------------------------------------

    def _get_recent_messages(self, state: CampaignState, n: int = 8) -> list:
        """Return last n messages.

        If the conversation has already been summarised, older messages are
        replaced by the summary; only the most recent *n* raw turns are kept.
        """
        messages = state.get("messages", [])
        return messages[-n:]

    # ------------------------------------------------------------------
    # Private helpers — cycle history
    # ------------------------------------------------------------------

    def _get_compact_cycle_history(self, cycle_records: list[dict]) -> list[dict]:
        """Return a compact representation of cycle history for context bundles.

        Only includes the most actionable fields to stay within token budget.
        """
        compact = []
        for rec in cycle_records[-5:]:  # last 5 cycles max
            compact.append({
                "cycle": rec.get("cycle_number"),
                "sends": rec.get("total_sends", 0),
                "replies": rec.get("total_replies", 0),
                "winning_strategy": rec.get("winning_strategy"),
                "amplify": rec.get("approaches_to_amplify", [])[:3],
                "avoid": rec.get("approaches_to_avoid", [])[:3],
            })
        return compact

    # ------------------------------------------------------------------
    # Private helpers — findings
    # ------------------------------------------------------------------

    async def _get_top_findings(self, state: CampaignState, k: int = 5) -> list:
        """Fetch top-k high-confidence findings from MongoDB intelligence store."""
        return await get_top_findings(
            session_id=state["session_id"],
            k=k,
            min_confidence=0.6,
        )

    def _get_top_findings_from_state(self, state: CampaignState, k: int = 5) -> list:
        """Return the top-k findings already loaded into state (no DB call)."""
        findings = state.get("research_findings", [])
        # Sort by confidence descending, return top-k
        sorted_findings = sorted(findings, key=lambda f: f.get("confidence", 0.0), reverse=True)
        return sorted_findings[:k]

    def _get_findings_by_ids(self, state: CampaignState) -> list:
        """Return research findings referenced by selected variants.

        Falls back to all findings in state if no variant selection exists.
        """
        selected_variant_ids = set(state.get("selected_variant_ids", []))
        all_findings = state.get("research_findings", [])

        if not selected_variant_ids:
            # No variant selected yet — return top 5 for content generation
            return self._get_top_findings_from_state(state, k=5)

        # Gather finding IDs referenced by the selected variants
        referenced_finding_ids: set[str] = set()
        for variant in state.get("content_variants", []):
            if variant.get("id") in selected_variant_ids:
                referenced_finding_ids.update(variant.get("source_finding_ids", []))

        if not referenced_finding_ids:
            return self._get_top_findings_from_state(state, k=5)

        return [f for f in all_findings if f.get("id") in referenced_finding_ids]

    def _get_selected_segment(self, state: CampaignState) -> dict | None:
        """Return the selected segment dict, or None if not found."""
        segment_id = state.get("selected_segment_id")
        candidates = state.get("segment_candidates", [])
        if not candidates:
            return None
        if segment_id:
            for seg in candidates:
                if seg.get("id") == segment_id:
                    return seg
        return candidates[0] if candidates else None

    def _get_selected_variants(self, state: CampaignState) -> list:
        """Return the selected content variant dicts."""
        selected_ids = set(state.get("selected_variant_ids", []))
        all_variants = state.get("content_variants", [])
        if not selected_ids:
            return all_variants
        return [v for v in all_variants if v.get("id") in selected_ids]

    def _get_compact_prospect_cards(self, state: CampaignState) -> list:
        """Return only selected prospects as compact cards (ID + key fields).

        Never passes the full prospect table into the prompt.
        """
        selected_ids = set(state.get("selected_prospect_ids", []))
        return [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "email": p.get("email"),
                "title": p.get("title"),
                "company": p.get("company"),
                "angle": p.get("angle_recommendation"),
            }
            for p in state.get("prospect_cards", [])
            if not selected_ids or p.get("id") in selected_ids
        ]

    def _get_prospect_cards_for_content(self, state: CampaignState) -> list:
        """Return prospect cards with personalization-relevant fields for content generation.

        Includes personalization_fields, angle_recommendation, channel_recommendation,
        and fit_score — the fields the content agent needs to deeply personalize messages.
        """
        all_prospects = state.get("prospect_cards", [])
        selected_ids = set(state.get("selected_prospect_ids", []))

        prospects = [
            p for p in all_prospects
            if not selected_ids or p.get("id") in selected_ids
        ]

        # Sort by fit_score descending, limit to top 5
        sorted_prospects = sorted(
            prospects, key=lambda p: p.get("fit_score", 0.0), reverse=True
        )
        return [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "email": p.get("email"),
                "title": p.get("title"),
                "company": p.get("company"),
                "angle_recommendation": p.get("angle_recommendation"),
                "channel_recommendation": p.get("channel_recommendation"),
                "fit_score": p.get("fit_score"),
                "personalization_fields": p.get("personalization_fields", {}),
            }
            for p in sorted_prospects[:5]
        ]

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    def _get_llm(self):
        return get_llm(temperature=0.1)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

memory_manager = MemoryManager()


# ---------------------------------------------------------------------------
# Standalone graph node — pass-through between orchestrator and specialists
# ---------------------------------------------------------------------------


async def maybe_summarize_node(state: CampaignState) -> dict:
    """LangGraph pass-through node that conditionally summarises the conversation.

    Inserted between the orchestrator node and all specialist agents so that
    every agent call starts with a compact, within-budget context.

    Trigger rules:
    - No-op when ``messages`` length ≤ SUMMARIZATION_THRESHOLD (20).
    - No-op when fewer than RESUMMARIZE_EVERY_N (10) messages have accumulated
      since the last summary.
    - Otherwise, summarises messages[last_coverage:-VERBATIM_KEEP_LAST_N] and
      writes the result back to state.
    """
    messages = state.get("messages", [])

    if len(messages) <= SUMMARIZATION_THRESHOLD:
        return {}

    last_summary_coverage = state.get("_last_summary_message_count", 0)
    if len(messages) - last_summary_coverage < RESUMMARIZE_EVERY_N:
        return {}

    return await memory_manager.maybe_summarize_conversation(state)


# ---------------------------------------------------------------------------
# Decision log helpers
# ---------------------------------------------------------------------------


def log_decision(state: CampaignState, entry: dict) -> dict:
    """Return a state patch that appends a typed entry to the decision log.

    Callers pass the event-specific fields (``type``, plus any domain keys).
    This function stamps a unique ``id`` and ``created_at`` automatically.

    Supported entry types and their required extra keys:
    - ``segment_selected``: ``segment_id``, ``label``
    - ``variants_selected``: ``variant_ids``
    - ``deployment_confirmed``: ``prospect_count``
    - ``cycle_complete``: ``cycle``, ``winner_id``

    Example::

        patch = log_decision(state, {
            "type": "segment_selected",
            "segment_id": "seg-001",
            "label": "VP Sales at Series B SaaS",
        })
        # merge patch back into state update dict

    Returns:
        Dict with a single key ``decision_log`` containing the full updated list.
    """
    existing = list(state.get("decision_log", []))
    existing.append(
        {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **entry,
        }
    )
    return {"decision_log": existing}
