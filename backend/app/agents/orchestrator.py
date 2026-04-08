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
"""

import json
import logging
from typing import Any
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.models.campaign_state import CampaignState
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)

# Valid intent modes
VALID_INTENTS = frozenset([
    "research",
    "segment",
    "generate",
    "deploy",
    "feedback",
    "refined_cycle",
    "clarify",
])

# Intent to node mapping
INTENT_TO_NODE = {
    "research": "research",
    "segment": "segment",
    "generate": "generate",
    "deploy": "deploy",
    "feedback": "feedback",
    "refined_cycle": "orchestrator",  # re-entry for new cycle
    "clarify": "clarify",
}

SYSTEM_PROMPT = """You are the Orchestrator of Signal to Action, a multi-agent growth intelligence system.

Your sole job: classify the user's latest message into exactly one intent mode and return a routing decision.

## Intent Modes
- research: user wants market intelligence, competitor analysis, audience signals, channel trends
- segment: user wants to define a target segment or select/score prospects
- generate: user wants content created (outreach, social posts, briefs)
- deploy: user wants to send content to a channel
- feedback: user is reporting engagement results or a webhook event has arrived
- refined_cycle: user wants to restart the loop using accumulated intelligence
- clarify: message is ambiguous — generate a specific clarification question

## Rules
- Read intent from full conversation context, not just latest message
- "Now write three variants" after research → "generate"
- "Go back to research" → override any prior intent immediately with "research"
- Never hallucinate a mode. If genuinely unclear → "clarify"
- Do not generate any content. Only classify and route.

## Output format (strict JSON, no prose, no markdown code blocks)
{
  "current_intent": "<one of: research, segment, generate, deploy, feedback, refined_cycle, clarify>",
  "reasoning": "<one sentence explaining your classification>",
  "clarification_question": "<only if current_intent=clarify, else null>",
  "clarification_options": ["<option1>", "<option2>", "..."],
  "next_node": "<research, segment, generate, deploy, feedback, clarify>"
}"""

DEFAULT_CLARIFICATION = (
    "I didn't quite catch that — could you clarify what you'd like to do? "
    "(research / segment / generate / deploy / feedback)"
)

DEFAULT_OPTIONS = ["Research competitors", "Generate content", "Deploy campaign", "Report feedback"]


def _get_llm():
    """Get the Gemini LLM client."""
    if settings.USE_MOCK_LLM:
        return None  # Tests will provide mock

    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in environment variables")

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",
        temperature=0,
        api_key=settings.GEMINI_API_KEY,
    )


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

    # Build context bundle (last 12 messages + stage summary)
    all_messages = state.get("messages", [])
    context_messages = all_messages[-12:] if len(all_messages) > 12 else all_messages

    # Get the LLM client
    llm = _get_llm()

    if llm is None:
        # Mock mode — return default clarify response
        logger.info("USE_MOCK_LLM is true, returning default clarify response")
        return _make_clarify_response(state)

    # Build the prompt
    prompt = f"""Campaign context:
- Product: {state.get('product_name', 'Unknown')}
- Description: {state.get('product_description', 'No description')}
- Target Market: {state.get('target_market', 'Unknown')}
- Stage: {state.get('active_stage_summary', 'starting')}
- Cycle: {state.get('cycle_number', 1)}
- Prior intent: {state.get('previous_intent', 'none')}

Conversation (last {len(context_messages)} turns):
{format_messages(context_messages)}

Classify the latest user intent."""

    # Try to get classification from Gemini (with retry)
    max_retries = 2
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = await llm.ainvoke([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])

            # Parse the response
            result = _parse_llm_response(response.content)
            result = _validate_and_normalize_result(result)

            logger.info(
                "Orchestrator classified intent | session=%s intent=%s next_node=%s",
                session_id,
                result["current_intent"],
                result["next_node"],
            )

            return {
                "current_intent": result["current_intent"],
                "previous_intent": state.get("current_intent"),
                "next_node": result["next_node"],
                "clarification_question": result.get("clarification_question"),
                "clarification_options": result.get("clarification_options", []),
                "intent_history": state.get("intent_history", []) + [result["current_intent"]],
            }

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
