"""CampaignState TypedDict — the shared state that travels through the entire LangGraph graph."""

import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class CampaignState(TypedDict):
    # Session identity
    session_id: str
    product_name: str
    product_description: str
    target_market: str

    # Conversation
    messages: Annotated[list, add_messages]
    conversation_summary: Optional[str]
    decision_log: list[dict]
    intent_history: list[str]

    # Orchestrator routing
    current_intent: Optional[str]
    previous_intent: Optional[str]
    next_node: Optional[str]
    clarification_question: Optional[str]
    clarification_options: list[str]
    session_complete: bool

    # Cycle tracking
    cycle_number: int
    prior_cycle_summary: Optional[str]
    active_stage_summary: Optional[str]

    # Research stage
    research_query: Optional[str]
    active_thread_types: list[str]
    thread_type: Optional[str]  # Injected by research fan-out Send
    research_findings: Annotated[list, operator.add]
    briefing_summary: Optional[str]
    research_gaps: list[str]
    failed_threads: list[str]

    # Segment / prospect stage
    selected_segment_id: Optional[str]
    segment_candidates: list[dict]
    selected_prospect_ids: list[str]
    prospect_pool_ref: Optional[str]
    prospect_cards: list[dict]

    # Content stage
    content_request: Optional[str]
    content_variants: list[dict]
    selected_variant_ids: list[str]
    visual_artifacts: list[dict]

    # Deployment stage
    selected_channels: list[str]
    ab_split_plan: Optional[dict]
    deployment_confirmed: bool
    deployment_records: list[dict]

    # Feedback stage
    normalized_feedback_events: list[dict]
    engagement_results: list[dict]
    winning_variant_id: Optional[str]

    # Memory and error tracking
    memory_refs: dict
    error_messages: list[str]
