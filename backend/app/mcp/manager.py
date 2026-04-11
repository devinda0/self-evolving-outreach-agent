"""MCP server process lifecycle and JSON-RPC communication.

Manages starting/stopping MCP server subprocesses, discovering tools via the
MCP protocol (JSON-RPC over stdio), and invoking tools on behalf of agents.
Supports both stdio and SSE transports.
"""

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from app.mcp.models import (
    MCPServerConfig,
    MCPServerState,
    MCPServerStatus,
    MCPTool,
    MCPToolParameter,
    MCPTransport,
)

logger = logging.getLogger(__name__)

# JSON-RPC message ID counter
_msg_id = 0


def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id


class MCPServerProcess:
    """Wraps a single MCP server subprocess and its JSON-RPC communication."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def start(self) -> list[MCPTool]:
        """Start the subprocess, send initialize, and discover tools."""
        if self.config.transport == MCPTransport.SSE:
            raise NotImplementedError("SSE transport is not yet supported")

        env = {**os.environ, **self.config.env}

        self.process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Initialize handshake
        init_result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "signal-to-action", "version": "0.1.0"},
        })

        if init_result is None:
            raise RuntimeError("MCP server did not respond to initialize")

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

        # Discover tools
        tools_result = await self._send_request("tools/list", {})
        tools: list[MCPTool] = []
        if tools_result and "tools" in tools_result:
            for raw_tool in tools_result["tools"]:
                tools.append(_parse_tool(raw_tool))

        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool and return the result."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if result is None:
            raise RuntimeError(f"No response from MCP server for tool '{tool_name}'")

        # MCP tools return content array
        content = result.get("content", [])
        if len(content) == 1 and content[0].get("type") == "text":
            return content[0]["text"]
        return content

    async def stop(self) -> None:
        """Terminate the subprocess."""
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
        self.process = None

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request and wait for the response."""
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None

        msg_id = _next_id()
        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        async with self._write_lock:
            data = json.dumps(message) + "\n"
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()

        # Read response — skip notifications until we get our response
        async with self._read_lock:
            try:
                response = await asyncio.wait_for(
                    self._read_response(msg_id), timeout=30
                )
                return response
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for MCP response: method=%s id=%d", method, msg_id)
                return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.process or not self.process.stdin:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        async with self._write_lock:
            data = json.dumps(message) + "\n"
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()

    async def _read_response(self, expected_id: int) -> dict | None:
        """Read lines from stdout until we get the response matching expected_id."""
        if not self.process or not self.process.stdout:
            return None

        while True:
            line = await self.process.stdout.readline()
            if not line:
                return None

            text = line.decode().strip()
            if not text:
                continue

            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue

            # Skip notifications (no id field)
            if "id" not in msg:
                continue

            if msg.get("id") == expected_id:
                if "error" in msg:
                    err = msg["error"]
                    logger.error("MCP error: %s", err)
                    raise RuntimeError(
                        f"MCP error {err.get('code', '?')}: {err.get('message', 'unknown')}"
                    )
                return msg.get("result")

            # Wrong ID — could be a stale response; skip it
            logger.debug("Skipping MCP response with unexpected id=%s (wanted %d)", msg.get("id"), expected_id)


def _parse_tool(raw: dict) -> MCPTool:
    """Parse a raw MCP tool definition into our model."""
    params: list[MCPToolParameter] = []
    schema = raw.get("inputSchema", {})
    props = schema.get("properties", {})
    required_set = set(schema.get("required", []))

    for param_name, param_def in props.items():
        params.append(MCPToolParameter(
            name=param_name,
            type=param_def.get("type", "string"),
            description=param_def.get("description", ""),
            required=param_name in required_set,
        ))

    return MCPTool(
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        parameters=params,
        input_schema=schema,
    )


class MCPSSEServerProcess:
    """Wraps an MCP server accessible via classic SSE (Server-Sent Events) transport.

    The classic SSE MCP protocol works as follows:
    1. Client opens a persistent GET connection to the SSE endpoint.
    2. Server sends an ``endpoint`` event whose data is the message URL.
    3. Client POSTs JSON-RPC requests to that message URL.
    4. Responses arrive as ``message`` SSE events on the persistent stream.

    This is the transport used by hosted MCP providers such as Bright Data.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._base_url: str = config.url or ""
        self._message_url: str | None = None
        # Maps JSON-RPC message id → Future awaiting the response
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._sse_connected = asyncio.Event()
        self._running: bool = False

    async def start(self) -> list[MCPTool]:
        """Connect to the SSE endpoint, discover the message URL, initialize, and list tools."""
        if not self._base_url:
            raise RuntimeError("SSE server URL is required")

        sse_headers: dict[str, str] = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        # Forward env vars as request headers (e.g. auth tokens)
        for key, value in self.config.env.items():
            header_name = key.replace("_", "-").title()
            sse_headers[header_name] = value

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
        )
        self._running = True

        # Start the background SSE reader; it will set _sse_connected once the
        # endpoint event is received.
        self._reader_task = asyncio.create_task(self._sse_reader(sse_headers))

        try:
            await asyncio.wait_for(self._sse_connected.wait(), timeout=30)
        except asyncio.TimeoutError:
            self._running = False
            raise RuntimeError("SSE MCP server did not send endpoint event within 30 s")

        if not self._message_url:
            # _sse_connected was set due to a connection error
            raise RuntimeError("SSE MCP server did not respond to initialize")

        # Initialize handshake
        init_result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "signal-to-action", "version": "0.1.0"},
        })

        if init_result is None:
            raise RuntimeError("SSE MCP server did not respond to initialize")

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

        # Discover tools
        tools_result = await self._send_request("tools/list", {})
        tools: list[MCPTool] = []
        if tools_result and "tools" in tools_result:
            for raw_tool in tools_result["tools"]:
                tools.append(_parse_tool(raw_tool))

        return tools

    async def _sse_reader(self, headers: dict[str, str]) -> None:
        """Background task: keeps the SSE stream open and dispatches responses."""
        try:
            async with self._client.stream("GET", self._base_url, headers=headers) as resp:
                resp.raise_for_status()

                event_type: str | None = None
                data_lines: list[str] = []

                async for raw_line in resp.aiter_lines():
                    if not self._running:
                        break

                    line = raw_line.strip()

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line == "":
                        # Blank line signals end of an SSE event — process it
                        data_str = "\n".join(data_lines).strip()
                        data_lines = []

                        if not data_str:
                            event_type = None
                            continue

                        if event_type == "endpoint":
                            # data is the message URL (may be relative)
                            msg_url = data_str
                            if msg_url.startswith("/"):
                                from urllib.parse import urlparse
                                parsed = urlparse(self._base_url)
                                self._message_url = f"{parsed.scheme}://{parsed.netloc}{msg_url}"
                            else:
                                self._message_url = msg_url
                            self._sse_connected.set()

                        elif event_type in ("message", None):
                            try:
                                msg = json.loads(data_str)
                            except json.JSONDecodeError:
                                event_type = None
                                continue

                            msg_id = msg.get("id")
                            if msg_id is not None:
                                fut = self._pending.pop(msg_id, None)
                                if fut and not fut.done():
                                    if "error" in msg:
                                        err = msg["error"]
                                        fut.set_exception(RuntimeError(
                                            f"MCP error {err.get('code', '?')}: {err.get('message', 'unknown')}"
                                        ))
                                    else:
                                        fut.set_result(msg.get("result"))

                        event_type = None

        except Exception as exc:
            if self._running:
                logger.error("SSE reader error: %s", exc)
            # Unblock anything waiting on the connection event
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)
            self._pending.clear()
            self._sse_connected.set()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool via the message URL and receive the result over SSE."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if result is None:
            raise RuntimeError(f"No response from SSE MCP server for tool '{tool_name}'")

        content = result.get("content", [])
        if len(content) == 1 and content[0].get("type") == "text":
            return content[0]["text"]
        return content

    async def stop(self) -> None:
        """Tear down the SSE stream and HTTP client."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        self._message_url = None

    @property
    def is_running(self) -> bool:
        return self._running and self._client is not None

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """POST a JSON-RPC request to the message URL; await the SSE response."""
        if not self._client or not self._message_url:
            return None

        msg_id = _next_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[msg_id] = fut

        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        try:
            resp = await self._client.post(
                self._message_url,
                json=message,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._pending.pop(msg_id, None)
            if not fut.done():
                fut.cancel()
            logger.error("SSE MCP HTTP error: %s", exc.response.status_code)
            return None
        except httpx.RequestError as exc:
            self._pending.pop(msg_id, None)
            if not fut.done():
                fut.cancel()
            logger.error("SSE MCP request error: %s", exc)
            return None

        try:
            return await asyncio.wait_for(fut, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            logger.error("Timeout waiting for SSE MCP response: method=%s id=%d", method, msg_id)
            return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """POST a JSON-RPC notification (no response expected)."""
        if not self._client or not self._message_url:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            await self._client.post(
                self._message_url,
                json=message,
                headers={"Content-Type": "application/json"},
            )
        except Exception:
            logger.debug("SSE notification send failed (non-critical): %s", method)

class MCPManager:
    """Singleton manager for all MCP server instances."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerState] = {}
        self._processes: dict[str, MCPServerProcess | MCPSSEServerProcess] = {}
        self._lock = asyncio.Lock()

    async def load_from_db(self) -> None:
        """Load saved configurations from MongoDB and start enabled servers."""
        from app.db.crud import list_mcp_servers

        configs = await list_mcp_servers()
        for cfg_dict in configs:
            config = MCPServerConfig(**cfg_dict)
            self._servers[config.server_id] = MCPServerState(
                server_id=config.server_id,
                config=config,
                status=MCPServerStatus.STOPPED,
            )
            if config.enabled:
                # Start in background — don't block app startup
                asyncio.create_task(self._start_server(config.server_id))

    async def add_server(self, config: MCPServerConfig) -> MCPServerState:
        """Add and optionally start a new MCP server."""
        async with self._lock:
            self._servers[config.server_id] = MCPServerState(
                server_id=config.server_id,
                config=config,
                status=MCPServerStatus.STOPPED,
            )

        if config.enabled:
            await self._start_server(config.server_id)

        return self._servers[config.server_id]

    async def remove_server(self, server_id: str) -> None:
        """Stop and remove a server."""
        await self.stop_server(server_id)
        async with self._lock:
            self._servers.pop(server_id, None)

    async def _start_server(self, server_id: str) -> None:
        """Start an MCP server subprocess and discover its tools."""
        state = self._servers.get(server_id)
        if not state:
            return

        async with self._lock:
            state.status = MCPServerStatus.STARTING
            state.error_message = None

        # Pick the right process class based on transport
        proc: MCPServerProcess | MCPSSEServerProcess
        if state.config.transport == MCPTransport.SSE:
            proc = MCPSSEServerProcess(state.config)
        else:
            proc = MCPServerProcess(state.config)
        try:
            tools = await proc.start()
            async with self._lock:
                state.status = MCPServerStatus.RUNNING
                state.tools = tools
                if isinstance(proc, MCPServerProcess):
                    state.pid = proc.process.pid if proc.process else None
                else:
                    state.pid = None  # SSE servers are remote — no local PID
                self._processes[server_id] = proc

            logger.info(
                "MCP server started: %s (%s) — %d tools discovered",
                state.config.name,
                server_id,
                len(tools),
            )
        except Exception as exc:
            logger.error("Failed to start MCP server %s: %s", server_id, exc)
            async with self._lock:
                state.status = MCPServerStatus.ERROR
                state.error_message = str(exc)
            await proc.stop()

    async def stop_server(self, server_id: str) -> None:
        """Stop an MCP server subprocess."""
        proc = self._processes.pop(server_id, None)
        if proc:
            await proc.stop()

        state = self._servers.get(server_id)
        if state:
            async with self._lock:
                state.status = MCPServerStatus.STOPPED
                state.tools = []
                state.pid = None

    async def restart_server(self, server_id: str) -> MCPServerState | None:
        """Restart an MCP server."""
        await self.stop_server(server_id)
        await self._start_server(server_id)
        return self._servers.get(server_id)

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on a running MCP server."""
        proc = self._processes.get(server_id)
        if not proc or not proc.is_running:
            raise RuntimeError(f"MCP server '{server_id}' is not running")

        return await proc.call_tool(tool_name, arguments)

    def get_server(self, server_id: str) -> MCPServerState | None:
        return self._servers.get(server_id)

    def list_servers(self) -> list[MCPServerState]:
        return list(self._servers.values())

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Return all available tools across all running servers."""
        tools = []
        for state in self._servers.values():
            if state.status == MCPServerStatus.RUNNING:
                for tool in state.tools:
                    tools.append({
                        "server_id": state.server_id,
                        "server_name": state.config.name,
                        "tool_name": tool.name,
                        "description": tool.description,
                        "parameters": [p.model_dump() for p in tool.parameters],
                        "input_schema": tool.input_schema,
                    })
        return tools

    def find_tool(self, tool_name: str) -> tuple[str, MCPTool] | None:
        """Find a tool by name across all running servers. Returns (server_id, tool) or None."""
        for state in self._servers.values():
            if state.status == MCPServerStatus.RUNNING:
                for tool in state.tools:
                    if tool.name == tool_name:
                        return (state.server_id, tool)
        return None

    async def shutdown(self) -> None:
        """Stop all running servers. Called during app shutdown."""
        server_ids = list(self._processes.keys())
        for sid in server_ids:
            try:
                await self.stop_server(sid)
            except Exception:
                logger.warning("Error stopping MCP server %s during shutdown", sid, exc_info=True)
        logger.info("MCP manager shutdown complete — %d servers stopped", len(server_ids))


# Singleton
_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    """Return the singleton MCPManager instance."""
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
