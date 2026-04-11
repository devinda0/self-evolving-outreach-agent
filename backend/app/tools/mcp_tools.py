"""Shared MCP tool dispatch helpers.

All agents that need external capabilities (search, extract, email/messaging)
should call these helpers rather than using hardcoded tool clients directly.

Each helper follows the same pattern:
  1. Scan the MCPManager for a running server that has a matching tool.
  2. Call that tool with best-effort argument name inference.
  3. Normalise the result to the shape the rest of the system expects.
  4. On failure or absence of an MCP tool, fall back to the built-in client.
"""

import json
import logging
from typing import Any

from app.mcp.manager import get_mcp_manager
from app.mcp.models import MCPServerStatus, MCPTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Capability keyword sets
# ---------------------------------------------------------------------------

_SEARCH_KEYWORDS = frozenset({"search", "web_search", "serp", "query", "find"})
_EXTRACT_KEYWORDS = frozenset({"scrape", "extract", "fetch", "browse", "navigate", "crawl"})
_EMAIL_KEYWORDS = frozenset({"email", "send_email", "mail", "smtp", "outreach", "send_message"})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_mcp_tool(capability: str) -> tuple[str, str, MCPTool] | None:
    """Return ``(server_id, tool_name, tool)`` for the first RUNNING MCP tool
    whose name matches *capability*.

    capability: ``"search"`` | ``"extract"`` | ``"email"``
    """
    patterns: frozenset[str]
    if capability == "search":
        patterns = _SEARCH_KEYWORDS
    elif capability == "extract":
        patterns = _EXTRACT_KEYWORDS
    else:
        patterns = _EMAIL_KEYWORDS

    manager = get_mcp_manager()
    for state in manager.list_servers():
        if state.status != MCPServerStatus.RUNNING:
            continue
        for tool in state.tools:
            if any(kw in tool.name.lower() for kw in patterns):
                return state.server_id, tool.name, tool
    return None


def _infer_param(tool: MCPTool, preferred: tuple[str, ...]) -> str:
    """Return the best matching parameter name from *preferred*, or fall back
    to the first required parameter, then the first parameter overall."""
    param_names = {p.name for p in tool.parameters}
    for name in preferred:
        if name in param_names:
            return name
    for p in tool.parameters:
        if p.required:
            return p.name
    return tool.parameters[0].name if tool.parameters else preferred[0]


def _normalize_search_results(raw: Any) -> list[dict]:
    """Normalise heterogeneous MCP search output to ``[{title, url, content, score}]``."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return [{"title": "", "url": "", "content": raw, "score": 0.5}]
    if not isinstance(raw, list):
        return []
    results: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": item.get("title") or item.get("name") or "",
            "url": item.get("url") or item.get("link") or item.get("href") or "",
            "content": (
                item.get("description")
                or item.get("snippet")
                or item.get("content")
                or item.get("text")
                or ""
            ),
            "score": float(item.get("score") or item.get("relevance") or 0.5),
        })
    return results


# ---------------------------------------------------------------------------
# Public dispatch helpers
# ---------------------------------------------------------------------------


async def mcp_search(
    query: str,
    max_results: int = 5,
    recency_days: int = 30,
) -> list[dict] | None:
    """Try to run a web search via an MCP tool.

    Returns a normalised result list on success, or ``None`` if no MCP search
    tool is available or the call fails (caller should fall back to Tavily).
    """
    hit = _find_mcp_tool("search")
    if not hit:
        return None

    server_id, tool_name, tool = hit
    q_param = _infer_param(tool, ("query", "q", "search_query", "text", "search", "term", "keyword"))
    args: dict[str, Any] = {q_param: query}

    # Pass result count if the tool supports it
    for p in tool.parameters:
        if p.name in {"count", "max_results", "num_results", "limit", "results"}:
            args[p.name] = max_results
            break

    try:
        raw = await get_mcp_manager().call_tool(server_id, tool_name, args)
        results = _normalize_search_results(raw)
        if results:
            logger.info("mcp_search via %s/%s → %d results", server_id[:8], tool_name, len(results))
            return results
    except Exception as exc:
        logger.warning("mcp_search tool %s failed: %s", tool_name, exc)

    return None


async def mcp_extract(url: str) -> str | None:
    """Try to extract page content via an MCP tool.

    Returns the extracted text on success, or ``None`` if no MCP extract tool
    is available or the call fails (caller should fall back to Tavily).
    """
    hit = _find_mcp_tool("extract")
    if not hit:
        return None

    server_id, tool_name, tool = hit
    u_param = _infer_param(tool, ("url", "uri", "link", "href", "page_url"))

    try:
        raw = await get_mcp_manager().call_tool(server_id, tool_name, {u_param: url})
        if isinstance(raw, str) and raw.strip():
            logger.debug("mcp_extract via %s/%s — %d chars", server_id[:8], tool_name, len(raw))
            return raw
        if isinstance(raw, list) and raw:
            return str(raw[0])
    except Exception as exc:
        logger.warning("mcp_extract tool %s failed: %s", tool_name, exc)

    return None


async def mcp_send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    tags: dict[str, str] | None = None,
    session_id: str = "",
) -> str | None:
    """Try to send an email via an MCP tool.

    Returns the provider message ID string on success, or ``None`` if no MCP
    email tool is available or the call fails (caller should fall back to Resend).
    """
    hit = _find_mcp_tool("email")
    if not hit:
        return None

    server_id, tool_name, tool = hit
    param_names = {p.name for p in tool.parameters}

    # Build best-effort args from the tool's schema
    args: dict[str, Any] = {}

    to_param = _infer_param(tool, ("to", "to_email", "recipient", "email", "address"))
    args[to_param] = to_email

    if "to_name" in param_names or "name" in param_names:
        args["to_name" if "to_name" in param_names else "name"] = to_name

    subject_param = _infer_param(tool, ("subject", "subject_line", "title"))
    args[subject_param] = subject

    body_param = _infer_param(tool, ("html_body", "body", "html", "content", "message"))
    args[body_param] = html_body

    if tags:
        for tag_key in ("tags", "metadata", "extra"):
            if tag_key in param_names:
                args[tag_key] = tags
                break

    try:
        raw = await get_mcp_manager().call_tool(server_id, tool_name, args)
        # Normalise the response to a message ID string
        if isinstance(raw, str):
            msg_id = raw.strip() or f"mcp_{tool_name}_{session_id}"
        elif isinstance(raw, dict):
            msg_id = (
                raw.get("id")
                or raw.get("message_id")
                or raw.get("messageId")
                or f"mcp_{tool_name}_{session_id}"
            )
        else:
            msg_id = f"mcp_{tool_name}_{session_id}"
        logger.info("mcp_send_email via %s/%s → id=%s", server_id[:8], tool_name, msg_id)
        return str(msg_id)
    except Exception as exc:
        logger.warning("mcp_send_email tool %s failed: %s", tool_name, exc)

    return None


# ---------------------------------------------------------------------------
# High-level convenience wrappers with automatic fallback
# ---------------------------------------------------------------------------


async def do_search(
    query: str,
    max_results: int = 5,
    recency_days: int = 30,
) -> list[dict]:
    """Search the web — MCP tool first, Tavily fallback."""
    result = await mcp_search(query, max_results=max_results, recency_days=recency_days)
    if result is not None:
        return result
    from app.tools.search import search_web
    return await search_web(query, max_results=max_results, recency_days=recency_days)


async def do_extract(url: str) -> str:
    """Extract page content — MCP tool first, Tavily fallback."""
    result = await mcp_extract(url)
    if result is not None:
        return result
    from app.tools.search import extract_page
    return await extract_page(url)


async def do_send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    tags: dict[str, str] | None = None,
    session_id: str = "",
) -> str:
    """Send an email — MCP tool first, Resend fallback.

    Returns the provider message ID.
    """
    result = await mcp_send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        tags=tags,
        session_id=session_id,
    )
    if result is not None:
        return result
    from app.tools.resend_client import send_email
    resp = await send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        tags=tags or {},
        session_id=session_id,
    )
    return resp["id"]
