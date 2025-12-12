"""Audio processing helper for OpenAI Realtime integration."""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import struct
import wave
from dataclasses import dataclass, field
from typing import Any, Callable

from .const import AUDIO_SAMPLE_RATE

_LOGGER = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    """Audio configuration."""

    sample_rate: int = AUDIO_SAMPLE_RATE
    channels: int = 1
    sample_width: int = 2  # 16-bit
    chunk_size: int = 4800  # 200ms at 24kHz


@dataclass
class AudioBuffer:
    """Circular audio buffer for streaming."""

    max_size: int = 24000 * 60  # 60 seconds at 24kHz
    data: bytes = field(default_factory=bytes)

    def append(self, audio: bytes) -> None:
        """Append audio data to buffer."""
        self.data += audio
        # Trim if exceeds max size
        if len(self.data) > self.max_size:
            self.data = self.data[-self.max_size:]

    def get_and_clear(self) -> bytes:
        """Get buffer contents and clear."""
        data = self.data
        self.data = b""
        return data

    def clear(self) -> None:
        """Clear the buffer."""
        self.data = b""

    def __len__(self) -> int:
        """Return buffer size."""
        return len(self.data)


class AudioProcessor:
    """Process audio for OpenAI Realtime API."""

    def __init__(self, config: AudioConfig | None = None) -> None:
        """Initialize the audio processor."""
        self.config = config or AudioConfig()
        self._input_buffer = AudioBuffer()
        self._output_buffer = AudioBuffer()
        self._on_audio_callback: Callable[[bytes], None] | None = None

    def set_audio_callback(self, callback: Callable[[bytes], None]) -> None:
        """Set callback for processed audio output."""
        self._on_audio_callback = callback

    def process_input(self, audio_data: bytes) -> bytes:
        """Process input audio for the API.
        
        Converts audio to PCM 16-bit 24kHz mono if needed.
        """
        # Assuming input is already in correct format
        # Add resampling logic here if needed
        self._input_buffer.append(audio_data)
        return audio_data

    def process_output(self, audio_data: bytes) -> bytes:
        """Process output audio from the API.
        
        The API returns PCM 16-bit 24kHz audio.
        """
        self._output_buffer.append(audio_data)
        if self._on_audio_callback:
            self._on_audio_callback(audio_data)
        return audio_data

    def get_input_buffer(self) -> bytes:
        """Get and clear input buffer."""
        return self._input_buffer.get_and_clear()

    def get_output_buffer(self) -> bytes:
        """Get and clear output buffer."""
        return self._output_buffer.get_and_clear()

    def clear_buffers(self) -> None:
        """Clear all buffers."""
        self._input_buffer.clear()
        self._output_buffer.clear()

    @staticmethod
    def pcm_to_wav(pcm_data: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> bytes:
        """Convert PCM data to WAV format."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return buffer.getvalue()

    @staticmethod
    def wav_to_pcm(wav_data: bytes) -> tuple[bytes, int]:
        """Convert WAV data to PCM format.
        
        Returns (pcm_data, sample_rate).
        """
        buffer = io.BytesIO(wav_data)
        with wave.open(buffer, "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            pcm_data = wav_file.readframes(wav_file.getnframes())
        return pcm_data, sample_rate

    @staticmethod
    def resample(
        audio_data: bytes,
        from_rate: int,
        to_rate: int,
    ) -> bytes:
        """Simple resampling using linear interpolation.
        
        For production, consider using scipy or librosa.
        """
        if from_rate == to_rate:
            return audio_data

        # Unpack 16-bit samples
        samples = struct.unpack(f"<{len(audio_data) // 2}h", audio_data)

        # Calculate new length
        ratio = to_rate / from_rate
        new_length = int(len(samples) * ratio)

        # Linear interpolation
        resampled = []
        for i in range(new_length):
            src_idx = i / ratio
            idx = int(src_idx)
            frac = src_idx - idx

            if idx + 1 < len(samples):
                value = samples[idx] * (1 - frac) + samples[idx + 1] * frac
            else:
                value = samples[idx] if idx < len(samples) else 0

            resampled.append(int(value))

        # Pack back to bytes
        return struct.pack(f"<{len(resampled)}h", *resampled)

    @staticmethod
    def encode_base64(audio_data: bytes) -> str:
        """Encode audio to base64."""
        return base64.b64encode(audio_data).decode("utf-8")

    @staticmethod
    def decode_base64(encoded: str) -> bytes:
        """Decode base64 audio."""
        return base64.b64decode(encoded)

    @staticmethod
    def calculate_duration_ms(audio_data: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> int:
        """Calculate audio duration in milliseconds."""
        # 16-bit mono audio = 2 bytes per sample
        samples = len(audio_data) // 2
        return int(samples * 1000 / sample_rate)


class AudioStreamHandler:
    """Handle streaming audio input/output."""

    def __init__(
        self,
        processor: AudioProcessor | None = None,
        chunk_duration_ms: int = 100,
    ) -> None:
        """Initialize the stream handler."""
        self.processor = processor or AudioProcessor()
        self.chunk_duration_ms = chunk_duration_ms
        self._chunk_size = int(
            AUDIO_SAMPLE_RATE * chunk_duration_ms / 1000 * 2
        )  # 16-bit = 2 bytes
        self._input_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start the stream handler."""
        self._running = True

    async def stop(self) -> None:
        """Stop the stream handler."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def put_input(self, audio: bytes) -> None:
        """Add input audio to the queue."""
        await self._input_queue.put(audio)

    async def get_input_chunk(self) -> bytes | None:
        """Get a chunk of input audio."""
        if self._input_queue.empty():
            return None

        chunks = []
        total_size = 0

        while total_size < self._chunk_size and not self._input_queue.empty():
            try:
                chunk = self._input_queue.get_nowait()
                chunks.append(chunk)
                total_size += len(chunk)
            except asyncio.QueueEmpty:
                break

        if chunks:
            return b"".join(chunks)
        return None

    async def put_output(self, audio: bytes) -> None:
        """Add output audio to the queue."""
        await self._output_queue.put(audio)

    async def get_output(self) -> bytes | None:
        """Get output audio."""
        try:
            return await asyncio.wait_for(self._output_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    def clear_queues(self) -> None:
        """Clear all queues."""
        while not self._input_queue.empty():
            try:
                self._input_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        while not self._output_queue.empty():
            try:
                self._output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
