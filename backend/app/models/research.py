"""Research policy — runtime-configurable constraints for the Research subgraph."""

from typing import TypedDict


class ResearchPolicy(TypedDict):
    enabled_threads: list[str]
    max_search_results_per_query: int
    max_pages_to_extract: int
    max_branch_depth: int
    max_subinvestigations_per_thread: int
    recency_days: int
    allowed_tool_groups: list[str]
    evidence_threshold: float
