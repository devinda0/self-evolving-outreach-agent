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
        "deploy",
        "feedback",
        "refined_cycle",
        "clarify",
        "answer",
        "update_context",
    ]
)

# Intent to node mapping
INTENT_TO_NODE = {
    "research": "research",
    "segment": "segment",
    "prospect_manage": "prospect_manage",
    "generate": "generate",
    "deploy": "deploy",
    "feedback": "feedback",
    "refined_cycle": "orchestrator",  # re-entry for new cycle
    "clarify": "clarify",
    "answer": "answer",
    "update_context": "update_context",
}

SYSTEM_PROMPT = """You are the Orchestrator of Signal to Action, a multi-agent growth intelligence system.

Your sole job: classify the user's latest message into exactly one intent mode and return a routing decision.

## Intent Modes
- research: user wants market intelligence, competitor analysis, audience signals, channel trends
- segment: user wants to define a target segment or select/score prospects (initial discovery)
- prospect_manage: user wants to manage prospects — add/remove/edit individual prospects, upload CSV, view current prospect list, select specific prospects by name, clear prospects, or change who receives outreach. Use this when the user references specific people or asks to modify the prospect list AFTER initial discovery.
- generate: user wants content created (outreach, social posts, briefs)
- deploy: user wants to send content to a channel
- feedback: user is reporting engagement results or a webhook event has arrived
- refined_cycle: user wants to restart the loop using accumulated intelligence
- answer: user is asking a question about the campaign, product, system status, strategy, or any topic that can be answered from existing context — NOT requesting new research or content generation
- update_context: user is providing clarifications, corrections, or additional information about their product, company, target market, goals, or preferences — NOT requesting an action
- clarify: message is genuinely ambiguous and you cannot determine ANY of the above intents — generate a specific clarification question

## Rules
- Read intent from full conversation context, not just latest message
- "Now write three variants" after research → "generate"
- "Go back to research" → override any prior intent immediately with "research"
- "Send only to John" or "remove Alice from the list" or "add john@example.com" or "show me the prospects" or "upload a CSV" or "I only want to send to sarah@company.com" → "prospect_manage"
- "who are we sending to?" or "show selected prospects" → "prospect_manage"
- If user asks a direct question (e.g. "what is our target market?", "how many variants did we create?", "what should I focus on?") → "answer"
- If user provides new info without requesting an action (e.g. "our company focuses on B2B SaaS", "actually our target market is enterprise HR teams", "our budget is $5000/month") → "update_context"
- If user answers a previous clarification question or provides info the system asked for → "update_context"
- Only use "clarify" as a last resort when the message is truly unintelligible or has multiple conflicting interpretations
- Never hallucinate a mode. If genuinely unclear → "clarify"
- Do not generate any content. Only classify and route.

## Output format (strict JSON, no prose, no markdown code blocks)
{
  "current_intent": "<one of: research, segment, prospect_manage, generate, deploy, feedback, refined_cycle, answer, update_context, clarify>",
  "reasoning": "<one sentence explaining your classification>",
  "user_directive": "<a clear, actionable summary of WHAT the user wants the next agent to do — capture specific focus areas, constraints, preferences, and tone from the user's message. Examples: 'Research competitor pricing strategies for enterprise SaaS', 'Generate 3 email variants with a casual, friendly tone focused on cost savings', 'Deploy only the ROI-focused variant to top 3 prospects'. This MUST reflect the user's specific request, not a generic description of what the agent does.>",
  "clarification_question": "<only if current_intent=clarify, else null>",
  "clarification_options": ["<option1>", "<option2>", "..."],
  "next_node": "<research, segment, generate, deploy, feedback, answer, update_context, clarify>"
}"""

DEFAULT_CLARIFICATION = (
    "I didn't quite catch that — could you clarify what you'd like to do? "
    "(research / segment / manage prospects / generate / deploy / feedback)"
)

DEFAULT_OPTIONS = ["Research competitors", "Manage prospects", "Generate content", "Deploy campaign", "Report feedback"]


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
    prompt = f"""Campaign context:
- Product: {task.get("product_name", "Unknown")}
- Description: {state.get("product_description", "No description")}
- Target Market: {task.get("target_market", "Unknown")}
- Stage: {stage.get("active_stage_summary", "starting")}
- Cycle: {task.get("cycle_number", 1)}
- Prior intent: {stage.get("previous_intent", "none")}

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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
Keep answers focused and brief (1-3 paragraphs max)."""


async def answer_node(state: CampaignState) -> dict[str, Any]:
    """Answer a user question directly from campaign context.

    Uses the LLM to generate a contextual answer based on the current campaign
    state — research findings, variants, deployment records, etc.

    Args:
        state: Current campaign state.

    Returns:
        State update with the answer as an AI message and UI frame.
    """
    session_id = state.get("session_id", "unknown")
    logger.info("answer_node called | session=%s", session_id)

    bundle = await memory_manager.build_context_bundle(state, "orchestrator")
    context_messages = bundle.get("recent_messages", [])

    # Build rich context for answering
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

    # Include deployment records if available
    records = state.get("deployment_records", [])
    if records:
        context_parts.append(f"\nDeployment Records: {len(records)} sends")

    # Include feedback if available
    feedback = state.get("engagement_results", [])
    if feedback:
        context_parts.append(f"\nEngagement Results: {len(feedback)} events")

    context_str = "\n".join(context_parts)

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
