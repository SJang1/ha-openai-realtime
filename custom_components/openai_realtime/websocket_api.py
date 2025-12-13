"""WebSocket API for OpenAI Realtime audio streaming."""
from __future__ import annotations

import base64
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED,
    EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED,
    EVENT_INPUT_AUDIO_TRANSCRIPTION_COMPLETED,
    EVENT_RESPONSE_DONE,
    EVENT_RESPONSE_OUTPUT_AUDIO_DELTA,
    EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DELTA,
    EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE,
    EVENT_RESPONSE_OUTPUT_TEXT_DELTA,
)
from .mcp_handler import HomeAssistantMCPTools
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Set up the WebSocket API."""
    websocket_api.async_register_command(hass, websocket_realtime_connect)
    websocket_api.async_register_command(hass, websocket_realtime_send_audio)
    websocket_api.async_register_command(hass, websocket_realtime_send_text)
    websocket_api.async_register_command(hass, websocket_realtime_commit_audio)
    websocket_api.async_register_command(hass, websocket_realtime_cancel)
    websocket_api.async_register_command(hass, websocket_realtime_disconnect)
    websocket_api.async_register_command(hass, websocket_realtime_subscribe)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/connect",
    }
)
@websocket_api.async_response
async def websocket_realtime_connect(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Connect to OpenAI Realtime API."""
    client = _get_client(hass)

    if not client:
        connection.send_error(msg["id"], "not_configured", "OpenAI Realtime not configured")
        return

    if not client.connected:
        success = await client.connect()
        if not success:
            connection.send_error(msg["id"], "connection_failed", "Failed to connect to OpenAI Realtime API")
            return

    connection.send_result(msg["id"], {"connected": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/send_audio",
        vol.Required("audio"): str,  # Base64 encoded PCM audio
    }
)
@websocket_api.async_response
async def websocket_realtime_send_audio(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send audio data to OpenAI Realtime API."""
    client = _get_client(hass)

    if not client or not client.connected:
        connection.send_error(msg["id"], "not_connected", "Not connected to OpenAI Realtime API")
        return

    try:
        audio_data = base64.b64decode(msg["audio"])
        await client.send_audio(audio_data)
        connection.send_result(msg["id"], {"sent": len(audio_data)})
    except Exception as e:
        connection.send_error(msg["id"], "send_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/send_text",
        vol.Required("text"): str,
    }
)
@websocket_api.async_response
async def websocket_realtime_send_text(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send text to OpenAI Realtime API."""
    client = _get_client(hass)

    if not client or not client.connected:
        connection.send_error(msg["id"], "not_connected", "Not connected to OpenAI Realtime API")
        return

    try:
        response = await client.send_text(msg["text"])
        connection.send_result(msg["id"], {
            "response_id": response.id,
            "text": response.text or response.audio_transcript,
            "status": response.status,
        })
    except Exception as e:
        connection.send_error(msg["id"], "send_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/commit_audio",
    }
)
@websocket_api.async_response
async def websocket_realtime_commit_audio(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Commit audio buffer to trigger response."""
    client = _get_client(hass)

    if not client or not client.connected:
        connection.send_error(msg["id"], "not_connected", "Not connected to OpenAI Realtime API")
        return

    try:
        await client.commit_audio()
        connection.send_result(msg["id"], {"committed": True})
    except Exception as e:
        connection.send_error(msg["id"], "commit_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/cancel",
    }
)
@websocket_api.async_response
async def websocket_realtime_cancel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Cancel current response."""
    client = _get_client(hass)

    if not client or not client.connected:
        connection.send_error(msg["id"], "not_connected", "Not connected to OpenAI Realtime API")
        return

    try:
        await client.cancel_response()
        await client.clear_audio_buffer()
        connection.send_result(msg["id"], {"cancelled": True})
    except Exception as e:
        connection.send_error(msg["id"], "cancel_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/disconnect",
    }
)
@websocket_api.async_response
async def websocket_realtime_disconnect(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Disconnect from OpenAI Realtime API."""
    client = _get_client(hass)

    if client:
        await client.disconnect()

    connection.send_result(msg["id"], {"disconnected": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openai_realtime/subscribe",
    }
)
@websocket_api.async_response
async def websocket_realtime_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to OpenAI Realtime events."""
    client = _get_client(hass)

    if not client:
        connection.send_error(msg["id"], "not_configured", "OpenAI Realtime not configured")
        return

    # Store subscription info
    subscription_id = msg["id"]

    async def on_speech_started(data: dict[str, Any]) -> None:
        """Handle speech started event - cancel current response if any."""
        # Only cancel if there's audio output in progress, not during function calls
        # Function calls need to complete before being cancelled
        _LOGGER.debug("Speech started event received")
        
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "speech_started",
                "audio_start_ms": data.get("audio_start_ms"),
            },
        })

    @callback
    def on_speech_stopped(data: dict[str, Any]) -> None:
        """Handle speech stopped event."""
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "speech_stopped",
                "audio_end_ms": data.get("audio_end_ms"),
            },
        })

    @callback
    def on_transcript_delta(data: dict[str, Any]) -> None:
        """Handle AI response transcript delta event."""
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "response_transcript_delta",
                "delta": data.get("delta", ""),
            },
        })

    @callback
    def on_transcript_done(data: dict[str, Any]) -> None:
        """Handle AI response transcript done event."""
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "response_transcript_done",
                "transcript": data.get("transcript", ""),
            },
        })

    @callback
    def on_audio_delta(data: dict[str, Any]) -> None:
        """Handle audio delta event."""
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "audio_delta",
                "audio": data.get("delta", ""),  # Already base64
            },
        })

    @callback
    def on_text_delta(data: dict[str, Any]) -> None:
        """Handle text delta event."""
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "text_delta",
                "delta": data.get("delta", ""),
            },
        })

    @callback
    def on_response_done(data: dict[str, Any]) -> None:
        """Handle response done event."""
        response = data.get("response", {})
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "response_done",
                "response_id": response.get("id"),
                "status": response.get("status"),
            },
        })

    @callback
    def on_user_transcript(data: dict[str, Any]) -> None:
        """Handle user input transcription completed event."""
        connection.send_message({
            "id": subscription_id,
            "type": "event",
            "event": {
                "type": "user_transcript",
                "transcript": data.get("transcript", ""),
            },
        })

    async def on_function_call(data: dict[str, Any]) -> None:
        """Handle function call from OpenAI."""
        call_id = data.get("call_id", "")
        name = data.get("name", "")
        arguments = data.get("arguments", {})  # Already parsed by realtime_client
        
        _LOGGER.info("Function call received in websocket_api: name=%s call_id=%s args=%s", name, call_id, arguments)
        
        # Check if this is an MCP server function call (format: server_name__tool_name)
        if "__" in name:
            mcp_handler = _get_mcp_handler(hass)
            if mcp_handler:
                parsed = mcp_handler.parse_function_name(name)
                if parsed:
                    server_name, tool_name = parsed
                    _LOGGER.info("Calling MCP server tool: server=%s tool=%s", server_name, tool_name)
                    try:
                        result = await mcp_handler.call_tool(server_name, tool_name, arguments)
                        _LOGGER.info("MCP tool result: %s", result)
                        
                        if client.connected:
                            await client.send_function_result(call_id, result)
                            _LOGGER.info("MCP tool result sent to OpenAI")
                        else:
                            _LOGGER.warning("Client not connected, cannot send MCP tool result")
                        return
                    except Exception as e:
                        _LOGGER.error("Error executing MCP tool %s: %s", name, e)
                        if client.connected:
                            await client.send_function_result(call_id, {"error": str(e)})
                        return
        
        # Execute the function using HomeAssistantMCPTools
        ha_tools = _get_ha_tools(hass)
        _LOGGER.info("ha_tools retrieved: %s", ha_tools is not None)
        
        if ha_tools and name in ["get_entity_state", "call_service", "get_entities_by_domain", "get_area_entities"]:
            try:
                result = await ha_tools.execute_tool(name, arguments)
                _LOGGER.info("Function result: %s", result)
                
                # Send result back to OpenAI
                if client.connected:
                    await client.send_function_result(call_id, result)
                    _LOGGER.info("Function result sent to OpenAI")
                else:
                    _LOGGER.warning("Client not connected, cannot send function result")
            except Exception as e:
                _LOGGER.error("Error executing function %s: %s", name, e)
                if client.connected:
                    await client.send_function_result(call_id, {"error": str(e)})
        else:
            _LOGGER.warning("Unknown function or no HA tools: %s (ha_tools=%s)", name, ha_tools is not None)
            if client.connected:
                await client.send_function_result(call_id, {"error": f"Unknown function: {name}"})

    # Register event handlers
    _LOGGER.info("Registering event handlers including function_call handler")
    client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED, on_speech_started)
    client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED, on_speech_stopped)
    client.on(EVENT_INPUT_AUDIO_TRANSCRIPTION_COMPLETED, on_user_transcript)
    client.on(EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DELTA, on_transcript_delta)
    client.on(EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE, on_transcript_done)
    client.on(EVENT_RESPONSE_OUTPUT_AUDIO_DELTA, on_audio_delta)
    client.on(EVENT_RESPONSE_OUTPUT_TEXT_DELTA, on_text_delta)
    client.on(EVENT_RESPONSE_DONE, on_response_done)
    client.on("function_call", on_function_call)  # Custom event emitted by realtime_client
    _LOGGER.info("Event handlers registered, function_call handlers count: %d", 
                 len(client._event_handlers.get("function_call", [])))

    # Cleanup when connection closes
    @callback
    def on_disconnect() -> None:
        """Handle WebSocket disconnect."""
        client.off(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED, on_speech_started)
        client.off(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED, on_speech_stopped)
        client.off(EVENT_INPUT_AUDIO_TRANSCRIPTION_COMPLETED, on_user_transcript)
        client.off(EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DELTA, on_transcript_delta)
        client.off(EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE, on_transcript_done)
        client.off(EVENT_RESPONSE_OUTPUT_AUDIO_DELTA, on_audio_delta)
        client.off(EVENT_RESPONSE_OUTPUT_TEXT_DELTA, on_text_delta)
        client.off(EVENT_RESPONSE_DONE, on_response_done)
        client.off("function_call", on_function_call)  # Custom event

    connection.subscriptions[subscription_id] = on_disconnect

    connection.send_result(msg["id"], {"subscribed": True})


def _get_client(hass: HomeAssistant) -> OpenAIRealtimeClient | None:
    """Get the OpenAI Realtime client."""
    if DOMAIN not in hass.data:
        return None

    for entry_id, data in hass.data[DOMAIN].items():
        # Skip special keys and non-dict entries
        if entry_id.startswith("_") or not isinstance(data, dict):
            continue
        client = data.get("client")
        if client:
            return client

    return None


def _get_ha_tools(hass: HomeAssistant) -> HomeAssistantMCPTools | None:
    """Get or create HomeAssistant MCP Tools instance."""
    if DOMAIN not in hass.data:
        return None

    for entry_id, data in hass.data[DOMAIN].items():
        # Skip special keys and non-dict entries
        if entry_id.startswith("_") or not isinstance(data, dict):
            continue
        # Try to get existing ha_tools or create new one
        if "ha_tools" in data:
            return data["ha_tools"]
        elif "client" in data:  # Only create for valid entry data
            ha_tools = HomeAssistantMCPTools(hass)
            data["ha_tools"] = ha_tools
            return ha_tools

    return None


def _get_mcp_handler(hass: HomeAssistant):
    """Get MCP handler instance."""
    from .mcp_handler import MCPServerHandler
    
    if DOMAIN not in hass.data:
        return None

    for entry_id, data in hass.data[DOMAIN].items():
        # Skip special keys and non-dict entries
        if entry_id.startswith("_") or not isinstance(data, dict):
            continue
        if "mcp_handler" in data:
            return data["mcp_handler"]

    return None
