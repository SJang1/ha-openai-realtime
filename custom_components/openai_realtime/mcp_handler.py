"""MCP (Model Context Protocol) server handler for OpenAI Realtime integration."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    CONF_MCP_SERVER_ARGS,
    CONF_MCP_SERVER_COMMAND,
    CONF_MCP_SERVER_ENABLED,
    CONF_MCP_SERVER_ENV,
    CONF_MCP_SERVER_NAME,
    CONF_MCP_SERVER_TOKEN,
    CONF_MCP_SERVER_TYPE,
    CONF_MCP_SERVER_URL,
    MCP_SERVER_TYPE_SSE,
    MCP_SERVER_TYPE_STDIO,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Represents an MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    name: str
    server_type: str = MCP_SERVER_TYPE_SSE  # 'sse' or 'stdio'
    url: str = ""  # For SSE servers
    token: str | None = None  # For SSE servers
    command: str = ""  # For stdio servers
    args: list[str] = field(default_factory=list)  # For stdio servers
    env: dict[str, str] = field(default_factory=dict)  # For stdio servers
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerConfig":
        """Create config from dictionary."""
        return cls(
            name=data.get(CONF_MCP_SERVER_NAME, "mcp_server"),
            server_type=data.get(CONF_MCP_SERVER_TYPE, MCP_SERVER_TYPE_SSE),
            url=data.get(CONF_MCP_SERVER_URL, ""),
            token=data.get(CONF_MCP_SERVER_TOKEN),
            command=data.get(CONF_MCP_SERVER_COMMAND, ""),
            args=data.get(CONF_MCP_SERVER_ARGS, []),
            env=data.get(CONF_MCP_SERVER_ENV, {}),
            enabled=data.get(CONF_MCP_SERVER_ENABLED, True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            CONF_MCP_SERVER_NAME: self.name,
            CONF_MCP_SERVER_TYPE: self.server_type,
            CONF_MCP_SERVER_URL: self.url,
            CONF_MCP_SERVER_TOKEN: self.token,
            CONF_MCP_SERVER_COMMAND: self.command,
            CONF_MCP_SERVER_ARGS: self.args,
            CONF_MCP_SERVER_ENV: self.env,
            CONF_MCP_SERVER_ENABLED: self.enabled,
        }


@dataclass
class MCPServer:
    """Represents an MCP server."""

    config: MCPServerConfig
    tools: list[MCPTool] = field(default_factory=list)
    connected: bool = False

    @property
    def name(self) -> str:
        """Get server name."""
        return self.config.name

    @property
    def server_type(self) -> str:
        """Get server type."""
        return self.config.server_type

    @property
    def url(self) -> str:
        """Get server URL (for SSE)."""
        return self.config.url

    @property
    def token(self) -> str | None:
        """Get server token (for SSE)."""
        return self.config.token

    @property
    def enabled(self) -> bool:
        """Check if server is enabled."""
        return self.config.enabled


class MCPTransport(ABC):
    """Abstract base class for MCP transports."""

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the MCP server."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        pass

    @abstractmethod
    async def send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and return the result."""
        pass


class SSETransport(MCPTransport):
    """SSE (Server-Sent Events) transport for MCP."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str | None = None,
    ) -> None:
        """Initialize SSE transport."""
        self._session = session
        self._url = url
        self._token = token
        self._connected = False
        self._request_id = 0

    async def connect(self) -> bool:
        """Connect to the SSE server."""
        try:
            headers = {"Content-Type": "application/json"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"

            # Test connection with initialize
            async with self._session.post(
                self._url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._get_request_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "home-assistant-openai-realtime",
                            "version": "1.0.0"
                        }
                    },
                },
            ) as response:
                if response.status == 200:
                    self._connected = True
                    return True
        except aiohttp.ClientError as e:
            _LOGGER.error("SSE connection error: %s", e)
        return False

    async def disconnect(self) -> None:
        """Disconnect from the SSE server."""
        self._connected = False

    def _get_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    async def send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": method,
        }
        if params:
            request["params"] = params

        try:
            async with self._session.post(
                self._url,
                headers=headers,
                json=request,
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    return {"error": {"code": response.status, "message": error_text}}
        except aiohttp.ClientError as e:
            return {"error": {"code": -1, "message": str(e)}}


class StdioTransport(MCPTransport):
    """Stdio transport for MCP servers."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize stdio transport."""
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._connected = False
        self._lock = asyncio.Lock()
        self._response_futures: dict[int, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        """Start the stdio MCP server process."""
        try:
            # Prepare environment
            process_env = os.environ.copy()
            process_env.update(self._env)

            # Start the process
            cmd = [self._command] + self._args
            _LOGGER.info("Starting stdio MCP server: %s", " ".join(cmd))

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )

            # Start reading responses
            self._read_task = asyncio.create_task(self._read_responses())

            # Send initialize request
            result = await self.send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "home-assistant-openai-realtime",
                        "version": "1.0.0"
                    }
                }
            )

            if "error" not in result:
                # Send initialized notification
                await self._send_notification("notifications/initialized", {})
                self._connected = True
                _LOGGER.info("Stdio MCP server connected successfully")
                return True
            else:
                _LOGGER.error("Stdio MCP server initialization failed: %s", result)
                return False

        except Exception as e:
            _LOGGER.error("Failed to start stdio MCP server: %s", e)
            return False

    async def disconnect(self) -> None:
        """Stop the stdio MCP server process."""
        self._connected = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception as e:
                _LOGGER.error("Error stopping stdio process: %s", e)
            finally:
                self._process = None

    def _get_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    async def _read_responses(self) -> None:
        """Read responses from the process stdout."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break

                try:
                    response = json.loads(line.decode())
                    request_id = response.get("id")
                    if request_id and request_id in self._response_futures:
                        future = self._response_futures.pop(request_id)
                        if not future.done():
                            future.set_result(response)
                except json.JSONDecodeError:
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Error reading stdio responses: %s", e)

    async def _send_notification(
        self, method: str, params: dict[str, Any]
    ) -> None:
        """Send a notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            message = json.dumps(notification) + "\n"
            self._process.stdin.write(message.encode())
            await self._process.stdin.drain()
        except Exception as e:
            _LOGGER.error("Error sending notification: %s", e)

    async def send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not self._process or not self._process.stdin:
            return {"error": {"code": -1, "message": "Process not running"}}

        async with self._lock:
            request_id = self._get_request_id()
            request: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params:
                request["params"] = params

            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._response_futures[request_id] = future

            try:
                message = json.dumps(request) + "\n"
                self._process.stdin.write(message.encode())
                await self._process.stdin.drain()

                # Wait for response with timeout
                result = await asyncio.wait_for(future, timeout=30.0)
                return result

            except asyncio.TimeoutError:
                self._response_futures.pop(request_id, None)
                return {"error": {"code": -1, "message": "Request timeout"}}
            except Exception as e:
                self._response_futures.pop(request_id, None)
                return {"error": {"code": -1, "message": str(e)}}


class MCPServerHandler:
    """Handler for MCP server connections and tool management."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the MCP server handler."""
        self._session = session
        self._servers: dict[str, MCPServer] = {}
        self._transports: dict[str, MCPTransport] = {}
        self._tools: dict[str, MCPTool] = {}

    def add_server(
        self,
        name: str,
        url: str = "",
        token: str | None = None,
        server_type: str = MCP_SERVER_TYPE_SSE,
        command: str = "",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        enabled: bool = True,
    ) -> MCPServer:
        """Add an MCP server configuration."""
        config = MCPServerConfig(
            name=name,
            server_type=server_type,
            url=url,
            token=token,
            command=command,
            args=args or [],
            env=env or {},
            enabled=enabled,
        )
        server = MCPServer(config=config)
        self._servers[name] = server
        _LOGGER.info("Added MCP server: %s (type: %s)", name, server_type)
        return server

    def add_server_from_config(self, config: dict[str, Any]) -> MCPServer:
        """Add an MCP server from configuration dictionary."""
        server_config = MCPServerConfig.from_dict(config)
        server = MCPServer(config=server_config)
        self._servers[server_config.name] = server
        _LOGGER.info(
            "Added MCP server from config: %s (type: %s)",
            server_config.name,
            server_config.server_type,
        )
        return server

    def update_server(self, name: str, config: dict[str, Any]) -> MCPServer | None:
        """Update an existing MCP server configuration."""
        if name not in self._servers:
            return None

        # Disconnect if connected
        if name in self._transports:
            asyncio.create_task(self._transports[name].disconnect())
            del self._transports[name]

        # Update config
        server_config = MCPServerConfig.from_dict(config)
        server = MCPServer(config=server_config)
        self._servers[name] = server
        _LOGGER.info("Updated MCP server: %s", name)
        return server

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server."""
        if name in self._servers:
            # Remove associated tools
            server = self._servers[name]
            for tool in server.tools:
                tool_key = f"{name}:{tool.name}"
                if tool_key in self._tools:
                    del self._tools[tool_key]

            # Disconnect transport
            if name in self._transports:
                asyncio.create_task(self._transports[name].disconnect())
                del self._transports[name]

            del self._servers[name]
            _LOGGER.info("Removed MCP server: %s", name)
            return True
        return False

    def _create_transport(self, server: MCPServer) -> MCPTransport:
        """Create appropriate transport for server type."""
        if server.server_type == MCP_SERVER_TYPE_STDIO:
            return StdioTransport(
                command=server.config.command,
                args=server.config.args,
                env=server.config.env,
            )
        else:  # SSE is default
            return SSETransport(
                session=self._session,
                url=server.url,
                token=server.token,
            )

    async def connect_server(self, name: str) -> bool:
        """Connect to an MCP server and fetch its tools."""
        if name not in self._servers:
            _LOGGER.error("MCP server not found: %s", name)
            return False

        server = self._servers[name]

        if not server.enabled:
            _LOGGER.info("MCP server %s is disabled", name)
            return False

        try:
            # Create transport if needed
            if name not in self._transports:
                self._transports[name] = self._create_transport(server)

            transport = self._transports[name]

            # Connect
            if not await transport.connect():
                _LOGGER.error("Failed to connect to MCP server: %s", name)
                return False

            # List tools
            result = await transport.send_request("tools/list")

            if "error" in result:
                _LOGGER.error(
                    "Failed to list tools from MCP server %s: %s",
                    name,
                    result.get("error"),
                )
                return False

            tools_data = result.get("result", {}).get("tools", [])

            server.tools.clear()
            for tool_data in tools_data:
                tool = MCPTool(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                    server_name=name,
                )
                server.tools.append(tool)
                tool_key = f"{name}:{tool.name}"
                self._tools[tool_key] = tool

            server.connected = True
            _LOGGER.info(
                "Connected to MCP server %s (type: %s), found %d tools",
                name,
                server.server_type,
                len(server.tools),
            )
            return True

        except Exception as e:
            _LOGGER.error("Error connecting to MCP server %s: %s", name, e)
            return False

    async def connect_all_servers(self) -> dict[str, bool]:
        """Connect to all configured MCP servers."""
        results = {}
        for name in self._servers:
            results[name] = await self.connect_server(name)
        return results

    async def disconnect_all_servers(self) -> None:
        """Disconnect from all MCP servers."""
        for name, transport in list(self._transports.items()):
            try:
                await transport.disconnect()
            except Exception as e:
                _LOGGER.error("Error disconnecting from %s: %s", name, e)
        self._transports.clear()
        for server in self._servers.values():
            server.connected = False

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool on an MCP server."""
        if server_name not in self._servers:
            return {"error": f"Server not found: {server_name}"}

        server = self._servers[server_name]

        if not server.connected:
            connected = await self.connect_server(server_name)
            if not connected:
                return {"error": f"Could not connect to server: {server_name}"}

        if server_name not in self._transports:
            return {"error": f"No transport for server: {server_name}"}

        transport = self._transports[server_name]

        try:
            result = await transport.send_request(
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": arguments,
                },
            )

            if "error" in result:
                _LOGGER.error(
                    "MCP tool call failed: %s/%s - %s",
                    server_name,
                    tool_name,
                    result.get("error"),
                )
                return {"error": result.get("error")}

            _LOGGER.info(
                "MCP tool call successful: %s/%s",
                server_name,
                tool_name,
            )
            return result.get("result", {})

        except Exception as e:
            _LOGGER.error(
                "Error calling MCP tool %s/%s: %s",
                server_name,
                tool_name,
                e,
            )
            return {"error": str(e)}

    def get_all_tools(self) -> list[MCPTool]:
        """Get all tools from all connected servers."""
        return list(self._tools.values())

    def get_server_tools(self, server_name: str) -> list[MCPTool]:
        """Get tools from a specific server."""
        if server_name in self._servers:
            return self._servers[server_name].tools
        return []

    def get_tool(self, server_name: str, tool_name: str) -> MCPTool | None:
        """Get a specific tool."""
        tool_key = f"{server_name}:{tool_name}"
        return self._tools.get(tool_key)

    def get_tools_for_realtime_api(self) -> list[dict[str, Any]]:
        """Get tools formatted for OpenAI Realtime API MCP integration.
        
        Note: Only SSE servers can be used directly with OpenAI Realtime API.
        Stdio servers are handled locally.
        """
        mcp_tools: list[dict[str, Any]] = []
        for server in self._servers.values():
            if not server.enabled:
                continue
            # Only SSE servers can be directly used with OpenAI Realtime API
            if server.server_type == MCP_SERVER_TYPE_SSE and server.url:
                mcp_tool: dict[str, Any] = {
                    "type": "mcp",
                    "server_label": server.name,
                    "server_url": server.url,
                    "require_approval": "never",
                }
                if server.token:
                    mcp_tool["headers"] = {
                        "Authorization": f"Bearer {server.token}"
                    }
                mcp_tools.append(mcp_tool)
        return mcp_tools

    def get_stdio_servers(self) -> list[MCPServer]:
        """Get list of stdio servers (handled locally)."""
        return [
            server for server in self._servers.values()
            if server.server_type == MCP_SERVER_TYPE_STDIO and server.enabled
        ]

    def get_server_configs(self) -> list[dict[str, Any]]:
        """Get all server configurations as list of dictionaries."""
        return [server.config.to_dict() for server in self._servers.values()]

    def get_tools_as_functions(self) -> list[dict[str, Any]]:
        """Get all tools formatted as OpenAI function definitions.
        
        This can be used when you want to handle tool calls locally
        instead of letting OpenAI directly call the MCP servers.
        """
        functions = []
        for tool in self._tools.values():
            function_def = {
                "type": "function",
                "name": f"{tool.server_name}__{tool.name}",
                "description": tool.description,
                "parameters": tool.input_schema or {
                    "type": "object",
                    "properties": {},
                },
            }
            functions.append(function_def)
        return functions

    def parse_function_name(self, function_name: str) -> tuple[str, str] | None:
        """Parse a function name into server and tool names."""
        if "__" in function_name:
            parts = function_name.split("__", 1)
            return parts[0], parts[1]
        return None

    @property
    def servers(self) -> dict[str, MCPServer]:
        """Get all configured servers."""
        return self._servers.copy()

    @property
    def connected_servers(self) -> list[str]:
        """Get names of connected servers."""
        return [name for name, server in self._servers.items() if server.connected]


class HomeAssistantMCPTools:
    """Provides Home Assistant specific MCP-style tools."""

    def __init__(self, hass: Any) -> None:
        """Initialize with Home Assistant instance."""
        self._hass = hass

    def get_builtin_tools(self) -> list[dict[str, Any]]:
        """Get built-in Home Assistant tools for the Realtime API."""
        return [
            {
                "type": "function",
                "name": "get_entity_state",
                "description": "Get the current state of a Home Assistant entity",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {
                            "type": "string",
                            "description": "The entity ID (e.g., light.living_room, sensor.temperature)",
                        },
                    },
                    "required": ["entity_id"],
                },
            },
            {
                "type": "function",
                "name": "call_service",
                "description": "Call a Home Assistant service",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "description": "The service domain (e.g., light, switch, climate)",
                        },
                        "service": {
                            "type": "string",
                            "description": "The service name (e.g., turn_on, turn_off, set_temperature)",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "The target entity ID",
                        },
                        "data": {
                            "type": "object",
                            "description": "Additional service data",
                        },
                    },
                    "required": ["domain", "service"],
                },
            },
            {
                "type": "function",
                "name": "get_entities_by_domain",
                "description": "Get all entities in a specific domain",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "description": "The domain to list entities for (e.g., light, switch, sensor)",
                        },
                    },
                    "required": ["domain"],
                },
            },
            {
                "type": "function",
                "name": "get_area_entities",
                "description": "Get all entities in a specific area",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "area_name": {
                            "type": "string",
                            "description": "The name of the area",
                        },
                    },
                    "required": ["area_name"],
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a built-in Home Assistant tool."""
        if tool_name == "get_entity_state":
            return await self._get_entity_state(arguments)
        elif tool_name == "call_service":
            return await self._call_service(arguments)
        elif tool_name == "get_entities_by_domain":
            return await self._get_entities_by_domain(arguments)
        elif tool_name == "get_area_entities":
            return await self._get_area_entities(arguments)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _get_entity_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get the state of an entity."""
        entity_id = arguments.get("entity_id", "")
        state = self._hass.states.get(entity_id)

        if state is None:
            return {"error": f"Entity not found: {entity_id}"}

        return {
            "entity_id": entity_id,
            "state": state.state,
            "attributes": dict(state.attributes),
            "last_changed": state.last_changed.isoformat(),
            "last_updated": state.last_updated.isoformat(),
        }

    async def _call_service(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a Home Assistant service."""
        domain = arguments.get("domain", "")
        service = arguments.get("service", "")
        entity_id = arguments.get("entity_id")
        data = arguments.get("data", {})

        # Include any extra arguments as service data
        # (AI sometimes passes service-specific params like temperature at top level)
        reserved_keys = {"domain", "service", "entity_id", "data"}
        for key, value in arguments.items():
            if key not in reserved_keys and key not in data:
                data[key] = value

        if entity_id:
            data["entity_id"] = entity_id

        try:
            await self._hass.services.async_call(
                domain,
                service,
                data,
                blocking=True,
            )
            return {
                "success": True,
                "message": f"Called {domain}.{service}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def _get_entities_by_domain(
        self, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Get all entities in a domain."""
        domain = arguments.get("domain", "")
        entities = []

        for entity_id in self._hass.states.async_entity_ids(domain):
            state = self._hass.states.get(entity_id)
            if state:
                entities.append({
                    "entity_id": entity_id,
                    "state": state.state,
                    "friendly_name": state.attributes.get("friendly_name", entity_id),
                })

        return {
            "domain": domain,
            "count": len(entities),
            "entities": entities,
        }

    async def _get_area_entities(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get all entities in an area."""
        from homeassistant.helpers import area_registry, entity_registry, device_registry
        
        area_name = arguments.get("area_name", "").lower()

        area_reg = area_registry.async_get(self._hass)
        entity_reg = entity_registry.async_get(self._hass)
        device_reg = device_registry.async_get(self._hass)

        # Find the area
        target_area = None
        for area in area_reg.async_list_areas():
            if area.name.lower() == area_name:
                target_area = area
                break

        if not target_area:
            return {"error": f"Area not found: {area_name}"}

        entities = []

        # Get entities directly assigned to the area
        for entry in entity_reg.entities.values():
            if entry.area_id == target_area.id:
                state = self._hass.states.get(entry.entity_id)
                if state:
                    entities.append({
                        "entity_id": entry.entity_id,
                        "state": state.state,
                        "friendly_name": state.attributes.get("friendly_name", entry.entity_id),
                    })

        # Get entities from devices in the area
        for device in device_reg.devices.values():
            if device.area_id == target_area.id:
                for entry in entity_reg.entities.values():
                    if entry.device_id == device.id and entry.area_id is None:
                        state = self._hass.states.get(entry.entity_id)
                        if state:
                            entities.append({
                                "entity_id": entry.entity_id,
                                "state": state.state,
                                "friendly_name": state.attributes.get("friendly_name", entry.entity_id),
                            })

        return {
            "area": target_area.name,
            "count": len(entities),
            "entities": entities,
        }
