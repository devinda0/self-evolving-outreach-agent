"""Prospect and segment models."""

from typing import Optional

from pydantic import BaseModel, Field


class Prospect(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    title: str
    company: str
    fit_score: float = Field(ge=0.0, le=1.0)
    urgency_score: float = Field(ge=0.0, le=1.0)
    angle_recommendation: str
    channel_recommendation: str
    personalization_fields: dict


class Segment(BaseModel):
    id: str
    session_id: str
    label: str
    description: str
    criteria: dict
    prospect_count: int = Field(ge=0)
