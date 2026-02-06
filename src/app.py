"""
Main application orchestrator for Voice Injector.
Wires together audio capture, VAD, STT, text injection, hotkeys, overlay, and system tray.
"""

import logging
import sys
import threading
import time
from typing import Optional

from src.audio.capture import AudioCapture
from src.audio.mute_control import MuteControl
from src.audio.vad import VoiceActivityDetector
from src.config_loader import AppConfig, load_config
from src.injector.text_injector import TextInjector
from src.stt.engine import STTEngine
from src.ui.hotkeys import HotkeyManager
from src.ui.overlay import OverlayWindow
from src.ui.tray import SystemTray

logger = logging.getLogger(__name__)


class VoiceInjectorApp:
    """
    Main application class that orchestrates all components.

    Flow:
    1. User holds push-to-talk hotkey
    2. Audio capture starts buffering microphone input
    3. Overlay shows "Recording..." with green animation
    4. User releases hotkey
    5. Overlay shows "Processing..." with orange animation
    6. Audio is sent to STT engine (transcribe or translate)
    7. Transcribed text is injected at cursor position via SendInput
    8. Overlay shows injected text briefly, then returns to idle
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or load_config()
        self._running = False
        self._is_recording = False
        self._processing_lock = threading.Lock()

        # Initialize components
        self._audio = AudioCapture(
            sample_rate=self.config.audio.sample_rate,
            channels=self.config.audio.channels,
            chunk_duration_ms=self.config.audio.chunk_duration_ms,
            device_index=self.config.audio.device_index,
        )

        self._vad = VoiceActivityDetector(
            sample_rate=self.config.audio.sample_rate,
            chunk_duration_ms=self.config.audio.chunk_duration_ms,
            aggressiveness=self.config.vad.aggressiveness,
            min_speech_duration=self.config.vad.min_speech_duration,
            silence_duration=self.config.vad.silence_duration,
            pre_speech_pad=self.config.vad.pre_speech_pad,
        )

        self._stt = STTEngine(
            model_size=self.config.stt.model_size,
            device=self.config.stt.device,
            compute_type=self.config.stt.compute_type,
            beam_size=self.config.stt.beam_size,
            language=self.config.stt.language,
            initial_prompt=self.config.stt.initial_prompt,
        )
        self._stt.set_task(self.config.stt.default_task)

        self._injector = TextInjector(
            keystroke_delay=self.config.injector.keystroke_delay,
            add_trailing_space=self.config.injector.add_trailing_space,
            add_trailing_newline=self.config.injector.add_trailing_newline,
        )

        self._mute = MuteControl(enabled=self.config.audio.mute_speaker_on_record)

        self._hotkeys = HotkeyManager()

        self._overlay = OverlayWindow()

        self._tray = SystemTray(
            on_toggle_mode=self._toggle_mode,
            on_quit=self.stop,
        )

    def _setup_hotkeys(self):
        """Register all hotkeys."""
        # Push-to-talk
        self._hotkeys.register_push_to_talk(
            name="push_to_talk",
            hotkey_str=self.config.hotkeys.push_to_talk,
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
        )

        # Toggle transcribe/translate
        self._hotkeys.register_toggle(
            name="toggle_mode",
            hotkey_str=self.config.hotkeys.toggle_mode,
            on_toggle=self._toggle_mode,
        )

        # Quit
        self._hotkeys.register_toggle(
            name="quit",
            hotkey_str=self.config.hotkeys.quit,
            on_toggle=self.stop,
        )

    def _on_ptt_press(self):
        """Called when push-to-talk hotkey is pressed (held down)."""
        if self._is_recording:
            return

        self._is_recording = True
        self._mute.mute()  # Mute speakers to avoid interference
        self._vad.reset()
        self._audio.start_buffering()
        self._tray.update_status("listening")
        self._overlay.show_recording()
        logger.info("Push-to-talk: RECORDING")

    def _on_ptt_release(self):
        """Called when push-to-talk hotkey is released."""
        if not self._is_recording:
            return

        self._is_recording = False
        self._mute.unmute()  # Restore speakers
        logger.info("Push-to-talk: RELEASED - processing audio...")

        # Get buffered audio
        audio_data = self._audio.stop_buffering()

        if not audio_data or len(audio_data) < 1000:
            logger.info("No significant audio captured, skipping")
            self._tray.update_status("idle")
            self._overlay.show_idle()
            return

        # Show processing state
        self._tray.update_status("processing")
        self._overlay.show_processing()

        # Process in background thread so we don't block the hotkey listener
        threading.Thread(
            target=self._process_audio,
            args=(audio_data,),
            daemon=True,
        ).start()

    def _process_audio(self, audio_data: bytes):
        """Process captured audio: STT -> inject text."""
        with self._processing_lock:
            try:
                # Transcribe
                text = self._stt.transcribe(
                    audio_data,
                    sample_rate=self.config.audio.sample_rate,
                )

                if text:
                    # Small delay to ensure the target window is focused
                    time.sleep(0.1)
                    # Inject text at cursor
                    self._injector.inject_text_fast(text)
                    logger.info(f"Injected: '{text}'")
                    self._overlay.show_result(text)
                else:
                    logger.info("No text transcribed")
                    self._overlay.show_idle()

            except Exception as e:
                logger.error(f"Audio processing failed: {e}", exc_info=True)
                self._tray.update_status("error")
                self._overlay.show_error(str(e))
                time.sleep(1)

            finally:
                if self._running:
                    self._tray.update_status("idle")

    def _toggle_mode(self):
        """Toggle between transcribe and translate modes."""
        new_mode = self._stt.toggle_task()
        self._tray.update_mode(new_mode)
        self._overlay.update_mode(new_mode)
        logger.info(f"Mode switched to: {new_mode}")

    def start(self):
        """Start the Voice Injector application."""
        logger.info("=" * 60)
        logger.info("  Voice Injector Starting")
        logger.info("=" * 60)

        # Load STT model (this takes a while on first run)
        logger.info("Loading speech recognition model (this may take a moment)...")
        self._stt.load_model()

        # Initialize speaker mute control
        self._mute.initialize()

        # Start audio stream
        self._audio.start_stream()

        # Setup and start hotkeys
        self._setup_hotkeys()
        self._hotkeys.start()

        # Start overlay
        self._overlay.update_mode(self._stt.current_task)
        self._overlay.start()

        # Start system tray
        self._tray.update_mode(self._stt.current_task)
        self._tray.start()

        self._running = True

        logger.info("")
        logger.info("  Voice Injector is READY!")
        logger.info(f"  Mode: {self._stt.current_task.upper()}")
        logger.info(f"  Push-to-talk: {self.config.hotkeys.push_to_talk}")
        logger.info(f"  Toggle mode:  {self.config.hotkeys.toggle_mode}")
        logger.info(f"  Quit:         {self.config.hotkeys.quit}")
        logger.info("")
        logger.info("  Hold push-to-talk, speak, then release to inject text.")
        logger.info("=" * 60)

        # Keep main thread alive
        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            self.stop()

    def stop(self):
        """Stop the Voice Injector application."""
        if not self._running:
            return

        logger.info("Shutting down Voice Injector...")
        self._running = False

        self._mute.force_unmute()  # Safety: ensure speakers are unmuted on exit
        self._hotkeys.stop()
        self._audio.stop_stream()
        self._overlay.stop()
        self._tray.stop()

        logger.info("Voice Injector stopped. Goodbye!")
