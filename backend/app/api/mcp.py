"""MCP server configuration API — REST endpoints for managing MCP servers.

Provides CRUD for server configurations, server lifecycle management,
tool discovery, template browsing, and guided setup via a test-connection flow.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db.crud import delete_mcp_server, save_mcp_server
from app.mcp.manager import get_mcp_manager
from app.mcp.models import (
    MCPServerConfig,
    MCPServerCreateRequest,
    MCPServerResponse,
    MCPServerStatus,
    MCPServerUpdateRequest,
    MCPToolCallRequest,
    MCPToolCallResponse,
)
from app.mcp.registry import TEMPLATES, get_template, get_templates_by_category

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _build_response(server_id: str) -> MCPServerResponse:
    """Build a safe response object (env values redacted)."""
    mgr = get_mcp_manager()
    state = mgr.get_server(server_id)
    if not state:
        raise HTTPException(status_code=404, detail="MCP server not found")

    return MCPServerResponse(
        server_id=state.server_id,
        name=state.config.name,
        description=state.config.description,
        transport=state.config.transport,
        command=state.config.command,
        args=state.config.args,
        env_keys=list(state.config.env.keys()),
        url=state.config.url,
        enabled=state.config.enabled,
        status=state.status,
        tools=state.tools,
        error_message=state.error_message,
        created_at=state.config.created_at,
        updated_at=state.config.updated_at,
    )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.get("/templates")
async def list_templates() -> dict[str, Any]:
    """Return available MCP server templates grouped by category."""
    by_cat = get_templates_by_category()
    return {
        "categories": {
            cat: [t.model_dump() for t in templates]
            for cat, templates in by_cat.items()
        },
        "total": len(TEMPLATES),
    }


@router.get("/templates/{template_id}")
async def get_template_detail(template_id: str) -> dict[str, Any]:
    """Return details for a specific template."""
    t = get_template(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t.model_dump()


# ---------------------------------------------------------------------------
# Server CRUD
# ---------------------------------------------------------------------------


@router.get("/servers")
async def list_servers() -> list[MCPServerResponse]:
    """Return all configured MCP servers with their runtime status."""
    mgr = get_mcp_manager()
    results = []
    for state in mgr.list_servers():
        results.append(_build_response(state.server_id))
    return results


@router.post("/servers", status_code=201)
async def create_server(req: MCPServerCreateRequest) -> MCPServerResponse:
    """Create and start a new MCP server configuration."""
    server_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    config = MCPServerConfig(
        server_id=server_id,
        name=req.name,
        description=req.description,
        transport=req.transport,
        command=req.command,
        args=req.args,
        env=req.env,
        url=req.url,
        enabled=True,
        created_at=now,
        updated_at=now,
    )

    # Persist to DB
    await save_mcp_server(config.model_dump())

    # Register and start
    mgr = get_mcp_manager()
    await mgr.add_server(config)

    return _build_response(server_id)


@router.post("/servers/from-template/{template_id}", status_code=201)
async def create_from_template(
    template_id: str,
    env: dict[str, str] | None = None,
    args_override: list[str] | None = None,
    url_override: str | None = None,
) -> MCPServerResponse:
    """Create an MCP server from a template with provided env vars."""
    t = get_template(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate required env keys
    provided_env = env or {}
    missing = [k for k in t.env_keys if k not in provided_env]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required environment variables: {', '.join(missing)}",
        )

    server_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    config = MCPServerConfig(
        server_id=server_id,
        name=t.name,
        description=t.description,
        transport=t.transport,
        command=t.command,
        args=args_override if args_override is not None else t.args,
        env=provided_env,
        url=url_override or t.url_template,
        enabled=True,
        created_at=now,
        updated_at=now,
    )

    await save_mcp_server(config.model_dump())

    mgr = get_mcp_manager()
    await mgr.add_server(config)

    return _build_response(server_id)


@router.get("/servers/{server_id}")
async def get_server(server_id: str) -> MCPServerResponse:
    """Return details for a specific MCP server."""
    return _build_response(server_id)


@router.patch("/servers/{server_id}")
async def update_server(server_id: str, req: MCPServerUpdateRequest) -> MCPServerResponse:
    """Update an MCP server configuration. Restarts if command/args/env changed."""
    mgr = get_mcp_manager()
    state = mgr.get_server(server_id)
    if not state:
        raise HTTPException(status_code=404, detail="MCP server not found")

    needs_restart = False
    config = state.config

    if req.name is not None:
        config.name = req.name
    if req.description is not None:
        config.description = req.description
    if req.command is not None and req.command != config.command:
        config.command = req.command
        needs_restart = True
    if req.args is not None and req.args != config.args:
        config.args = req.args
        needs_restart = True
    if req.env is not None and req.env != config.env:
        config.env = req.env
        needs_restart = True
    if req.url is not None:
        config.url = req.url
        needs_restart = True
    if req.enabled is not None:
        config.enabled = req.enabled
        if not req.enabled:
            await mgr.stop_server(server_id)
        elif req.enabled and state.status == MCPServerStatus.STOPPED:
            needs_restart = True

    config.updated_at = datetime.now(tz=timezone.utc)
    await save_mcp_server(config.model_dump())

    if needs_restart and config.enabled:
        await mgr.restart_server(server_id)

    return _build_response(server_id)


@router.delete("/servers/{server_id}", status_code=204)
async def remove_server(server_id: str) -> None:
    """Stop and permanently remove an MCP server."""
    mgr = get_mcp_manager()
    if not mgr.get_server(server_id):
        raise HTTPException(status_code=404, detail="MCP server not found")

    await mgr.remove_server(server_id)
    await delete_mcp_server(server_id)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/start")
async def start_server(server_id: str) -> MCPServerResponse:
    """Start (or restart) an MCP server."""
    mgr = get_mcp_manager()
    state = mgr.get_server(server_id)
    if not state:
        raise HTTPException(status_code=404, detail="MCP server not found")

    await mgr.restart_server(server_id)
    return _build_response(server_id)


@router.post("/servers/{server_id}/stop")
async def stop_server(server_id: str) -> MCPServerResponse:
    """Stop a running MCP server."""
    mgr = get_mcp_manager()
    if not mgr.get_server(server_id):
        raise HTTPException(status_code=404, detail="MCP server not found")

    await mgr.stop_server(server_id)
    return _build_response(server_id)


@router.post("/servers/{server_id}/test")
async def test_connection(server_id: str) -> dict[str, Any]:
    """Test an MCP server connection — restart it and report tool discovery results."""
    mgr = get_mcp_manager()
    state = mgr.get_server(server_id)
    if not state:
        raise HTTPException(status_code=404, detail="MCP server not found")

    result = await mgr.restart_server(server_id)
    if result and result.status == MCPServerStatus.RUNNING:
        return {
            "success": True,
            "tools_discovered": len(result.tools),
            "tools": [{"name": t.name, "description": t.description} for t in result.tools],
        }
    return {
        "success": False,
        "error": result.error_message if result else "Server not found after restart",
    }


# ---------------------------------------------------------------------------
# Tool operations
# ---------------------------------------------------------------------------


@router.get("/tools")
async def list_all_tools() -> list[dict[str, Any]]:
    """Return all available tools across all running MCP servers."""
    mgr = get_mcp_manager()
    return mgr.get_all_tools()


@router.post("/tools/call")
async def call_tool(req: MCPToolCallRequest) -> MCPToolCallResponse:
    """Invoke a tool on a specific MCP server."""
    mgr = get_mcp_manager()
    state = mgr.get_server(req.server_id)
    if not state:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if state.status != MCPServerStatus.RUNNING:
        raise HTTPException(status_code=409, detail="MCP server is not running")

    try:
        result = await mgr.call_tool(req.server_id, req.tool_name, req.arguments)
        return MCPToolCallResponse(success=True, result=result)
    except RuntimeError as exc:
        return MCPToolCallResponse(success=False, error=str(exc))
