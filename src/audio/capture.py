"""
Audio capture module using sounddevice.
Records microphone input into a buffer for processing.
"""

import collections
import logging
import struct
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures audio from the microphone using sounddevice."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 30,
        device_index: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        self.device_index = device_index

        # Calculate frames per chunk
        self.frames_per_chunk = int(sample_rate * chunk_duration_ms / 1000)

        # Callback for delivering audio chunks
        self._on_audio_chunk: Optional[Callable[[bytes], None]] = None

        # Callback for audio level (0.0 - 1.0 RMS)
        self._on_audio_level: Optional[Callable[[float], None]] = None

        # Stream reference
        self._stream: Optional[sd.RawInputStream] = None
        self._is_recording = False
        self._lock = threading.Lock()

        # Buffer for accumulating audio during push-to-talk
        self._audio_buffer: list[bytes] = []
        self._is_buffering = False

        # Adaptive RMS tracking for level normalization
        # Start at a reasonable default so first few frames aren't spiked
        self._rms_peak: float = 50.0

    def set_audio_callback(self, callback: Callable[[bytes], None]):
        """Set the callback function that receives raw audio chunks (16-bit PCM)."""
        self._on_audio_chunk = callback

    def set_level_callback(self, callback: Callable[[float], None]):
        """Set a callback that receives normalized RMS audio level (0.0 - 1.0)."""
        self._on_audio_level = callback

    def _audio_callback(self, indata, frames, time_info, status):
        """Internal sounddevice callback - runs in audio thread."""
        if status:
            logger.warning(f"Audio stream status: {status}")

        # indata is a bytes object (raw 16-bit PCM)
        raw_bytes = bytes(indata)

        if self._on_audio_chunk:
            self._on_audio_chunk(raw_bytes)

        # Calculate and report audio level during buffering
        if self._is_buffering:
            self._audio_buffer.append(raw_bytes)

            if self._on_audio_level:
                try:
                    samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(
                        np.float32
                    )
                    rms = np.sqrt(np.mean(samples**2))

                    # Adaptive normalization: track running peak RMS
                    # This auto-scales to any mic volume (even very quiet
                    # virtual devices like SteelSeries Sonar)
                    if rms > self._rms_peak:
                        # Ramp UP quickly when louder audio comes in
                        self._rms_peak = rms
                    else:
                        # Decay slowly so brief pauses don't spike
                        self._rms_peak *= 0.998

                    # Normalize against peak with perceptual curve
                    if self._rms_peak > 0.1:
                        level = min(1.0, (rms / self._rms_peak) ** 0.5)
                    else:
                        level = 0.0
                    self._on_audio_level(level)
                except Exception as e:
                    logger.debug(f"Audio level callback error: {e}")

    def start_stream(self):
        """Start the audio input stream."""
        with self._lock:
            if self._is_recording:
                logger.warning("Audio stream already running")
                return

            logger.info(
                f"Starting audio capture: {self.sample_rate}Hz, "
                f"{self.channels}ch, {self.chunk_duration_ms}ms chunks, "
                f"device={self.device_index or 'default'}"
            )

            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.frames_per_chunk,
                dtype="int16",
                channels=self.channels,
                callback=self._audio_callback,
                device=self.device_index,
            )
            self._stream.start()
            self._is_recording = True
            logger.info("Audio capture started")

    def stop_stream(self):
        """Stop the audio input stream."""
        with self._lock:
            if not self._is_recording:
                return

            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

            self._is_recording = False
            logger.info("Audio capture stopped")

    def start_buffering(self):
        """Start buffering audio data (for push-to-talk)."""
        self._audio_buffer.clear()
        self._rms_peak = 50.0  # Reset to conservative default (adapts up quickly)
        self._is_buffering = True
        logger.debug("Audio buffering started")

    def stop_buffering(self) -> bytes:
        """Stop buffering and return accumulated audio as a single bytes object."""
        self._is_buffering = False
        result = b"".join(self._audio_buffer)
        self._audio_buffer.clear()
        logger.debug(f"Audio buffering stopped, captured {len(result)} bytes")
        return result

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @staticmethod
    def list_devices() -> str:
        """List available audio input devices."""
        return sd.query_devices()

    @staticmethod
    def get_default_input_device() -> dict:
        """Get information about the default input device."""
        device_id = sd.default.device[0]
        return sd.query_devices(device_id)
