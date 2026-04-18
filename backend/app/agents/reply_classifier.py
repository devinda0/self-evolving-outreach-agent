"""Reply Classifier — LLM-powered intelligent analysis of inbound email replies.

Classifies reply intent, sentiment, and extracts actionable signals from
prospect responses to outreach emails. This intelligence feeds into the
feedback agent's learning loop to inform future campaign cycles.
"""

import json
import logging
from typing import Any

from app.core.llm import get_llm

logger = logging.getLogger(__name__)


def _llm_response_to_text(response: Any) -> str:
    """Normalize LangChain response content into plain text."""
    raw_content = response.content if hasattr(response, "content") else response
    return raw_content if isinstance(raw_content, str) else str(raw_content)

# ---------------------------------------------------------------------------
# Classification taxonomy
# ---------------------------------------------------------------------------

REPLY_CLASSIFICATIONS = {
    "interested": "Prospect shows interest, asks for more info, or wants to meet",
    "not_interested": "Prospect declines, says not relevant, or asks to stop",
    "question": "Prospect asks a clarifying question about the offering",
    "referral": "Prospect redirects to another person or department",
    "out_of_office": "Auto-reply indicating absence or vacation",
    "unsubscribe": "Explicit request to be removed from mailing list",
    "bounce_auto": "Automated delivery failure or mailbox-full notification",
    "positive_sentiment": "Warm acknowledgment without clear next step",
    "negative_sentiment": "Negative reaction to the outreach",
    "irrelevant": "Reply unrelated to the outreach (spam, noise, etc.)",
}

SENTIMENT_LEVELS = ["very_positive", "positive", "neutral", "negative", "very_negative"]

# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """You are an expert email reply analyst for a B2B outreach platform.

Analyze this reply to an outreach email and provide a structured classification.

## Original Outreach Email
Subject: {original_subject}
Body excerpt: {original_body_excerpt}

## Prospect Information
Name: {prospect_name}
Company: {prospect_company}
Role: {prospect_role}

## Inbound Reply
From: {reply_from}
Subject: {reply_subject}
Body:
{reply_body}

## Task
Classify this reply with the following JSON structure. Be precise and evidence-based.

{{
    "classification": "<one of: interested, not_interested, question, referral, out_of_office, unsubscribe, bounce_auto, positive_sentiment, negative_sentiment, irrelevant>",
    "sentiment": "<one of: very_positive, positive, neutral, negative, very_negative>",
    "confidence": <float 0.0-1.0>,
    "key_signals": ["<signal 1>", "<signal 2>"],
    "summary": "<one sentence summary of the reply's meaning>",
    "suggested_action": "<recommended next step: follow_up, schedule_meeting, send_info, remove_from_list, wait, escalate, no_action>",
    "extracted_info": {{
        "requested_topic": "<what they want to know more about, if applicable>",
        "objection": "<their concern or reason for declining, if applicable>",
        "referred_to": "<name/role of person they referred to, if applicable>",
        "timeline": "<any mentioned timeline or urgency>",
        "tone_notes": "<brief note on communication style/tone>"
    }}
}}

Respond ONLY with valid JSON. No markdown, no explanation."""


def _truncate(text: str, max_chars: int = 500) -> str:
    """Truncate text to max_chars, adding ellipsis if truncated."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


async def classify_reply(
    reply_body: str,
    reply_subject: str | None = None,
    reply_from: str | None = None,
    original_subject: str | None = None,
    original_body: str | None = None,
    prospect_name: str | None = None,
    prospect_company: str | None = None,
    prospect_role: str | None = None,
) -> dict[str, Any]:
    """Classify an inbound email reply using LLM.

    Returns a structured classification dict with:
    - classification: str (one of REPLY_CLASSIFICATIONS keys)
    - sentiment: str (one of SENTIMENT_LEVELS)
    - confidence: float
    - key_signals: list[str]
    - summary: str
    - suggested_action: str
    - extracted_info: dict

    Falls back to heuristic classification if LLM is unavailable.
    """
    # First try heuristic pre-classification for obvious cases
    heuristic = _heuristic_classify(reply_body, reply_subject)
    if heuristic and heuristic.get("confidence", 0) >= 0.9:
        logger.info(
            "classify_reply: heuristic match classification=%s confidence=%.2f",
            heuristic["classification"],
            heuristic["confidence"],
        )
        return heuristic

    # Use LLM for nuanced classification
    llm = get_llm(temperature=0)
    if llm is None:
        logger.warning("classify_reply: LLM unavailable, using heuristic fallback")
        return heuristic or _default_classification(reply_body)

    prompt = _CLASSIFY_PROMPT.format(
        original_subject=original_subject or "(unknown)",
        original_body_excerpt=_truncate(original_body or "", 300),
        prospect_name=prospect_name or "(unknown)",
        prospect_company=prospect_company or "(unknown)",
        prospect_role=prospect_role or "(unknown)",
        reply_from=reply_from or "(unknown)",
        reply_subject=reply_subject or "(no subject)",
        reply_body=_truncate(reply_body, 1500),
    )

    try:
        response = await llm.ainvoke(prompt)
        content = _llm_response_to_text(response)

        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        result = json.loads(content)

        # Validate and sanitize the classification
        if result.get("classification") not in REPLY_CLASSIFICATIONS:
            result["classification"] = "irrelevant"
        if result.get("sentiment") not in SENTIMENT_LEVELS:
            result["sentiment"] = "neutral"
        result.setdefault("confidence", 0.5)
        result.setdefault("key_signals", [])
        result.setdefault("summary", "")
        result.setdefault("suggested_action", "no_action")
        result.setdefault("extracted_info", {})

        logger.info(
            "classify_reply: LLM classification=%s sentiment=%s confidence=%.2f",
            result["classification"],
            result["sentiment"],
            result["confidence"],
        )
        return result

    except json.JSONDecodeError as exc:
        logger.error("classify_reply: LLM returned invalid JSON: %s", exc)
        return heuristic or _default_classification(reply_body)
    except Exception as exc:
        logger.error("classify_reply: LLM call failed: %s", exc)
        return heuristic or _default_classification(reply_body)


# ---------------------------------------------------------------------------
# Heuristic pre-classification for obvious patterns
# ---------------------------------------------------------------------------

_OOO_PATTERNS = [
    "out of office", "out of the office", "away from", "on vacation",
    "on leave", "maternity leave", "paternity leave", "auto-reply",
    "automatic reply", "i am currently out", "i'm currently out",
    "will return", "returning on", "limited access",
]

_UNSUBSCRIBE_PATTERNS = [
    "unsubscribe", "remove me", "stop emailing", "stop sending",
    "opt out", "opt-out", "do not contact", "don't contact",
    "take me off", "remove from list",
]

_BOUNCE_PATTERNS = [
    "delivery failed", "undeliverable", "mailbox full",
    "address not found", "user unknown", "no such user",
    "message not delivered", "permanent failure",
    "mailer-daemon", "postmaster",
]

_INTERESTED_PATTERNS = [
    "interested", "tell me more", "sounds great", "let's chat",
    "schedule a call", "book a meeting", "would love to learn",
    "send me more", "can you share", "i'd like to",
    "let's discuss", "looking forward", "sounds interesting",
    "i'm curious", "happy to connect",
]

_NOT_INTERESTED_PATTERNS = [
    "not interested", "no thanks", "no thank you", "not relevant",
    "not a good fit", "not the right time", "pass on this",
    "we're not looking", "we already have", "we don't need",
    "not for us", "decline",
]


def _heuristic_classify(body: str, subject: str | None = None) -> dict[str, Any] | None:
    """Fast pattern-based classification for obvious reply types.

    Returns a classification dict or None if no high-confidence match.
    """
    if not body:
        return None

    text = (body + " " + (subject or "")).lower().strip()

    # Check OOO (highest priority — these are automated)
    if any(p in text for p in _OOO_PATTERNS):
        return {
            "classification": "out_of_office",
            "sentiment": "neutral",
            "confidence": 0.95,
            "key_signals": ["auto-reply detected"],
            "summary": "Out-of-office auto-reply",
            "suggested_action": "wait",
            "extracted_info": {},
        }

    # Check bounce patterns
    if any(p in text for p in _BOUNCE_PATTERNS):
        return {
            "classification": "bounce_auto",
            "sentiment": "neutral",
            "confidence": 0.95,
            "key_signals": ["delivery failure detected"],
            "summary": "Email delivery failure / bounce",
            "suggested_action": "remove_from_list",
            "extracted_info": {},
        }

    # Check unsubscribe
    if any(p in text for p in _UNSUBSCRIBE_PATTERNS):
        return {
            "classification": "unsubscribe",
            "sentiment": "negative",
            "confidence": 0.9,
            "key_signals": ["unsubscribe request"],
            "summary": "Prospect requests removal from mailing list",
            "suggested_action": "remove_from_list",
            "extracted_info": {},
        }

    # Check clear interest signals
    interest_matches = [p for p in _INTERESTED_PATTERNS if p in text]
    if len(interest_matches) >= 2:
        return {
            "classification": "interested",
            "sentiment": "positive",
            "confidence": 0.85,
            "key_signals": interest_matches[:3],
            "summary": "Prospect shows interest in the offering",
            "suggested_action": "follow_up",
            "extracted_info": {},
        }

    # Check clear disinterest
    disinterest_matches = [p for p in _NOT_INTERESTED_PATTERNS if p in text]
    if disinterest_matches:
        return {
            "classification": "not_interested",
            "sentiment": "negative",
            "confidence": 0.85,
            "key_signals": disinterest_matches[:3],
            "summary": "Prospect declines the outreach",
            "suggested_action": "no_action",
            "extracted_info": {},
        }

    # No high-confidence heuristic match — defer to LLM
    return None


def _default_classification(body: str) -> dict[str, Any]:
    """Fallback classification when both LLM and heuristics fail."""
    return {
        "classification": "irrelevant" if not body or len(body.strip()) < 10 else "question",
        "sentiment": "neutral",
        "confidence": 0.3,
        "key_signals": [],
        "summary": "Unable to classify — requires manual review",
        "suggested_action": "no_action",
        "extracted_info": {},
    }


# ---------------------------------------------------------------------------
# Batch classification for feedback agent
# ---------------------------------------------------------------------------


async def classify_reply_events(
    events: list[dict[str, Any]],
    threads: list[dict[str, Any]] | None = None,
    prospects: list[dict[str, Any]] | None = None,
    variants: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Classify all reply events, enriching each with LLM analysis.

    Args:
        events: Reply-type feedback events (event_type == "reply").
        threads: Email threads for context (optional).
        prospects: Prospect cards for context (optional).
        variants: Content variants for original email context (optional).

    Returns:
        The same events list, each enriched with 'reply_classification' dict.
    """
    # Build lookup maps
    prospect_map = {p["id"]: p for p in (prospects or []) if p.get("id")}
    variant_map = {v["id"]: v for v in (variants or []) if v.get("id")}
    thread_map = {}
    if threads:
        for t in threads:
            pid = t.get("prospect_id")
            if pid:
                thread_map[pid] = t

    classified = []
    for event in events:
        prospect_id = event.get("prospect_id")
        variant_id = event.get("variant_id")
        prospect = prospect_map.get(prospect_id, {})
        variant = variant_map.get(variant_id, {})
        thread = thread_map.get(prospect_id, {})

        reply_body = event.get("reply_body") or event.get("qualitative_signal") or ""

        if not reply_body:
            # No body to classify — mark as irrelevant with low confidence
            event["reply_classification"] = _default_classification("")
            classified.append(event)
            continue

        # Find original email context from thread or variant
        original_subject = variant.get("subject_line")
        original_body = variant.get("body")

        # Try to get original subject from thread
        if not original_subject and thread:
            original_subject = thread.get("subject")

        classification = await classify_reply(
            reply_body=reply_body,
            reply_subject=event.get("reply_subject"),
            reply_from=prospect.get("email"),
            original_subject=original_subject,
            original_body=original_body,
            prospect_name=prospect.get("name"),
            prospect_company=prospect.get("company"),
            prospect_role=prospect.get("role"),
        )

        event["reply_classification"] = classification
        classified.append(event)

    return classified
