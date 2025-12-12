"""MCP (Model Context Protocol) server handler for OpenAI Realtime integration."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    CONF_MCP_SERVER_NAME,
    CONF_MCP_SERVER_TOKEN,
    CONF_MCP_SERVER_URL,
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
class MCPServer:
    """Represents an MCP server configuration."""

    name: str
    url: str
    token: str | None = None
    tools: list[MCPTool] = field(default_factory=list)
    connected: bool = False


class MCPServerHandler:
    """Handler for MCP server connections and tool management."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the MCP server handler."""
        self._session = session
        self._servers: dict[str, MCPServer] = {}
        self._tools: dict[str, MCPTool] = {}

    def add_server(
        self,
        name: str,
        url: str,
        token: str | None = None,
    ) -> MCPServer:
        """Add an MCP server configuration."""
        server = MCPServer(
            name=name,
            url=url,
            token=token,
        )
        self._servers[name] = server
        _LOGGER.info("Added MCP server: %s at %s", name, url)
        return server

    def add_server_from_config(self, config: dict[str, str]) -> MCPServer:
        """Add an MCP server from configuration dictionary."""
        return self.add_server(
            name=config.get(CONF_MCP_SERVER_NAME, "mcp_server"),
            url=config.get(CONF_MCP_SERVER_URL, ""),
            token=config.get(CONF_MCP_SERVER_TOKEN),
        )

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server."""
        if name in self._servers:
            # Remove associated tools
            server = self._servers[name]
            for tool in server.tools:
                tool_key = f"{name}:{tool.name}"
                if tool_key in self._tools:
                    del self._tools[tool_key]
            del self._servers[name]
            _LOGGER.info("Removed MCP server: %s", name)
            return True
        return False

    async def connect_server(self, name: str) -> bool:
        """Connect to an MCP server and fetch its tools."""
        if name not in self._servers:
            _LOGGER.error("MCP server not found: %s", name)
            return False

        server = self._servers[name]

        try:
            headers = {"Content-Type": "application/json"}
            if server.token:
                headers["Authorization"] = f"Bearer {server.token}"

            # List tools endpoint (MCP protocol)
            async with self._session.post(
                server.url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    tools_data = data.get("result", {}).get("tools", [])

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
                        "Connected to MCP server %s, found %d tools",
                        name,
                        len(server.tools),
                    )
                    return True
                else:
                    _LOGGER.error(
                        "Failed to connect to MCP server %s: %d",
                        name,
                        response.status,
                    )
                    return False

        except aiohttp.ClientError as e:
            _LOGGER.error("Error connecting to MCP server %s: %s", name, e)
            return False

    async def connect_all_servers(self) -> dict[str, bool]:
        """Connect to all configured MCP servers."""
        results = {}
        for name in self._servers:
            results[name] = await self.connect_server(name)
        return results

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

        try:
            headers = {"Content-Type": "application/json"}
            if server.token:
                headers["Authorization"] = f"Bearer {server.token}"

            async with self._session.post(
                server.url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("result", {})
                    _LOGGER.info(
                        "MCP tool call successful: %s/%s",
                        server_name,
                        tool_name,
                    )
                    return result
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "MCP tool call failed: %s/%s - %s",
                        server_name,
                        tool_name,
                        error_text,
                    )
                    return {"error": error_text}

        except aiohttp.ClientError as e:
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
        """Get tools formatted for OpenAI Realtime API MCP integration."""
        mcp_tools: list[dict[str, Any]] = []
        for server in self._servers.values():
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
