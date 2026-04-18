"""MCP configuration agent — handles adding/removing/managing MCP servers via chat.

When users ask to configure an MCP server (e.g. "configure bright data mcp server
https://mcp.brightdata.com/mcp?token=..."), this agent:
1. Parses the request to extract server details (URL, tokens, type)
2. Creates the MCPServerConfig
3. Persists and starts it via MCPManager
4. Reports back with results (tools discovered, status)
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.llm import get_llm
from app.db.crud import delete_mcp_server, save_mcp_server
from app.mcp.manager import get_mcp_manager
from app.mcp.models import MCPServerConfig, MCPServerStatus, MCPTransport
from app.mcp.registry import TEMPLATES
from app.memory.manager import memory_manager
from app.models.campaign_state import CampaignState
from app.models.ui_frames import UIFrame

logger = logging.getLogger(__name__)

# Pattern to match URLs in user messages
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

# Known MCP server providers and their detection patterns
_KNOWN_PROVIDERS: dict[str, dict[str, Any]] = {
    "brightdata": {
        "url_patterns": ["brightdata.com", "bright-data"],
        "name": "Bright Data",
        "description": "Web scraping, SERP, and data collection via Bright Data MCP",
        "transport": MCPTransport.SSE,
    },
    "composio": {
        "url_patterns": ["composio.dev"],
        "name": "Composio",
        "description": "Composio MCP tool integration",
        "transport": MCPTransport.SSE,
    },
    "zapier": {
        "url_patterns": ["zapier.com"],
        "name": "Zapier",
        "description": "Zapier MCP automation tools",
        "transport": MCPTransport.SSE,
    },
    "smithery": {
        "url_patterns": ["smithery.ai"],
        "name": "Smithery",
        "description": "Smithery MCP server",
        "transport": MCPTransport.SSE,
    },
}


def _llm_response_to_text(response: Any) -> str:
    """Normalize LangChain response content into plain text."""
    raw_content = response.content if hasattr(response, "content") else response
    return raw_content if isinstance(raw_content, str) else str(raw_content)

MCP_CONFIG_SYSTEM_PROMPT = """You are an MCP server configuration assistant for the Signal to Action system.

Your job: extract MCP server configuration details from the user's message.

You understand the Model Context Protocol (MCP) and can configure servers from:
- Direct URLs (SSE/HTTP transport) — e.g. https://mcp.brightdata.com/mcp?token=xxx
- NPX-based servers (stdio transport) — e.g. "add the github mcp server"
- Docker-based servers
- Custom configurations

## Rules
- If a URL is provided, determine the transport type (usually SSE for remote URLs)
- Extract any tokens/keys from URLs or the message
- Match against known templates when possible
- For unknown servers, extract what you can and ask for missing details
- NEVER strip tokens or authentication from URLs — they are part of the config

## Available Templates
{templates}

## Output format (strict JSON, no prose, no markdown code blocks)
{{
  "action": "<add | remove | list | status>",
  "server_config": {{
    "name": "<human-friendly name>",
    "description": "<what this server does>",
    "transport": "<stdio | sse>",
    "command": "<command for stdio, empty string for SSE>",
    "args": ["<args for stdio>"],
    "url": "<full URL for SSE transport, null for stdio>",
    "env": {{"KEY": "value"}},
    "template_id": "<matching template ID or null>"
  }},
  "confirmation_message": "<brief message to show the user about what you're about to do>",
  "needs_more_info": false,
  "missing_info_question": null
}}"""


def _detect_provider(url: str) -> dict[str, Any] | None:
    """Try to match a URL against known MCP providers."""
    url_lower = url.lower()
    for provider_id, info in _KNOWN_PROVIDERS.items():
        for pattern in info["url_patterns"]:
            if pattern in url_lower:
                return {**info, "provider_id": provider_id}
    return None


def _extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text string."""
    return _URL_PATTERN.findall(text)


def _build_template_context() -> str:
    """Build a summary of available templates for the LLM prompt."""
    lines = []
    for t in TEMPLATES:
        env_info = f" (needs: {', '.join(t.env_keys)})" if t.env_keys else ""
        lines.append(f"- {t.template_id}: {t.name} — {t.description}{env_info}")
    return "\n".join(lines)


async def mcp_config_node(state: CampaignState) -> dict[str, Any]:
    """Handle MCP server configuration requests from chat.

    Parses user intent, extracts server details, and configures the MCP server.

    Args:
        state: Current campaign state.

    Returns:
        State update with configuration results as UI frames.
    """
    session_id = state.get("session_id", "unknown")
    logger.info("mcp_config_node called | session=%s", session_id)

    await memory_manager.build_context_bundle(state, "orchestrator")

    # Get the latest user message
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            user_message = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    if not user_message:
        return _make_error_response("I couldn't find your configuration request. Could you describe what MCP server you'd like to set up?")

    # Quick path: if user provides a URL, try direct configuration
    urls = _extract_urls(user_message)

    # Try LLM-based parsing for full understanding
    llm = get_llm(temperature=0)

    if llm is None:
        # Mock mode — try URL-based detection
        if urls:
            return await _configure_from_url(urls[0], user_message)
        return _make_error_response("MCP configuration requires the AI model. Please check your LLM settings.")

    template_context = _build_template_context()
    system_prompt = MCP_CONFIG_SYSTEM_PROMPT.format(templates=template_context)

    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
        )

        content = _llm_response_to_text(response).strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            first_nl = content.find("\n")
            if first_nl != -1:
                content = content[first_nl + 1:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("LLM parsing failed for MCP config: %s", e)
        # Fallback: if we have a URL, try direct configuration
        if urls:
            return await _configure_from_url(urls[0], user_message)
        return _make_error_response(
            "I had trouble understanding your MCP configuration request. "
            "Please provide either:\n"
            "- A server URL (e.g. `https://mcp.brightdata.com/mcp?token=...`)\n"
            "- A server name from our templates (GitHub, Slack, Brave Search, PostgreSQL, etc.)"
        )

    action = result.get("action", "add")

    if action == "list":
        return await _handle_list_servers()
    elif action == "remove":
        server_name = result.get("server_config", {}).get("name", "")
        return await _handle_remove_server(server_name)
    elif action == "status":
        return await _handle_server_status()
    elif result.get("needs_more_info"):
        question = result.get("missing_info_question", "Could you provide more details about the MCP server you want to configure?")
        return _make_question_response(question)

    # Add server
    server_config = result.get("server_config", {})
    return await _configure_server(server_config)


async def _configure_from_url(url: str, user_message: str) -> dict[str, Any]:
    """Configure an MCP server directly from a URL (fallback path)."""
    provider = _detect_provider(url)

    name = provider["name"] if provider else "Custom MCP Server"
    description = provider["description"] if provider else "Custom MCP server"
    transport = provider["transport"] if provider else MCPTransport.SSE

    config_dict: dict[str, Any] = {
        "name": name,
        "description": description,
        "transport": transport.value if isinstance(transport, MCPTransport) else transport,
        "command": "",
        "args": [],
        "url": url,
        "env": {},
    }

    return await _configure_server(config_dict)


async def _configure_server(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Create, persist, and start an MCP server from parsed config."""
    server_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    transport_val = config_dict.get("transport", "sse")
    if isinstance(transport_val, str):
        transport = MCPTransport(transport_val)
    else:
        transport = transport_val

    # Check if this matches a template
    template_id = config_dict.get("template_id")
    if template_id:
        from app.mcp.registry import get_template
        template = get_template(template_id)
        if template:
            config = MCPServerConfig(
                server_id=server_id,
                name=template.name,
                description=template.description,
                transport=template.transport,
                command=template.command or config_dict.get("command", ""),
                args=config_dict.get("args") or template.args,
                env=config_dict.get("env", {}),
                url=config_dict.get("url") or template.url_template,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        else:
            config = _build_config(server_id, config_dict, transport, now)
    else:
        config = _build_config(server_id, config_dict, transport, now)

    # Persist to DB
    await save_mcp_server(config.model_dump())

    # Register and start
    mgr = get_mcp_manager()
    state = await mgr.add_server(config)

    # Build response based on outcome
    if state.status == MCPServerStatus.RUNNING:
        tool_count = len(state.tools)
        tool_names = [t.name for t in state.tools[:10]]
        tool_list = "\n".join(f"  - `{name}`" for name in tool_names)
        if len(state.tools) > 10:
            tool_list += f"\n  - ... and {len(state.tools) - 10} more"

        success_text = (
            f"**{config.name}** MCP server configured and running.\n\n"
            f"**{tool_count} tools** discovered:\n{tool_list}\n\n"
            f"These tools are now available for the agent to use."
        )
        return _make_success_response(success_text)

    elif state.status == MCPServerStatus.ERROR:
        error_msg = state.error_message or "Unknown error"
        return _make_error_response(
            f"Failed to start **{config.name}** MCP server.\n\n"
            f"**Error:** {error_msg}\n\n"
            f"Please verify the URL/credentials and try again."
        )
    else:
        return _make_success_response(
            f"**{config.name}** MCP server configuration saved. "
            f"Status: {state.status.value}. It will start automatically."
        )


def _build_config(
    server_id: str,
    config_dict: dict[str, Any],
    transport: MCPTransport,
    now: datetime,
) -> MCPServerConfig:
    """Build an MCPServerConfig from a parsed config dict."""
    return MCPServerConfig(
        server_id=server_id,
        name=config_dict.get("name", "Custom MCP Server"),
        description=config_dict.get("description", ""),
        transport=transport,
        command=config_dict.get("command", ""),
        args=config_dict.get("args", []),
        env=config_dict.get("env", {}),
        url=config_dict.get("url"),
        enabled=True,
        created_at=now,
        updated_at=now,
    )


async def _handle_list_servers() -> dict[str, Any]:
    """List all configured MCP servers."""
    mgr = get_mcp_manager()
    servers = mgr.list_servers()

    if not servers:
        return _make_success_response(
            "No MCP servers configured yet.\n\n"
            "You can add one by providing a URL or asking me to set up a server "
            "(e.g. \"configure GitHub MCP server\" or provide an MCP URL)."
        )

    lines = ["**Configured MCP Servers:**\n"]
    for s in servers:
        status_icon = "🟢" if s.status == MCPServerStatus.RUNNING else "🔴" if s.status == MCPServerStatus.ERROR else "⚪"
        tool_count = len(s.tools) if s.status == MCPServerStatus.RUNNING else 0
        lines.append(f"{status_icon} **{s.config.name}** — {s.status.value} ({tool_count} tools)")

    return _make_success_response("\n".join(lines))


async def _handle_remove_server(server_name: str) -> dict[str, Any]:
    """Remove an MCP server by name."""
    mgr = get_mcp_manager()

    # Find server by name (case-insensitive)
    target = None
    for s in mgr.list_servers():
        if s.config.name.lower() == server_name.lower():
            target = s
            break

    if not target:
        return _make_error_response(
            f"No MCP server found with name \"{server_name}\".\n"
            "Use \"list MCP servers\" to see configured servers."
        )

    await mgr.remove_server(target.server_id)
    await delete_mcp_server(target.server_id)

    return _make_success_response(f"**{target.config.name}** MCP server removed.")


async def _handle_server_status() -> dict[str, Any]:
    """Show detailed status of all MCP servers."""
    return await _handle_list_servers()


def _make_success_response(text: str) -> dict[str, Any]:
    """Build a state update with a success message UI frame."""
    instance_id = f"mcp_cfg_{uuid4().hex[:8]}"
    ui_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=instance_id,
        props={"content": text, "role": "assistant"},
        actions=[],
    )
    return {
        "active_stage_summary": "MCP server configured",
        "session_complete": True,
        "pending_ui_frames": [ui_frame.model_dump()],
    }


def _make_error_response(text: str) -> dict[str, Any]:
    """Build a state update with an error message UI frame."""
    instance_id = f"mcp_cfg_{uuid4().hex[:8]}"
    ui_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=instance_id,
        props={"content": text, "role": "assistant"},
        actions=[],
    )
    return {
        "active_stage_summary": "MCP configuration failed",
        "session_complete": True,
        "pending_ui_frames": [ui_frame.model_dump()],
    }


def _make_question_response(question: str) -> dict[str, Any]:
    """Build a state update asking the user for more information."""
    instance_id = f"mcp_cfg_{uuid4().hex[:8]}"
    ui_frame = UIFrame(
        type="text",
        component="MessageRenderer",
        instance_id=instance_id,
        props={"content": question, "role": "assistant"},
        actions=[],
    )
    return {
        "active_stage_summary": "awaiting MCP configuration details",
        "session_complete": True,
        "pending_ui_frames": [ui_frame.model_dump()],
    }
