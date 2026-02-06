"""
Voice Activity Detection module using webrtcvad.
Detects speech segments in audio stream.
"""

import collections
import logging
from typing import Callable, Optional

import webrtcvad

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """
    Detects speech in audio chunks using WebRTC VAD.

    Used in push-to-talk mode to trim silence from the beginning
    and end of recordings, improving transcription quality.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 30,
        aggressiveness: int = 2,
        min_speech_duration: float = 0.5,
        silence_duration: float = 0.8,
        pre_speech_pad: float = 0.3,
    ):
        """
        Args:
            sample_rate: Audio sample rate (must be 8000, 16000, 32000, or 48000)
            chunk_duration_ms: Duration of each audio chunk (must be 10, 20, or 30)
            aggressiveness: VAD aggressiveness (0-3, higher = more aggressive)
            min_speech_duration: Minimum speech duration in seconds
            silence_duration: Silence duration to end speech segment
            pre_speech_pad: Seconds of audio to keep before speech starts
        """
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(
                f"Sample rate must be 8000, 16000, 32000, or 48000, got {sample_rate}"
            )
        if chunk_duration_ms not in (10, 20, 30):
            raise ValueError(
                f"Chunk duration must be 10, 20, or 30 ms, got {chunk_duration_ms}"
            )

        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self.min_speech_duration = min_speech_duration
        self.silence_duration = silence_duration
        self.pre_speech_pad = pre_speech_pad

        # Initialize VAD
        self.vad = webrtcvad.Vad(aggressiveness)

        # Calculate chunk sizes
        self._chunk_bytes = int(
            sample_rate * 2 * chunk_duration_ms / 1000
        )  # 16-bit = 2 bytes
        self._chunks_per_second = 1000 / chunk_duration_ms
        self._min_speech_chunks = int(min_speech_duration * self._chunks_per_second)
        self._silence_chunks = int(silence_duration * self._chunks_per_second)
        self._pre_pad_chunks = int(pre_speech_pad * self._chunks_per_second)

        # Ring buffer for pre-speech padding
        self._ring_buffer = collections.deque(maxlen=self._pre_pad_chunks)

        # State tracking
        self._is_speech = False
        self._speech_chunks_count = 0
        self._silence_chunks_count = 0
        self._speech_buffer: list[bytes] = []

    def is_speech(self, audio_chunk: bytes) -> bool:
        """Check if an audio chunk contains speech."""
        if len(audio_chunk) != self._chunk_bytes:
            # Pad or trim to expected size
            if len(audio_chunk) < self._chunk_bytes:
                audio_chunk = audio_chunk + b"\x00" * (
                    self._chunk_bytes - len(audio_chunk)
                )
            else:
                audio_chunk = audio_chunk[: self._chunk_bytes]

        try:
            return self.vad.is_speech(audio_chunk, self.sample_rate)
        except Exception as e:
            logger.warning(f"VAD error: {e}")
            return False

    def process_chunk(self, audio_chunk: bytes) -> Optional[bytes]:
        """
        Process an audio chunk through the VAD.

        Returns:
            Complete speech segment as bytes when speech ends, None otherwise.
        """
        speech_detected = self.is_speech(audio_chunk)

        if not self._is_speech:
            # Not currently in speech
            self._ring_buffer.append(audio_chunk)

            if speech_detected:
                self._speech_chunks_count += 1
                if self._speech_chunks_count >= 3:  # Need a few consecutive chunks
                    # Speech started!
                    self._is_speech = True
                    self._silence_chunks_count = 0
                    # Include pre-speech padding
                    self._speech_buffer = list(self._ring_buffer)
                    self._ring_buffer.clear()
                    logger.debug("Speech detected - started collecting")
            else:
                self._speech_chunks_count = 0
        else:
            # Currently in speech
            self._speech_buffer.append(audio_chunk)

            if speech_detected:
                self._silence_chunks_count = 0
            else:
                self._silence_chunks_count += 1

                if self._silence_chunks_count >= self._silence_chunks:
                    # Speech ended!
                    self._is_speech = False
                    self._speech_chunks_count = 0
                    self._silence_chunks_count = 0

                    # Check minimum duration
                    total_chunks = len(self._speech_buffer)
                    if total_chunks >= self._min_speech_chunks:
                        result = b"".join(self._speech_buffer)
                        self._speech_buffer.clear()
                        logger.debug(
                            f"Speech segment complete: {total_chunks} chunks, "
                            f"{len(result)} bytes"
                        )
                        return result
                    else:
                        logger.debug(
                            f"Speech too short ({total_chunks} chunks), discarding"
                        )
                        self._speech_buffer.clear()

        return None

    def reset(self):
        """Reset VAD state."""
        self._is_speech = False
        self._speech_chunks_count = 0
        self._silence_chunks_count = 0
        self._speech_buffer.clear()
        self._ring_buffer.clear()

    def flush(self) -> Optional[bytes]:
        """
        Flush any remaining audio in the buffer.
        Call this when push-to-talk is released to get any remaining speech.
        """
        if self._speech_buffer and len(self._speech_buffer) >= self._min_speech_chunks:
            result = b"".join(self._speech_buffer)
            self._speech_buffer.clear()
            self.reset()
            return result

        self.reset()
        return None
