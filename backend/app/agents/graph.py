"""LangGraph graph topology — full state machine with stub agent nodes.

This module wires all nodes, conditional edges, and the fan-out/fan-in research
pattern. Each node is a stub that logs invocation and returns a minimal state update.
Real agent logic will replace these stubs in later issues.
"""

import logging

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.agents.checkpointer import MongoDBSaver
from app.agents.content_agent import content_agent_node
from app.agents.deployment_agent import deployment_agent_node
from app.agents.orchestrator import clarify_node, orchestrator_node
from app.agents.research import (
    research_dispatcher_node,
    research_synthesizer_node,
    research_thread_node,
)
from app.agents.segment_agent import segment_agent_node
from app.db.client import get_db
from app.models.campaign_state import CampaignState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def route_from_orchestrator(state: CampaignState) -> str:
    """Read next_node from state and return the routing key."""
    session_id = state.get("session_id", "unknown")

    if state.get("session_complete"):
        logger.info(
            "route_from_orchestrator → END (session_complete=True) | session=%s next_node=%s",
            session_id,
            state.get("next_node"),
        )
        return END

    next_node = state.get("next_node")
    if next_node in (
        "research",
        "segment",
        "generate",
        "deploy",
        "feedback",
        "clarify",
    ):
        logger.info(
            "route_from_orchestrator → %s | session=%s intent=%s",
            next_node,
            session_id,
            state.get("current_intent"),
        )
        return next_node

    logger.warning(
        "route_from_orchestrator: unrecognised next_node '%s', falling back to clarify | session=%s",
        next_node,
        session_id,
    )
    return "clarify"


def research_fan_out(state: CampaignState) -> list[Send]:
    """Dispatch parallel research threads based on active_thread_types."""
    thread_types = state.get("active_thread_types", [])
    if not thread_types:
        thread_types = ["competitor", "audience", "channel", "market"]
    return [
        Send("research_thread", {**state, "thread_type": t})
        for t in thread_types
    ]


# ---------------------------------------------------------------------------
# Stub node implementations (will be replaced by real agents in later issues)
# ---------------------------------------------------------------------------


async def feedback_agent_node(state: CampaignState) -> dict:
    """STUB: process engagement feedback."""
    logger.info("feedback_agent_node called | session=%s", state.get("session_id"))
    return {
        "engagement_results": [{"variant_id": "var-stub-1", "open_rate": 0.0}],
    }


# Note: orchestrator_node and clarify_node are imported from app.agents.orchestrator
# Note: deployment_agent_node is imported from app.agents.deployment_agent


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(checkpointer: MongoDBSaver | None = None) -> CompiledStateGraph:
    """Build and compile the full LangGraph state machine.

    Args:
        checkpointer: Optional MongoDBSaver instance. When None the graph is
            compiled without persistence (useful for tests).

    Returns:
        A compiled LangGraph ``CompiledStateGraph``.
    """
    builder = StateGraph(CampaignState)

    # -- Add nodes --
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("research_dispatcher", research_dispatcher_node)
    builder.add_node("research_thread", research_thread_node)
    builder.add_node("research_synthesizer", research_synthesizer_node)
    builder.add_node("segment_agent", segment_agent_node)
    builder.add_node("content_agent", content_agent_node)
    builder.add_node("deployment_agent", deployment_agent_node)
    builder.add_node("feedback_agent", feedback_agent_node)
    builder.add_node("clarify", clarify_node)

    # -- Entry point --
    builder.set_entry_point("orchestrator")

    # -- Conditional routing from orchestrator --
    builder.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "research": "research_dispatcher",
            "segment": "segment_agent",
            "generate": "content_agent",
            "deploy": "deployment_agent",
            "feedback": "feedback_agent",
            "clarify": "clarify",
            END: END,
        },
    )

    # -- Research fan-out (dispatcher → parallel threads) --
    builder.add_conditional_edges("research_dispatcher", research_fan_out)

    # -- Research fan-in → synthesizer → END (fresh run triggered by next user message) --
    builder.add_edge("research_thread", "research_synthesizer")
    builder.add_edge("research_synthesizer", END)

    # -- All specialist agents route to END; each user turn starts a fresh run from orchestrator --
    builder.add_edge("segment_agent", END)
    builder.add_edge("content_agent", END)
    builder.add_edge("deployment_agent", END)
    builder.add_edge("feedback_agent", END)
    builder.add_edge("clarify", END)

    return builder.compile(checkpointer=checkpointer)


def get_graph():
    """Build a graph with the default MongoDB checkpointer.

    Requires the database to be connected first (``connect_db()``).
    """
    db = get_db()
    checkpointer = MongoDBSaver(db)
    return build_graph(checkpointer=checkpointer)
