"""Deployment Agent — mock send layer with full deployment record tracking.

Handles:
- A/B split plan generation (round-robin assignment of prospects to variant cohorts)
- Content personalisation ({{first_name}}, {{company}} token replacement)
- Mock send simulation (returns fake provider_message_id)
- DeploymentRecord creation persisted to MongoDB
- DeploymentConfirm UI frame (pre-send) and DeliveryStatusCard (post-send)
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.db.crud import save_deployment_record
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


def personalize_variant(variant: dict, prospect: dict) -> str:
    """Replace {{first_name}} and {{company}} tokens with prospect data."""
    content = variant.get("body", "")
    name = prospect.get("name", "")
    first_name = name.split()[0] if name else ""
    company = prospect.get("company", "")
    content = content.replace("{{first_name}}", first_name)
    content = content.replace("{{company}}", company)
    return content


# ---------------------------------------------------------------------------
# Mock send
# ---------------------------------------------------------------------------


async def mock_send(channel: str, prospect: dict, content: str) -> str:
    """Simulate a send. Returns a fake provider_message_id."""
    await asyncio.sleep(0.05)  # simulate network latency
    return f"mock_{channel}_{uuid4().hex[:8]}"


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
                    "status": "sent",
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
    logger.info("deployment_agent_node called | session=%s", session_id)

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
            "error_messages": [
                "No content variants found. Please generate content before deploying."
            ],
        }

    if not selected_prospects:
        logger.warning("deployment_agent_node: no prospects available | session=%s", session_id)
        return {
            "next_node": "orchestrator",
            "error_messages": [
                "No prospects found. Please run segmentation before deploying."
            ],
        }

    # -- If not yet confirmed, emit DeploymentConfirm and wait --
    if not state.get("deployment_confirmed"):
        ab_plan = build_ab_split_plan(selected_variants, selected_prospects)
        confirm_frame = build_deployment_confirm_frame(
            selected_variants,
            selected_prospects,
            ab_plan,
            f"deploy-confirm-{session_id[:8]}",
        )
        logger.info(
            "deployment_agent_node: awaiting confirmation | session=%s variants=%d prospects=%d",
            session_id,
            len(selected_variants),
            len(selected_prospects),
        )
        return {
            "ab_split_plan": ab_plan,
            "next_node": "orchestrator",
            "pending_ui_frames": [confirm_frame],
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

        # Personalise content
        rendered_content = personalize_variant(variant, prospect)

        # Send via mock provider
        provider_message_id = await mock_send(
            channel=variant.get("intended_channel", "email"),
            prospect=prospect,
            content=rendered_content,
        )

        # Create deployment record
        record = DeploymentRecord(
            id=str(uuid4()),
            session_id=session_id,
            variant_id=variant.get("id", ""),
            segment_id=segment_id,
            prospect_id=prospect.get("id", ""),
            channel=variant.get("intended_channel", "email"),
            provider="mock",
            provider_message_id=provider_message_id,
            ab_cohort=cohort,
            rendered_content_hash=hashlib.md5(  # noqa: S324
                rendered_content.encode()
            ).hexdigest(),
            sent_at=datetime.now(timezone.utc),
        )

        await save_deployment_record(record.model_dump())
        deployment_records.append(record.model_dump())

    # -- Emit DeliveryStatusCard --
    status_frame = build_delivery_status_frame(
        deployment_records,
        f"delivery-status-{session_id[:8]}",
    )

    logger.info(
        "deployment_agent_node completed | session=%s records=%d",
        session_id,
        len(deployment_records),
    )

    return {
        "deployment_records": deployment_records,
        "deployment_confirmed": False,  # reset for next cycle
        "next_node": "orchestrator",
        "pending_ui_frames": [status_frame],
    }
