"""Media player platform for OpenAI Realtime audio handling."""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from homeassistant.components import media_player
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AUDIO_SAMPLE_RATE,
    DOMAIN,
    EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED,
    EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED,
    EVENT_RESPONSE_DONE,
    EVENT_RESPONSE_OUTPUT_AUDIO_DELTA,
    EVENT_RESPONSE_OUTPUT_AUDIO_DONE,
)
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenAI Realtime media player."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: OpenAIRealtimeClient = data["client"]

    async_add_entities([OpenAIRealtimeMediaPlayer(hass, entry, client)])


class OpenAIRealtimeMediaPlayer(MediaPlayerEntity):
    """Media player for OpenAI Realtime audio I/O."""

    _attr_has_entity_name = True
    _attr_name = "Realtime Audio"
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
    )
    _attr_media_content_type = MediaType.MUSIC
    _attr_device_class = media_player.MediaPlayerDeviceClass.SPEAKER

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the media player."""
        self.hass = hass
        self._entry = entry
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="OpenAI Realtime",
            manufacturer="OpenAI",
            model="Realtime API",
        )
        self._state = MediaPlayerState.IDLE
        self._volume = 1.0
        self._is_speaking = False
        self._is_listening = False
        self._audio_buffer: bytes = b""
        self._response_audio: bytes = b""

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        return self._state

    @property
    def volume_level(self) -> float:
        """Return the volume level."""
        return self._volume

    @property
    def is_speaking(self) -> bool:
        """Return if the assistant is speaking."""
        return self._is_speaking

    @property
    def is_listening(self) -> bool:
        """Return if the assistant is listening."""
        return self._is_listening

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "is_speaking": self._is_speaking,
            "is_listening": self._is_listening,
            "audio_buffer_size": len(self._audio_buffer),
            "response_audio_size": len(self._response_audio),
            "connected": self._client.connected if self._client else False,
        }

    async def async_added_to_hass(self) -> None:
        """Register event handlers when entity is added."""
        if self._client:
            self._client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED, self._on_speech_started)
            self._client.on(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED, self._on_speech_stopped)
            self._client.on(EVENT_RESPONSE_OUTPUT_AUDIO_DELTA, self._on_audio_delta)
            self._client.on(EVENT_RESPONSE_OUTPUT_AUDIO_DONE, self._on_audio_done)
            self._client.on(EVENT_RESPONSE_DONE, self._on_response_done)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister event handlers when entity is removed."""
        if self._client:
            self._client.off(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STARTED, self._on_speech_started)
            self._client.off(EVENT_INPUT_AUDIO_BUFFER_SPEECH_STOPPED, self._on_speech_stopped)
            self._client.off(EVENT_RESPONSE_OUTPUT_AUDIO_DELTA, self._on_audio_delta)
            self._client.off(EVENT_RESPONSE_OUTPUT_AUDIO_DONE, self._on_audio_done)
            self._client.off(EVENT_RESPONSE_DONE, self._on_response_done)

    @callback
    def _on_speech_started(self, data: dict[str, Any]) -> None:
        """Handle speech started event."""
        self._is_listening = True
        self._state = MediaPlayerState.BUFFERING
        self.async_write_ha_state()

    @callback
    def _on_speech_stopped(self, data: dict[str, Any]) -> None:
        """Handle speech stopped event."""
        self._is_listening = False
        self.async_write_ha_state()

    @callback
    def _on_audio_delta(self, data: dict[str, Any]) -> None:
        """Handle audio delta event."""
        delta = data.get("delta", "")
        if delta:
            audio_bytes = base64.b64decode(delta)
            self._response_audio += audio_bytes
            if not self._is_speaking:
                self._is_speaking = True
                self._state = MediaPlayerState.PLAYING
                self.async_write_ha_state()

    @callback
    def _on_audio_done(self, data: dict[str, Any]) -> None:
        """Handle audio done event."""
        pass  # Audio may still be playing

    @callback
    def _on_response_done(self, data: dict[str, Any]) -> None:
        """Handle response done event."""
        self._is_speaking = False
        self._state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Start listening for audio input."""
        if not self._client.connected:
            await self._client.connect()
        self._state = MediaPlayerState.BUFFERING
        self._is_listening = True
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop audio processing."""
        if self._client:
            await self._client.cancel_response()
            await self._client.clear_audio_buffer()
        self._state = MediaPlayerState.IDLE
        self._is_listening = False
        self._is_speaking = False
        self._audio_buffer = b""
        self._response_audio = b""
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level."""
        self._volume = volume
        self.async_write_ha_state()

    async def async_send_audio(self, audio_data: bytes) -> None:
        """Send audio data to the Realtime API."""
        if not self._client:
            _LOGGER.error("Client not initialized")
            return

        if not self._client.connected:
            await self._client.connect()

        await self._client.send_audio(audio_data)
        self._audio_buffer += audio_data

    async def async_commit_audio(self) -> None:
        """Commit the audio buffer for processing."""
        if self._client:
            await self._client.commit_audio()
            self._audio_buffer = b""

    async def async_clear_audio(self) -> None:
        """Clear the audio buffer."""
        if self._client:
            await self._client.clear_audio_buffer()
        self._audio_buffer = b""
        self._response_audio = b""

    def get_response_audio(self) -> bytes:
        """Get the response audio data."""
        audio = self._response_audio
        self._response_audio = b""
        return audio
