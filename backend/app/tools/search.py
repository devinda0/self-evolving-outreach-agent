"""External research tool wrappers — Tavily search, page extraction, news, community.

All functions are async, cache results via MongoDB, and handle failures gracefully.
"""

import hashlib
import logging

import httpx

from app.core.config import settings
from app.db.crud import cache_tool_result, get_cached_tool_result

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

_TIMEOUT = 30  # seconds


def _cache_key(*parts: str) -> str:
    """Build a deterministic cache key from parts."""
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


async def search_web(
    query: str,
    max_results: int = 5,
    recency_days: int | None = 30,
    include_domains: list[str] | None = None,
) -> list[dict]:
    """Search the web using Tavily. Returns list of {title, url, content, score}.

    Pass recency_days=None to search without any date restriction (needed for
    person/profile lookups where content age is irrelevant).
    """
    cache_key = _cache_key("search", query, str(max_results), str(recency_days), str(include_domains))
    cached = await get_cached_tool_result(cache_key)
    if cached is not None:
        return cached

    payload: dict = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
    }
    if recency_days is not None:
        payload["days"] = recency_days
    if include_domains:
        payload["include_domains"] = include_domains

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TAVILY_SEARCH_URL,
                json=payload,
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.error("search_web failed for query=%r: %s", query, exc)
        return []

    results = response.json().get("results", [])
    await cache_tool_result(cache_key, results, ttl_seconds=3600)
    return results


async def extract_page(url: str) -> str:
    """Extract main text content from a URL using Tavily extract."""
    cache_key = _cache_key("extract", url)
    cached = await get_cached_tool_result(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TAVILY_EXTRACT_URL,
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "urls": [url],
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.error("extract_page failed for url=%r: %s", url, exc)
        return ""

    text = response.json().get("results", [{}])[0].get("raw_content", "")
    await cache_tool_result(cache_key, text, ttl_seconds=86400)
    return text


async def search_news(query: str, days: int = 7) -> list[dict]:
    """Search recent news articles via Tavily."""
    return await search_web(query + " news", max_results=5, recency_days=days)


async def search_community(query: str) -> list[dict]:
    """Search community content (Reddit, HN, forums) for audience language."""
    community_query = f"site:reddit.com OR site:news.ycombinator.com {query}"
    return await search_web(community_query, max_results=5)
