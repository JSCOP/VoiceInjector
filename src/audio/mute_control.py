"""
System audio mute control.
Mutes speaker output while recording to prevent interference with STT.

Uses Windows Core Audio API (pycaw) to:
1. Mute system audio when push-to-talk starts
2. Unmute when push-to-talk ends
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MuteControl:
    """
    Controls system speaker mute state during voice recording.

    Prevents speaker audio (music, videos, notifications) from
    being picked up by the microphone during speech recognition.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._volume = None
        self._was_muted_before = False
        self._original_volume: Optional[float] = None
        self._initialized = False

    def initialize(self):
        """Initialize the audio endpoint. Call once at startup."""
        if not self.enabled:
            logger.info("Speaker mute control: disabled")
            return

        try:
            from pycaw.pycaw import AudioUtilities

            dev = AudioUtilities.GetSpeakers()
            self._volume = dev.EndpointVolume

            current = self._volume.GetMasterVolumeLevelScalar()
            logger.info(
                f"Speaker mute control: initialized "
                f"({dev.FriendlyName}, volume={current * 100:.0f}%)"
            )
            self._initialized = True

        except ImportError:
            logger.warning(
                "pycaw not installed. Speaker mute disabled. "
                "Install with: pip install pycaw"
            )
            self.enabled = False
        except Exception as e:
            logger.warning(f"Speaker mute control init failed: {e}")
            self.enabled = False

    def mute(self):
        """
        Mute system audio. Call when recording starts.
        Remembers previous mute state to restore correctly.
        """
        if not self.enabled or not self._initialized:
            return

        try:
            # Remember if already muted (don't unmute later if user had it muted)
            self._was_muted_before = bool(self._volume.GetMute())

            if not self._was_muted_before:
                self._volume.SetMute(1, None)
                logger.debug("Speaker muted for recording")

        except Exception as e:
            logger.warning(f"Failed to mute speaker: {e}")

    def unmute(self):
        """
        Restore system audio. Call when recording ends.
        Only unmutes if it wasn't muted before we muted it.
        """
        if not self.enabled or not self._initialized:
            return

        try:
            if not self._was_muted_before:
                self._volume.SetMute(0, None)
                logger.debug("Speaker unmuted after recording")

        except Exception as e:
            logger.warning(f"Failed to unmute speaker: {e}")

    def force_unmute(self):
        """Force unmute regardless of previous state. Safety method."""
        if not self._initialized:
            return

        try:
            self._volume.SetMute(0, None)
        except Exception:
            pass
