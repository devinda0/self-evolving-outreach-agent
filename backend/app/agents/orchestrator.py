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
from typing import Any
from uuid import uuid4

from app.core.llm import get_llm
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
}

SYSTEM_PROMPT = """You are the Orchestrator of Signal to Action, a multi-agent growth intelligence system.

Your sole job: classify the user's latest message into exactly one intent mode and return a routing decision.

## Intent Modes
- research: user wants market intelligence, competitor analysis, audience signals, channel trends
- segment: user wants to define a target segment or select/score prospects (initial discovery)
- prospect_manage: user wants to manage prospects — add/remove/edit individual prospects, upload CSV, view current prospect list, select specific prospects by name, clear prospects, or change who receives outreach. Use this when the user references specific people or asks to modify the prospect list AFTER initial discovery.
- generate: user wants content created (outreach, social posts, briefs)
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
- Only use "clarify" as a last resort when the message is truly unintelligible or has multiple conflicting interpretations
- Never hallucinate a mode. If genuinely unclear → "clarify"
- Do not generate any content. Only classify and route.

## Output format (strict JSON, no prose, no markdown code blocks)
{{
  "current_intent": "<one of: research, segment, prospect_manage, generate, content_refine, deploy, feedback, refined_cycle, mcp_configure, answer, update_context, clarify>",
  "reasoning": "<one sentence explaining your classification>",
  "user_directive": "<a clear, actionable summary of WHAT the user wants the next agent to do — capture specific focus areas, constraints, preferences, and tone from the user's message. Examples: 'Research competitor pricing strategies for enterprise SaaS', 'Generate 3 email variants with a casual, friendly tone focused on cost savings', 'Deploy only the ROI-focused variant to top 3 prospects'. This MUST reflect the user's specific request, not a generic description of what the agent does.>",
  "clarification_question": "<only if current_intent=clarify, else null>",
  "clarification_options": ["<option1>", "<option2>", "..."],
  "next_node": "<research, segment, generate, content_refine, deploy, feedback, refined_cycle, answer, update_context, clarify>"
}}"""

DEFAULT_CLARIFICATION = (
    "I didn't quite catch that — could you clarify what you'd like to do? "
    "(research / segment / manage prospects / generate / refine content / deploy / feedback / configure MCP)"
)

DEFAULT_OPTIONS = ["Research competitors", "Manage prospects", "Generate content", "Refine content", "Deploy campaign", "Report feedback", "Configure MCP server"]


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

    prompt = f"""Campaign context:
- Product: {task.get("product_name", "Unknown")}
- Description: {state.get("product_description", "No description")}
- Target Market: {task.get("target_market", "Unknown")}
- Stage: {stage.get("active_stage_summary", "starting")}
- Cycle: {cycle_number}
- Prior intent: {stage.get("previous_intent", "none")}
- Content variants exist: {"yes (" + str(len(state.get("content_variants", []))) + " variants)" if state.get("content_variants") else "no"}

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
If the information is not available in the context, say so honestly rather than guessing.
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

    # Include content variants if available
    variants = state.get("content_variants", [])
    if variants:
        context_parts.append(f"\nContent Variants ({len(variants)} total):")
        for v in variants[:5]:
            label = v.get("angle_label", "unknown") if isinstance(v, dict) else str(v)
            context_parts.append(f"  - {label}")

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
