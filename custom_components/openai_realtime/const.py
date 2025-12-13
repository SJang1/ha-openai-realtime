"""Constants for the OpenAI Realtime integration."""
from typing import Final

DOMAIN: Final = "openai_realtime"

# Configuration keys
CONF_API_KEY: Final = "api_key"
CONF_MODEL: Final = "model"
CONF_VOICE: Final = "voice"
CONF_INSTRUCTIONS: Final = "instructions"
CONF_MCP_SERVERS: Final = "mcp_servers"
CONF_MCP_SERVER_URL: Final = "url"
CONF_MCP_SERVER_NAME: Final = "name"
CONF_MCP_SERVER_TOKEN: Final = "token"
CONF_MCP_SERVER_TYPE: Final = "server_type"
CONF_MCP_SERVER_COMMAND: Final = "command"
CONF_MCP_SERVER_ARGS: Final = "args"
CONF_MCP_SERVER_ENV: Final = "env"
CONF_MCP_SERVER_ENABLED: Final = "enabled"
CONF_MCP_SERVER_TIMEOUT: Final = "timeout"
CONF_TEMPERATURE: Final = "temperature"
CONF_MAX_OUTPUT_TOKENS: Final = "max_output_tokens"
CONF_TURN_DETECTION: Final = "turn_detection"
CONF_INPUT_AUDIO_TRANSCRIPTION: Final = "input_audio_transcription"

# MCP Server Types
MCP_SERVER_TYPE_SSE: Final = "sse"
MCP_SERVER_TYPE_STDIO: Final = "stdio"
MCP_SERVER_TYPES: Final = [
    MCP_SERVER_TYPE_SSE,
    MCP_SERVER_TYPE_STDIO,
]

# Default values
DEFAULT_MODEL: Final = "gpt-realtime"
DEFAULT_VOICE: Final = "alloy"
DEFAULT_INSTRUCTIONS: Final = "I want you to act as smart home manager of Home Assistant.\nI will provide information of smart home along with a question, you will truthfully make correction or answer using information provided in one sentence in everyday language.\nUse MCP server to control or check anything."
DEFAULT_TEMPERATURE: Final = 0.8
DEFAULT_MAX_OUTPUT_TOKENS: Final = 4096

# Available voices
VOICES: Final = [
    "alloy",
    "echo",
    "fable",
    "onyx",
    "nova",
    "shimmer",
    "marin",
]

# Available models
MODELS: Final = [
    "gpt-realtime",
    "gpt-realtime-mini",
]

# API endpoints
OPENAI_REALTIME_WS_URL: Final = "wss://api.openai.com/v1/realtime"
OPENAI_REALTIME_REST_URL: Final = "https://api.openai.com/v1/realtime"
OPENAI_CLIENT_SECRET_URL: Final = "https://api.openai.com/v1/realtime/client_secrets"

# Audio settings
AUDIO_SAMPLE_RATE: Final = 24000
AUDIO_FORMAT: Final = "pcm16"

# Event types - Client events
EVENT_SESSION_UPDATE: Final = "session.update"
EVENT_INPUT_AUDIO_BUFFER_APPEND: Final = "input_audio_buffer.append"
EVENT_INPUT_AUDIO_BUFFER_COMMIT: Final = "input_audio_buffer.commit"
EVENT_INPUT_AUDIO_BUFFER_CLEAR: Final = "input_audio_buffer.clear"
EVENT_CONVERSATION_ITEM_CREATE: Final = "conversation.item.create"
EVENT_CONVERSATION_ITEM_TRUNCATE: Final = "conversation.item.truncate"
EVENT_CONVERSATION_ITEM_DELETE: Final = "conversation.item.delete"
EVENT_RESPONSE_CREATE: Final = "response.create"
EVENT_RESPONSE_CANCEL: Final = "response.cancel"

# Event types - Server events
EVENT_ERROR: Final = "error"
EVENT_SESSION_CREATED: Final = "session.created"
EVENT_SESSION_UPDATED: Final = "session.updated"
EVENT_CONVERSATION_ITEM_ADDED: Final = "conversation.item.added"
EVENT_CONVERSATION_ITEM_DONE: Final = "conversation.item.done"
EVENT_INPUT_AUDIO_BUFFER_COMMITTED: Final = "input_audio_buffer.committed"
EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED: Final = "input_audio_buffer.speech_started"
EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED: Final = "input_audio_buffer.speech_stopped"
EVENT_INPUT_AUDIO_TRANSCRIPTION_COMPLETED: Final = "conversation.item.input_audio_transcription.completed"
EVENT_RESPONSE_CREATED: Final = "response.created"
EVENT_RESPONSE_DONE: Final = "response.done"
EVENT_RESPONSE_OUTPUT_ITEM_ADDED: Final = "response.output_item.added"
EVENT_RESPONSE_OUTPUT_ITEM_DONE: Final = "response.output_item.done"
EVENT_RESPONSE_CONTENT_PART_ADDED: Final = "response.content_part.added"
EVENT_RESPONSE_CONTENT_PART_DONE: Final = "response.content_part.done"
EVENT_RESPONSE_OUTPUT_TEXT_DELTA: Final = "response.text.delta"
EVENT_RESPONSE_OUTPUT_TEXT_DONE: Final = "response.text.done"
EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DELTA: Final = "response.audio_transcript.delta"
EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE: Final = "response.audio_transcript.done"
EVENT_RESPONSE_OUTPUT_AUDIO_DELTA: Final = "response.audio.delta"
EVENT_RESPONSE_OUTPUT_AUDIO_DONE: Final = "response.audio.done"
EVENT_RESPONSE_FUNCTION_CALL_ARGUMENTS_DELTA: Final = "response.function_call_arguments.delta"
EVENT_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE: Final = "response.function_call_arguments.done"
EVENT_RESPONSE_MCP_CALL_ARGUMENTS_DELTA: Final = "response.mcp_call_arguments.delta"
EVENT_RESPONSE_MCP_CALL_ARGUMENTS_DONE: Final = "response.mcp_call_arguments.done"
EVENT_RESPONSE_MCP_CALL_IN_PROGRESS: Final = "response.mcp_call.in_progress"
EVENT_RESPONSE_MCP_CALL_COMPLETED: Final = "response.mcp_call.completed"
EVENT_RESPONSE_MCP_CALL_FAILED: Final = "response.mcp_call.failed"
EVENT_MCP_LIST_TOOLS_IN_PROGRESS: Final = "mcp_list_tools.in_progress"
EVENT_MCP_LIST_TOOLS_COMPLETED: Final = "mcp_list_tools.completed"
EVENT_MCP_LIST_TOOLS_FAILED: Final = "mcp_list_tools.failed"
EVENT_RATE_LIMITS_UPDATED: Final = "rate_limits.updated"

# Conversation item types
ITEM_TYPE_MESSAGE: Final = "message"
ITEM_TYPE_FUNCTION_CALL: Final = "function_call"
ITEM_TYPE_FUNCTION_CALL_OUTPUT: Final = "function_call_output"

# Roles
ROLE_USER: Final = "user"
ROLE_ASSISTANT: Final = "assistant"
ROLE_SYSTEM: Final = "system"

# Response status
STATUS_IN_PROGRESS: Final = "in_progress"
STATUS_COMPLETED: Final = "completed"
STATUS_CANCELLED: Final = "cancelled"
STATUS_FAILED: Final = "failed"
STATUS_INCOMPLETE: Final = "incomplete"
