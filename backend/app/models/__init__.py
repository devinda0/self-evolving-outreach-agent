"""Models package — all data contracts for the Signal-to-Action system."""

from app.models.campaign_state import CampaignState
from app.models.intelligence import (
    ContentVariant,
    DeploymentRecord,
    IntelligenceEntry,
    NormalizedFeedbackEvent,
    ResearchFinding,
)
from app.models.prospect import Prospect, Segment
from app.models.research import ResearchPolicy
from app.models.ui_frames import UIAction, UIFrame

__all__ = [
    "CampaignState",
    "ContentVariant",
    "DeploymentRecord",
    "IntelligenceEntry",
    "NormalizedFeedbackEvent",
    "Prospect",
    "ResearchFinding",
    "ResearchPolicy",
    "Segment",
    "UIAction",
    "UIFrame",
]
