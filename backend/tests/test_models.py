"""Unit tests for all data models — instantiation and JSON round-trip."""

from datetime import datetime, timezone

from app.models import (
    CampaignState,
    ContentVariant,
    DeploymentRecord,
    IntelligenceEntry,
    NormalizedFeedbackEvent,
    Prospect,
    ResearchFinding,
    ResearchPolicy,
    Segment,
    UIAction,
    UIFrame,
)


NOW = datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# CampaignState
# ---------------------------------------------------------------------------

def test_campaign_state_instantiation():
    state: CampaignState = {
        "session_id": "sess-001",
        "product_name": "Acme Widget",
        "product_description": "Best widget ever",
        "target_market": "SMB SaaS",
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
        "selected_segment_id": None,
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
    }
    assert state["session_id"] == "sess-001"
    assert state["session_complete"] is False
    assert state["cycle_number"] == 1


# ---------------------------------------------------------------------------
# ResearchFinding
# ---------------------------------------------------------------------------

def test_research_finding_instantiation():
    finding = ResearchFinding(
        id="rf-001",
        session_id="sess-001",
        cycle_number=1,
        signal_type="competitor",
        claim="Competitor X launched a new pricing tier",
        evidence="Blog post from 2026-03-15",
        source_url="https://example.com/blog",
        confidence=0.85,
        audience_language=["too expensive", "not worth it"],
        actionable_implication="Undercut on price messaging",
        created_at=NOW,
    )
    assert finding.confidence == 0.85
    assert finding.signal_type == "competitor"


def test_research_finding_json_round_trip():
    finding = ResearchFinding(
        id="rf-002",
        session_id="sess-001",
        cycle_number=1,
        signal_type="audience",
        claim="Users want faster onboarding",
        evidence="Reddit thread with 200 upvotes",
        source_url="https://reddit.com/r/saas/123",
        confidence=0.72,
        audience_language=["just let me start", "too many steps"],
        actionable_implication="Lead with speed-to-value",
        created_at=NOW,
    )
    data = finding.model_dump(mode="json")
    restored = ResearchFinding.model_validate(data)
    assert restored == finding


# ---------------------------------------------------------------------------
# ContentVariant
# ---------------------------------------------------------------------------

def test_content_variant_instantiation():
    variant = ContentVariant(
        id="cv-001",
        session_id="sess-001",
        cycle_number=1,
        source_finding_ids=["rf-001", "rf-002"],
        target_segment_id="seg-001",
        intended_channel="email",
        hypothesis="Leading with speed-to-value increases reply rate",
        success_metric="reply_rate > 5%",
        subject_line="Get started in 30 seconds",
        body="Hi {{name}}, ...",
        cta="Start free trial",
        created_at=NOW,
    )
    assert variant.source_finding_ids == ["rf-001", "rf-002"]


def test_content_variant_json_round_trip():
    variant = ContentVariant(
        id="cv-002",
        session_id="sess-001",
        cycle_number=1,
        source_finding_ids=["rf-001"],
        target_segment_id="seg-001",
        intended_channel="linkedin",
        hypothesis="Competitor-gap angle works for VP Sales",
        success_metric="acceptance_rate > 30%",
        subject_line=None,
        body="Hey {{name}}, noticed you're using X...",
        cta="See how we compare",
        created_at=NOW,
    )
    data = variant.model_dump(mode="json")
    restored = ContentVariant.model_validate(data)
    assert restored == variant


# ---------------------------------------------------------------------------
# DeploymentRecord
# ---------------------------------------------------------------------------

def test_deployment_record_instantiation():
    record = DeploymentRecord(
        id="dr-001",
        session_id="sess-001",
        variant_id="cv-001",
        segment_id="seg-001",
        prospect_id="p-001",
        channel="email",
        provider="resend",
        provider_message_id="msg_abc123",
        ab_cohort="A",
        rendered_content_hash="sha256:abcdef",
        sent_at=NOW,
    )
    assert record.provider == "resend"
    assert record.ab_cohort == "A"


def test_deployment_record_json_round_trip():
    record = DeploymentRecord(
        id="dr-002",
        session_id="sess-001",
        variant_id="cv-002",
        segment_id="seg-001",
        prospect_id="p-002",
        channel="linkedin",
        provider="unipile",
        provider_message_id=None,
        ab_cohort="B",
        rendered_content_hash="sha256:fedcba",
        sent_at=NOW,
    )
    data = record.model_dump(mode="json")
    restored = DeploymentRecord.model_validate(data)
    assert restored == record


# ---------------------------------------------------------------------------
# NormalizedFeedbackEvent
# ---------------------------------------------------------------------------

def test_normalized_feedback_event_instantiation():
    event = NormalizedFeedbackEvent(
        provider="resend",
        provider_event_id="evt_001",
        provider_message_id="msg_abc123",
        deployment_record_id="dr-001",
        session_id="sess-001",
        variant_id="cv-001",
        prospect_id="p-001",
        channel="email",
        event_type="open",
        event_value=None,
        qualitative_signal=None,
        received_at=NOW,
        dedupe_key="resend:evt_001",
    )
    assert event.event_type == "open"


def test_normalized_feedback_event_json_round_trip():
    event = NormalizedFeedbackEvent(
        provider="resend",
        provider_event_id=None,
        provider_message_id=None,
        deployment_record_id=None,
        session_id="sess-001",
        variant_id=None,
        prospect_id=None,
        channel="email",
        event_type="manual_report",
        event_value=0.15,
        qualitative_signal="positive reply, asked for demo",
        received_at=NOW,
        dedupe_key="manual:sess-001:1712300000",
    )
    data = event.model_dump(mode="json")
    restored = NormalizedFeedbackEvent.model_validate(data)
    assert restored == event


# ---------------------------------------------------------------------------
# IntelligenceEntry
# ---------------------------------------------------------------------------

def test_intelligence_entry_instantiation():
    entry = IntelligenceEntry(
        id="ie-001",
        session_id="sess-001",
        cycle_number=1,
        learning_delta="Speed-to-value angle outperformed competitor-gap by 2x on reply rate",
        confidence_updates=[
            {"finding_id": "rf-001", "old": 0.85, "new": 0.6},
            {"finding_id": "rf-002", "old": 0.72, "new": 0.88},
        ],
        winning_variant_id="cv-001",
        created_at=NOW,
    )
    assert len(entry.confidence_updates) == 2


def test_intelligence_entry_json_round_trip():
    entry = IntelligenceEntry(
        id="ie-002",
        session_id="sess-001",
        cycle_number=2,
        learning_delta="LinkedIn DMs had higher acceptance than email for VP Sales",
        confidence_updates=[],
        winning_variant_id=None,
        created_at=NOW,
    )
    data = entry.model_dump(mode="json")
    restored = IntelligenceEntry.model_validate(data)
    assert restored == entry


# ---------------------------------------------------------------------------
# Prospect
# ---------------------------------------------------------------------------

def test_prospect_instantiation():
    prospect = Prospect(
        id="p-001",
        name="Jane Smith",
        email="jane@example.com",
        linkedin_url="https://linkedin.com/in/janesmith",
        title="VP Sales",
        company="Acme Corp",
        fit_score=0.9,
        urgency_score=0.75,
        angle_recommendation="speed-to-value",
        channel_recommendation="email",
        personalization_fields={"recent_post": "Scaling outbound in 2026"},
    )
    assert prospect.fit_score == 0.9


def test_prospect_json_round_trip():
    prospect = Prospect(
        id="p-002",
        name="John Doe",
        email=None,
        linkedin_url="https://linkedin.com/in/johndoe",
        title="Founder",
        company="Startup Inc",
        fit_score=0.65,
        urgency_score=0.5,
        angle_recommendation="competitor-gap",
        channel_recommendation="linkedin",
        personalization_fields={},
    )
    data = prospect.model_dump(mode="json")
    restored = Prospect.model_validate(data)
    assert restored == prospect


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------

def test_segment_instantiation():
    segment = Segment(
        id="seg-001",
        session_id="sess-001",
        label="VP Sales at Series B SaaS",
        description="Sales leaders at mid-stage SaaS companies replacing SDR headcount",
        criteria={"title": "VP Sales", "company_stage": "Series B", "industry": "SaaS"},
        prospect_count=42,
    )
    assert segment.prospect_count == 42


def test_segment_json_round_trip():
    segment = Segment(
        id="seg-002",
        session_id="sess-001",
        label="RevOps in outbound teams",
        description="RevOps leaders running high-volume outbound motions",
        criteria={"title": "RevOps", "motion": "outbound"},
        prospect_count=18,
    )
    data = segment.model_dump(mode="json")
    restored = Segment.model_validate(data)
    assert restored == segment


# ---------------------------------------------------------------------------
# UIAction & UIFrame
# ---------------------------------------------------------------------------

def test_ui_action_instantiation():
    action = UIAction(
        id="act-001",
        label="Select top 10",
        action_type="select_prospects",
        payload={"count": 10},
    )
    assert action.action_type == "select_prospects"


def test_ui_frame_instantiation():
    frame = UIFrame(
        type="ui_component",
        component="ProspectPicker",
        instance_id="pp-001",
        props={"prospects": [], "segment": "VP Sales"},
        actions=[
            UIAction(
                id="act-001",
                label="Select all",
                action_type="select_all",
                payload={},
            )
        ],
    )
    assert frame.component == "ProspectPicker"
    assert len(frame.actions) == 1


def test_ui_frame_json_round_trip():
    frame = UIFrame(
        type="progress",
        component=None,
        instance_id="prog-001",
        props={"percent": 45, "message": "Researching competitors..."},
        actions=[],
    )
    data = frame.model_dump(mode="json")
    restored = UIFrame.model_validate(data)
    assert restored == frame


# ---------------------------------------------------------------------------
# ResearchPolicy
# ---------------------------------------------------------------------------

def test_research_policy_instantiation():
    policy: ResearchPolicy = {
        "enabled_threads": ["competitor", "audience", "channel", "market"],
        "max_search_results_per_query": 10,
        "max_pages_to_extract": 30,
        "max_branch_depth": 2,
        "max_subinvestigations_per_thread": 2,
        "recency_days": 90,
        "allowed_tool_groups": ["search_web", "extract_page", "search_news"],
        "evidence_threshold": 0.6,
    }
    assert policy["max_branch_depth"] == 2
    assert len(policy["enabled_threads"]) == 4
