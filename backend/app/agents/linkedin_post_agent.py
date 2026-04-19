"""LinkedIn Post Agent — create, refine, publish, and monitor LinkedIn feed posts.

Flow:
  Phase 1 (Compose):  LLM generates a flyer HTML + post caption from campaign context.
  Phase 2 (Refine):   User iterates on flyer design or caption as many times as wanted.
  Phase 3 (Confirm):  User says "post it" → confirmation gate shown before publishing.
  Phase 4 (Publish):  Confirmed → post to LinkedIn feed via Unipile API.
  Phase 5 (Monitor):  Fetch post comments; LLM generates suggested replies.
"""

import base64
import binascii
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.llm import get_llm
from app.models.campaign_state import CampaignState
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)
_INLINE_IMAGE_RE = re.compile(r"^data:(image/[-+\w.]+);base64,(.+)$", re.DOTALL)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

COMPOSE_PROMPT = """\
You are a LinkedIn content strategist creating a B2B campaign post.

Your output MUST be a JSON object with exactly two keys: "caption" and "html".

╔══════════════════════════════════════════════════════════════════╗
║  USER DIRECTION (highest priority — shape everything around this):
║  {user_directive}
╚══════════════════════════════════════════════════════════════════╝

Campaign context:
  Product:         {product_name}
  Description:     {product_description}
  Target audience: {segment_label}
  Research brief:  {briefing_summary}

━━━━━ CAPTION RULES ━━━━━
- Open with a bold, direct hook — never "I'm excited to announce" or "Thrilled to share"
- 3–5 short paragraphs (2–3 sentences each), optimised for LinkedIn's feed algorithm
- Use 1–3 emojis purposefully — not decoratively
- Close with a clear open question to invite comments
- Add 3–5 relevant hashtags at the very end (not inline)
- Tone: conversational yet authoritative B2B voice

━━━━━ HTML FLYER RULES ━━━━━
- Inline CSS ONLY — absolutely no external assets, CDN links, or @import rules
- Max 600 px wide, designed to render cleanly inside a <div>
- Modern B2B design: gradient background, crisp typography, clear visual hierarchy
- Must include: prominent headline, 2–3 value bullets, one CTA button, brand/product name
- No <html>/<head>/<body> wrapper — return a snippet only

Output ONLY valid JSON. No markdown fences, no prose before or after.
{{"caption": "...", "html": "..."}}
"""

REFINE_PROMPT = """\
You are refining a LinkedIn post based on user feedback. Change ONLY what the user asked for.

CURRENT CAPTION:
{current_caption}

CURRENT FLYER HTML:
{current_html}

USER FEEDBACK:
{user_feedback}

Rules:
- Feedback about text / wording / tone → update caption only, keep html identical
- Feedback about design / colour / layout / visual → update html only, keep caption identical
- Feedback that applies to both → update both
- Preserve EVERYTHING the user did NOT mention

Output ONLY valid JSON. Same structure.
{{"caption": "...", "html": "..."}}
"""

COMMENT_REPLY_PROMPT = """\
You are crafting professional LinkedIn comment replies on behalf of the brand.

POST CAPTION:
{caption}

PRODUCT: {product_name}

COMMENTS TO REPLY TO:
{comments_text}

For each comment write a genuine reply that:
- Directly addresses the commenter's specific point
- Adds real value or naturally extends the conversation
- Mentions the product only when it is genuinely relevant (never forced)
- Is 1–2 sentences — concise, warm, and human

Output ONLY a JSON array. No prose.
[{{"comment_id": "...", "commenter_name": "...", "suggested_reply": "..."}}]
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PUBLISH_TRIGGERS = frozenset([
    "post it", "publish", "go ahead", "send it", "share it",
    "post now", "looks good", "perfect", "ready", "deploy",
    "post this", "upload", "push it", "do it", "yes, post",
    "confirm", "let's post", "publish it",
])


def _user_wants_to_publish(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _PUBLISH_TRIGGERS)


def _extract_last_user_message(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            return (msg.content if isinstance(msg.content, str) else str(msg.content))[:1200]
        if isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", ""))[:1200]
    return ""


async def _call_llm_for_post(prompt: str) -> tuple[str, str]:
    """Invoke LLM and extract (caption, html) from the JSON response."""
    llm = get_llm(temperature=0.5)
    if llm is None:
        return _mock_caption(), _mock_html()

    try:
        resp = await llm.ainvoke(prompt)
        raw = str(resp.content) if hasattr(resp, "content") else str(resp)
        raw = raw.strip()
        if raw.startswith("```"):
            idx = raw.find("\n")
            raw = raw[idx + 1:] if idx != -1 else raw[3:]
            raw = raw.rstrip("`").strip()
        parsed = json.loads(raw)
        return parsed.get("caption", ""), parsed.get("html", "")
    except Exception as exc:
        logger.warning("_call_llm_for_post: LLM failed (%s) — using mock", exc)
        return _mock_caption(), _mock_html()


async def _generate_comment_replies(
    comments: list[dict],
    caption: str,
    product_name: str,
) -> list[dict]:
    """Generate AI reply suggestions for post comments."""
    if not comments:
        return []

    llm = get_llm(temperature=0.4)
    if llm is None:
        return [
            {
                "comment_id": c.get("id", ""),
                "commenter_name": c.get("author", ""),
                "suggested_reply": "Thank you for your thoughtful comment! Happy to share more details.",
            }
            for c in comments[:5]
        ]

    comments_text = "\n".join(
        f"- ID: {c.get('id', 'unknown')} | {c.get('author', 'Unknown')}: "
        f"{c.get('text', c.get('content', ''))}"
        for c in comments[:10]
    )

    prompt = COMMENT_REPLY_PROMPT.format(
        caption=caption[:1000],
        product_name=product_name,
        comments_text=comments_text,
    )

    try:
        resp = await llm.ainvoke(prompt)
        raw = str(resp.content) if hasattr(resp, "content") else str(resp)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception as exc:
        logger.warning("_generate_comment_replies: LLM failed (%s)", exc)
        return []


def _mock_caption() -> str:
    return (
        "Most B2B teams are leaving pipeline on the table — not because of effort, "
        "but because they're targeting the wrong people at the wrong time. 🎯\n\n"
        "We've seen teams 3x their reply rates by switching from spray-and-pray to "
        "intelligence-led outreach. The difference? Real context, not guesswork.\n\n"
        "When your message speaks directly to where a prospect is RIGHT NOW, it stops "
        "feeling like a cold email and starts feeling like a conversation they wanted.\n\n"
        "What's the biggest challenge you face with B2B outreach today? 👇\n\n"
        "#B2BSales #Outreach #SalesIntelligence #GrowthStrategy #LeadGeneration"
    )


def _mock_html() -> str:
    return (
        '<div style="max-width:600px;margin:0 auto;background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);'
        'border-radius:16px;padding:48px 40px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;">'
        '<div style="display:inline-block;background:#22d3ee;color:#0f172a;font-size:11px;font-weight:700;'
        'letter-spacing:1.5px;padding:4px 14px;border-radius:20px;margin-bottom:28px;text-transform:uppercase;">'
        'Intelligence-Led Outreach</div>'
        '<h1 style="font-size:34px;font-weight:800;line-height:1.15;margin:0 0 20px;color:#ffffff;">'
        'Stop Guessing.<br>Start Converting.</h1>'
        '<p style="font-size:16px;color:#94a3b8;margin:0 0 32px;line-height:1.7;">'
        'AI-powered signals that tell you exactly who to reach, when to reach them, and what to say.</p>'
        '<ul style="list-style:none;padding:0;margin:0 0 36px;">'
        '<li style="padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.08);color:#e2e8f0;font-size:15px;">'
        '✦ Real-time intent signals from 50+ sources</li>'
        '<li style="padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.08);color:#e2e8f0;font-size:15px;">'
        '✦ Hyper-personalised outreach at scale</li>'
        '<li style="padding:12px 0;color:#e2e8f0;font-size:15px;">✦ 3× reply rates in the first 30 days</li></ul>'
        '<a href="#" style="display:inline-block;background:#22d3ee;color:#0f172a;padding:14px 36px;'
        'border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.3px;">'
        'See How It Works →</a></div>'
    )


def _format_http_error(exc: Exception) -> str:
    """Extract a concise, user-visible error from an HTTP exception."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return str(exc)

    status = exc.response.status_code
    detail = ""
    try:
        payload = exc.response.json()
        if isinstance(payload, dict):
            detail = (
                str(payload.get("message") or payload.get("error") or payload.get("detail") or "")
                .strip()
            )
        elif isinstance(payload, list):
            detail = json.dumps(payload)[:300]
    except Exception:
        detail = exc.response.text.strip()

    detail = " ".join(detail.split())[:300]
    return f"HTTP {status}" + (f" — {detail}" if detail else "")


def _decode_inline_flyer_image(
    data_url: str | None,
) -> tuple[str, bytes, str] | None:
    """Convert a browser-captured data URL into a multipart attachment tuple."""
    if not data_url:
        return None

    match = _INLINE_IMAGE_RE.match(data_url.strip())
    if not match:
        logger.warning("_decode_inline_flyer_image: unsupported data URL format")
        return None

    mime_type = match.group(1).lower()
    extension = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
    }.get(mime_type)
    if not extension:
        logger.warning("_decode_inline_flyer_image: unsupported mime type %s", mime_type)
        return None

    try:
        content = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error):
        logger.warning("_decode_inline_flyer_image: invalid base64 payload")
        return None

    return (f"linkedin-flyer.{extension}", content, mime_type)


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_linkedin_post_composer_frame(html: str, caption: str, instance_id: str) -> dict:
    """LinkedInPostComposer — shows flyer preview + editable caption + action buttons."""
    return UIFrame(
        type="ui_component",
        component="LinkedInPostComposer",
        instance_id=instance_id,
        props={"html": html, "caption": caption},
        actions=[
            UIAction(
                id="publish_linkedin_post",
                label="Post to LinkedIn",
                action_type="publish_linkedin_post",
                payload={},
            ),
            UIAction(
                id="refine_linkedin_post",
                label="Refine flyer / caption",
                action_type="refine_linkedin_post",
                payload={},
            ),
        ],
    ).model_dump()


def build_linkedin_post_confirm_frame(html: str, caption: str, instance_id: str) -> dict:
    """Confirmation gate shown before the post is actually published."""
    preview = caption[:250] + "…" if len(caption) > 250 else caption
    return UIFrame(
        type="ui_component",
        component="LinkedInPostConfirm",
        instance_id=instance_id,
        props={
            "html": html,
            "caption": caption,
            "caption_preview": preview,
            "channel": "linkedin_feed",
            "warning": "This will publish the post to your connected LinkedIn account.",
        },
        actions=[
            UIAction(
                id="confirm_linkedin_post",
                label="Confirm & Publish",
                action_type="confirm_linkedin_post",
                payload={},
            ),
            UIAction(
                id="cancel_linkedin_post",
                label="Go Back & Edit",
                action_type="cancel_linkedin_post",
                payload={},
            ),
        ],
    ).model_dump()


def build_linkedin_post_published_frame(post: dict, instance_id: str) -> dict:
    """Result card shown after a successful publish."""
    return UIFrame(
        type="ui_component",
        component="LinkedInPostPublished",
        instance_id=instance_id,
        props={
            "post_id": post.get("id", ""),
            "provider_id": post.get("provider_id", ""),
            "published_at": post.get("published_at", ""),
            "caption_preview": post.get("caption", "")[:250],
            "status": post.get("status", "sent"),
        },
        actions=[
            UIAction(
                id="monitor_linkedin_comments",
                label="Check Comments & Replies",
                action_type="monitor_linkedin_comments",
                payload={},
            ),
        ],
    ).model_dump()


def build_linkedin_comment_review_frame(
    comments: list[dict],
    reply_suggestions: list[dict],
    instance_id: str,
) -> dict:
    """Comment review card with AI-generated reply suggestions."""
    suggestion_map = {
        s.get("comment_id", ""): s.get("suggested_reply", "")
        for s in reply_suggestions
    }
    enriched = [
        {**c, "suggested_reply": suggestion_map.get(c.get("id", ""), "")}
        for c in comments
    ]
    return UIFrame(
        type="ui_component",
        component="LinkedInCommentReview",
        instance_id=instance_id,
        props={"comments": enriched, "total_count": len(comments)},
        actions=[
            UIAction(
                id="refresh_comments",
                label="Refresh Comments",
                action_type="monitor_linkedin_comments",
                payload={},
            ),
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Phase handlers
# ---------------------------------------------------------------------------


async def _compose_post(
    state: CampaignState,
    session_id: str,
    user_directive: str,
) -> dict:
    """Phase 1 — generate flyer HTML + caption from scratch."""
    from app.agents.content_agent import get_segment_by_id

    product_name = state.get("product_name", "Our Product")
    product_description = state.get("product_description", "")
    briefing_summary = state.get("briefing_summary") or ""

    selected_segment = get_segment_by_id(
        state.get("selected_segment_id"),
        state.get("segment_candidates", []),
    )
    segment_label = (
        selected_segment.get("label", "Target Audience") if selected_segment else "Target Audience"
    )

    prompt = COMPOSE_PROMPT.format(
        user_directive=user_directive or "Create a compelling LinkedIn post for this product",
        product_name=product_name,
        product_description=product_description[:500] if product_description else "(not provided)",
        segment_label=segment_label,
        briefing_summary=briefing_summary[:800] if briefing_summary else "(no research available yet)",
    )

    caption, html = await _call_llm_for_post(prompt)
    if not html:
        html = _mock_html()
    if not caption:
        caption = _mock_caption()

    ui_frames = [
        UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"li_compose_{uuid4().hex[:8]}",
            props={
                "content": (
                    "Here's your LinkedIn post with a custom flyer. "
                    "Refine the caption or design as many times as you like — "
                    "when you're happy, click **Post to LinkedIn**."
                ),
                "role": "assistant",
            },
            actions=[],
        ).model_dump(),
        build_linkedin_post_composer_frame(html, caption, f"li-composer-{session_id[:8]}"),
    ]

    logger.info("_compose_post completed | session=%s", session_id)

    return {
        "linkedin_post_html": html,
        "linkedin_post_caption": caption,
        "linkedin_post_image_data_url": None,
        "linkedin_post_phase": "composed",
        "linkedin_post_confirmed": False,
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


async def _refine_post(
    state: CampaignState,
    session_id: str,
    user_feedback: str,
) -> dict:
    """Phase 2 — refine existing flyer/caption based on user feedback."""
    current_html = state.get("linkedin_post_html") or _mock_html()
    current_caption = state.get("linkedin_post_caption") or _mock_caption()

    prompt = REFINE_PROMPT.format(
        current_caption=current_caption,
        current_html=current_html[:4000],
        user_feedback=user_feedback,
    )

    caption, html = await _call_llm_for_post(prompt)
    if not html:
        html = current_html
    if not caption:
        caption = current_caption

    ui_frames = [
        UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"li_refine_{uuid4().hex[:8]}",
            props={
                "content": "Updated. Keep refining or click **Post to LinkedIn** when you're ready.",
                "role": "assistant",
            },
            actions=[],
        ).model_dump(),
        build_linkedin_post_composer_frame(html, caption, f"li-composer-{session_id[:8]}"),
    ]

    logger.info("_refine_post completed | session=%s", session_id)

    return {
        "linkedin_post_html": html,
        "linkedin_post_caption": caption,
        "linkedin_post_image_data_url": None,
        "linkedin_post_phase": "composed",
        "linkedin_post_confirmed": False,
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


async def _show_publish_confirm(state: CampaignState, session_id: str) -> dict:
    """Phase 3 — show publish confirmation gate before sending to LinkedIn."""
    html = state.get("linkedin_post_html") or ""
    caption = state.get("linkedin_post_caption") or ""

    ui_frames = [
        UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"li_confirm_intro_{uuid4().hex[:8]}",
            props={
                "content": (
                    "Ready to publish to your LinkedIn feed. "
                    "Review the preview below and confirm to post."
                ),
                "role": "assistant",
            },
            actions=[],
        ).model_dump(),
        build_linkedin_post_confirm_frame(html, caption, f"li-confirm-{session_id[:8]}"),
    ]

    logger.info("_show_publish_confirm: awaiting confirmation | session=%s", session_id)

    return {
        "linkedin_post_phase": "confirming",
        "linkedin_post_confirmed": False,
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


async def _publish_post(state: CampaignState, session_id: str) -> dict:
    """Phase 4 — publish to LinkedIn via Unipile API."""
    from app.tools.unipile_client import create_linkedin_post, get_unipile_config_errors

    caption = state.get("linkedin_post_caption") or ""
    html = state.get("linkedin_post_html") or ""
    image_data_url = state.get("linkedin_post_image_data_url") or ""
    flyer_attachment = _decode_inline_flyer_image(image_data_url)

    if not caption:
        error_text = "No caption found. Please compose a post first before publishing."
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "error_messages": [error_text],
            "pending_ui_frames": [
                UIFrame(
                    type="text",
                    component="MessageRenderer",
                    instance_id=f"li_pub_err_{uuid4().hex[:8]}",
                    props={"content": error_text, "role": "assistant"},
                    actions=[],
                ).model_dump()
            ],
        }

    post_record: dict = {
        "id": f"li-post-{uuid4().hex[:8]}",
        "session_id": session_id,
        "caption": caption,
        "html": html,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "provider_id": None,
        "status": "sent",
    }

    if settings.USE_MOCK_SEND:
        post_record["provider_id"] = f"mock-post-{uuid4().hex[:8]}"
        post_record["status"] = "mock_sent"
        logger.info("_publish_post: mock mode | session=%s", session_id)
    else:
        config_errors = get_unipile_config_errors(require_account=True)
        if config_errors:
            error_text = (
                "Cannot publish to LinkedIn — Unipile is not configured:\n\n"
                + "\n".join(f"• {e}" for e in config_errors)
                + "\n\nSet `USE_MOCK_SEND=true` to test without real publishing, "
                "or configure the Unipile credentials above."
            )
            return {
                "next_node": "orchestrator",
                "session_complete": True,
                "error_messages": config_errors,
                "pending_ui_frames": [
                    UIFrame(
                        type="text",
                        component="MessageRenderer",
                        instance_id=f"li_pub_cfg_err_{uuid4().hex[:8]}",
                        props={"content": error_text, "role": "assistant"},
                        actions=[],
                    ).model_dump()
                ],
            }
        try:
            result = await create_linkedin_post(
                text=caption,
                attachments=[flyer_attachment] if flyer_attachment else None,
            )
            post_record["provider_id"] = (
                result.get("social_id")
                or result.get("provider_id")
                or result.get("id")
                or result.get("post_id")
                or ""
            )
            post_record["status"] = "sent"
            logger.info(
                "_publish_post: published | session=%s provider_id=%s",
                session_id,
                post_record["provider_id"],
            )
        except Exception as exc:
            logger.error(
                "_publish_post: Unipile publish failed | session=%s error=%s", session_id, exc
            )
            error_detail = _format_http_error(exc)
            error_text = (
                f"Failed to publish to LinkedIn: {error_detail}\n\n"
                "The post was not sent. Check your Unipile credentials and try again."
            )
            return {
                "next_node": "orchestrator",
                "session_complete": True,
                "error_messages": [str(exc)],
                "pending_ui_frames": [
                    UIFrame(
                        type="text",
                        component="MessageRenderer",
                        instance_id=f"li_pub_err_{uuid4().hex[:8]}",
                        props={"content": error_text, "role": "assistant"},
                        actions=[],
                    ).model_dump()
                ],
            }

    ui_frames = [
        UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"li_published_{uuid4().hex[:8]}",
            props={
                "content": (
                    "Your post is live on LinkedIn! 🎉 "
                    "Click **Check Comments** below whenever you want to see responses "
                    "and get AI-suggested replies."
                ),
                "role": "assistant",
            },
            actions=[],
        ).model_dump(),
        build_linkedin_post_published_frame(post_record, f"li-result-{session_id[:8]}"),
    ]

    return {
        "linkedin_posts": [post_record],
        "linkedin_post_phase": "published",
        "linkedin_post_image_data_url": None,
        "linkedin_post_confirmed": False,
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


async def _monitor_comments(state: CampaignState, session_id: str) -> dict:
    """Phase 5 — fetch post comments and generate AI reply suggestions."""
    from app.tools.unipile_client import list_post_comments

    posts = state.get("linkedin_posts", [])
    if not posts:
        error_text = "No published LinkedIn post found in this session. Please publish a post first."
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "pending_ui_frames": [
                UIFrame(
                    type="text",
                    component="MessageRenderer",
                    instance_id=f"li_mon_err_{uuid4().hex[:8]}",
                    props={"content": error_text, "role": "assistant"},
                    actions=[],
                ).model_dump()
            ],
        }

    latest_post = posts[-1]
    provider_id = latest_post.get("provider_id", "")
    caption = state.get("linkedin_post_caption") or latest_post.get("caption", "")
    product_name = state.get("product_name", "Our Product")

    # Fetch comments — use mock data in mock mode or when no real provider_id
    if settings.USE_MOCK_SEND or not provider_id or provider_id.startswith("mock-"):
        comments: list[dict] = [
            {
                "id": "c1",
                "author": "Sarah Chen",
                "text": "This is really insightful! How does the AI targeting work in practice?",
            },
            {
                "id": "c2",
                "author": "Marcus Johnson",
                "text": "We've been struggling with exactly this problem. Would love to learn more.",
            },
        ]
    else:
        comments = await list_post_comments(provider_id)

    reply_suggestions = await _generate_comment_replies(comments, caption, product_name)

    intro_text = (
        f"Found **{len(comments)}** comment(s) on your post. Here are AI-suggested replies:"
        if comments
        else "No comments on your post yet — check back later!"
    )

    ui_frames = [
        UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"li_monitor_{uuid4().hex[:8]}",
            props={"content": intro_text, "role": "assistant"},
            actions=[],
        ).model_dump(),
    ]
    if comments:
        ui_frames.append(
            build_linkedin_comment_review_frame(
                comments, reply_suggestions, f"li-comments-{session_id[:8]}"
            )
        )

    logger.info(
        "_monitor_comments completed | session=%s comments=%d suggestions=%d",
        session_id,
        len(comments),
        len(reply_suggestions),
    )

    return {
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": ui_frames,
    }


# ---------------------------------------------------------------------------
# Main agent node
# ---------------------------------------------------------------------------


async def linkedin_post_agent_node(state: CampaignState) -> dict:
    """LinkedIn feed post agent — routes through compose → refine → confirm → publish → monitor."""
    session_id = state.get("session_id", "")
    phase = state.get("linkedin_post_phase")
    confirmed = state.get("linkedin_post_confirmed", False)
    last_user_message = _extract_last_user_message(state.get("messages", []))
    user_directive = state.get("user_directive") or last_user_message

    logger.info(
        "linkedin_post_agent_node | session=%s phase=%s confirmed=%s",
        session_id,
        phase,
        confirmed,
    )

    # Phase 1: Nothing composed yet → generate from scratch
    if not phase:
        return await _compose_post(state, session_id, user_directive)

    # Phase 3: Awaiting confirmation click
    if phase == "confirming":
        if confirmed or _user_wants_to_publish(last_user_message):
            return await _publish_post(state, session_id)
        # User changed their mind — go back to editor
        return await _refine_post(state, session_id, last_user_message)

    # Phase 4: Post published → monitor comments
    if phase == "published":
        return await _monitor_comments(state, session_id)

    # Phase 2: Post is composed — refine or move to confirm
    if phase == "composed":
        if confirmed or _user_wants_to_publish(last_user_message):
            return await _show_publish_confirm(state, session_id)
        lower = last_user_message.lower()
        if any(kw in lower for kw in ("new post", "start over", "different post", "generate new")):
            return await _compose_post(state, session_id, user_directive)
        return await _refine_post(state, session_id, last_user_message)

    # Fallback
    return await _compose_post(state, session_id, user_directive)
