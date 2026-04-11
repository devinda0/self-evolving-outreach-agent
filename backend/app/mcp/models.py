"""Pydantic models for MCP server configuration and tool definitions."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MCPTransport(str, Enum):
    STDIO = "stdio"
    SSE = "sse"


class MCPServerStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class MCPToolParameter(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False


class MCPTool(BaseModel):
    name: str
    description: str = ""
    parameters: list[MCPToolParameter] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    """Persisted configuration for an MCP server."""

    server_id: str
    name: str
    description: str = ""
    transport: MCPTransport = MCPTransport.STDIO
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None  # for SSE transport
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())


class MCPServerState(BaseModel):
    """Runtime state of an MCP server (not persisted)."""

    server_id: str
    config: MCPServerConfig
    status: MCPServerStatus = MCPServerStatus.STOPPED
    tools: list[MCPTool] = Field(default_factory=list)
    error_message: str | None = None
    pid: int | None = None


class MCPServerTemplate(BaseModel):
    """Pre-configured template for popular MCP servers."""

    template_id: str
    name: str
    description: str
    icon: str = "⚡"
    category: str = "general"
    command: str
    args: list[str] = Field(default_factory=list)
    env_keys: list[str] = Field(default_factory=list)
    env_descriptions: dict[str, str] = Field(default_factory=dict)
    env_placeholders: dict[str, str] = Field(default_factory=dict)
    transport: MCPTransport = MCPTransport.STDIO
    url_template: str | None = None  # for SSE servers
    setup_hint: str = ""


# -- API request/response models --


class MCPServerCreateRequest(BaseModel):
    name: str
    description: str = ""
    transport: MCPTransport = MCPTransport.STDIO
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None


class MCPServerUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    enabled: bool | None = None
    url: str | None = None


class MCPServerResponse(BaseModel):
    server_id: str
    name: str
    description: str
    transport: MCPTransport
    command: str
    args: list[str]
    env_keys: list[str]  # never expose env values
    url: str | None
    enabled: bool
    status: MCPServerStatus
    tools: list[MCPTool]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class MCPToolCallRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallResponse(BaseModel):
    success: bool
    result: Any = None
    error: str | None = None
