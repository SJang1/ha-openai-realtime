"""Config flow for OpenAI Realtime integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_INSTRUCTIONS,
    CONF_MAX_OUTPUT_TOKENS,
    CONF_MCP_SERVER_NAME,
    CONF_MCP_SERVER_TOKEN,
    CONF_MCP_SERVER_URL,
    CONF_MCP_SERVERS,
    CONF_MODEL,
    CONF_TEMPERATURE,
    CONF_VOICE,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_VOICE,
    DOMAIN,
    MODELS,
    OPENAI_CLIENT_SECRET_URL,
    VOICES,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_key(hass: HomeAssistant, api_key: str) -> bool:
    """Validate the API key by attempting to create a client secret."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with session.post(
            OPENAI_CLIENT_SECRET_URL,
            headers=headers,
            json={
                "expires_after": {"anchor": "created_at", "seconds": 60},
                "session": {"type": "realtime", "model": DEFAULT_MODEL},
            },
        ) as response:
            return response.status == 200
    except aiohttp.ClientError:
        return False


class OpenAIRealtimeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenAI Realtime."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str | None = None
        self._mcp_servers: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]

            if await validate_api_key(self.hass, api_key):
                self._api_key = api_key
                return await self.async_step_configure()
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the integration settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            return await self.async_step_mcp_servers(user_input)

        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default="OpenAI Realtime"): str,
                    vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=MODELS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_VOICE, default=DEFAULT_VOICE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=VOICES,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_INSTRUCTIONS, default=DEFAULT_INSTRUCTIONS
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True,
                        )
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0,
                            max=2.0,
                            step=0.1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_MAX_OUTPUT_TOKENS, default=DEFAULT_MAX_OUTPUT_TOKENS
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=4096,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_mcp_servers(
        self, previous_input: dict[str, Any], user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure MCP servers."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("add_mcp_server"):
                # Add the MCP server
                self._mcp_servers.append(
                    {
                        CONF_MCP_SERVER_NAME: user_input.get(CONF_MCP_SERVER_NAME, ""),
                        CONF_MCP_SERVER_URL: user_input.get(CONF_MCP_SERVER_URL, ""),
                        CONF_MCP_SERVER_TOKEN: user_input.get(CONF_MCP_SERVER_TOKEN, ""),
                    }
                )
                # Show form again for more servers
                return self.async_show_form(
                    step_id="mcp_server_add",
                    data_schema=self._get_mcp_server_schema(),
                    errors=errors,
                    description_placeholders={
                        "server_count": str(len(self._mcp_servers))
                    },
                )
            else:
                # Done adding servers, create the entry
                return self._create_entry(previous_input)

        # First time here, ask if they want to add MCP servers
        return self.async_show_form(
            step_id="mcp_server_add",
            data_schema=self._get_mcp_server_schema(),
            errors=errors,
            description_placeholders={"server_count": str(len(self._mcp_servers))},
        )

    async def async_step_mcp_server_add(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add an MCP server."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_MCP_SERVER_URL):
                # Validate URL format
                url = user_input.get(CONF_MCP_SERVER_URL, "")
                if not url.startswith(("http://", "https://", "ws://", "wss://")):
                    errors[CONF_MCP_SERVER_URL] = "invalid_url"
                else:
                    self._mcp_servers.append(
                        {
                            CONF_MCP_SERVER_NAME: user_input.get(CONF_MCP_SERVER_NAME, f"MCP Server {len(self._mcp_servers) + 1}"),
                            CONF_MCP_SERVER_URL: url,
                            CONF_MCP_SERVER_TOKEN: user_input.get(CONF_MCP_SERVER_TOKEN, ""),
                        }
                    )

            if not user_input.get("add_another"):
                # Done adding servers
                return await self.async_step_finish()

        return self.async_show_form(
            step_id="mcp_server_add",
            data_schema=self._get_mcp_server_schema(),
            errors=errors,
            description_placeholders={"server_count": str(len(self._mcp_servers))},
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish the configuration."""
        # Retrieve stored config from context
        config = getattr(self, "_config", {})
        return self._create_entry(config)

    def _get_mcp_server_schema(self) -> vol.Schema:
        """Get the schema for MCP server configuration."""
        return vol.Schema(
            {
                vol.Optional(CONF_MCP_SERVER_NAME): str,
                vol.Optional(CONF_MCP_SERVER_URL): str,
                vol.Optional(CONF_MCP_SERVER_TOKEN): str,
                vol.Optional("add_another", default=False): bool,
            }
        )

    def _create_entry(self, config: dict[str, Any]) -> FlowResult:
        """Create the config entry."""
        data = {
            CONF_API_KEY: self._api_key,
            CONF_MODEL: config.get(CONF_MODEL, DEFAULT_MODEL),
            CONF_VOICE: config.get(CONF_VOICE, DEFAULT_VOICE),
            CONF_INSTRUCTIONS: config.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS),
            CONF_TEMPERATURE: config.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
            CONF_MAX_OUTPUT_TOKENS: config.get(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS),
            CONF_MCP_SERVERS: self._mcp_servers,
        }

        return self.async_create_entry(
            title=config.get(CONF_NAME, "OpenAI Realtime"),
            data=data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpenAIRealtimeOptionsFlow:
        """Get the options flow for this handler."""
        return OpenAIRealtimeOptionsFlow()


class OpenAIRealtimeOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for OpenAI Realtime."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._mcp_servers: list[dict[str, str]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        # Initialize MCP servers from config entry on first call
        if not self._mcp_servers:
            self._mcp_servers = list(
                self.config_entry.data.get(CONF_MCP_SERVERS, [])
            )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
                    CONF_VOICE: user_input.get(CONF_VOICE, DEFAULT_VOICE),
                    CONF_INSTRUCTIONS: user_input.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS),
                    CONF_TEMPERATURE: user_input.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                    CONF_MAX_OUTPUT_TOKENS: user_input.get(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS),
                    CONF_MCP_SERVERS: self._mcp_servers,
                },
            )

        current_config = {**self.config_entry.data, **self.config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MODEL,
                        default=current_config.get(CONF_MODEL, DEFAULT_MODEL),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=MODELS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_VOICE,
                        default=current_config.get(CONF_VOICE, DEFAULT_VOICE),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=VOICES,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_INSTRUCTIONS,
                        default=current_config.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True,
                        )
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE,
                        default=current_config.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0,
                            max=2.0,
                            step=0.1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_MAX_OUTPUT_TOKENS,
                        default=current_config.get(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=4096,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )
