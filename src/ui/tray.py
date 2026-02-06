"""
System tray icon module using pystray.
Provides visual status indicator and quick settings access.
"""

import logging
import threading
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Status colors
COLOR_IDLE = (100, 100, 100)  # Gray - idle
COLOR_LISTENING = (0, 200, 0)  # Green - recording/listening
COLOR_PROCESSING = (255, 165, 0)  # Orange - processing speech
COLOR_TRANSLATE = (0, 120, 255)  # Blue - translate mode
COLOR_ERROR = (255, 0, 0)  # Red - error


def create_icon_image(color: tuple, text: str = "V", size: int = 64) -> Image.Image:
    """Create a simple colored icon with a letter."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Draw filled circle
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=color,
        outline=(255, 255, 255),
        width=2,
    )

    # Draw text centered
    try:
        font = ImageFont.truetype("arial.ttf", size // 2)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) // 2
    text_y = (size - text_h) // 2 - 2
    draw.text((text_x, text_y), text, fill=(255, 255, 255), font=font)

    return image


class SystemTray:
    """
    System tray icon for Voice Injector.

    Shows current status and provides quick access to:
    - Toggle mode (Transcribe / Translate)
    - Quit application
    """

    def __init__(
        self,
        on_toggle_mode: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
    ):
        self._on_toggle_mode = on_toggle_mode
        self._on_quit = on_quit
        self._icon = None
        self._current_status = "idle"
        self._current_mode = "transcribe"
        self._thread: Optional[threading.Thread] = None

    def _build_menu(self):
        """Build the tray icon context menu."""
        import pystray

        mode_text = f"Mode: {self._current_mode.capitalize()}"
        status_text = f"Status: {self._current_status.capitalize()}"

        return pystray.Menu(
            pystray.MenuItem(status_text, None, enabled=False),
            pystray.MenuItem(mode_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Toggle Mode (Ctrl+Shift+T)",
                lambda: self._on_toggle_mode() if self._on_toggle_mode else None,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit (Ctrl+Shift+Q)", self._quit),
        )

    def _quit(self, *args):
        """Handle quit from tray menu."""
        logger.info("Quit requested from system tray")
        if self._on_quit:
            self._on_quit()
        self.stop()

    def _get_color(self) -> tuple:
        """Get color based on current status and mode."""
        if self._current_status == "listening":
            return COLOR_LISTENING
        elif self._current_status == "processing":
            return COLOR_PROCESSING
        elif self._current_status == "error":
            return COLOR_ERROR
        else:
            if self._current_mode == "translate":
                return COLOR_TRANSLATE
            return COLOR_IDLE

    def _get_label(self) -> str:
        """Get icon label text."""
        if self._current_mode == "translate":
            return "T"
        return "V"

    def update_status(self, status: str):
        """
        Update the tray icon status.

        Args:
            status: One of 'idle', 'listening', 'processing', 'error'
        """
        self._current_status = status
        self._refresh_icon()

    def update_mode(self, mode: str):
        """
        Update the current mode display.

        Args:
            mode: 'transcribe' or 'translate'
        """
        self._current_mode = mode
        self._refresh_icon()

    def _refresh_icon(self):
        """Refresh the tray icon appearance."""
        if self._icon:
            try:
                color = self._get_color()
                label = self._get_label()
                self._icon.icon = create_icon_image(color, label)
                self._icon.title = (
                    f"Voice Injector - {self._current_mode.capitalize()} "
                    f"({self._current_status})"
                )
                # Update menu
                self._icon.menu = self._build_menu()
            except Exception as e:
                logger.warning(f"Failed to refresh tray icon: {e}")

    def start(self):
        """Start the system tray icon in a background thread."""
        import pystray

        color = self._get_color()
        label = self._get_label()

        self._icon = pystray.Icon(
            "voice_injector",
            icon=create_icon_image(color, label),
            title=f"Voice Injector - {self._current_mode.capitalize()} (idle)",
            menu=self._build_menu(),
        )

        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        logger.info("System tray icon started")

    def stop(self):
        """Stop and remove the system tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        logger.info("System tray icon stopped")
