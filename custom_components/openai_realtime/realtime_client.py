"""WebSocket client for OpenAI Realtime API."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import WSMsgType

from .const import (
    AUDIO_FORMAT,
    AUDIO_SAMPLE_RATE,
    CONF_MCP_SERVER_NAME,
    CONF_MCP_SERVER_TOKEN,
    CONF_MCP_SERVER_URL,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    EVENT_CONVERSATION_ITEM_ADDED,
    EVENT_CONVERSATION_ITEM_CREATE,
    EVENT_CONVERSATION_ITEM_DONE,
    EVENT_ERROR,
    EVENT_INPUT_AUDIO_BUFFER_APPEND,
    EVENT_INPUT_AUDIO_BUFFER_CLEAR,
    EVENT_INPUT_AUDIO_BUFFER_COMMIT,
    EVENT_MCP_LIST_TOOLS_COMPLETED,
    EVENT_MCP_LIST_TOOLS_FAILED,
    EVENT_MCP_LIST_TOOLS_IN_PROGRESS,
    EVENT_RATE_LIMITS_UPDATED,
    EVENT_RESPONSE_CANCEL,
    EVENT_RESPONSE_CONTENT_PART_ADDED,
    EVENT_RESPONSE_CONTENT_PART_DONE,
    EVENT_RESPONSE_CREATE,
    EVENT_RESPONSE_CREATED,
    EVENT_RESPONSE_DONE,
    EVENT_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE,
    EVENT_RESPONSE_MCP_CALL_COMPLETED,
    EVENT_RESPONSE_MCP_CALL_FAILED,
    EVENT_RESPONSE_MCP_CALL_IN_PROGRESS,
    EVENT_RESPONSE_OUTPUT_AUDIO_DELTA,
    EVENT_RESPONSE_OUTPUT_AUDIO_DONE,
    EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DELTA,
    EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE,
    EVENT_RESPONSE_OUTPUT_ITEM_ADDED,
    EVENT_RESPONSE_OUTPUT_ITEM_DONE,
    EVENT_RESPONSE_OUTPUT_TEXT_DELTA,
    EVENT_RESPONSE_OUTPUT_TEXT_DONE,
    EVENT_SESSION_CREATED,
    EVENT_SESSION_UPDATE,
    EVENT_SESSION_UPDATED,
    OPENAI_REALTIME_WS_URL,
    ROLE_ASSISTANT,
    ROLE_USER,
    STATUS_COMPLETED,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class RealtimeSession:
    """Represents a realtime session configuration."""

    model: str = DEFAULT_MODEL
    voice: str = DEFAULT_VOICE
    instructions: str = DEFAULT_INSTRUCTIONS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    temperature: float = 0.8
    tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, str]] = field(default_factory=list)
    turn_detection: dict[str, Any] | None = None
    input_audio_transcription: dict[str, Any] | None = None


@dataclass
class ConversationItem:
    """Represents a conversation item."""

    id: str
    type: str
    role: str | None = None
    content: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"


@dataclass
class RealtimeResponse:
    """Represents a response from the API."""

    id: str
    status: str
    output: list[ConversationItem] = field(default_factory=list)
    text: str = ""
    audio_transcript: str = ""
    audio_data: bytes = b""


class OpenAIRealtimeClient:
    """WebSocket client for OpenAI Realtime API."""

    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        session_config: RealtimeSession | None = None,
    ) -> None:
        """Initialize the client."""
        self._api_key = api_key
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session_config = session_config or RealtimeSession()
        self._connected = False
        self._event_handlers: dict[str, list[Callable]] = {}
        self._current_response: RealtimeResponse | None = None
        self._conversation_items: list[ConversationItem] = []
        self._listen_task: asyncio.Task | None = None
        self._response_futures: dict[str, asyncio.Future] = {}
        self._mcp_tools: dict[str, dict[str, Any]] = {}

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connected

    def on(self, event_type: str, handler: Callable) -> None:
        """Register an event handler."""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    def off(self, event_type: str, handler: Callable) -> None:
        """Remove an event handler."""
        if event_type in self._event_handlers:
            self._event_handlers[event_type].remove(handler)

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to registered handlers."""
        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    _LOGGER.error("Error in event handler for %s: %s", event_type, e)

    async def connect(self) -> bool:
        """Connect to the OpenAI Realtime API."""
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            }

            url = f"{OPENAI_REALTIME_WS_URL}?model={self._session_config.model}"

            self._ws = await self._session.ws_connect(
                url,
                headers=headers,
                heartbeat=30,
            )

            self._connected = True
            self._listen_task = asyncio.create_task(self._listen())

            _LOGGER.info("Connected to OpenAI Realtime API")
            return True

        except aiohttp.ClientError as e:
            _LOGGER.error("Failed to connect to OpenAI Realtime API: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the API."""
        self._connected = False

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        _LOGGER.info("Disconnected from OpenAI Realtime API")

    async def _listen(self) -> None:
        """Listen for messages from the WebSocket."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        _LOGGER.error("Failed to parse message: %s", e)
                elif msg.type == WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", msg.data)
                    break
                elif msg.type == WSMsgType.CLOSED:
                    _LOGGER.info("WebSocket closed")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Error in WebSocket listener: %s", e)
        finally:
            self._connected = False

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming WebSocket messages."""
        event_type = data.get("type", "")

        _LOGGER.debug("Received event: %s", event_type)

        # Log function call events specifically
        if "function" in event_type.lower():
            _LOGGER.info("Function-related event received: %s, data: %s", event_type, data)

        # Emit to any registered handlers
        await self._emit(event_type, data)

        # Handle specific events
        if event_type == EVENT_SESSION_CREATED:
            _LOGGER.info("Session created: %s", data.get("session", {}).get("id"))
            # Update session after creation
            await self.update_session()

        elif event_type == EVENT_SESSION_UPDATED:
            _LOGGER.info("Session updated")

        elif event_type == EVENT_ERROR:
            error = data.get("error", {})
            _LOGGER.error(
                "API Error: %s - %s",
                error.get("code"),
                error.get("message"),
            )

        elif event_type == EVENT_RESPONSE_CREATED:
            response_data = data.get("response", {})
            self._current_response = RealtimeResponse(
                id=response_data.get("id", ""),
                status=response_data.get("status", ""),
            )

        elif event_type == EVENT_RESPONSE_OUTPUT_TEXT_DELTA:
            if self._current_response:
                delta = data.get("delta", "")
                self._current_response.text += delta

        elif event_type == EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DELTA:
            if self._current_response:
                delta = data.get("delta", "")
                self._current_response.audio_transcript += delta

        elif event_type == EVENT_RESPONSE_OUTPUT_AUDIO_DELTA:
            if self._current_response:
                delta = data.get("delta", "")
                if delta:
                    audio_bytes = base64.b64decode(delta)
                    self._current_response.audio_data += audio_bytes

        elif event_type == EVENT_RESPONSE_DONE:
            response_data = data.get("response", {})
            if self._current_response:
                self._current_response.status = response_data.get("status", STATUS_COMPLETED)

                # Extract output items
                for output in response_data.get("output", []):
                    item = ConversationItem(
                        id=output.get("id", ""),
                        type=output.get("type", ""),
                        role=output.get("role"),
                        content=output.get("content", []),
                        status=output.get("status", "completed"),
                    )
                    self._current_response.output.append(item)

                # Resolve any waiting futures
                response_id = self._current_response.id
                if response_id in self._response_futures:
                    future = self._response_futures.pop(response_id)
                    if not future.done():
                        future.set_result(self._current_response)

        elif event_type == EVENT_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            # Handle function call completion
            _LOGGER.info("Received function call event from OpenAI: %s", data)
            await self._handle_function_call(data)

        elif event_type == EVENT_RESPONSE_MCP_CALL_COMPLETED:
            _LOGGER.info("MCP call completed: %s", data.get("item_id"))

        elif event_type == EVENT_RESPONSE_MCP_CALL_FAILED:
            _LOGGER.error("MCP call failed: %s", data.get("item_id"))

        elif event_type == EVENT_MCP_LIST_TOOLS_COMPLETED:
            _LOGGER.info("MCP tools listed: %s", data.get("item_id"))

        elif event_type == EVENT_CONVERSATION_ITEM_ADDED:
            item_data = data.get("item", {})
            item = ConversationItem(
                id=item_data.get("id", ""),
                type=item_data.get("type", ""),
                role=item_data.get("role"),
                content=item_data.get("content", []),
                status=item_data.get("status", "completed"),
            )
            self._conversation_items.append(item)

    async def _handle_function_call(self, data: dict[str, Any]) -> None:
        """Handle a function call from the model."""
        call_id = data.get("call_id", "")
        item_id = data.get("item_id", "")
        name = data.get("name", "")  # Function name
        arguments_str = data.get("arguments", "{}")

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            arguments = {}

        _LOGGER.info("Function call: name=%s call_id=%s args=%s", name, call_id, arguments)

        # Emit function call event for external handling
        await self._emit("function_call", {
            "call_id": call_id,
            "item_id": item_id,
            "name": name,
            "arguments": arguments,
        })

    async def send(self, event: dict[str, Any]) -> None:
        """Send an event to the API."""
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")

        if "event_id" not in event:
            event["event_id"] = str(uuid.uuid4())

        await self._ws.send_json(event)
        _LOGGER.debug("Sent event: %s", event.get("type"))

    async def update_session(self) -> None:
        """Update the session configuration."""
        # Ensure max_output_tokens is either an integer or "inf"
        max_tokens = self._session_config.max_output_tokens
        if max_tokens is None or max_tokens == 0:
            max_tokens_value: int | str = "inf"
        elif isinstance(max_tokens, float):
            max_tokens_value = int(max_tokens)
        else:
            max_tokens_value = max_tokens
        
        session_update: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "instructions": self._session_config.instructions,
            "voice": self._session_config.voice,
            "input_audio_format": AUDIO_FORMAT,
            "output_audio_format": AUDIO_FORMAT,
            "input_audio_transcription": {
                "model": "whisper-1",
            },
            "turn_detection": self._session_config.turn_detection or {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "create_response": True,
            },
            "tools": self._session_config.tools,
            "tool_choice": "auto",
            "temperature": self._session_config.temperature,
            "max_response_output_tokens": max_tokens_value,
        }

        # Add MCP servers if configured
        if self._session_config.mcp_servers:
            mcp_tools: list[dict[str, Any]] = []
            for server in self._session_config.mcp_servers:
                mcp_tool: dict[str, Any] = {
                    "type": "mcp",
                    "server_label": server.get(CONF_MCP_SERVER_NAME, "mcp_server"),
                    "server_url": server.get(CONF_MCP_SERVER_URL, ""),
                    "require_approval": "never",
                }
                if server.get(CONF_MCP_SERVER_TOKEN):
                    mcp_tool["headers"] = {
                        "Authorization": f"Bearer {server[CONF_MCP_SERVER_TOKEN]}"
                    }
                mcp_tools.append(mcp_tool)

            session_update["tools"] = self._session_config.tools + mcp_tools

        _LOGGER.info("Updating session with %d tools: %s", 
                     len(session_update.get("tools", [])),
                     [t.get("name") for t in session_update.get("tools", []) if t.get("type") == "function"])

        await self.send({
            "type": EVENT_SESSION_UPDATE,
            "session": session_update,
        })

    async def send_text(self, text: str) -> RealtimeResponse:
        """Send a text message and wait for response."""
        # Create conversation item
        await self.send({
            "type": EVENT_CONVERSATION_ITEM_CREATE,
            "item": {
                "type": "message",
                "role": ROLE_USER,
                "content": [
                    {
                        "type": "input_text",
                        "text": text,
                    }
                ],
            },
        })

        # Create response
        response_future: asyncio.Future[RealtimeResponse] = asyncio.get_event_loop().create_future()

        await self.send({
            "type": EVENT_RESPONSE_CREATE,
        })

        # Wait for response with timeout
        try:
            # Store future temporarily
            temp_id = str(uuid.uuid4())
            self._response_futures[temp_id] = response_future

            # Listen for response.created to get actual ID
            async def on_response_created(data: dict[str, Any]) -> None:
                response_id = data.get("response", {}).get("id", "")
                if response_id and temp_id in self._response_futures:
                    self._response_futures[response_id] = self._response_futures.pop(temp_id)

            self.on(EVENT_RESPONSE_CREATED, on_response_created)

            response = await asyncio.wait_for(response_future, timeout=60.0)

            self.off(EVENT_RESPONSE_CREATED, on_response_created)

            return response

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for response")
            raise

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to the input buffer."""
        encoded = base64.b64encode(audio_data).decode("utf-8")

        await self.send({
            "type": EVENT_INPUT_AUDIO_BUFFER_APPEND,
            "audio": encoded,
        })

    async def commit_audio(self) -> None:
        """Commit the audio buffer."""
        await self.send({
            "type": EVENT_INPUT_AUDIO_BUFFER_COMMIT,
        })

    async def clear_audio_buffer(self) -> None:
        """Clear the audio buffer."""
        await self.send({
            "type": EVENT_INPUT_AUDIO_BUFFER_CLEAR,
        })

    async def cancel_response(self, response_id: str | None = None) -> None:
        """Cancel an in-progress response."""
        event: dict[str, Any] = {"type": EVENT_RESPONSE_CANCEL}
        if response_id:
            event["response_id"] = response_id
        await self.send(event)

    def add_tool(self, tool: dict[str, Any]) -> None:
        """Add a function tool to the session."""
        self._session_config.tools.append(tool)

    def add_mcp_server(self, name: str, url: str, token: str | None = None) -> None:
        """Add an MCP server to the session."""
        server = {
            CONF_MCP_SERVER_NAME: name,
            CONF_MCP_SERVER_URL: url,
        }
        if token:
            server[CONF_MCP_SERVER_TOKEN] = token
        self._session_config.mcp_servers.append(server)

    async def send_function_result(
        self, call_id: str, result: dict[str, Any] | str
    ) -> None:
        """Send a function call result back to the API."""
        if isinstance(result, dict):
            result_str = json.dumps(result)
        else:
            result_str = str(result)

        _LOGGER.info("Sending function result for call_id=%s: %s", call_id, result_str[:200])

        await self.send({
            "type": EVENT_CONVERSATION_ITEM_CREATE,
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result_str,
            },
        })

        # Trigger a new response
        await self.send({
            "type": EVENT_RESPONSE_CREATE,
        })

    def get_conversation_history(self) -> list[ConversationItem]:
        """Get the conversation history."""
        return self._conversation_items.copy()

    def clear_conversation(self) -> None:
        """Clear the conversation history."""
        self._conversation_items.clear()
