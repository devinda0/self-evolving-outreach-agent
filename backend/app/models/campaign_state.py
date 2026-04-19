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
    user_directive: Optional[str]  # What the user specifically wants from the next agent
    clarification_question: Optional[str]
    clarification_options: list[str]
    session_complete: bool

    # Cycle tracking
    cycle_number: int
    prior_cycle_summary: Optional[str]
    active_stage_summary: Optional[str]
    cycle_records: list[dict]  # Persistent snapshots of completed cycles
    accumulated_learnings: Optional[str]  # Evolved knowledge from all past cycles

    # Research stage
    research_query: Optional[str]
    active_thread_types: list[str]
    thread_type: Optional[str]  # Injected by research fan-out Send
    research_policy: dict  # Research policy controlling thread behavior
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

    # Content agent sub-phases
    content_phase: Optional[str]  # "clarify" | "generate" | "refine" | None
    content_clarifications: list[dict]  # Q&A pairs resolved during clarification
    content_pending_questions: list[dict]  # Questions waiting for user answers
    content_generation_context: Optional[dict]  # Resolved context snapshot for generation
    content_refinement_history: list[dict]  # History of refinement prompts and diffs

    # Deployment stage
    selected_channels: list[str]
    ab_split_plan: Optional[dict]
    deployment_confirmed: bool
    deployment_records: list[dict]

    # Feedback stage
    normalized_feedback_events: list[dict]
    engagement_results: list[dict]
    winning_variant_id: Optional[str]

    # LinkedIn feed post stage
    linkedin_post_phase: Optional[str]    # None | "composed" | "confirming" | "published"
    linkedin_post_html: Optional[str]     # current flyer HTML being worked on
    linkedin_post_caption: Optional[str]  # current post caption being worked on
    linkedin_post_image_data_url: Optional[str]  # transient PNG data URL captured for publish
    linkedin_post_confirmed: bool         # publish gate (mirrors deployment_confirmed pattern)
    linkedin_posts: Annotated[list, operator.add]  # published post records (accumulates)

    # Memory and error tracking
    memory_refs: dict
    error_messages: list[str]

    # UI frame queue — agents append dicts here; the WS handler drains and sends them
    pending_ui_frames: Annotated[list, operator.add]

    # Internal summarisation tracking — index into messages list covered by last summary
    _last_summary_message_count: int
