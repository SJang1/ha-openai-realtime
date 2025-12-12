"""STT provider for OpenAI Realtime integration.

This provides speech-to-text using OpenAI Realtime API's native
audio transcription, bypassing the default HA STT pipeline.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable
from typing import Any

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    Provider,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AUDIO_SAMPLE_RATE,
    DOMAIN,
    EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE,
)
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenAI Realtime STT provider."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: OpenAIRealtimeClient = data["client"]

    provider = OpenAIRealtimeSTTProvider(hass, entry, client)
    hass.data[DOMAIN][entry.entry_id]["stt_provider"] = provider


class OpenAIRealtimeSTTProvider(Provider):
    """OpenAI Realtime STT provider."""

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
        self._transcript: str = ""
        self._transcript_ready = asyncio.Event()

    @property
    def supported_languages(self) -> list[str]:
        """Return list of supported languages."""
        # OpenAI supports many languages
        return ["en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko"]

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return list of supported audio formats."""
        return [AudioFormats.WAV, AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return list of supported audio codecs."""
        return [AudioCodecs.PCM, AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return list of supported bit rates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return list of supported sample rates."""
        return [
            AudioSampleRates.SAMPLERATE_16000,
            AudioSampleRates.SAMPLERATE_44100,
            AudioSampleRates.SAMPLERATE_48000,
        ]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return list of supported audio channels."""
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self,
        metadata: SpeechMetadata,
        stream: AsyncIterable[bytes],
    ) -> SpeechResult:
        """Process audio stream and return transcript."""
        if not self._client:
            return SpeechResult(
                text=None,
                result=SpeechResultState.ERROR,
            )

        # Ensure connected
        if not self._client.connected:
            connected = await self._client.connect()
            if not connected:
                return SpeechResult(
                    text=None,
                    result=SpeechResultState.ERROR,
                )

        # Reset state
        self._transcript = ""
        self._transcript_ready.clear()

        # Register transcript handler
        async def on_transcript_done(data: dict[str, Any]) -> None:
            self._transcript = data.get("transcript", "")
            self._transcript_ready.set()

        self._client.on(EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE, on_transcript_done)

        try:
            # Stream audio to API
            async for chunk in stream:
                # Convert to correct format if needed
                audio_data = self._convert_audio(chunk, metadata)
                await self._client.send_audio(audio_data)

            # Commit the audio buffer
            await self._client.commit_audio()

            # Wait for transcript
            try:
                await asyncio.wait_for(self._transcript_ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                return SpeechResult(
                    text=None,
                    result=SpeechResultState.ERROR,
                )

            if self._transcript:
                return SpeechResult(
                    text=self._transcript,
                    result=SpeechResultState.SUCCESS,
                )
            else:
                return SpeechResult(
                    text=None,
                    result=SpeechResultState.ERROR,
                )

        finally:
            self._client.off(EVENT_RESPONSE_OUTPUT_AUDIO_TRANSCRIPT_DONE, on_transcript_done)

    def _convert_audio(self, audio: bytes, metadata: SpeechMetadata) -> bytes:
        """Convert audio to format expected by API (PCM 24kHz)."""
        from .audio_processor import AudioProcessor

        # If sample rate differs, resample
        if metadata.sample_rate != AUDIO_SAMPLE_RATE:
            audio = AudioProcessor.resample(
                audio,
                metadata.sample_rate,
                AUDIO_SAMPLE_RATE,
            )

        return audio
