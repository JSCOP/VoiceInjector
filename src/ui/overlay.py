"""
Floating overlay window at the bottom of the screen.
Shows recording status, processing indicator, transcribed text,
and a visible translate ON/OFF toggle.

Uses tkinter (built-in, no extra dependencies).
The window is:
- Always on top
- Semi-transparent
- Click-through (doesn't steal focus)
- Positioned at bottom-center of screen
"""

import ctypes
import logging
import queue
import threading
import tkinter as tk
from typing import Optional

logger = logging.getLogger(__name__)

# Win32 constants for click-through window
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

# Colors
COLOR_BG_IDLE = "#1E1E1E"
COLOR_BG_RECORDING = "#0D2818"
COLOR_BG_PROCESSING = "#2D1B00"
COLOR_BG_ERROR = "#2D0A0A"

COLOR_TEXT_IDLE = "#888888"
COLOR_TEXT_RECORDING = "#00FF88"
COLOR_TEXT_PROCESSING = "#FFB347"
COLOR_TEXT_RESULT = "#FFFFFF"
COLOR_TEXT_ERROR = "#FF4444"

COLOR_TRANSLATE_ON_BG = "#1A3A5C"
COLOR_TRANSLATE_ON_FG = "#4DB8FF"
COLOR_TRANSLATE_OFF_BG = "#2A2A2A"
COLOR_TRANSLATE_OFF_FG = "#666666"

COLOR_BORDER = "#3A3A3A"

# Dot animation for recording
RECORDING_DOTS = ["", ".", "..", "..."]


class OverlayWindow:
    """
    Floating overlay at the bottom of the screen showing voice injector status.

    Layout:
    ┌─────────────────────────────────────────────────────────┐
    │  ● Ready                    [KO/EN] [Translate: OFF]    │
    │  Win+Ctrl to speak                                      │
    └─────────────────────────────────────────────────────────┘

    States:
    - idle: Shows current mode, dimmed
    - recording: Green pulsing dot animation "Recording..."
    - processing: Orange "Processing..." with spinner
    - result: Shows the transcribed text briefly, then fades back to idle
    - error: Red error message
    """

    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._thread: Optional[threading.Thread] = None
        self._command_queue: queue.Queue = queue.Queue()
        self._running = False
        self._ready = threading.Event()

        # State
        self._current_mode = "transcribe"
        self._current_state = "idle"
        self._dot_index = 0
        self._result_timer_id = None

        # UI elements
        self._status_label: Optional[tk.Label] = None
        self._translate_badge: Optional[tk.Label] = None
        self._lang_badge: Optional[tk.Label] = None
        self._text_label: Optional[tk.Label] = None
        self._canvas: Optional[tk.Canvas] = None
        self._dot_indicator: Optional[int] = None

    def start(self):
        """Start the overlay window in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        logger.info("Overlay window started")

    def stop(self):
        """Stop and destroy the overlay window."""
        self._running = False
        self._send_command("quit")
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("Overlay window stopped")

    def show_idle(self):
        self._send_command("idle")

    def show_recording(self):
        self._send_command("recording")

    def show_processing(self):
        self._send_command("processing")

    def show_result(self, text: str):
        self._send_command("result", text)

    def show_error(self, message: str):
        self._send_command("error", message)

    def update_mode(self, mode: str):
        """Update the displayed mode (transcribe/translate)."""
        self._current_mode = mode
        self._send_command("mode", mode)

    def _send_command(self, cmd: str, data: str = ""):
        try:
            self._command_queue.put_nowait((cmd, data))
        except queue.Full:
            pass

    def _run_tk(self):
        try:
            self._root = tk.Tk()
            self._setup_window()
            self._build_ui()
            self._make_click_through()
            self._root.after(50, self._poll_commands)
            self._ready.set()
            self._root.mainloop()
        except Exception as e:
            logger.error(f"Overlay window error: {e}", exc_info=True)
            self._ready.set()

    def _setup_window(self):
        root = self._root
        root.title("Voice Injector")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)
        root.configure(bg=COLOR_BG_IDLE)

        width = 520
        height = 64
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = screen_h - height - 60  # above taskbar

        root.geometry(f"{width}x{height}+{x}+{y}")
        root.resizable(False, False)

    def _build_ui(self):
        root = self._root

        # Outer border frame
        border_frame = tk.Frame(root, bg=COLOR_BORDER, padx=1, pady=1)
        border_frame.pack(fill=tk.BOTH, expand=True)

        # Main frame
        frame = tk.Frame(border_frame, bg=COLOR_BG_IDLE, padx=12, pady=6)
        frame.pack(fill=tk.BOTH, expand=True)

        # === Top row: [dot] [status] ... [lang badge] [translate badge] ===
        top_frame = tk.Frame(frame, bg=COLOR_BG_IDLE)
        top_frame.pack(fill=tk.X)

        # Dot indicator
        self._canvas = tk.Canvas(
            top_frame, width=14, height=14, bg=COLOR_BG_IDLE, highlightthickness=0
        )
        self._canvas.pack(side=tk.LEFT, padx=(0, 6), pady=2)
        self._dot_indicator = self._canvas.create_oval(
            2, 2, 12, 12, fill=COLOR_TEXT_IDLE, outline=""
        )

        # Status label
        self._status_label = tk.Label(
            top_frame,
            text="Ready",
            font=("Segoe UI", 11, "bold"),
            fg=COLOR_TEXT_IDLE,
            bg=COLOR_BG_IDLE,
            anchor="w",
        )
        self._status_label.pack(side=tk.LEFT, padx=(0, 8))

        # --- Right side badges ---

        # Translate toggle badge (rightmost)
        self._translate_badge = tk.Label(
            top_frame,
            text="  Translate: OFF  ",
            font=("Segoe UI", 8, "bold"),
            fg=COLOR_TRANSLATE_OFF_FG,
            bg=COLOR_TRANSLATE_OFF_BG,
            padx=8,
            pady=2,
        )
        self._translate_badge.pack(side=tk.RIGHT, padx=(4, 0))

        # Language detection badge
        self._lang_badge = tk.Label(
            top_frame,
            text=" KO / EN ",
            font=("Segoe UI", 8),
            fg="#999999",
            bg="#2A2A2A",
            padx=6,
            pady=2,
        )
        self._lang_badge.pack(side=tk.RIGHT, padx=(4, 0))

        # === Bottom row: help text / transcribed text ===
        self._text_label = tk.Label(
            frame,
            text="Win+Ctrl to speak  |  Win+Shift to toggle translate",
            font=("Segoe UI", 9),
            fg="#555555",
            bg=COLOR_BG_IDLE,
            anchor="w",
            wraplength=490,
        )
        self._text_label.pack(fill=tk.X, pady=(4, 0))

        # Store references
        self._frame = frame
        self._top_frame = top_frame
        self._border_frame = border_frame

    def _make_click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (
                style
                | WS_EX_LAYERED
                | WS_EX_TRANSPARENT
                | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE
            )
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as e:
            logger.warning(f"Could not set click-through: {e}")

    def _poll_commands(self):
        if not self._running:
            self._root.quit()
            return

        try:
            while True:
                cmd, data = self._command_queue.get_nowait()
                self._handle_command(cmd, data)
        except queue.Empty:
            pass

        self._root.after(50, self._poll_commands)

    def _handle_command(self, cmd: str, data: str):
        if cmd == "quit":
            self._running = False
            self._root.quit()
        elif cmd == "idle":
            self._set_idle()
        elif cmd == "recording":
            self._set_recording()
        elif cmd == "processing":
            self._set_processing()
        elif cmd == "result":
            self._set_result(data)
        elif cmd == "error":
            self._set_error(data)
        elif cmd == "mode":
            self._set_mode(data)

    def _set_bg(self, color: str):
        """Update background color of all widgets."""
        self._root.configure(bg=color)
        self._border_frame.configure(bg=COLOR_BORDER)
        self._frame.configure(bg=color)
        self._top_frame.configure(bg=color)
        self._status_label.configure(bg=color)
        self._text_label.configure(bg=color)
        self._canvas.configure(bg=color)

    def _set_idle(self):
        self._current_state = "idle"
        self._cancel_result_timer()
        self._set_bg(COLOR_BG_IDLE)
        self._canvas.itemconfig(self._dot_indicator, fill=COLOR_TEXT_IDLE)
        self._status_label.configure(text="Ready", fg=COLOR_TEXT_IDLE)
        self._text_label.configure(
            text="Win+Ctrl to speak  |  Win+Shift to toggle translate",
            fg="#555555",
        )

    def _set_recording(self):
        self._current_state = "recording"
        self._cancel_result_timer()
        self._set_bg(COLOR_BG_RECORDING)
        self._canvas.itemconfig(self._dot_indicator, fill=COLOR_TEXT_RECORDING)
        self._status_label.configure(text="Recording...", fg=COLOR_TEXT_RECORDING)
        self._text_label.configure(text="Speak now...", fg=COLOR_TEXT_RECORDING)
        self._dot_index = 0
        self._animate_recording()

    def _animate_recording(self):
        if self._current_state != "recording":
            return
        dots = RECORDING_DOTS[self._dot_index % len(RECORDING_DOTS)]
        self._status_label.configure(text=f"Recording{dots}")
        colors = [COLOR_TEXT_RECORDING, "#00CC66", "#00FF88", "#00CC66"]
        self._canvas.itemconfig(
            self._dot_indicator, fill=colors[self._dot_index % len(colors)]
        )
        self._dot_index += 1
        self._root.after(300, self._animate_recording)

    def _set_processing(self):
        self._current_state = "processing"
        self._cancel_result_timer()
        self._set_bg(COLOR_BG_PROCESSING)
        self._canvas.itemconfig(self._dot_indicator, fill=COLOR_TEXT_PROCESSING)
        self._status_label.configure(text="Processing...", fg=COLOR_TEXT_PROCESSING)
        self._text_label.configure(
            text="Transcribing speech...", fg=COLOR_TEXT_PROCESSING
        )
        self._dot_index = 0
        self._animate_processing()

    def _animate_processing(self):
        if self._current_state != "processing":
            return
        spinner = ["   ", ".  ", ".. ", "...", " ..", "  ."]
        s = spinner[self._dot_index % len(spinner)]
        self._status_label.configure(text=f"Processing {s}")
        self._dot_index += 1
        self._root.after(200, self._animate_processing)

    def _set_result(self, text: str):
        self._current_state = "result"
        self._cancel_result_timer()
        self._set_bg(COLOR_BG_IDLE)
        self._canvas.itemconfig(self._dot_indicator, fill="#00FF88")
        self._status_label.configure(text="Injected", fg="#00FF88")
        display = text if len(text) <= 80 else text[:77] + "..."
        self._text_label.configure(text=display, fg=COLOR_TEXT_RESULT)
        self._result_timer_id = self._root.after(3000, self._set_idle)

    def _set_error(self, message: str):
        self._current_state = "error"
        self._cancel_result_timer()
        self._set_bg(COLOR_BG_ERROR)
        self._canvas.itemconfig(self._dot_indicator, fill=COLOR_TEXT_ERROR)
        self._status_label.configure(text="Error", fg=COLOR_TEXT_ERROR)
        self._text_label.configure(text=message, fg=COLOR_TEXT_ERROR)
        self._result_timer_id = self._root.after(4000, self._set_idle)

    def _set_mode(self, mode: str):
        """Update mode display - toggle translate badge ON/OFF."""
        self._current_mode = mode

        if mode == "translate":
            self._translate_badge.configure(
                text="  Translate: ON  ",
                fg=COLOR_TRANSLATE_ON_FG,
                bg=COLOR_TRANSLATE_ON_BG,
            )
            self._lang_badge.configure(
                text=" KO -> EN ",
                fg=COLOR_TRANSLATE_ON_FG,
                bg="#1A2A3C",
            )
        else:
            self._translate_badge.configure(
                text="  Translate: OFF  ",
                fg=COLOR_TRANSLATE_OFF_FG,
                bg=COLOR_TRANSLATE_OFF_BG,
            )
            self._lang_badge.configure(
                text=" KO / EN ",
                fg="#999999",
                bg="#2A2A2A",
            )

    def _cancel_result_timer(self):
        if self._result_timer_id is not None:
            try:
                self._root.after_cancel(self._result_timer_id)
            except Exception:
                pass
            self._result_timer_id = None
