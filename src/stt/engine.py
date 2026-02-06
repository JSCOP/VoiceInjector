"""
Speech-to-Text engine using faster-whisper + Google Translate.

Architecture:
- Whisper handles ONLY transcription (what it's good at)
- Google Translate handles translation (much more reliable than Whisper's translate task)

Two modes:
- Transcribe: Speech → text in original language
- Translate:  Speech → Korean text → Google Translate → English text
"""

import logging
import os
import re
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class STTEngine:
    """
    Speech-to-Text engine with reliable translation.

    Transcribe mode:
      - Whisper auto-detects language
      - Outputs text as spoken (Korean stays Korean, English stays English)
      - Handles code-switching reasonably well

    Translate mode:
      - Whisper transcribes in Korean (forced)
      - Google Translate converts Korean → English
      - Much more reliable than Whisper's built-in translate task
    """

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "cuda",
        compute_type: str = "float16",
        beam_size: int = 5,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.language = language  # None = auto-detect
        self.initial_prompt = initial_prompt

        self._model = None
        self._current_task = "transcribe"  # "transcribe" or "translate"
        self._translator = None

    def load_model(self):
        """Load the Whisper model and translator."""
        from faster_whisper import WhisperModel

        logger.info(
            f"Loading Whisper model '{self.model_size}' "
            f"(device={self.device}, compute={self.compute_type})..."
        )

        start = time.time()

        model_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models"
        )
        os.makedirs(model_dir, exist_ok=True)

        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
            download_root=model_dir,
        )

        elapsed = time.time() - start
        logger.info(f"Model loaded in {elapsed:.1f}s")

        # Initialize Google Translator
        try:
            from deep_translator import GoogleTranslator

            self._translator = GoogleTranslator(source="auto", target="en")
            logger.info("Google Translator initialized")
        except Exception as e:
            logger.warning(f"Google Translator init failed: {e}")
            self._translator = None

    def set_task(self, task: str):
        """Set the current task: 'transcribe' or 'translate'."""
        if task not in ("transcribe", "translate"):
            raise ValueError(f"Task must be 'transcribe' or 'translate', got '{task}'")
        self._current_task = task
        logger.info(f"STT task set to: {task}")

    def toggle_task(self) -> str:
        """Toggle between transcribe and translate. Returns the new task name."""
        if self._current_task == "transcribe":
            self._current_task = "translate"
        else:
            self._current_task = "transcribe"
        logger.info(f"STT task toggled to: {self._current_task}")
        return self._current_task

    @property
    def current_task(self) -> str:
        return self._current_task

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """
        Process audio: transcribe or transcribe+translate.

        Args:
            audio_bytes: Raw 16-bit PCM audio data
            sample_rate: Sample rate of the audio

        Returns:
            Processed text string
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        if not audio_bytes or len(audio_bytes) < 1000:
            logger.debug("Audio too short, skipping")
            return ""

        # Convert raw 16-bit PCM to float32 numpy array
        audio_np = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )

        min_samples = int(sample_rate * 0.5)
        if len(audio_np) < min_samples:
            logger.debug("Audio too short after conversion, skipping")
            return ""

        start = time.time()

        try:
            # Step 1: Always transcribe with Whisper (never use task="translate")
            # For translate mode, force Korean to ensure proper transcription
            # For transcribe mode, auto-detect language for code-switching
            if self._current_task == "translate":
                whisper_lang = "ko"
            else:
                whisper_lang = self.language  # None = auto-detect

            segments, info = self._model.transcribe(
                audio_np,
                beam_size=self.beam_size,
                task="transcribe",  # Always transcribe, never translate
                language=whisper_lang,
                initial_prompt=self.initial_prompt,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
            )

            # Collect all segment texts
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            text = " ".join(text_parts).strip()

            stt_elapsed = time.time() - start
            audio_duration = len(audio_np) / sample_rate

            logger.info(
                f"[STT] lang={info.language}({info.language_probability:.0%}) "
                f"audio={audio_duration:.1f}s -> stt={stt_elapsed:.2f}s "
                f"text='{text[:80]}{'...' if len(text) > 80 else ''}'"
            )

            if not text:
                return ""

            # Step 2: If translate mode, translate the text via Google Translate
            if self._current_task == "translate":
                text = self._translate_text(text)

            return text

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            return ""

    def _translate_text(self, text: str) -> str:
        """Translate text to English using Google Translate."""
        if not self._translator:
            logger.warning("Translator not available, returning original text")
            return text

        if not text.strip():
            return text

        try:
            start = time.time()

            translated = self._translator.translate(text)

            elapsed = time.time() - start
            logger.info(
                f"[Translate] {elapsed:.2f}s: '{text[:40]}' -> '{translated[:40]}'"
            )

            return translated if translated else text

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return text  # Fallback: return original text

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
