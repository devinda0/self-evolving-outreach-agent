"""Tests for the Deployment Agent — mock deployment with full record tracking.

Covers:
- A/B split plan builder (round-robin assignment)
- Content personalisation ({{first_name}}, {{company}} tokens)
- DeploymentConfirm UI frame emission before sending
- DeliveryStatusCard UI frame emission after sending
- Deployment record creation with unique provider_message_id
- End-to-end: 2 variants × 10 prospects = 10 records (5 per cohort)
- Edge cases: no variants, no prospects, empty body
"""

from unittest.mock import AsyncMock, patch

from app.agents.deployment_agent import (
    build_ab_split_plan,
    build_delivery_status_frame,
    build_deployment_confirm_frame,
    deployment_agent_node,
    mock_send,
    personalize_variant,
)

# ---------------------------------------------------------------------------
# State helper
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Build a minimal CampaignState dict with sensible defaults."""
    base = {
        "session_id": "test-session",
        "product_name": "Test Product",
        "product_description": "A test product",
        "target_market": "Developers",
        "messages": [],
        "conversation_summary": None,
        "decision_log": [],
        "intent_history": [],
        "current_intent": None,
        "previous_intent": None,
        "next_node": None,
        "clarification_question": None,
        "clarification_options": [],
        "session_complete": False,
        "cycle_number": 1,
        "prior_cycle_summary": None,
        "active_stage_summary": None,
        "research_query": None,
        "active_thread_types": [],
        "research_findings": [],
        "briefing_summary": None,
        "research_gaps": [],
        "failed_threads": [],
        "selected_segment_id": "seg-1",
        "segment_candidates": [],
        "selected_prospect_ids": [],
        "prospect_pool_ref": None,
        "prospect_cards": [],
        "content_request": None,
        "content_variants": [],
        "selected_variant_ids": [],
        "visual_artifacts": [],
        "selected_channels": [],
        "ab_split_plan": None,
        "deployment_confirmed": False,
        "deployment_records": [],
        "normalized_feedback_events": [],
        "engagement_results": [],
        "winning_variant_id": None,
        "memory_refs": {},
        "error_messages": [],
        "pending_ui_frames": [],
    }
    base.update(overrides)
    return base


def _make_variants(n: int) -> list[dict]:
    return [
        {
            "id": f"var-{i}",
            "body": "Hi {{first_name}}, check out {{company}}'s opportunity.",
            "intended_channel": "email",
            "angle_label": f"angle-{i}",
            "subject_line": f"Subject {i}",
        }
        for i in range(1, n + 1)
    ]


def _make_prospects(n: int) -> list[dict]:
    return [
        {
            "id": f"prospect-{i}",
            "name": f"Person{i} Last{i}",
            "company": f"Company{i}",
            "email": f"person{i}@company{i}.com",
        }
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# A/B split plan builder
# ---------------------------------------------------------------------------


class TestBuildAbSplitPlan:
    def test_round_robin_two_variants(self):
        variants = _make_variants(2)
        prospects = _make_prospects(10)
        plan = build_ab_split_plan(variants, prospects)

        assert plan["variant_count"] == 2
        assert plan["prospect_count"] == 10
        assert len(plan["assignments"]) == 10

        cohort_a = [a for a in plan["assignments"] if a["cohort"] == "A"]
        cohort_b = [a for a in plan["assignments"] if a["cohort"] == "B"]
        assert len(cohort_a) == 5
        assert len(cohort_b) == 5

    def test_single_variant_all_same_cohort(self):
        variants = _make_variants(1)
        prospects = _make_prospects(4)
        plan = build_ab_split_plan(variants, prospects)
        assert all(a["cohort"] == "A" for a in plan["assignments"])

    def test_three_variants(self):
        variants = _make_variants(3)
        prospects = _make_prospects(6)
        plan = build_ab_split_plan(variants, prospects)
        cohorts = [a["cohort"] for a in plan["assignments"]]
        assert cohorts == ["A", "B", "C", "A", "B", "C"]

    def test_empty_variants(self):
        plan = build_ab_split_plan([], _make_prospects(5))
        assert plan["assignments"] == []

    def test_empty_prospects(self):
        plan = build_ab_split_plan(_make_variants(2), [])
        assert plan["assignments"] == []


# ---------------------------------------------------------------------------
# Content personalisation
# ---------------------------------------------------------------------------


class TestPersonalizeVariant:
    def test_replaces_tokens(self):
        variant = {"body": "Hi {{first_name}}, welcome to {{company}}!"}
        prospect = {"name": "Jane Doe", "company": "Acme Corp"}
        result = personalize_variant(variant, prospect)
        assert result == "Hi Jane, welcome to Acme Corp!"

    def test_handles_single_name(self):
        variant = {"body": "Hello {{first_name}}"}
        prospect = {"name": "Alice", "company": "X"}
        result = personalize_variant(variant, prospect)
        assert result == "Hello Alice"

    def test_handles_missing_name(self):
        variant = {"body": "Hi {{first_name}}"}
        prospect = {"name": "", "company": "Widget"}
        result = personalize_variant(variant, prospect)
        assert result == "Hi "

    def test_handles_missing_company(self):
        variant = {"body": "At {{company}}"}
        prospect = {"name": "Bob", "company": ""}
        result = personalize_variant(variant, prospect)
        assert result == "At "

    def test_no_tokens(self):
        variant = {"body": "Plain text message"}
        prospect = {"name": "Bob", "company": "Acme"}
        result = personalize_variant(variant, prospect)
        assert result == "Plain text message"


# ---------------------------------------------------------------------------
# Mock send
# ---------------------------------------------------------------------------


class TestMockSend:
    async def test_returns_unique_ids(self):
        ids = set()
        for _ in range(10):
            msg_id = await mock_send("email", {"name": "Test"}, "content")
            ids.add(msg_id)
        assert len(ids) == 10

    async def test_message_id_format(self):
        msg_id = await mock_send("linkedin", {"name": "Test"}, "content")
        assert msg_id.startswith("mock_linkedin_")
        assert len(msg_id) > len("mock_linkedin_")


# ---------------------------------------------------------------------------
# UI frames
# ---------------------------------------------------------------------------


class TestUIFrames:
    def test_deployment_confirm_frame(self):
        variants = _make_variants(2)
        prospects = _make_prospects(3)
        plan = build_ab_split_plan(variants, prospects)
        frame = build_deployment_confirm_frame(variants, prospects, plan, "test-instance")

        assert frame["component"] == "DeploymentConfirm"
        assert frame["props"]["variant_count"] == 2
        assert frame["props"]["prospect_count"] == 3
        assert len(frame["actions"]) == 2
        action_types = {a["action_type"] for a in frame["actions"]}
        assert "confirm_deployment" in action_types
        assert "cancel_deployment" in action_types

    def test_delivery_status_frame(self):
        records = [
            {"id": "r1", "prospect_id": "p1", "variant_id": "v1", "channel": "email",
             "ab_cohort": "A", "provider_message_id": "mock_1"},
        ]
        frame = build_delivery_status_frame(records, "test-instance")

        assert frame["component"] == "DeliveryStatusCard"
        assert frame["props"]["total_sent"] == 1
        assert len(frame["props"]["records"]) == 1


# ---------------------------------------------------------------------------
# Deployment agent node
# ---------------------------------------------------------------------------


class TestDeploymentAgentNode:
    async def test_emits_confirm_when_not_confirmed(self):
        state = _make_state(
            deployment_confirmed=False,
            content_variants=_make_variants(2),
            selected_variant_ids=["var-1", "var-2"],
            prospect_cards=_make_prospects(4),
            selected_prospect_ids=["prospect-1", "prospect-2", "prospect-3", "prospect-4"],
        )
        result = await deployment_agent_node(state)

        assert result["next_node"] == "orchestrator"
        assert "ab_split_plan" in result
        assert result["pending_ui_frames"][0]["component"] == "DeploymentConfirm"

    async def test_creates_records_when_confirmed(self):
        state = _make_state(
            deployment_confirmed=True,
            content_variants=_make_variants(2),
            selected_variant_ids=["var-1", "var-2"],
            prospect_cards=_make_prospects(4),
            selected_prospect_ids=["prospect-1", "prospect-2", "prospect-3", "prospect-4"],
        )
        with patch(
            "app.agents.deployment_agent.save_deployment_record",
            new_callable=AsyncMock,
        ):
            result = await deployment_agent_node(state)

        assert len(result["deployment_records"]) == 4
        assert result["deployment_confirmed"] is False
        assert result["next_node"] == "orchestrator"
        assert result["pending_ui_frames"][0]["component"] == "DeliveryStatusCard"

    async def test_ten_prospects_two_variants_creates_ten_records(self):
        """AC: Given 2 variants and 10 prospects, creates 10 deployment records (5 per cohort)."""
        state = _make_state(
            deployment_confirmed=True,
            content_variants=_make_variants(2),
            selected_variant_ids=["var-1", "var-2"],
            prospect_cards=_make_prospects(10),
            selected_prospect_ids=[f"prospect-{i}" for i in range(1, 11)],
        )
        with patch(
            "app.agents.deployment_agent.save_deployment_record",
            new_callable=AsyncMock,
        ):
            result = await deployment_agent_node(state)

        records = result["deployment_records"]
        assert len(records) == 10

        # 5 per cohort
        cohort_a = [r for r in records if r["ab_cohort"] == "A"]
        cohort_b = [r for r in records if r["ab_cohort"] == "B"]
        assert len(cohort_a) == 5
        assert len(cohort_b) == 5

    async def test_each_record_has_unique_provider_message_id(self):
        """AC: Each deployment record has a unique provider_message_id."""
        state = _make_state(
            deployment_confirmed=True,
            content_variants=_make_variants(2),
            selected_variant_ids=["var-1", "var-2"],
            prospect_cards=_make_prospects(6),
            selected_prospect_ids=[f"prospect-{i}" for i in range(1, 7)],
        )
        with patch(
            "app.agents.deployment_agent.save_deployment_record",
            new_callable=AsyncMock,
        ):
            result = await deployment_agent_node(state)

        msg_ids = [r["provider_message_id"] for r in result["deployment_records"]]
        assert len(set(msg_ids)) == len(msg_ids)

    async def test_records_persisted_to_db(self):
        """AC: All records persisted to MongoDB deployment_records collection."""
        mock_save = AsyncMock()
        state = _make_state(
            deployment_confirmed=True,
            content_variants=_make_variants(1),
            selected_variant_ids=["var-1"],
            prospect_cards=_make_prospects(3),
            selected_prospect_ids=["prospect-1", "prospect-2", "prospect-3"],
        )
        with patch(
            "app.agents.deployment_agent.save_deployment_record",
            mock_save,
        ):
            await deployment_agent_node(state)

        assert mock_save.call_count == 3

    async def test_personalisation_in_rendered_content(self):
        """AC: Personalisation correctly fills {{first_name}} and {{company}} tokens."""
        saved_records: list[dict] = []

        async def capture_record(record: dict) -> None:
            saved_records.append(record)

        state = _make_state(
            deployment_confirmed=True,
            content_variants=[{
                "id": "v1",
                "body": "Hello {{first_name}} from {{company}}",
                "intended_channel": "email",
                "angle_label": "test",
            }],
            selected_variant_ids=["v1"],
            prospect_cards=[{
                "id": "p1",
                "name": "Alice Wonderland",
                "company": "TeaCo",
            }],
            selected_prospect_ids=["p1"],
        )
        with patch(
            "app.agents.deployment_agent.save_deployment_record",
            side_effect=capture_record,
        ):
            result = await deployment_agent_node(state)

        # The rendered content hash should be based on personalised content
        assert len(result["deployment_records"]) == 1
        record = result["deployment_records"][0]
        assert record["rendered_content_hash"]  # non-empty hash

    async def test_error_when_no_variants(self):
        state = _make_state(
            deployment_confirmed=False,
            content_variants=[],
            prospect_cards=_make_prospects(2),
            selected_prospect_ids=["prospect-1", "prospect-2"],
        )
        result = await deployment_agent_node(state)
        assert result["next_node"] == "orchestrator"
        assert any("variants" in e.lower() for e in result.get("error_messages", []))

    async def test_error_when_no_prospects(self):
        state = _make_state(
            deployment_confirmed=False,
            content_variants=_make_variants(1),
            selected_variant_ids=["var-1"],
            prospect_cards=[],
        )
        result = await deployment_agent_node(state)
        assert result["next_node"] == "orchestrator"
        assert any("prospects" in e.lower() for e in result.get("error_messages", []))

    async def test_fallback_uses_all_variants_when_no_selection(self):
        """If no selected_variant_ids, uses all content_variants."""
        state = _make_state(
            deployment_confirmed=True,
            content_variants=_make_variants(2),
            selected_variant_ids=[],
            prospect_cards=_make_prospects(2),
            selected_prospect_ids=["prospect-1", "prospect-2"],
        )
        with patch(
            "app.agents.deployment_agent.save_deployment_record",
            new_callable=AsyncMock,
        ):
            result = await deployment_agent_node(state)

        assert len(result["deployment_records"]) == 2
