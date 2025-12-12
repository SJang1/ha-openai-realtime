"""Binary sensor platform for OpenAI Realtime status."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED,
    EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED,
    EVENT_RESPONSE_CREATED,
    EVENT_RESPONSE_DONE,
    EVENT_SESSION_CREATED,
)
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenAI Realtime binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: OpenAIRealtimeClient = data["client"]

    entities = [
        OpenAIRealtimeConnectionSensor(hass, entry, client),
        OpenAIRealtimeListeningSensor(hass, entry, client),
        OpenAIRealtimeSpeakingSensor(hass, entry, client),
        OpenAIRealtimeProcessingSensor(hass, entry, client),
    ]

    async_add_entities(entities)


class OpenAIRealtimeBaseSensor(BinarySensorEntity):
    """Base class for OpenAI Realtime sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._client = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="OpenAI Realtime",
            manufacturer="OpenAI",
            model="Realtime API",
        )


class OpenAIRealtimeConnectionSensor(OpenAIRealtimeBaseSensor):
    """Sensor for connection status."""

    _attr_name = "Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, client)
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return if connected."""
        return self._client.connected if self._client else False

    async def async_added_to_hass(self) -> None:
        """Register event handlers."""
        if self._client:
            self._client.on(EVENT_SESSION_CREATED, self._on_session_created)

    @callback
    def _on_session_created(self, data: dict[str, Any]) -> None:
        """Handle session created event."""
        self._is_on = True
        self.async_write_ha_state()


class OpenAIRealtimeListeningSensor(OpenAIRealtimeBaseSensor):
    """Sensor for listening status."""

    _attr_name = "Listening"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, client)
        self._attr_unique_id = f"{entry.entry_id}_listening"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return if listening."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Register event handlers."""
        if self._client:
            self._client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED, self._on_speech_started)
            self._client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED, self._on_speech_stopped)

    @callback
    def _on_speech_started(self, data: dict[str, Any]) -> None:
        """Handle speech started event."""
        self._is_on = True
        self.async_write_ha_state()

    @callback
    def _on_speech_stopped(self, data: dict[str, Any]) -> None:
        """Handle speech stopped event."""
        self._is_on = False
        self.async_write_ha_state()


class OpenAIRealtimeSpeakingSensor(OpenAIRealtimeBaseSensor):
    """Sensor for speaking status."""

    _attr_name = "Speaking"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, client)
        self._attr_unique_id = f"{entry.entry_id}_speaking"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return if speaking."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Register event handlers."""
        if self._client:
            self._client.on(EVENT_RESPONSE_CREATED, self._on_response_created)
            self._client.on(EVENT_RESPONSE_DONE, self._on_response_done)

    @callback
    def _on_response_created(self, data: dict[str, Any]) -> None:
        """Handle response created event."""
        self._is_on = True
        self.async_write_ha_state()

    @callback
    def _on_response_done(self, data: dict[str, Any]) -> None:
        """Handle response done event."""
        self._is_on = False
        self.async_write_ha_state()


class OpenAIRealtimeProcessingSensor(OpenAIRealtimeBaseSensor):
    """Sensor for processing status."""

    _attr_name = "Processing"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, client)
        self._attr_unique_id = f"{entry.entry_id}_processing"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return if processing."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Register event handlers."""
        if self._client:
            self._client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED, self._on_processing_start)
            self._client.on(EVENT_RESPONSE_CREATED, self._on_processing_start)
            self._client.on(EVENT_RESPONSE_DONE, self._on_processing_done)

    @callback
    def _on_processing_start(self, data: dict[str, Any]) -> None:
        """Handle processing start."""
        self._is_on = True
        self.async_write_ha_state()

    @callback
    def _on_processing_done(self, data: dict[str, Any]) -> None:
        """Handle processing done."""
        self._is_on = False
        self.async_write_ha_state()
