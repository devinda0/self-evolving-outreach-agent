"""Intelligence domain models — research findings, content variants, deployment, feedback, learning."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ResearchFinding(BaseModel):
    id: str
    session_id: str
    cycle_number: int
    signal_type: Literal["competitor", "audience", "channel", "market", "adjacent", "temporal"]
    claim: str
    evidence: str
    source_url: str
    confidence: float = Field(ge=0.0, le=1.0)
    audience_language: list[str]
    actionable_implication: str
    created_at: datetime


class ContentVariant(BaseModel):
    id: str
    session_id: str
    cycle_number: int
    source_finding_ids: list[str]
    target_segment_id: str
    intended_channel: str
    hypothesis: str
    success_metric: str
    subject_line: Optional[str] = None
    body: str
    cta: str
    angle_label: Optional[str] = None
    personalized_for: Optional[str] = None  # prospect ID this variant was tailored for
    created_at: datetime


class DeploymentRecord(BaseModel):
    id: str
    session_id: str
    variant_id: str
    segment_id: str
    prospect_id: str
    channel: str
    provider: str
    provider_message_id: Optional[str] = None
    ab_cohort: str
    rendered_content_hash: str
    sent_at: datetime
    status: Literal["sent", "failed"] = "sent"
    error_detail: Optional[str] = None


class NormalizedFeedbackEvent(BaseModel):
    provider: str
    provider_event_id: Optional[str] = None
    provider_message_id: Optional[str] = None
    deployment_record_id: Optional[str] = None
    session_id: str
    variant_id: Optional[str] = None
    prospect_id: Optional[str] = None
    channel: str
    event_type: Literal["sent", "open", "click", "reply", "bounce", "manual_report"]
    event_value: Optional[float] = None
    qualitative_signal: Optional[str] = None
    received_at: datetime
    dedupe_key: str


class IntelligenceEntry(BaseModel):
    id: str
    session_id: str
    cycle_number: int
    learning_delta: str
    confidence_updates: list[dict]
    winning_variant_id: Optional[str] = None
    created_at: datetime


class ApproachOutcome(BaseModel):
    """Tracks whether a specific outreach approach worked or failed."""

    approach: str  # e.g. "ROI-focused email with casual tone"
    channel: str
    variant_id: Optional[str] = None
    engagement_rate: float = 0.0  # reply_rate or best available metric
    sample_size: int = 0
    verdict: Literal["effective", "ineffective", "insufficient_data"]


class CycleRecord(BaseModel):
    """Persistent snapshot of a completed campaign cycle.

    Captures all key outcomes so that future cycles can learn from past
    approaches without re-reading raw data.
    """

    id: str
    session_id: str
    cycle_number: int

    # What was attempted
    research_summary: str = ""
    segments_used: list[str] = Field(default_factory=list)
    content_strategies: list[str] = Field(default_factory=list)
    channels_used: list[str] = Field(default_factory=list)
    prospects_contacted: int = 0

    # What happened
    total_sends: int = 0
    total_opens: int = 0
    total_replies: int = 0
    total_bounces: int = 0
    winning_variant_id: Optional[str] = None
    winning_strategy: Optional[str] = None

    # Approach-level outcomes for self-evolution
    approach_outcomes: list[ApproachOutcome] = Field(default_factory=list)

    # Accumulated learnings
    learning_delta: str = ""
    approaches_to_avoid: list[str] = Field(default_factory=list)
    approaches_to_amplify: list[str] = Field(default_factory=list)

    # Interaction tracking
    interaction_count: int = 0
    key_decisions: list[str] = Field(default_factory=list)

    completed_at: datetime
