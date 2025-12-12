"""The OpenAI Realtime integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
)
from .conversation import (
    OpenAIRealtimeConversationAgent,
    async_setup_conversation,
    async_unload_conversation,
)
from .mcp_handler import MCPServerHandler
from .realtime_client import OpenAIRealtimeClient, RealtimeSession

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CONVERSATION,
    Platform.MEDIA_PLAYER,
    Platform.BINARY_SENSOR,
    Platform.STT,
    Platform.TTS,
]

# Service schemas
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_ADD_MCP_SERVER = "add_mcp_server"
SERVICE_REMOVE_MCP_SERVER = "remove_mcp_server"
SERVICE_CLEAR_CONVERSATION = "clear_conversation"
SERVICE_SEND_AUDIO = "send_audio"
SERVICE_START_LISTENING = "start_listening"
SERVICE_STOP_LISTENING = "stop_listening"

SEND_MESSAGE_SCHEMA = vol.Schema({
    vol.Required("message"): cv.string,
})

SEND_AUDIO_SCHEMA = vol.Schema({
    vol.Required("audio_data"): cv.string,
})

ADD_MCP_SERVER_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Required("url"): cv.url,
    vol.Optional("token"): cv.string,
})

REMOVE_MCP_SERVER_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenAI Realtime from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = {**entry.data, **entry.options}

    # Get aiohttp session
    session = async_get_clientsession(hass)

    # Create MCP handler
    mcp_handler = MCPServerHandler(session)

    # Add configured MCP servers
    mcp_servers = config.get(CONF_MCP_SERVERS, [])
    for server_config in mcp_servers:
        mcp_handler.add_server_from_config(server_config)

    # Get built-in Home Assistant tools
    from .mcp_handler import HomeAssistantMCPTools
    ha_tools = HomeAssistantMCPTools(hass)
    builtin_tools = ha_tools.get_builtin_tools()

    # Create session configuration with built-in tools
    session_config = RealtimeSession(
        model=config.get(CONF_MODEL, DEFAULT_MODEL),
        voice=config.get(CONF_VOICE, DEFAULT_VOICE),
        instructions=config.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS),
        max_output_tokens=config.get(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS),
        mcp_servers=mcp_servers,
        tools=builtin_tools,
    )

    # Create the realtime client
    client = OpenAIRealtimeClient(
        api_key=config[CONF_API_KEY],
        session=session,
        session_config=session_config,
    )

    # Store references
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "mcp_handler": mcp_handler,
        "session_config": session_config,
        "ha_tools": ha_tools,
    }

    # Set up the conversation agent
    agent = await async_setup_conversation(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["agent"] = agent

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register services
    await async_register_services(hass)

    # Register WebSocket API
    from .websocket_api import async_setup_websocket_api
    await async_setup_websocket_api(hass)

    # Register frontend
    from .frontend import async_setup_frontend
    await async_setup_frontend(hass)

    _LOGGER.info("OpenAI Realtime integration set up successfully")

    return True


async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_send_message(call: ServiceCall) -> None:
        """Handle send_message service call."""
        message = call.data["message"]

        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            agent: OpenAIRealtimeConversationAgent | None = data.get("agent")
            if agent:
                # Use the agent to send message
                from homeassistant.components.conversation import ConversationInput
                from homeassistant.util import ulid

                user_input = ConversationInput(
                    text=message,
                    context=call.context,
                    conversation_id=ulid.ulid_now(),
                    language="en",
                )
                await agent.async_process(user_input)
                break

    async def handle_add_mcp_server(call: ServiceCall) -> None:
        """Handle add_mcp_server service call."""
        name = call.data["name"]
        url = call.data["url"]
        token = call.data.get("token")

        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            mcp_handler: MCPServerHandler | None = data.get("mcp_handler")
            if mcp_handler:
                mcp_handler.add_server(name, url, token)
                await mcp_handler.connect_server(name)
                _LOGGER.info("Added MCP server: %s", name)
                break

    async def handle_remove_mcp_server(call: ServiceCall) -> None:
        """Handle remove_mcp_server service call."""
        name = call.data["name"]

        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            mcp_handler: MCPServerHandler | None = data.get("mcp_handler")
            if mcp_handler:
                mcp_handler.remove_server(name)
                _LOGGER.info("Removed MCP server: %s", name)
                break

    async def handle_clear_conversation(call: ServiceCall) -> None:
        """Handle clear_conversation service call."""
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            client: OpenAIRealtimeClient | None = data.get("client")
            if client:
                client.clear_conversation()
                _LOGGER.info("Cleared conversation history")
                break

    async def handle_send_audio(call: ServiceCall) -> None:
        """Handle send_audio service call."""
        import base64
        audio_data_b64 = call.data["audio_data"]

        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            client: OpenAIRealtimeClient | None = data.get("client")
            if client:
                if not client.connected:
                    await client.connect()
                audio_bytes = base64.b64decode(audio_data_b64)
                await client.send_audio(audio_bytes)
                _LOGGER.debug("Sent audio data: %d bytes", len(audio_bytes))
                break

    async def handle_start_listening(call: ServiceCall) -> None:
        """Handle start_listening service call."""
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            client: OpenAIRealtimeClient | None = data.get("client")
            if client:
                if not client.connected:
                    await client.connect()
                _LOGGER.info("Started listening session")
                break

    async def handle_stop_listening(call: ServiceCall) -> None:
        """Handle stop_listening service call."""
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            client: OpenAIRealtimeClient | None = data.get("client")
            if client:
                await client.cancel_response()
                await client.clear_audio_buffer()
                _LOGGER.info("Stopped listening session")
                break

    # Register services if not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_MESSAGE, handle_send_message, schema=SEND_MESSAGE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_AUDIO):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_AUDIO, handle_send_audio, schema=SEND_AUDIO_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_START_LISTENING):
        hass.services.async_register(
            DOMAIN, SERVICE_START_LISTENING, handle_start_listening
        )
    if not hass.services.has_service(DOMAIN, SERVICE_STOP_LISTENING):
        hass.services.async_register(
            DOMAIN, SERVICE_STOP_LISTENING, handle_stop_listening
        )
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_MCP_SERVER):
        hass.services.async_register(
            DOMAIN, SERVICE_ADD_MCP_SERVER, handle_add_mcp_server, schema=ADD_MCP_SERVER_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REMOVE_MCP_SERVER):
        hass.services.async_register(
            DOMAIN, SERVICE_REMOVE_MCP_SERVER, handle_remove_mcp_server, schema=REMOVE_MCP_SERVER_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_CONVERSATION):
        hass.services.async_register(
            DOMAIN, SERVICE_CLEAR_CONVERSATION, handle_clear_conversation
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Unload conversation agent
        await async_unload_conversation(hass, entry)

        # Disconnect client
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        client: OpenAIRealtimeClient | None = data.get("client")
        if client:
            await client.disconnect()

        # Disconnect agent
        agent: OpenAIRealtimeConversationAgent | None = data.get("agent")
        if agent:
            await agent.async_disconnect()

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", entry.version)

    if entry.version == 1:
        # Future migration logic
        pass

    return True


def get_client(hass: HomeAssistant, entry_id: str) -> OpenAIRealtimeClient | None:
    """Get the OpenAI Realtime client for an entry."""
    if DOMAIN not in hass.data:
        return None
    entry_data = hass.data[DOMAIN].get(entry_id, {})
    return entry_data.get("client")


def get_mcp_handler(hass: HomeAssistant, entry_id: str) -> MCPServerHandler | None:
    """Get the MCP handler for an entry."""
    if DOMAIN not in hass.data:
        return None
    entry_data = hass.data[DOMAIN].get(entry_id, {})
    return entry_data.get("mcp_handler")
