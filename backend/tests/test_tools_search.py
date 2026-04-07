"""Unit tests for research tools — search_web, extract_page, search_news, search_community.

All Tavily HTTP calls are mocked via monkeypatching httpx.AsyncClient.
MongoDB cache is mocked via monkeypatching the crud helpers.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.tools.search import (
    extract_page,
    search_community,
    search_news,
    search_web,
)
from app.tools.research_policy import DEFAULT_RESEARCH_POLICY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_SEARCH_RESULTS = [
    {"title": "Result 1", "url": "https://a.com", "content": "Content 1", "score": 0.9},
    {"title": "Result 2", "url": "https://b.com", "content": "Content 2", "score": 0.8},
    {"title": "Result 3", "url": "https://c.com", "content": "Content 3", "score": 0.7},
]

FAKE_EXTRACT_RESPONSE = {
    "results": [{"raw_content": "Extracted page text here."}],
}


def _mock_post_factory(json_body: dict, status_code: int = 200):
    """Return an async function that mimics httpx.AsyncClient.post."""

    async def _mock_post(*args, **kwargs):
        resp = httpx.Response(status_code, json=json_body, request=httpx.Request("POST", args[0]))
        return resp

    return _mock_post


# ---------------------------------------------------------------------------
# search_web
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_web_returns_results():
    mock_post = _mock_post_factory({"results": FAKE_SEARCH_RESULTS})

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("app.tools.search.cache_tool_result", new_callable=AsyncMock) as mock_cache,
        patch("httpx.AsyncClient.post", side_effect=mock_post),
    ):
        results = await search_web("AI sales tools")

    assert len(results) == 3
    assert results[0]["url"] == "https://a.com"
    mock_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_web_returns_cached():
    with patch(
        "app.tools.search.get_cached_tool_result",
        new_callable=AsyncMock,
        return_value=FAKE_SEARCH_RESULTS,
    ):
        results = await search_web("AI sales tools")

    assert len(results) == 3
    assert results[0]["title"] == "Result 1"


@pytest.mark.asyncio
async def test_search_web_timeout_returns_empty():
    async def _timeout_post(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient.post", side_effect=_timeout_post),
    ):
        results = await search_web("AI sales tools")

    assert results == []


@pytest.mark.asyncio
async def test_search_web_http_error_returns_empty():
    mock_post = _mock_post_factory({"error": "bad request"}, status_code=400)

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient.post", side_effect=mock_post),
    ):
        results = await search_web("AI sales tools")

    assert results == []


@pytest.mark.asyncio
async def test_search_web_connect_error_returns_empty():
    async def _connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient.post", side_effect=_connect_error),
    ):
        results = await search_web("AI sales tools")

    assert results == []


# ---------------------------------------------------------------------------
# extract_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_page_returns_text():
    mock_post = _mock_post_factory(FAKE_EXTRACT_RESPONSE)

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("app.tools.search.cache_tool_result", new_callable=AsyncMock) as mock_cache,
        patch("httpx.AsyncClient.post", side_effect=mock_post),
    ):
        text = await extract_page("https://example.com")

    assert text == "Extracted page text here."
    mock_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_page_returns_cached():
    with patch(
        "app.tools.search.get_cached_tool_result",
        new_callable=AsyncMock,
        return_value="cached text",
    ):
        text = await extract_page("https://example.com")

    assert text == "cached text"


@pytest.mark.asyncio
async def test_extract_page_timeout_returns_empty():
    async def _timeout(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient.post", side_effect=_timeout),
    ):
        text = await extract_page("https://example.com")

    assert text == ""


# ---------------------------------------------------------------------------
# search_news delegates to search_web
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_news_appends_news_keyword():
    mock_post = _mock_post_factory({"results": FAKE_SEARCH_RESULTS})

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("app.tools.search.cache_tool_result", new_callable=AsyncMock),
        patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_http,
    ):
        results = await search_news("AI funding")

    assert len(results) == 3
    # Verify the query sent to Tavily includes " news"
    call_kwargs = mock_http.call_args
    sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert "news" in sent_json["query"]


# ---------------------------------------------------------------------------
# search_community delegates to search_web
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_community_uses_site_filter():
    mock_post = _mock_post_factory({"results": FAKE_SEARCH_RESULTS})

    with (
        patch("app.tools.search.get_cached_tool_result", new_callable=AsyncMock, return_value=None),
        patch("app.tools.search.cache_tool_result", new_callable=AsyncMock),
        patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_http,
    ):
        results = await search_community("devtools pain points")

    assert len(results) == 3
    call_kwargs = mock_http.call_args
    sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert "site:reddit.com" in sent_json["query"]


# ---------------------------------------------------------------------------
# DEFAULT_RESEARCH_POLICY
# ---------------------------------------------------------------------------

def test_default_research_policy_has_required_keys():
    assert set(DEFAULT_RESEARCH_POLICY.keys()) == {
        "enabled_threads",
        "max_search_results_per_query",
        "max_pages_to_extract",
        "max_branch_depth",
        "max_subinvestigations_per_thread",
        "recency_days",
        "allowed_tool_groups",
        "evidence_threshold",
    }


def test_default_research_policy_values():
    assert DEFAULT_RESEARCH_POLICY["max_branch_depth"] == 2
    assert DEFAULT_RESEARCH_POLICY["evidence_threshold"] == 0.6
    assert "competitor" in DEFAULT_RESEARCH_POLICY["enabled_threads"]
