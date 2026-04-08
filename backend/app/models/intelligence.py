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
