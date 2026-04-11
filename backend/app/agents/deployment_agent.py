"""Deployment Agent — send layer with full deployment record tracking.

Handles:
- A/B split plan generation (round-robin assignment of prospects to variant cohorts)
- Content personalisation ({{first_name}}, {{company}} token replacement)
- Real email sending via Resend when USE_MOCK_SEND=false
- Mock send fallback for local development and non-email channels
- DeploymentRecord creation persisted to MongoDB (status: sent | failed)
- DeploymentConfirm UI frame (pre-send) and DeliveryStatusCard (post-send)
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx

from app.core.config import settings
from app.db.crud import save_deployment_record
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.intelligence import DeploymentRecord
from app.models.ui_frames import UIAction, UIFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# A/B split plan builder
# ---------------------------------------------------------------------------


def build_ab_split_plan(variants: list[dict], prospects: list[dict]) -> dict:
    """Assign each prospect to a variant cohort (round-robin).

    Returns a dict with:
    - assignments: list of {variant, prospect, cohort} mappings
    - variant_count: number of variants
    - prospect_count: number of prospects
    """
    if not variants or not prospects:
        return {"assignments": [], "variant_count": len(variants), "prospect_count": len(prospects)}

    assignments = []
    for i, prospect in enumerate(prospects):
        variant = variants[i % len(variants)]
        cohort = chr(65 + (i % len(variants)))  # A, B, C...
        assignments.append({"variant": variant, "prospect": prospect, "cohort": cohort})
    return {
        "assignments": assignments,
        "variant_count": len(variants),
        "prospect_count": len(prospects),
    }


# ---------------------------------------------------------------------------
# Content personalisation
# ---------------------------------------------------------------------------


def _apply_tokens(text: str, prospect: dict) -> str:
    """Replace {{first_name}} and {{company}} tokens in any string."""
    name = prospect.get("name", "")
    first_name = name.split()[0] if name else ""
    company = prospect.get("company", "")
    text = text.replace("{{first_name}}", first_name)
    text = text.replace("{{company}}", company)
    return text


def personalize_variant(variant: dict, prospect: dict) -> str:
    """Replace {{first_name}} and {{company}} tokens in the variant body (plain text)."""
    return _apply_tokens(variant.get("body", ""), prospect)


def personalize_variant_html(variant: dict, prospect: dict) -> str:
    """Return a personalised HTML body for email sending.

    Uses ``html_body`` if present on the variant; falls back to ``body``.
    Plain-text bodies are converted to basic HTML by replacing newlines
    with ``<br>`` tags.
    """
    raw = variant.get("html_body") or variant.get("body", "")
    content = _apply_tokens(raw, prospect)
    # If there are no HTML tags, wrap as simple paragraph HTML
    if "<" not in content:
        lines = content.replace("\r\n", "\n").split("\n")
        content = "<br>".join(lines)
        content = f"<p>{content}</p>"
    return content


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------


def check_production_readiness() -> list[str]:
    """Validate config required for real email sends.

    Returns a list of human-readable error strings. Empty list means production
    mode is safe to use.
    """
    errors: list[str] = []
    if not settings.RESEND_API_KEY:
        errors.append("RESEND_API_KEY is not set — cannot send real emails.")
    if (
        not settings.RESEND_FROM_EMAIL
        or settings.RESEND_FROM_EMAIL == "outreach@yourdomain.com"
    ):
        errors.append(
            "RESEND_FROM_EMAIL is still the default placeholder — set a verified sender address."
        )
    if not settings.UNSUBSCRIBE_URL:
        logger.warning("UNSUBSCRIBE_URL is not configured — recommended for CAN-SPAM compliance.")
    if not settings.PHYSICAL_ADDRESS:
        errors.append("PHYSICAL_ADDRESS is not configured — required for CAN-SPAM compliance.")
    return errors


async def mock_send(channel: str, prospect: dict, content: str) -> str:
    """Simulate a send. Returns a fake provider_message_id.

    Used when ``USE_MOCK_SEND=true`` or for non-email channels.
    """
    await asyncio.sleep(0.05)  # simulate network latency
    return f"mock_{channel}_{uuid4().hex[:8]}"


async def send_via_email(variant: dict, prospect: dict, session_id: str) -> str:
    """Send a real email — MCP email tool first, Resend fallback.

    Returns the provider_message_id.
    """
    from app.tools.mcp_tools import do_send_email

    rendered_html = personalize_variant_html(variant, prospect)
    subject = _apply_tokens(variant.get("subject_line", ""), prospect)
    tags = {
        "session_id": session_id,
        "variant_id": variant["id"],
        "prospect_id": prospect["id"],
    }

    return await do_send_email(
        to_email=prospect["email"],
        to_name=prospect.get("name", ""),
        subject=subject,
        html_body=rendered_html,
        tags=tags,
        session_id=session_id,
    )


async def _dispatch_send(
    channel: str,
    variant: dict,
    prospect: dict,
    session_id: str,
) -> tuple[str | None, str | None]:
    """Route a send to mock or real provider.

    Returns ``(provider_message_id, error_detail)``.  On success
    ``error_detail`` is ``None``; on failure ``provider_message_id`` is
    ``None``.
    """
    if settings.USE_MOCK_SEND or channel != "email":
        msg_id = await mock_send(channel, prospect, personalize_variant(variant, prospect))
        return msg_id, None

    try:
        msg_id = await send_via_email(variant, prospect, session_id)
        return msg_id, None
    except httpx.HTTPStatusError as exc:
        logger.error(
            "_dispatch_send Resend HTTP error prospect=%s status=%s",
            prospect.get("id"),
            exc.response.status_code,
        )
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "_dispatch_send unexpected error prospect=%s: %s",
            prospect.get("id"),
            exc,
        )
        return None, str(exc)


# ---------------------------------------------------------------------------
# UI frame builders
# ---------------------------------------------------------------------------


def build_deployment_confirm_frame(
    variants: list[dict],
    prospects: list[dict],
    ab_plan: dict,
    instance_id: str,
) -> dict:
    """Build a DeploymentConfirm UI frame for user approval before sending."""
    return UIFrame(
        type="ui_component",
        component="DeploymentConfirm",
        instance_id=instance_id,
        props={
            "variant_count": ab_plan["variant_count"],
            "prospect_count": ab_plan["prospect_count"],
            "variants": [
                {
                    "id": v.get("id"),
                    "angle_label": v.get("angle_label"),
                    "intended_channel": v.get("intended_channel"),
                    "subject_line": v.get("subject_line"),
                }
                for v in variants
            ],
            "prospects": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "company": p.get("company"),
                }
                for p in prospects
            ],
        },
        actions=[
            UIAction(
                id="confirm-deploy",
                label="Confirm & Send",
                action_type="confirm_deployment",
                payload={},
            ),
            UIAction(
                id="cancel-deploy",
                label="Cancel",
                action_type="cancel_deployment",
                payload={},
            ),
        ],
    ).model_dump()


def build_delivery_status_frame(
    deployment_records: list[dict],
    instance_id: str,
) -> dict:
    """Build a DeliveryStatusCard UI frame showing results after all sends complete."""
    return UIFrame(
        type="ui_component",
        component="DeliveryStatusCard",
        instance_id=instance_id,
        props={
            "total_sent": len(deployment_records),
            "records": [
                {
                    "id": r.get("id"),
                    "prospect_id": r.get("prospect_id"),
                    "variant_id": r.get("variant_id"),
                    "channel": r.get("channel"),
                    "ab_cohort": r.get("ab_cohort"),
                    "provider_message_id": r.get("provider_message_id"),
                    "status": r.get("status", "sent"),
                }
                for r in deployment_records
            ],
        },
        actions=[
            UIAction(
                id="view-details",
                label="View deployment details",
                action_type="view_deployment_details",
                payload={},
            ),
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Main agent node
# ---------------------------------------------------------------------------


async def deployment_agent_node(state: CampaignState) -> dict:
    """Deploy selected variants to selected prospects via mock send layer.

    Flow:
    1. If deployment_confirmed is False, emit DeploymentConfirm UI frame and wait.
    2. If confirmed, build A/B split plan, personalise content, send, create
       DeploymentRecord per send, persist to MongoDB, emit DeliveryStatusCard.

    Prerequisites:
    - content_variants and selected_variant_ids must be present
    - prospect_cards and selected_prospect_ids must be present
    """
    session_id = state.get("session_id", "")
    all_variants_count = len(state.get("content_variants", []))
    selected_variant_ids = state.get("selected_variant_ids", [])
    all_prospects_count = len(state.get("prospect_cards", []))
    selected_prospect_ids_count = len(state.get("selected_prospect_ids", []))
    deployment_confirmed = state.get("deployment_confirmed", False)
    logger.info(
        "deployment_agent_node called | session=%s variants=%d selected_variants=%d "
        "prospects=%d selected_prospects=%d confirmed=%s",
        session_id,
        all_variants_count,
        len(selected_variant_ids),
        all_prospects_count,
        selected_prospect_ids_count,
        deployment_confirmed,
    )

    # Build scoped context bundle — provides compact prospect cards and selected variants
    try:
        bundle = await memory_manager.build_context_bundle(state, "deployment")
        logger.debug(
            "deployment_agent_node: bundle built | variants=%d compact_prospects=%d",
            len(bundle.get("selected_variant", [])),
            len(bundle.get("selected_prospects", [])),
        )
    except Exception as exc:
        logger.warning("deployment_agent_node: memory bundle failed (%s) — continuing", exc)

    # -- Resolve selected variants --
    all_variants = state.get("content_variants", [])
    selected_variant_ids = state.get("selected_variant_ids", [])
    selected_variants = [v for v in all_variants if v.get("id") in selected_variant_ids]

    # Fallback: if no explicit selection, use all variants
    if not selected_variants:
        selected_variants = all_variants

    # -- Resolve selected prospects --
    all_prospects = state.get("prospect_cards", [])
    selected_prospect_ids = state.get("selected_prospect_ids", [])
    selected_prospects = [p for p in all_prospects if p.get("id") in selected_prospect_ids]

    # Fallback: if no explicit selection, use all prospects
    if not selected_prospects:
        selected_prospects = all_prospects

    # -- Guard: need at least variants and prospects --
    if not selected_variants:
        logger.warning("deployment_agent_node: no variants available | session=%s", session_id)
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "error_messages": [
                "No content variants found. Please generate content before deploying."
            ],
        }

    if not selected_prospects:
        logger.warning("deployment_agent_node: no prospects available | session=%s", session_id)
        return {
            "next_node": "orchestrator",
            "session_complete": True,
            "error_messages": ["No prospects found. Please run segmentation before deploying."],
        }

    # -- If not yet confirmed, emit DeploymentConfirm and wait --
    if not state.get("deployment_confirmed"):
        # Pre-flight: warn if production mode is misconfigured
        production_errors: list[str] = []
        if not settings.USE_MOCK_SEND:
            production_errors = check_production_readiness()
            if production_errors:
                logger.error(
                    "deployment_agent_node: production readiness check failed | session=%s errors=%s",
                    session_id,
                    production_errors,
                )
                return {
                    "next_node": "orchestrator",
                    "session_complete": True,
                    "error_messages": [
                        "Production email sending is enabled but configuration is incomplete:",
                        *production_errors,
                        "Set USE_MOCK_SEND=true to use mock mode, or fix the issues above.",
                    ],
                }

        ab_plan = build_ab_split_plan(selected_variants, selected_prospects)
        confirm_frame = build_deployment_confirm_frame(
            selected_variants,
            selected_prospects,
            ab_plan,
            f"deploy-confirm-{session_id[:8]}",
        )

        # Build a response message describing the deployment plan
        user_directive = state.get("user_directive")
        directive_note = ""
        if user_directive:
            directive_note = f" as you requested ({user_directive}). "
        else:
            directive_note = ". "

        variant_labels = [v.get("angle_label", v.get("intended_channel", "variant")) for v in selected_variants]
        prospect_names = [p.get("name", "Unknown") for p in selected_prospects[:3]]
        more_prospects = f" and {len(selected_prospects) - 3} more" if len(selected_prospects) > 3 else ""

        response_message = (
            f"Ready to deploy{directive_note}"
            f"Sending {len(selected_variants)} variant(s) ({', '.join(variant_labels)}) "
            f"to {len(selected_prospects)} prospect(s): {', '.join(prospect_names)}{more_prospects}. "
            "Please confirm the deployment below."
        )
        response_frame = UIFrame(
            type="text",
            component="MessageRenderer",
            instance_id=f"deploy_response_{uuid4().hex[:8]}",
            props={"content": response_message, "role": "assistant"},
            actions=[],
        ).model_dump()

        logger.info(
            "deployment_agent_node: awaiting confirmation | session=%s variants=%d prospects=%d",
            session_id,
            len(selected_variants),
            len(selected_prospects),
        )
        return {
            "ab_split_plan": ab_plan,
            "next_node": "orchestrator",
            "pending_ui_frames": [response_frame, confirm_frame],
        }

    # -- Confirmed: execute deployment --
    ab_plan = state.get("ab_split_plan") or build_ab_split_plan(
        selected_variants, selected_prospects
    )
    segment_id = state.get("selected_segment_id") or "seg-unknown"

    deployment_records: list[dict] = []
    for assignment in ab_plan.get("assignments", []):
        variant = assignment["variant"]
        prospect = assignment["prospect"]
        cohort = assignment["cohort"]

        channel = variant.get("intended_channel", "email")

        # Personalise content (plain text for hash; HTML built inside send_via_email)
        rendered_content = personalize_variant(variant, prospect)

        # Dispatch to real or mock provider
        provider_message_id, error_detail = await _dispatch_send(
            channel=channel,
            variant=variant,
            prospect=prospect,
            session_id=session_id,
        )
        send_status: Literal["sent", "failed"] = "failed" if error_detail else "sent"
        provider = "resend" if not settings.USE_MOCK_SEND and channel == "email" else "mock"

        # Create deployment record
        record = DeploymentRecord(
            id=str(uuid4()),
            session_id=session_id,
            variant_id=variant.get("id", ""),
            segment_id=segment_id,
            prospect_id=prospect.get("id", ""),
            channel=channel,
            provider=provider,
            provider_message_id=provider_message_id,
            ab_cohort=cohort,
            rendered_content_hash=hashlib.md5(  # noqa: S324
                rendered_content.encode()
            ).hexdigest(),
            sent_at=datetime.now(timezone.utc),
            status=send_status,
            error_detail=error_detail,
        )

        await save_deployment_record(record.model_dump())
        deployment_records.append(record.model_dump(mode="json"))

    # -- Emit DeliveryStatusCard --
    status_frame = build_delivery_status_frame(
        deployment_records,
        f"delivery-status-{session_id[:8]}",
    )

    # Build post-deployment response message
    sent_count = sum(1 for r in deployment_records if r.get("status") == "sent")
    failed_count = sum(1 for r in deployment_records if r.get("status") == "failed")
    channels_used = list({r.get("channel", "email") for r in deployment_records})

    if failed_count == 0:
        status_summary = f"All {sent_count} messages sent successfully"
    else:
        status_summary = f"{sent_count} sent, {failed_count} failed"

    response_message = (
        f"Deployment complete — {status_summary} via {', '.join(channels_used)}. "
        "You can track engagement results as they come in, or report feedback manually."
    )
    response_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=f"deploy_done_{uuid4().hex[:8]}",
        props={"content": response_message, "role": "assistant"},
        actions=[],
    ).model_dump()

    logger.info(
        "deployment_agent_node completed | session=%s records=%d",
        session_id,
        len(deployment_records),
    )

    return {
        "deployment_records": deployment_records,
        "deployment_confirmed": False,  # reset for next cycle
        "next_node": "orchestrator",
        "session_complete": True,
        "pending_ui_frames": [response_frame, status_frame],
    }
