"""TTS provider for OpenAI Realtime integration.

This provides text-to-speech using OpenAI Realtime API's native
audio output, bypassing the default HA TTS pipeline.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.tts import (
    Provider,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AUDIO_SAMPLE_RATE,
    CONF_VOICE,
    DEFAULT_VOICE,
    DOMAIN,
    EVENT_RESPONSE_OUTPUT_AUDIO_DONE,
    VOICES,
)
from .audio_processor import AudioProcessor
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenAI Realtime TTS provider."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: OpenAIRealtimeClient = data["client"]

    provider = OpenAIRealtimeTTSProvider(hass, entry, client)
    hass.data[DOMAIN][entry.entry_id]["tts_provider"] = provider


class OpenAIRealtimeTTSProvider(Provider):
    """OpenAI Realtime TTS provider."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OpenAIRealtimeClient,
    ) -> None:
        """Initialize the provider."""
        self.hass = hass
        self._entry = entry
        self._client = client
        self._audio_buffer: bytes = b""
        self._audio_ready = asyncio.Event()
        self._config = {**entry.data, **entry.options}

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return "en"

    @property
    def supported_languages(self) -> list[str]:
        """Return list of supported languages."""
        return ["en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko"]

    @property
    def supported_options(self) -> list[str]:
        """Return list of supported options."""
        return ["voice"]

    @property
    def default_options(self) -> dict[str, Any]:
        """Return default options."""
        return {
            "voice": self._config.get(CONF_VOICE, DEFAULT_VOICE),
        }

    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Return a list of supported voices for a language."""
        return [Voice(voice_id=v, name=v.title()) for v in VOICES]

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict[str, Any] | None = None,
    ) -> TtsAudioType:
        """Generate TTS audio from text."""
        if not self._client:
            return None, None

        # Ensure connected
        if not self._client.connected:
            connected = await self._client.connect()
            if not connected:
                return None, None

        # Reset state
        self._audio_buffer = b""
        self._audio_ready.clear()

        # Register audio handler
        async def on_audio_delta(data: dict[str, Any]) -> None:
            delta = data.get("delta", "")
            if delta:
                audio_bytes = AudioProcessor.decode_base64(delta)
                self._audio_buffer += audio_bytes

        async def on_audio_done(data: dict[str, Any]) -> None:
            self._audio_ready.set()

        self._client.on("response.output_audio.delta", on_audio_delta)
        self._client.on(EVENT_RESPONSE_OUTPUT_AUDIO_DONE, on_audio_done)

        try:
            # Send text and request audio response
            await self._client.send_text(message)

            # Wait for audio
            try:
                await asyncio.wait_for(self._audio_ready.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout waiting for TTS audio")
                return None, None

            if self._audio_buffer:
                # Convert PCM to WAV
                wav_data = AudioProcessor.pcm_to_wav(
                    self._audio_buffer,
                    AUDIO_SAMPLE_RATE,
                )
                return "wav", wav_data
            else:
                return None, None

        finally:
            self._client.off("response.output_audio.delta", on_audio_delta)
            self._client.off(EVENT_RESPONSE_OUTPUT_AUDIO_DONE, on_audio_done)
