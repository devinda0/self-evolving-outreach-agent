"""Orchestrator agent — Gemini-powered intent classifier and router.

The orchestrator is the brain of the system. Every user message flows through here,
and it classifies intent and routes to the appropriate specialist agent.

Intent modes:
- research: market intelligence, competitor analysis, audience signals
- segment: target segment definition, prospect scoring/selection
- generate: content creation (outreach, social posts, briefs)
- deploy: send content to channels
- feedback: engagement results reporting
- refined_cycle: restart loop with accumulated intelligence
- clarify: ambiguous message, need clarification
- answer: user asks a question answerable from existing context
- update_context: user provides clarifications or additional info about their product/company/goals
"""

import json
import logging
import re
from typing import Any
from uuid import uuid4

from app.core.llm import get_llm
from app.db.crud import get_latest_variants_for_session
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)

# Valid intent modes
VALID_INTENTS = frozenset(
    [
        "research",
        "segment",
        "prospect_manage",
        "generate",
        "content_refine",
        "deploy",
        "feedback",
        "refined_cycle",
        "clarify",
        "answer",
        "update_context",
        "mcp_configure",
        "lookup",
    ]
)

# Intent to node mapping
INTENT_TO_NODE = {
    "research": "research",
    "segment": "segment",
    "prospect_manage": "prospect_manage",
    "generate": "generate",
    "content_refine": "content_refine",
    "deploy": "deploy",
    "feedback": "feedback",
    "refined_cycle": "refined_cycle",
    "clarify": "clarify",
    "answer": "answer",
    "update_context": "update_context",
    "mcp_configure": "mcp_configure",
    "lookup": "lookup",
}

SYSTEM_PROMPT = """You are the Orchestrator of Signal to Action, a multi-agent growth intelligence system.

Your sole job: classify the user's latest message into exactly one intent mode and return a routing decision.

## Intent Modes
- research: user wants market intelligence, competitor analysis, audience signals, channel trends
- segment: user wants to define a target segment or score/rank/filter already-loaded prospects
- prospect_manage: user wants to find/discover MULTIPLE prospects for the campaign target market, OR manage the prospect list (add/remove/edit individuals, upload CSV, view prospects, select for outreach). Use for bulk discovery and list management. Key: "find prospects", "discover prospects", "search for prospects".
- lookup: user wants to find information about ONE SPECIFIC named individual — their LinkedIn profile URL, LinkedIn username, email, company, title, or other contact details. This is a targeted lookup for a single person, NOT bulk prospect discovery. Key phrases: "what is [name]'s LinkedIn?", "find [name]'s profile", "look up [name]", "can you find it through internet?", "search for [name] online", "find his/her LinkedIn", "what is his/her username?", "get me [name]'s contact info". IMPORTANT: When the previous AI message said something was "not available in the current context" about a specific person and the user asks to find it via internet, that is ALWAYS lookup.
- generate: user wants content created (outreach, social posts, briefs). Also use this when the message contains clarification answers for content generation (e.g. "Generate outreach content using my clarification answers", or text formatted as "Question: Answer" pairs related to content creation context).
- content_refine: user wants to MODIFY, EDIT, or IMPROVE already-generated content variants. Use this when content_variants already exist and the user asks to change tone, shorten, rewrite, make more casual/formal, adjust CTAs, change subject lines, or otherwise tweak existing content. Key phrases: "make it more casual", "shorten the emails", "rewrite the subject line", "change the tone", "make it punchier", "adjust the CTA", "refine the content", "edit the variants"
- deploy: user wants to send content to a channel
- feedback: user is reporting engagement results or a webhook event has arrived
- refined_cycle: user wants to proceed to the next cycle, start a new iteration, restart the loop, or reference moving forward. This captures the current cycle's learnings and advances to the next cycle. Key phrases: "next cycle", "proceed to cycle N", "start over", "iterate", "new cycle", "run another cycle", "let's do cycle N"
- mcp_configure: user wants to configure, add, remove, list, or manage MCP servers/tools — this includes providing MCP URLs, asking to connect external services via MCP, or managing tool integrations
- answer: user is asking a question about the campaign, product, system status, strategy, or any topic that can be answered from existing context — NOT requesting new research or content generation
- update_context: user is providing clarifications, corrections, or additional information about their product, company, target market, goals, or preferences — NOT requesting an action
- clarify: message is genuinely ambiguous and you cannot determine ANY of the above intents — generate a specific clarification question

## Cycle Awareness
You are currently in Cycle {cycle_number}. The system maintains persistent memory of all past cycles.
{cycle_context}

When the user mentions cycles:
- "proceed to cycle 2", "next cycle", "start cycle 3", "iterate", "run another round" → refined_cycle
- "what happened in cycle 1?" → answer (use cycle history to respond)
- "what worked last cycle?" → answer (use cycle learnings)
- "try a different approach this time" → this could be refined_cycle if starting new, or generate if mid-cycle

## Rules
- Read intent from full conversation context, not just latest message
- "Now write three variants" after research → "generate"
- "Go back to research" → override any prior intent immediately with "research"
- "Send only to John" or "remove Alice from the list" or "add john@example.com" or "show me the prospects" or "upload a CSV" or "I only want to send to sarah@company.com" → "prospect_manage"
- "who are we sending to?" or "show selected prospects" → "prospect_manage"
- "find some prospects" or "can you find prospects?" or "discover prospects" or "search for prospects" or "find me some targets" → "prospect_manage"
- "what is [specific person]'s LinkedIn?" or "find [name]'s LinkedIn profile" or "what is his/her username?" or "look up [specific name]" or "can you find it through internet?" (when prior turn was about a specific person) or "search for [name] on LinkedIn" → "lookup"
- If prior_intent is "lookup" AND the user's message provides more context about the person (company, university, role, location) without requesting a completely different action → "lookup" again (retry with the new context)
- KEY DISTINCTION: lookup = find ONE specific named person. prospect_manage = discover MULTIPLE prospects for the campaign.
- "configure MCP server" or "add mcp" or "connect brightdata" or any MCP/tool server URL → "mcp_configure"
- "list mcp servers" or "show connected tools" or "remove mcp server" → "mcp_configure"
- "proceed to next cycle" or "let's do cycle 2" or "start over with learnings" or "iterate" or "next round" → "refined_cycle"
- If content variants already exist and the user asks to modify/edit/improve them (tone change, shorten, rewrite, adjust CTA, etc.) → "content_refine"
- "make it more casual" or "shorten the emails" or "rewrite the subject lines" or "change the tone to professional" or "make it punchier" → "content_refine" (ONLY when variants exist)
- If no content variants exist yet and user asks for content modifications → "generate" (treat as new generation request)
- If user asks a direct question (e.g. "what is our target market?", "how many variants did we create?", "what should I focus on?") → "answer"
- If user asks about replies, received emails, engagement status, or campaign metrics (e.g. "are there any replies?", "did anyone respond?", "what are the received emails?", "show me engagement results", "is there any reply from X?", "check for responses", "what is the current status?") → "answer"
- If user provides new info without requesting an action (e.g. "our company focuses on B2B SaaS", "actually our target market is enterprise HR teams", "our budget is $5000/month") → "update_context"
- If user answers a previous clarification question or provides info the system asked for → "update_context"
- If user says "Generate outreach content using my clarification answers" or similar → "generate" (content clarification answers have been submitted)
- If "Content clarification questions pending" count > 0 in context, the user's message almost certainly contains answers to those questions → "generate" (do NOT classify as update_context or clarify)
- Only use "clarify" as a last resort when the message is truly unintelligible or has multiple conflicting interpretations
- Never hallucinate a mode. If genuinely unclear → "clarify"
- Do not generate any content. Only classify and route.

## Output format (strict JSON, no prose, no markdown code blocks)
{{
  "current_intent": "<one of: research, segment, prospect_manage, lookup, generate, content_refine, deploy, feedback, refined_cycle, mcp_configure, answer, update_context, clarify>",
  "reasoning": "<one sentence explaining your classification>",
  "user_directive": "<a clear, actionable summary of WHAT the user wants the next agent to do — capture specific focus areas, constraints, preferences, and tone from the user's message. Examples: 'Research competitor pricing strategies for enterprise SaaS', 'Generate 3 email variants with a casual, friendly tone focused on cost savings', 'Deploy only the ROI-focused variant to top 3 prospects'. This MUST reflect the user's specific request, not a generic description of what the agent does.>",
  "clarification_question": "<only if current_intent=clarify, else null>",
  "clarification_options": ["<option1>", "<option2>", "..."],
  "next_node": "<research, segment, prospect_manage, lookup, generate, content_refine, deploy, feedback, refined_cycle, answer, update_context, clarify>"
}}"""

DEFAULT_CLARIFICATION = (
    "I didn't quite catch that — could you clarify what you'd like to do? "
    "(research / segment / manage prospects / look up someone / generate / refine content / deploy / feedback / configure MCP)"
)

DEFAULT_OPTIONS = ["Research competitors", "Manage prospects", "Look up a person", "Generate content", "Refine content", "Deploy campaign", "Report feedback", "Configure MCP server"]


def _get_llm():
    """Get the LLM client via the central factory."""
    return get_llm(temperature=0)


def format_messages(messages: list[Any]) -> str:
    """Format messages for the prompt context.

    Accepts both plain dicts (role/content keys) and LangChain BaseMessage objects.

    Args:
        messages: List of messages (dicts or BaseMessage objects).

    Returns:
        Formatted string of messages.
    """
    if not messages:
        return "(no messages yet)"

    lines = []
    for msg in messages:
        # Handle LangChain BaseMessage objects (HumanMessage, AIMessage, etc.)
        if hasattr(msg, "type") and hasattr(msg, "content"):
            role = msg.type  # "human", "ai", "system"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
        else:
            # Plain dict fallback
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
        # Truncate very long messages
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"[{role}]: {content}")

    return "\n".join(lines)


def _parse_llm_response(content: str) -> dict[str, Any]:
    """Parse JSON from LLM response, handling potential markdown code blocks.

    Args:
        content: Raw LLM response string.

    Returns:
        Parsed JSON as dict.

    Raises:
        json.JSONDecodeError: If parsing fails.
    """
    # Strip whitespace
    content = content.strip()

    # Handle markdown code blocks
    if content.startswith("```"):
        # Find the end of the opening fence
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1 :]

        # Remove closing fence
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

    return json.loads(content)


def _validate_and_normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the LLM result.

    Args:
        result: Parsed JSON result from LLM.

    Returns:
        Normalized result with valid intent and next_node.
    """
    intent = result.get("current_intent", "clarify")

    # Validate intent — also handles missing key (default is "clarify")
    if intent not in VALID_INTENTS:
        logger.warning("Invalid intent '%s' from LLM, defaulting to 'clarify'", intent)
        intent = "clarify"

    # Always write back to ensure the key exists in the result dict
    result["current_intent"] = intent

    # Determine next_node from intent — always enforce consistency
    expected_node = INTENT_TO_NODE.get(intent, "clarify")
    next_node = result.get("next_node")

    if next_node != expected_node:
        if next_node and next_node != expected_node:
            logger.debug(
                "Overriding LLM next_node '%s' with '%s' to match intent '%s'",
                next_node,
                expected_node,
                intent,
            )
        result["next_node"] = expected_node

    # Ensure clarification fields for clarify intent
    if intent == "clarify":
        if not result.get("clarification_question"):
            result["clarification_question"] = DEFAULT_CLARIFICATION
        if not result.get("clarification_options"):
            result["clarification_options"] = DEFAULT_OPTIONS

    return result


def _build_cycle_context_for_prompt(state: CampaignState) -> str:
    """Build a compact cycle history context string for the orchestrator prompt."""
    cycle_records = state.get("cycle_records", [])
    accumulated = state.get("accumulated_learnings")
    cycle_number = state.get("cycle_number", 1)

    if not cycle_records and not accumulated:
        if cycle_number <= 1:
            return "This is the first cycle. No prior cycle history."
        return f"Currently in cycle {cycle_number}. No detailed cycle records available."

    lines: list[str] = [f"Currently in Cycle {cycle_number}."]

    if cycle_records:
        lines.append(f"Completed cycles: {len(cycle_records)}")
        for rec in cycle_records[-3:]:  # last 3 cycles for context
            cn = rec.get("cycle_number", "?")
            sends = rec.get("total_sends", 0)
            replies = rec.get("total_replies", 0)
            amplify = rec.get("approaches_to_amplify", [])
            avoid = rec.get("approaches_to_avoid", [])
            lines.append(
                f"  Cycle {cn}: {sends} sends, {replies} replies"
                + (f", amplify: {', '.join(amplify[:2])}" if amplify else "")
                + (f", avoid: {', '.join(avoid[:2])}" if avoid else "")
            )

    if accumulated:
        # Include only the directives section to keep prompt compact
        directives_start = accumulated.find("=== DIRECTIVES FOR NEXT CYCLE ===")
        if directives_start >= 0:
            lines.append(accumulated[directives_start:directives_start + 500])
        else:
            lines.append(accumulated[:300])

    return "\n".join(lines)


async def orchestrator_node(state: CampaignState) -> dict[str, Any]:
    """Classify user intent and route to the appropriate agent.

    This is the main entry point for all user messages. It uses Gemini to
    classify intent and returns routing decisions.

    Args:
        state: Current campaign state.

    Returns:
        State update dict with intent classification and routing.
    """
    session_id = state.get("session_id", "unknown")
    logger.info("orchestrator_node called | session=%s", session_id)

    # Summarise long conversations before building context
    summary_patch = await memory_manager.maybe_summarize_conversation(state)
    if summary_patch:
        # Apply summary patch to reading state for this turn only
        state = {**state, **summary_patch}  # type: ignore[assignment]

    # Build scoped context bundle via memory manager
    bundle = await memory_manager.build_context_bundle(state, "orchestrator")
    context_messages = bundle.get("recent_messages", [])

    # Get the LLM client
    llm = _get_llm()

    if llm is None:
        # Mock mode — return default clarify response
        logger.info("USE_MOCK_LLM is true, returning default clarify response")
        return _make_clarify_response(state)

    # Build the prompt
    task = bundle.get("task_header", {})
    stage = bundle.get("current_stage_state", {})

    # Build cycle context for the system prompt
    cycle_number = task.get("cycle_number", 1)
    cycle_context = _build_cycle_context_for_prompt(state)

    # Format the system prompt with cycle awareness
    formatted_system_prompt = SYSTEM_PROMPT.format(
        cycle_number=cycle_number,
        cycle_context=cycle_context,
    )

    pending_qs = state.get("content_pending_questions", []) or []
    prior_intent = state.get("current_intent") or stage.get("previous_intent", "none")
    lookup_hint = (
        " ← IMPORTANT: prior turn was a lookup. If the user is now providing more context "
        "(company, university, role, location) about the same person, classify as 'lookup' again."
        if prior_intent == "lookup" else ""
    )
    prompt = f"""Campaign context:
- Product: {task.get("product_name", "Unknown")}
- Description: {state.get("product_description", "No description")}
- Target Market: {task.get("target_market", "Unknown")}
- Stage: {stage.get("active_stage_summary", "starting")}
- Cycle: {cycle_number}
- Prior intent: {prior_intent}{lookup_hint}
- Content variants exist: {"yes (" + str(len(state.get("content_variants", []))) + " variants)" if state.get("content_variants") else "no"}
- Content clarification questions pending: {len(pending_qs)} {"(user's message likely contains answers to these questions → route to 'generate')" if pending_qs else ""}

{cycle_context}

Conversation (last {len(context_messages)} turns):
{format_messages(context_messages)}

Classify the latest user intent."""

    # Try to get classification from Gemini (with retry)
    max_retries = 2
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = await llm.ainvoke(
                [
                    {"role": "system", "content": formatted_system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )

            # Parse the response
            result = _parse_llm_response(response.content)
            result = _validate_and_normalize_result(result)

            logger.info(
                "Orchestrator classified intent | session=%s intent=%s next_node=%s",
                session_id,
                result["current_intent"],
                result["next_node"],
            )

            patch: dict[str, Any] = {
                "current_intent": result["current_intent"],
                "previous_intent": state.get("current_intent"),
                "next_node": result["next_node"],
                "user_directive": result.get("user_directive"),
                "clarification_question": result.get("clarification_question"),
                "clarification_options": result.get("clarification_options", []),
                "intent_history": state.get("intent_history", []) + [result["current_intent"]],
            }
            # Propagate any summary state updates produced earlier in this turn
            if summary_patch:
                patch.update(summary_patch)
            return patch

        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                "Failed to parse Gemini response (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "Gemini API error (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )

    # All retries failed — fallback to clarify
    logger.error(
        "Orchestrator failed after %d attempts, defaulting to clarify | session=%s error=%s",
        max_retries,
        session_id,
        last_error,
    )

    error_msg = f"Intent classification failed: {last_error}"
    return {
        "current_intent": "clarify",
        "previous_intent": state.get("current_intent"),
        "next_node": "clarify",
        "user_directive": None,
        "clarification_question": DEFAULT_CLARIFICATION,
        "clarification_options": DEFAULT_OPTIONS,
        "intent_history": state.get("intent_history", []) + ["clarify"],
        "error_messages": state.get("error_messages", []) + [error_msg],
    }


def _make_clarify_response(state: CampaignState) -> dict[str, Any]:
    """Create a default clarify response (used in mock mode or errors)."""
    return {
        "current_intent": "clarify",
        "previous_intent": state.get("current_intent"),
        "next_node": "clarify",
        "user_directive": None,
        "clarification_question": DEFAULT_CLARIFICATION,
        "clarification_options": DEFAULT_OPTIONS,
        "intent_history": state.get("intent_history", []) + ["clarify"],
    }


async def clarify_node(state: CampaignState) -> dict[str, Any]:
    """Emit a ClarificationPrompt UI frame and await user response.

    This node is called when the orchestrator classifies the intent as 'clarify'.
    It creates a UI frame that the frontend will render as an interactive
    clarification prompt.

    Args:
        state: Current campaign state.

    Returns:
        State update with clarification UI frame data.
    """
    session_id = state.get("session_id", "unknown")
    logger.info("clarify_node called | session=%s", session_id)

    question = state.get("clarification_question") or DEFAULT_CLARIFICATION
    options = state.get("clarification_options") or DEFAULT_OPTIONS

    # Create UI frame for the clarification prompt
    instance_id = f"clarify_{uuid4().hex[:8]}"

    ui_frame = UIFrame(
        type="ui_component",
        component="ClarificationPrompt",
        instance_id=instance_id,
        props={
            "question": question,
            "options": options,
        },
        actions=[
            UIAction(
                id=f"opt_{i}",
                label=opt,
                action_type="clarification_response",
                payload={"response": opt},
            )
            for i, opt in enumerate(options)
        ],
    )

    # The frame will be picked up by the API layer and streamed to frontend
    # For now, we store it in a way that can be retrieved
    return {
        "active_stage_summary": "awaiting clarification",
        "clarification_question": question,
        "clarification_options": options,
        "session_complete": True,
        "pending_ui_frames": [ui_frame.model_dump()],
    }


# ---------------------------------------------------------------------------
# Answer node — direct Q&A from campaign context
# ---------------------------------------------------------------------------

ANSWER_SYSTEM_PROMPT = """You are a helpful assistant for the Signal to Action growth intelligence system.

Answer the user's question directly and concisely using ONLY the campaign context provided below.
If the information is not available in the context, be honest AND proactively suggest how to get it:
- If the user is asking about a specific person's LinkedIn profile, email, or contact details that are not in context, say: "That information isn't in the current context. I can search the internet to find it — just say 'find it online' or ask me to look up [name]."
- If the user is asking for information that requires a web search, suggest they ask for a lookup.
Do NOT perform research, generate content, or take any actions — just answer the question.
Keep answers focused and brief (1-3 paragraphs max).

IMPORTANT: When the user asks about replies, received emails, engagement, or feedback:
- Always check the "Feedback Events from DB" and "Email Threads" sections for the latest data.
- These are real-time records from the database and take precedence over state-level summaries.
- Report specific details: who replied, what they said, when, email subject, etc."""


async def _build_answer_context(state: CampaignState) -> str:
    """Build rich context for the answer node by combining state AND live DB data.

    Webhooks write feedback events and email threads directly to MongoDB,
    bypassing LangGraph state. This function ensures the answer node sees
    ALL data — both from state and from the database.
    """
    from app.db.crud import (
        get_deployment_records_for_session,
        get_email_threads_for_session,
        get_feedback_events_for_session,
        get_reply_events_for_session,
    )

    session_id = state.get("session_id", "unknown")

    context_parts = [
        f"Product: {state.get('product_name', 'Unknown')}",
        f"Description: {state.get('product_description', 'No description')}",
        f"Target Market: {state.get('target_market', 'Unknown')}",
        f"Current Stage: {state.get('active_stage_summary', 'starting')}",
        f"Cycle: {state.get('cycle_number', 1)}",
    ]

    # Include research findings if available
    findings = state.get("research_findings", [])
    if findings:
        context_parts.append(f"\nResearch Findings ({len(findings)} total):")
        for f in findings[:5]:
            title = f.get("title", "Untitled") if isinstance(f, dict) else str(f)
            context_parts.append(f"  - {title}")

    briefing = state.get("briefing_summary")
    if briefing:
        context_parts.append(f"\nBriefing Summary: {briefing}")

    # Include content variants if available (fall back to persisted variants when
    # the active graph state does not currently hold them).
    variants = state.get("content_variants", [])
    if not variants:
        try:
            variants = await get_latest_variants_for_session(session_id)
        except Exception:
            logger.warning("_build_answer_context: could not load persisted variants", exc_info=True)

    if variants:
        context_parts.append(f"\nContent Variants ({len(variants)} total):")
        for v in variants[:5]:
            if not isinstance(v, dict):
                context_parts.append(f"  - {v}")
                continue
            label = v.get("angle_label") or v.get("id") or "unknown"
            channel = v.get("intended_channel", "unknown")
            context_parts.append(
                f"  - {label} | id: {v.get('id', 'unknown')} | channel: {channel}"
            )
            if v.get("subject_line"):
                context_parts.append(f"    Subject: {v['subject_line']}")
            if v.get("body"):
                context_parts.append(f"    Body: {v['body'][:1200]}")
            if v.get("cta"):
                context_parts.append(f"    CTA: {v['cta']}")
            if v.get("hypothesis"):
                context_parts.append(f"    Hypothesis: {v['hypothesis']}")

    # --- Live DB data (resilient to DB unavailability) ---
    db_records: list[dict] = []
    db_events: list[dict] = []
    db_threads: list[dict] = []
    db_replies: list[dict] = []

    try:
        db_records = await get_deployment_records_for_session(session_id)
        db_events = await get_feedback_events_for_session(session_id)
        db_threads = await get_email_threads_for_session(session_id)
        db_replies = await get_reply_events_for_session(session_id)
    except Exception:
        logger.warning("_build_answer_context: DB unavailable, using state-only context")

    # --- Deployment records ---
    state_records = state.get("deployment_records", [])
    records = db_records if db_records else state_records

    if records:
        context_parts.append(f"\nDeployment Records ({len(records)} sends):")
        for rec in records[:20]:
            prospect_email = rec.get("prospect_email", rec.get("recipient_email", "unknown"))
            prospect_name = rec.get("prospect_name", "")
            status = rec.get("status", "unknown")
            channel = rec.get("channel", "email")
            variant_id = rec.get("variant_id", "")
            sent_at = rec.get("sent_at", "")
            subject = rec.get("subject", "")
            detail = f"  - To: {prospect_name} <{prospect_email}> | status: {status} | channel: {channel}"
            if subject:
                detail += f" | subject: {subject}"
            if variant_id:
                detail += f" | variant: {variant_id}"
            if sent_at:
                detail += f" | sent: {sent_at}"
            context_parts.append(detail)

    # --- Feedback events ---
    state_events = state.get("engagement_results", [])
    all_events = db_events if db_events else state_events

    if all_events:
        context_parts.append(f"\nFeedback Events from DB ({len(all_events)} total):")
        # Group by event type for clarity
        by_type: dict[str, list] = {}
        for evt in all_events:
            et = evt.get("event_type", "unknown")
            by_type.setdefault(et, []).append(evt)
        for et, evts in by_type.items():
            context_parts.append(f"  {et}: {len(evts)} events")
            for evt in evts[:10]:
                prospect_id = evt.get("prospect_id", "")
                received = evt.get("received_at", "")
                detail = f"    - prospect={prospect_id} received={received}"
                if et == "reply":
                    body = evt.get("reply_body") or evt.get("qualitative_signal") or ""
                    subject = evt.get("reply_subject", "")
                    if subject:
                        detail += f" subject=\"{subject}\""
                    if body:
                        detail += f" body=\"{body[:200]}\""
                context_parts.append(detail)

    # --- Email threads (includes full reply content) ---
    if db_threads:
        context_parts.append(f"\nEmail Threads ({len(db_threads)} threads):")
        for thread in db_threads[:10]:
            prospect_email = thread.get("prospect_email", "unknown")
            status = thread.get("status", "unknown")
            reply_count = thread.get("reply_count", 0)
            subject = thread.get("subject", "")
            context_parts.append(
                f"  Thread with {prospect_email} | status: {status} | "
                f"replies: {reply_count} | subject: {subject}"
            )
            for msg in thread.get("messages", [])[:5]:
                direction = msg.get("direction", "unknown")
                sender = msg.get("sender_email", "")
                body = msg.get("body_text", "")
                ts = msg.get("timestamp", "")
                msg_subject = msg.get("subject", "")
                context_parts.append(
                    f"    [{direction}] from={sender} at={ts}"
                    + (f" subject=\"{msg_subject}\"" if msg_subject else "")
                    + (f"\n      \"{body[:300]}\"" if body else "")
                )

    # --- Reply events specifically ---
    if db_replies and not db_threads:
        # Only add this section if we didn't already get threads above
        context_parts.append(f"\nReply Events ({len(db_replies)} replies):")
        for reply in db_replies[:10]:
            from_info = reply.get("prospect_id", "unknown")
            body = reply.get("reply_body") or reply.get("qualitative_signal") or ""
            subject = reply.get("reply_subject", "")
            received = reply.get("received_at", "")
            context_parts.append(
                f"  - From prospect {from_info} at {received}"
                + (f" | subject: {subject}" if subject else "")
                + (f"\n    \"{body[:300]}\"" if body else "")
            )

    # Include cycle history if available
    cycle_records = state.get("cycle_records", [])
    if cycle_records:
        context_parts.append(f"\nCycle History ({len(cycle_records)} completed cycles):")
        for rec in cycle_records:
            cn = rec.get("cycle_number", "?")
            sends = rec.get("total_sends", 0)
            replies = rec.get("total_replies", 0)
            amplify = rec.get("approaches_to_amplify", [])
            avoid = rec.get("approaches_to_avoid", [])
            context_parts.append(
                f"  Cycle {cn}: {sends} sends, {replies} replies"
                + (f" | worked: {', '.join(amplify[:2])}" if amplify else "")
                + (f" | failed: {', '.join(avoid[:2])}" if avoid else "")
            )

    # Include accumulated learnings
    accumulated = state.get("accumulated_learnings")
    if accumulated:
        directives_start = accumulated.find("=== DIRECTIVES FOR NEXT CYCLE ===")
        if directives_start >= 0:
            context_parts.append(f"\nAccumulated Learnings:\n{accumulated[directives_start:directives_start + 500]}")
        else:
            context_parts.append(f"\nAccumulated Learnings: {accumulated[:300]}")

    return "\n".join(context_parts)


def _extract_last_user_message_content(messages: list[Any]) -> str:
    """Return the latest user-authored message content."""
    for msg in reversed(messages or []):
        if hasattr(msg, "type") and hasattr(msg, "content"):
            if getattr(msg, "type", "") == "human":
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                return content.strip()
            continue

        role = msg.get("role", "")
        if role == "user":
            return str(msg.get("content", "")).strip()

    return ""


def _normalize_variant_text(value: str) -> str:
    """Normalize text for loose matching against variant labels or IDs."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


async def _get_answer_variants(state: CampaignState) -> list[dict[str, Any]]:
    """Load the active content variants from state or persistent storage."""
    variants = state.get("content_variants", [])
    if variants:
        return variants

    try:
        return await get_latest_variants_for_session(state.get("session_id", ""))
    except Exception:
        logger.warning("_get_answer_variants: could not load persisted variants", exc_info=True)
        return []


def _format_variant_summary(variants: list[dict[str, Any]]) -> str:
    """Format a compact list of available content variants."""
    lines = [f"The campaign currently has {len(variants)} saved content variant(s):", ""]
    for variant in variants:
        label = variant.get("angle_label") or variant.get("id") or "unnamed"
        channel = variant.get("intended_channel", "unknown")
        subject = variant.get("subject_line")
        line = f"- {label} ({channel})"
        if subject:
            line += f" | subject: {subject}"
        lines.append(line)
    return "\n".join(lines)


def _format_variant_detail(variant: dict[str, Any]) -> str:
    """Format a full variant for direct display in chat."""
    label = variant.get("angle_label") or variant.get("id") or "saved"
    channel = variant.get("intended_channel", "unknown")
    parts = [f"Here is the {label} variant:", ""]
    parts.append(f"Channel: {channel}")
    if variant.get("subject_line"):
        parts.append(f"Subject: {variant['subject_line']}")
    if variant.get("hypothesis"):
        parts.append(f"Hypothesis: {variant['hypothesis']}")
    parts.append("")
    parts.append("Body:")
    parts.append(variant.get("body", "(no body saved)"))
    if variant.get("cta"):
        parts.append("")
        parts.append(f"CTA: {variant['cta']}")
    if variant.get("success_metric"):
        parts.append(f"Success metric: {variant['success_metric']}")
    return "\n".join(parts)


def _build_answer_variant_grid_frame(
    variants: list[dict[str, Any]],
    instance_id: str,
) -> dict[str, Any]:
    """Build a VariantGrid artifact for saved-content answers."""
    return UIFrame(
        type="ui_component",
        component="VariantGrid",
        instance_id=instance_id,
        props={
            "variants": variants,
            "refinement_enabled": True,
        },
        actions=[
            UIAction(
                id=f"select-{variant.get('id', 'unknown')}",
                label=f"Select: {variant.get('angle_label') or variant.get('intended_channel') or 'variant'}",
                action_type="select_variant",
                payload={"variant_id": variant.get("id")},
            )
            for variant in variants
            if variant.get("id")
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


def _match_variants_from_question(
    question: str,
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find variants referenced in a user question by label, ID, or subject."""
    normalized_question = _normalize_variant_text(question)
    matches: list[dict[str, Any]] = []

    for variant in variants:
        aliases = [
            str(variant.get("id", "")),
            str(variant.get("angle_label", "")),
            str(variant.get("subject_line", "")),
        ]
        normalized_aliases = {
            _normalize_variant_text(alias) for alias in aliases if alias.strip()
        }
        if any(alias and alias in normalized_question for alias in normalized_aliases):
            matches.append(variant)

    return matches


async def _try_answer_content_variant_question(state: CampaignState) -> dict[str, Any] | None:
    """Answer direct content-variant questions without relying on the LLM."""
    question = _extract_last_user_message_content(state.get("messages", []))
    if not question:
        return None

    lowered = question.lower()
    if not any(token in lowered for token in ("content", "variant", "angle", "subject")):
        return None

    variants = await _get_answer_variants(state)
    if not variants:
        return None

    matches = _match_variants_from_question(question, variants)
    wants_listing = any(
        token in lowered
        for token in (
            "what are",
            "what is",
            "which",
            "list",
            "available",
            "currently have",
            "how many",
        )
    )
    wants_detail = any(
        token in lowered
        for token in ("show", "display", "read", "open", "detail", "full", "content")
    )

    if len(matches) == 1 and wants_detail:
        variant = matches[0]
        label = variant.get("angle_label") or variant.get("id") or "saved"
        return {
            "text": f"Here is the {label} variant.",
            "variants": matches,
        }

    if len(matches) > 1:
        return {
            "text": f"I found {len(matches)} matching saved content variant(s).",
            "variants": matches,
        }

    if wants_listing:
        return {
            "text": _format_variant_summary(variants),
            "variants": variants,
        }

    return None


async def answer_node(state: CampaignState) -> dict[str, Any]:
    """Answer a user question directly from campaign context and live DB data.

    Queries MongoDB for feedback events, email threads, and deployment records
    so that webhook-delivered data (replies, opens, clicks) is always visible.

    Args:
        state: Current campaign state.

    Returns:
        State update with the answer as an AI message and UI frame.
    """
    session_id = state.get("session_id", "unknown")
    logger.info("answer_node called | session=%s", session_id)

    direct_variant_answer = await _try_answer_content_variant_question(state)
    if direct_variant_answer is not None:
        intro_frame = UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"answer_{uuid4().hex[:8]}",
            props={"content": direct_variant_answer["text"], "role": "assistant"},
            actions=[],
        ).model_dump()
        variant_grid_frame = _build_answer_variant_grid_frame(
            direct_variant_answer["variants"],
            f"answer-variant-grid-{session_id[:8]}",
        )
        return {
            "active_stage_summary": "answered user question",
            "session_complete": True,
            "pending_ui_frames": [intro_frame, variant_grid_frame],
        }
    else:
        bundle = await memory_manager.build_context_bundle(state, "orchestrator")
        context_messages = bundle.get("recent_messages", [])

        # Build rich context including live DB data
        context_str = await _build_answer_context(state)

        llm = _get_llm()

        if llm is None:
            # Mock mode
            answer_text = "I don't have enough context to answer that question in mock mode."
        else:
            try:
                prompt = f"""Campaign context:
{context_str}

Conversation history:
{format_messages(context_messages)}

Answer the user's latest question based on the above context."""

                response = await llm.ainvoke(
                    [
                        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ]
                )
                answer_text = response.content
            except Exception as e:
                logger.error("answer_node LLM error | session=%s error=%s", session_id, e)
                answer_text = "I'm sorry, I encountered an error trying to answer your question. Could you try rephrasing it?"

    instance_id = f"answer_{uuid4().hex[:8]}"
    ui_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=instance_id,
        props={"content": answer_text, "role": "assistant"},
        actions=[],
    )

    return {
        "active_stage_summary": "answered user question",
        "session_complete": True,
        "pending_ui_frames": [ui_frame.model_dump()],
    }


# ---------------------------------------------------------------------------
# Update-context node — absorb user clarifications into campaign state
# ---------------------------------------------------------------------------

UPDATE_CONTEXT_SYSTEM_PROMPT = """You are a context extraction assistant for the Signal to Action growth intelligence system.

The user has provided additional information or clarifications about their product, company, target market, or campaign goals.

Your job:
1. Extract the key facts from the user's message
2. Determine which campaign fields should be updated
3. Identify any follow-up questions needed to fill remaining gaps
4. Provide a brief confirmation of what you understood

## Output format (strict JSON, no prose, no markdown code blocks)
{
  "updates": {
    "product_name": "<updated value or null if not mentioned>",
    "product_description": "<updated/enriched description or null>",
    "target_market": "<updated value or null>"
  },
  "confirmation": "<brief 1-2 sentence summary of what you understood>",
  "follow_up_questions": ["<question1>", "<question2>"],
  "has_remaining_gaps": true/false
}"""


async def update_context_node(state: CampaignState) -> dict[str, Any]:
    """Absorb user clarifications and update campaign context.

    When users provide additional info about their company, product, or goals,
    this node extracts the updates, applies them to state, and asks follow-up
    questions if gaps remain.

    Args:
        state: Current campaign state.

    Returns:
        State update with extracted context and optional follow-up questions.
    """
    session_id = state.get("session_id", "unknown")
    logger.info("update_context_node called | session=%s", session_id)

    bundle = await memory_manager.build_context_bundle(state, "orchestrator")
    context_messages = bundle.get("recent_messages", [])

    llm = _get_llm()

    patch: dict[str, Any] = {"session_complete": True}

    if llm is None:
        # Mock mode — acknowledge the update generically
        confirmation = "Got it — I've noted your input. (Mock mode: no extraction performed.)"
        instance_id = f"ctx_{uuid4().hex[:8]}"
        ui_frame = UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=instance_id,
            props={"content": confirmation, "role": "assistant"},
            actions=[],
        )
        patch["pending_ui_frames"] = [ui_frame.model_dump()]
        patch["active_stage_summary"] = "context updated (mock)"
        return patch

    prompt = f"""Current campaign context:
- Product: {state.get("product_name", "Unknown")}
- Description: {state.get("product_description", "No description")}
- Target Market: {state.get("target_market", "Unknown")}
- Stage: {state.get("active_stage_summary", "starting")}

Conversation:
{format_messages(context_messages)}

Extract context updates from the user's latest message."""

    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": UPDATE_CONTEXT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        result = _parse_llm_response(response.content)
    except Exception as e:
        logger.error("update_context_node LLM error | session=%s error=%s", session_id, e)
        instance_id = f"ctx_{uuid4().hex[:8]}"
        ui_frame = UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=instance_id,
            props={
                "content": "I've noted your input, though I had trouble parsing the details. Could you rephrase?",
                "role": "assistant",
            },
            actions=[],
        )
        patch["pending_ui_frames"] = [ui_frame.model_dump()]
        patch["active_stage_summary"] = "context update failed"
        return patch

    # Apply field updates if present
    updates = result.get("updates", {})
    if updates.get("product_name"):
        patch["product_name"] = updates["product_name"]
    if updates.get("product_description"):
        # Enrich rather than replace — append new info to existing description
        existing = state.get("product_description", "")
        new_desc = updates["product_description"]
        if existing and existing != "No description":
            patch["product_description"] = f"{existing} {new_desc}"
        else:
            patch["product_description"] = new_desc
    if updates.get("target_market"):
        patch["target_market"] = updates["target_market"]

    confirmation = result.get("confirmation", "Got it — I've noted your input.")
    follow_ups = result.get("follow_up_questions", [])
    has_gaps = result.get("has_remaining_gaps", False)

    ui_frames = []

    # Confirmation message
    instance_id = f"ctx_{uuid4().hex[:8]}"
    ui_frames.append(
        UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=instance_id,
            props={"content": confirmation, "role": "assistant"},
            actions=[],
        ).model_dump()
    )

    # If there are follow-up questions, present them as plain text so the user
    # can read them and type answers in the chat input (not as clickable buttons
    # that would echo the question text back as the "answer").
    if follow_ups and has_gaps:
        follow_up_text = "I have a few follow-up questions:\n" + "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(follow_ups)
        )
        fup_instance_id = f"ctx_followup_{uuid4().hex[:8]}"
        ui_frames.append(
            UIFrame(
                type="text",
                component="MessageRenderer",
                instance_id=fup_instance_id,
                props={"content": follow_up_text, "role": "assistant"},
                actions=[],
            ).model_dump()
        )

    patch["pending_ui_frames"] = ui_frames
    patch["active_stage_summary"] = "context updated"

    logger.info(
        "update_context_node completed | session=%s updates=%s follow_ups=%d",
        session_id,
        list(updates.keys()),
        len(follow_ups),
    )

    return patch


# ---------------------------------------------------------------------------
# Lookup node — targeted search for a specific named individual
# ---------------------------------------------------------------------------

LOOKUP_SYSTEM_PROMPT = """You are a research assistant that finds LinkedIn profiles for a specific individual.

Your job: examine the search results and determine if ANY result is the specific person being looked for.

CRITICAL MATCHING RULES:
- The person's FULL NAME must appear in the URL, page title, or snippet — partial name matches (e.g. only first name or only last name) do NOT count
- If the search results contain the exact full name (both first and last name together), that IS a match
- If results only show people who share one part of the name (e.g. only "Devinda" without "Dilshan"), that is NOT a match

Return STRICT JSON only — no prose, no markdown:
{{
  "found": true/false,
  "linkedin_url": "https://linkedin.com/in/username or null",
  "linkedin_username": "username or null",
  "name": "full name as it appears on the profile or null",
  "title": "job title or null",
  "company": "company or university or null",
  "confidence": "high/medium/low",
  "message": "A 2-3 sentence human-readable summary. If found: state the URL and key details. If not found: explain what was found instead and suggest the user try LinkedIn's own search at linkedin.com/search/results/people/?keywords=NAME"
}}

confidence levels:
- high: exact full name match in URL (e.g. linkedin.com/in/devinda-dilshan) AND title/company match context
- medium: exact full name match in title or snippet, profile URL found
- low: partial match or uncertain"""

LOOKUP_EXTRACT_PROMPT = """You extract the target person's details from a conversation thread.
Look at ALL messages (not just the latest) to piece together the full picture of who is being searched.

Return JSON only:
{{"name": "Full Name", "company": "company or university name", "role": "job title or student", "context": "any other detail"}}

Rules:
- name: the person being looked up (required — infer from full thread if latest msg only says "find it" or provides extra context)
- company: their employer OR university — whichever is mentioned
- role: job title, "student", or null
- context: any other identifying detail
- All fields except name may be null if not mentioned anywhere in the thread"""


async def lookup_node(state: CampaignState) -> dict[str, Any]:
    """Look up a specific named individual's LinkedIn profile and contact details.

    Does a targeted web search for ONE person rather than bulk prospect discovery.
    Results are shown inline in chat with an option to add to the prospect list.
    """
    import re as _re

    from app.agents.prospect_manager import _create_manual_prospect
    from app.tools.search import search_web

    session_id = state.get("session_id", "unknown")
    logger.info("lookup_node called | session=%s", session_id)

    # Extract the latest user message and build prior context
    messages = state.get("messages", [])
    user_query = ""
    prior_context = ""
    count = 0
    for msg in reversed(messages):
        if hasattr(msg, "type") and hasattr(msg, "content"):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if not user_query and getattr(msg, "type", "") == "human":
                user_query = content
            if count < 8:
                prior_context = f"[{msg.type}]: {content[:300]}\n" + prior_context
        elif isinstance(msg, dict):
            content = msg.get("content", "")
            if not user_query and msg.get("role") == "user":
                user_query = content
            if count < 8:
                prior_context = f"[{msg.get('role', 'unknown')}]: {content[:300]}\n" + prior_context
        count += 1

    llm = _get_llm()
    ui_frames: list[dict[str, Any]] = []

    # Step 1: Extract person name + context from full conversation thread
    person_name = ""
    company_hint = ""
    role_hint = ""
    if llm:
        try:
            extract_response = await llm.ainvoke([
                {"role": "system", "content": LOOKUP_EXTRACT_PROMPT},
                {"role": "user", "content": f"Full conversation:\n{prior_context}\n\nLatest message: {user_query}"},
            ])
            extracted = _parse_llm_response(extract_response.content)
            person_name = extracted.get("name") or ""
            company_hint = extracted.get("company") or ""
            role_hint = extracted.get("role") or ""
        except Exception as e:
            logger.warning("lookup_node: name extraction failed: %s", e)

    if not person_name:
        directive = state.get("user_directive") or ""
        person_name = directive or user_query

    # Step 2: Build context string for search queries
    context_parts = [p for p in [company_hint, role_hint] if p]
    context_str = " ".join(context_parts)

    from app.tools.unipile_client import (
        get_unipile_config_errors,
        search_linkedin_people,
    )
    from app.core.config import settings as _settings

    # Step 3a: PRIMARY — Unipile authenticated LinkedIn search (best quality)
    unipile_profiles: list[dict] = []
    unipile_available = not get_unipile_config_errors(require_account=True)
    if unipile_available:
        search_keyword = f"{person_name} {context_str}".strip() if context_str else person_name
        try:
            unipile_profiles = await search_linkedin_people(
                keyword=search_keyword,
                account_id=_settings.UNIPILE_LINKEDIN_ACCOUNT_ID,
                limit=7,
            )
            logger.info("lookup_node: Unipile search returned %d profiles for %r", len(unipile_profiles), search_keyword)
        except Exception as e:
            logger.warning("lookup_node: Unipile search failed: %s", e)

    # Step 3b: FALLBACK — broad web search for "{name} linkedin" so Google/Bing surfaces
    # the actual profile URL. DO NOT restrict to linkedin.com domain — that returns
    # company/university pages listing many people, not individual profile pages.
    all_results: list[dict] = []
    if not unipile_profiles:
        broad_query = f'"{person_name}" linkedin'
        if context_str:
            broad_query += f" {context_str}"
        try:
            results = await search_web(broad_query, max_results=8, recency_days=None)
            all_results.extend(results)
            logger.info("lookup_node: broad web search returned %d for %r", len(results), broad_query)
        except Exception as e:
            logger.warning("lookup_node: broad web search failed: %s", e)

        if len(all_results) < 3:
            try:
                results = await search_web(
                    f'"{person_name}" linkedin profile',
                    max_results=5,
                    recency_days=None,
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning("lookup_node: linkedin profile search failed: %s", e)

    # Step 4: Match / synthesise result — cascade through paths, stop at first confirmed match
    linkedin_url = ""
    username = ""
    found = False
    confidence = "low"
    answer_text = ""
    extracted_title = ""
    extracted_company = company_hint

    name_parts = [p.lower() for p in (person_name or "").split() if len(p) > 1]

    # --- Path A: Unipile returned profiles → require ALL name parts in profile name ---
    if unipile_profiles and name_parts:
        best_unipile: dict | None = None
        for profile in unipile_profiles:
            profile_name = profile.get("name", "").lower()
            if all(part in profile_name for part in name_parts):
                best_unipile = profile
                break

        if best_unipile:
            linkedin_url = best_unipile.get("linkedin_url", "")
            username = best_unipile.get("public_identifier", "")
            extracted_title = best_unipile.get("occupation", "")
            extracted_company = best_unipile.get("location", "") or company_hint
            found = bool(linkedin_url)
            confidence = "high" if found else "low"
            if found:
                answer_text = (
                    f"Found **{best_unipile.get('name', person_name)}** on LinkedIn.\n\n"
                    f"- **LinkedIn URL:** {linkedin_url}\n"
                    f"- **Username:** `{username}`\n"
                    + (f"- **Title:** {extracted_title}\n" if extracted_title else "")
                    + (f"- **Location:** {best_unipile.get('location', '')}\n" if best_unipile.get("location") else "")
                )

    # --- Path B1: Extract linkedin.com/in/ URLs directly from web search results ---
    # Google/Bing often includes the actual profile URL in result snippets / URLs
    if not found and all_results and name_parts:
        linkedin_url_re = _re.compile(r'linkedin\.com/in/([\w][\w\-]*[\w])', _re.IGNORECASE)
        seen_slugs: set[str] = set()
        for r in all_results:
            for field in ("url", "title", "content"):
                m = linkedin_url_re.search(r.get(field, ""))
                if not m:
                    continue
                raw_slug = m.group(1)
                slug_lower = raw_slug.lower().strip("-")
                if slug_lower in seen_slugs or not slug_lower:
                    continue
                seen_slugs.add(slug_lower)
                # Accept slug only if at least one name part appears inside it
                if any(part in slug_lower for part in name_parts):
                    linkedin_url = f"https://www.linkedin.com/in/{raw_slug}"
                    username = raw_slug
                    found = True
                    confidence = "high"
                    answer_text = (
                        f"Found **{person_name}** on LinkedIn.\n\n"
                        f"- **LinkedIn URL:** {linkedin_url}\n"
                        f"- **Username:** `{username}`\n"
                        + (f"- **Context:** {context_str}\n" if context_str else "")
                    )
                    logger.info("lookup_node: direct URL extraction found %s", linkedin_url)
                    break
            if found:
                break

    # --- Path B2: LLM synthesis over web results as last-resort ---
    if not found and all_results and llm:
        results_text = "\n\n".join(
            f"URL: {r.get('url', '')}\nTitle: {r.get('title', '')}\nSnippet: {r.get('content', '')[:500]}"
            for r in all_results[:10]
        )
        try:
            lookup_response = await llm.ainvoke([
                {"role": "system", "content": LOOKUP_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"I'm looking for: {person_name or user_query}"
                        + (f" (works/studies at: {context_str})" if context_str else "")
                        + f"\n\nSearch results:\n{results_text}"
                    ),
                },
            ])
            parsed = _parse_llm_response(lookup_response.content)
            found = bool(parsed.get("found"))
            linkedin_url = parsed.get("linkedin_url") or ""
            confidence = parsed.get("confidence", "low")
            answer_text = parsed.get("message", "")
            extracted_title = parsed.get("title") or ""
            extracted_company = parsed.get("company") or company_hint

            # Guard: reject URL if no name part appears in the slug
            if found and linkedin_url and name_parts:
                slug = linkedin_url.lower().split("/in/")[-1].split("?")[0]
                if not any(part in slug for part in name_parts):
                    found = False
                    confidence = "low"
                    linkedin_url = ""
        except Exception as e:
            logger.error("lookup_node: LLM synthesis failed: %s", e)
            answer_text = f"I searched for **{person_name or user_query}** but encountered an error. Please try again."

    # --- Path C: Nothing found — provide direct search URL ---
    if not found and not answer_text:
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={person_name.replace(' ', '%20')}"
        answer_text = (
            f"I couldn't find an exact LinkedIn profile for **{person_name or user_query}**.\n\n"
            f"Try searching LinkedIn directly: [{search_url}]({search_url})"
        )

    # Step 5: Build text response frame
    instance_id = f"lookup_{uuid4().hex[:8]}"
    ui_frames.append(UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=instance_id,
        props={"content": answer_text, "role": "assistant"},
        actions=[],
    ).model_dump())

    # Step 6: Only show ProspectManager when LLM confirmed a match with medium/high confidence
    if found and linkedin_url and confidence in ("high", "medium") and person_name:
        found_prospect = _create_manual_prospect({
            "name": person_name,
            "linkedin_url": linkedin_url,
            "title": extracted_title,
            "company": extracted_company,
        })
        ui_frames.append(UIFrame(
            type="ui_component",
            component="ProspectManager",
            instance_id=f"lookup-prospect-{session_id[:8]}-{uuid4().hex[:4]}",
            props={
                "prospects": [found_prospect],
                "selected_ids": [found_prospect["id"]],
                "message": f"Found {person_name}'s LinkedIn profile. Add to prospect list?",
                "show_csv_upload": False,
                "total_count": 1,
                "selected_count": 1,
            },
            actions=[
                UIAction(
                    id="confirm-prospects",
                    label="Add to prospect list",
                    action_type="confirm_prospects",
                    payload={},
                ),
            ],
        ).model_dump())

    # Persist the found prospect into state so linkedin_url is available at deploy time.
    # prospect_cards uses a replace reducer — we must carry forward existing cards.
    state_update: dict[str, Any] = {
        "active_stage_summary": f"looked up {person_name or 'person'}",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }

    if found and linkedin_url and person_name:
        existing_cards: list[dict] = list(state.get("prospect_cards") or [])
        existing_ids = {c.get("id") for c in existing_cards}
        if found_prospect["id"] not in existing_ids:
            existing_cards = [*existing_cards, found_prospect]

        existing_selected: list[str] = list(state.get("selected_prospect_ids") or [])
        if found_prospect["id"] not in existing_selected:
            existing_selected = [*existing_selected, found_prospect["id"]]

        state_update["prospect_cards"] = existing_cards
        state_update["selected_prospect_ids"] = existing_selected

    logger.info(
        "lookup_node completed | session=%s person=%r found=%s confidence=%s linkedin=%r",
        session_id, person_name, found, confidence, linkedin_url,
    )

    return state_update
