"""Conversation agent for OpenAI Realtime integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.components.conversation import trace
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import ulid

from .const import (
    CONF_API_KEY,
    CONF_INSTRUCTIONS,
    CONF_MAX_OUTPUT_TOKENS,
    CONF_MCP_SERVERS,
    CONF_MODEL,
    CONF_VOICE,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    DOMAIN,
    EVENT_RESPONSE_DONE,
    EVENT_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE,
)
from .mcp_handler import HomeAssistantMCPTools, MCPServerHandler
from .realtime_client import OpenAIRealtimeClient, RealtimeResponse, RealtimeSession

_LOGGER = logging.getLogger(__name__)


class OpenAIRealtimeConversationAgent(conversation.AbstractConversationAgent):
    """OpenAI Realtime conversation agent."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self._client: OpenAIRealtimeClient | None = None
        self._mcp_handler: MCPServerHandler | None = None
        self._ha_tools: HomeAssistantMCPTools | None = None
        self._connected = False
        self._conversation_id: str | None = None
        self._pending_function_calls: dict[str, asyncio.Future] = {}

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"

    @property
    def attribution(self) -> conversation.Attribution:
        """Return attribution for the agent."""
        return {
            "name": "OpenAI Realtime",
            "url": "https://platform.openai.com/docs/guides/realtime",
        }

    async def async_initialize(self) -> None:
        """Initialize the conversation agent."""
        config = {**self.entry.data, **self.entry.options}

        session = async_get_clientsession(self.hass)

        # Initialize MCP handler
        self._mcp_handler = MCPServerHandler(session)

        # Add configured MCP servers
        mcp_servers = config.get(CONF_MCP_SERVERS, [])
        for server_config in mcp_servers:
            self._mcp_handler.add_server_from_config(server_config)

        # Connect to stdio MCP servers to get their tools
        stdio_servers = self._mcp_handler.get_stdio_servers()
        for server in stdio_servers:
            try:
                await self._mcp_handler.connect_server(server.name)
                _LOGGER.info(
                    "Connected to stdio MCP server %s with %d tools",
                    server.name,
                    len(server.tools),
                )
            except Exception as e:
                _LOGGER.error("Error connecting to stdio MCP server %s: %s", server.name, e)

        # Initialize Home Assistant tools
        self._ha_tools = HomeAssistantMCPTools(self.hass)
        
        # Build tools list: HA builtin + stdio MCP tools
        builtin_tools = self._ha_tools.get_builtin_tools()
        stdio_tools = self._mcp_handler.get_tools_as_functions()
        all_tools = builtin_tools + stdio_tools
        
        _LOGGER.info(
            "Agent tools: %d builtin + %d stdio MCP = %d total",
            len(builtin_tools),
            len(stdio_tools),
            len(all_tools),
        )

        # Create session configuration
        session_config = RealtimeSession(
            model=config.get(CONF_MODEL, DEFAULT_MODEL),
            voice=config.get(CONF_VOICE, DEFAULT_VOICE),
            instructions=self._build_instructions(config),
            max_output_tokens=config.get(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS),
            tools=all_tools,
            mcp_servers=mcp_servers,
        )

        # Create client
        self._client = OpenAIRealtimeClient(
            api_key=config[CONF_API_KEY],
            session=session,
            session_config=session_config,
        )

        # Register event handlers
        self._client.on(EVENT_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE, self._handle_function_call)

    def _build_instructions(self, config: dict[str, Any]) -> str:
        """Build the system instructions."""
        base_instructions = config.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS)

        ha_context = """
You are integrated with Home Assistant, a home automation platform.
You can control smart home devices and retrieve their states.

Available capabilities:
- Get the state of any entity (lights, sensors, switches, etc.)
- Call services to control devices (turn on/off, set temperature, etc.)
- List entities by domain or area
- Execute MCP server tools if configured

When the user asks to control a device or check its status, use the appropriate function.
Always confirm actions you take and provide helpful feedback.
"""
        return f"{base_instructions}\n\n{ha_context}"

    async def _ensure_connected(self) -> bool:
        """Ensure the client is connected."""
        if not self._client:
            await self.async_initialize()

        if self._client and not self._client.connected:
            self._connected = await self._client.connect()

            if self._connected and self._mcp_handler:
                # Connect to MCP servers
                await self._mcp_handler.connect_all_servers()

        return self._connected

    async def _handle_function_call(self, data: dict[str, Any]) -> None:
        """Handle function calls from the model."""
        import json

        call_id = data.get("call_id", "")
        arguments_str = data.get("arguments", "{}")

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            arguments = {}

        # Get the function name from the event data
        function_name = data.get("name", "")
        _LOGGER.info("Function call received: name=%s call_id=%s", function_name, call_id)

        # Try to execute as Home Assistant tool first
        if self._ha_tools:
            result = await self._execute_function(function_name, call_id, arguments)

            if self._client and result:
                await self._client.send_function_result(call_id, result)

    async def _execute_function(
        self,
        function_name: str,
        call_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a function call by name."""
        _LOGGER.info("Executing function: %s with args: %s", function_name, arguments)
        
        # Check for Home Assistant built-in tools
        if function_name in ["get_entity_state", "call_service", "get_entities_by_domain", "get_area_entities"]:
            return await self._ha_tools.execute_tool(function_name, arguments)
        
        # Check if this is an MCP server function (format: server_name__tool_name)
        if self._mcp_handler and "__" in function_name:
            parsed = self._mcp_handler.parse_function_name(function_name)
            if parsed:
                server_name, tool_name = parsed
                _LOGGER.info("Calling MCP tool: %s/%s", server_name, tool_name)
                return await self._mcp_handler.call_tool(server_name, tool_name, arguments)
        
        # Fallback: guess based on arguments (for backwards compatibility)
        if not function_name:
            if "entity_id" in arguments and "domain" not in arguments:
                return await self._ha_tools.execute_tool("get_entity_state", arguments)
            elif "domain" in arguments and "service" in arguments:
                return await self._ha_tools.execute_tool("call_service", arguments)
            elif "domain" in arguments:
                return await self._ha_tools.execute_tool("get_entities_by_domain", arguments)
            elif "area_name" in arguments:
                return await self._ha_tools.execute_tool("get_area_entities", arguments)

        return {"error": f"Unknown function: {function_name}"}

    async def async_process(
        self,
        user_input: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        """Process a user input."""
        if not await self._ensure_connected():
            return conversation.ConversationResult(
                response=intent.IntentResponse(language=user_input.language),
                conversation_id=user_input.conversation_id or ulid.ulid_now(),
            )

        # Set or continue conversation
        conversation_id = user_input.conversation_id or ulid.ulid_now()
        self._conversation_id = conversation_id

        # Trace the conversation
        trace.async_conversation_trace_append(
            trace.ConversationTraceEventType.AGENT_DETAIL,
            {"text": user_input.text},
        )

        try:
            # Send text to the Realtime API
            response = await self._client.send_text(user_input.text)

            # Extract the response text
            response_text = self._extract_response_text(response)

            # Create intent response
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_speech(response_text)

            trace.async_conversation_trace_append(
                trace.ConversationTraceEventType.AGENT_DETAIL,
                {"response": response_text},
            )

            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=conversation_id,
            )

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for OpenAI Realtime response")
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                "Request timed out",
            )
            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=conversation_id,
            )
        except Exception as e:
            _LOGGER.error("Error processing conversation: %s", e)
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Error: {str(e)}",
            )
            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=conversation_id,
            )

    def _extract_response_text(self, response: RealtimeResponse) -> str:
        """Extract text from the response."""
        # First try the direct text/transcript
        if response.text:
            return response.text
        if response.audio_transcript:
            return response.audio_transcript

        # Try to extract from output items
        for item in response.output:
            for content in item.content:
                if content.get("type") == "text":
                    return content.get("text", "")
                if content.get("type") == "output_audio":
                    return content.get("transcript", "")
                if content.get("type") == "output_text":
                    return content.get("text", "")

        return "I'm sorry, I couldn't generate a response."

    async def async_disconnect(self) -> None:
        """Disconnect from the API."""
        if self._client:
            await self._client.disconnect()
            self._connected = False


async def async_setup_conversation(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> OpenAIRealtimeConversationAgent:
    """Set up the conversation agent."""
    agent = OpenAIRealtimeConversationAgent(hass, entry)
    await agent.async_initialize()

    conversation.async_set_agent(hass, entry, agent)

    return agent


async def async_unload_conversation(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Unload the conversation agent."""
    conversation.async_unset_agent(hass, entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up conversation platform."""
    # The conversation agent is set up in __init__.py via async_setup_conversation
    # This function is required for the platform but doesn't need to do anything
    pass


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload conversation platform."""
    return True
