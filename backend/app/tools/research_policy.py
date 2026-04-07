"""Default research policy configuration."""

from app.models.research import ResearchPolicy

DEFAULT_RESEARCH_POLICY: ResearchPolicy = {
    "enabled_threads": ["competitor", "audience", "channel", "market"],
    "max_search_results_per_query": 5,
    "max_pages_to_extract": 5,
    "max_branch_depth": 2,
    "max_subinvestigations_per_thread": 2,
    "recency_days": 30,
    "allowed_tool_groups": [
        "search_discovery",
        "deep_extraction",
        "news_events",
        "community_language",
    ],
    "evidence_threshold": 0.6,
}
