"""
Floating overlay UI inspired by Wispr Flow.

Design: Dark pill-shaped capsule at bottom-center of screen.
- Minimal, no text clutter
- Animated dots during recording
- Spinner during processing
- Brief text flash for results
- Auto-hides to tiny dot after 1 second of idle
"""

import ctypes
import logging
import math
import queue
import threading
import tkinter as tk
from typing import Optional

logger = logging.getLogger(__name__)

# Win32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

# Palette
BG = "#0D0D0D"
BG_BORDER = "#1A1A1A"
BG_PILL = "#141414"
DOT_IDLE = "#333333"
DOT_RECORDING = "#E8B634"
DOT_PROCESSING = "#7EB8DA"
DOT_RESULT = "#4ADE80"
DOT_ERROR = "#EF4444"
TEXT_DIM = "#555555"
TEXT_RESULT = "#E0E0E0"
TRANSLATE_ON = "#4DB8FF"
TRANSLATE_OFF = "#444444"

# Sizes
PILL_WIDTH = 280
PILL_HEIGHT = 44
PILL_RADIUS = 22
MINI_SIZE = 14

# Timing
AUTO_HIDE_MS = 1000


class OverlayWindow:
    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._ready = threading.Event()

        self._current_mode = "transcribe"
        self._current_state = "idle"
        self._is_mini = False
        self._anim_index = 0
        self._anim_id = None
        self._hide_timer_id = None
        self._result_timer_id = None

        # Canvas elements
        self._canvas: Optional[tk.Canvas] = None
        self._mini_canvas: Optional[tk.Canvas] = None
        self._mini_dot = None
        self._full_frame: Optional[tk.Frame] = None
        self._mini_frame: Optional[tk.Frame] = None

        self._screen_w = 0
        self._screen_h = 0

    # ── Public API ──

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self):
        self._running = False
        self._cmd("quit")
        if self._thread:
            self._thread.join(timeout=3)

    def show_idle(self):
        self._cmd("idle")

    def show_recording(self):
        self._cmd("recording")

    def show_processing(self):
        self._cmd("processing")

    def show_result(self, text: str):
        self._cmd("result", text)

    def show_error(self, msg: str):
        self._cmd("error", msg)

    def update_mode(self, mode: str):
        self._current_mode = mode
        self._cmd("mode", mode)

    def _cmd(self, c: str, d: str = ""):
        try:
            self._queue.put_nowait((c, d))
        except queue.Full:
            pass

    # ── Tkinter ──

    def _run(self):
        try:
            self._root = tk.Tk()
            self._setup()
            self._build()
            self._click_through()
            self._root.after(50, self._poll)
            self._start_hide_timer()
            self._ready.set()
            self._root.mainloop()
        except Exception as e:
            logger.error(f"Overlay error: {e}", exc_info=True)
            self._ready.set()

    def _setup(self):
        r = self._root
        r.title("VI")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", 0.95)
        r.configure(bg=BG)

        self._screen_w = r.winfo_screenwidth()
        self._screen_h = r.winfo_screenheight()

        x = (self._screen_w - PILL_WIDTH) // 2
        y = self._screen_h - PILL_HEIGHT - 70
        r.geometry(f"{PILL_WIDTH}x{PILL_HEIGHT}+{x}+{y}")

    def _build(self):
        # ── Full mode: pill canvas ──
        self._full_frame = tk.Frame(self._root, bg=BG)
        self._full_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(
            self._full_frame,
            width=PILL_WIDTH,
            height=PILL_HEIGHT,
            bg=BG,
            highlightthickness=0,
        )
        self._canvas.pack()

        # Draw pill background
        self._draw_pill(0, 0, PILL_WIDTH, PILL_HEIGHT, PILL_RADIUS, BG_PILL, BG_BORDER)

        # ── Mini mode: tiny dot ──
        self._mini_frame = tk.Frame(self._root, bg=BG)
        self._mini_canvas = tk.Canvas(
            self._mini_frame,
            width=MINI_SIZE,
            height=MINI_SIZE,
            bg=BG,
            highlightthickness=0,
        )
        self._mini_canvas.pack()
        self._mini_dot = self._mini_canvas.create_oval(
            2, 2, MINI_SIZE - 2, MINI_SIZE - 2, fill=DOT_IDLE, outline=""
        )

        # Initial: draw idle dots
        self._draw_idle_dots()

    def _draw_pill(self, x1, y1, x2, y2, r, fill, outline):
        """Draw a rounded rectangle (pill shape) on canvas."""
        c = self._canvas
        # Using arcs and rectangles for rounded corners
        c.create_arc(
            x1,
            y1,
            x1 + 2 * r,
            y1 + 2 * r,
            start=90,
            extent=90,
            fill=fill,
            outline=outline,
            width=1,
        )
        c.create_arc(
            x2 - 2 * r,
            y1,
            x2,
            y1 + 2 * r,
            start=0,
            extent=90,
            fill=fill,
            outline=outline,
            width=1,
        )
        c.create_arc(
            x1,
            y2 - 2 * r,
            x1 + 2 * r,
            y2,
            start=180,
            extent=90,
            fill=fill,
            outline=outline,
            width=1,
        )
        c.create_arc(
            x2 - 2 * r,
            y2 - 2 * r,
            x2,
            y2,
            start=270,
            extent=90,
            fill=fill,
            outline=outline,
            width=1,
        )
        # Fill center
        c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
        c.create_rectangle(x1, y1 + r, x1 + r, y2 - r, fill=fill, outline="")
        c.create_rectangle(x2 - r, y1 + r, x2, y2 - r, fill=fill, outline="")
        # Border lines
        c.create_line(x1 + r, y1, x2 - r, y1, fill=outline)
        c.create_line(x1 + r, y2, x2 - r, y2, fill=outline)
        c.create_line(x1, y1 + r, x1, y2 - r, fill=outline)
        c.create_line(x2, y1 + r, x2, y2 - r, fill=outline)

    def _click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= (
                WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            )
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # ── Mode switching ──

    def _to_full(self):
        if not self._is_mini:
            return
        self._is_mini = False
        self._mini_frame.pack_forget()
        self._full_frame.pack(fill=tk.BOTH, expand=True)
        x = (self._screen_w - PILL_WIDTH) // 2
        y = self._screen_h - PILL_HEIGHT - 70
        self._root.geometry(f"{PILL_WIDTH}x{PILL_HEIGHT}+{x}+{y}")
        self._root.attributes("-alpha", 0.95)

    def _to_mini(self):
        if self._is_mini or self._current_state != "idle":
            return
        self._is_mini = True
        self._full_frame.pack_forget()
        self._mini_frame.pack(fill=tk.BOTH, expand=True)
        x = (self._screen_w - MINI_SIZE) // 2
        y = self._screen_h - MINI_SIZE - 75
        self._root.geometry(f"{MINI_SIZE}x{MINI_SIZE}+{x}+{y}")
        self._root.attributes("-alpha", 0.6)
        # Update mini dot color
        color = TRANSLATE_ON if self._current_mode == "translate" else DOT_IDLE
        self._mini_canvas.itemconfig(self._mini_dot, fill=color)

    def _ensure_full(self):
        if self._is_mini:
            self._to_full()
        self._cancel_hide_timer()

    # ── Timers ──

    def _start_hide_timer(self):
        self._cancel_hide_timer()
        self._hide_timer_id = self._root.after(AUTO_HIDE_MS, self._to_mini)

    def _cancel_hide_timer(self):
        if self._hide_timer_id:
            try:
                self._root.after_cancel(self._hide_timer_id)
            except Exception:
                pass
            self._hide_timer_id = None

    def _cancel_result_timer(self):
        if self._result_timer_id:
            try:
                self._root.after_cancel(self._result_timer_id)
            except Exception:
                pass
            self._result_timer_id = None

    def _cancel_anim(self):
        if self._anim_id:
            try:
                self._root.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    # ── Poll ──

    def _poll(self):
        if not self._running:
            self._root.quit()
            return
        try:
            while True:
                c, d = self._queue.get_nowait()
                self._handle(c, d)
        except queue.Empty:
            pass
        self._root.after(50, self._poll)

    def _handle(self, cmd, data):
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

    # ── Drawing helpers ──

    def _clear_content(self):
        """Remove all dynamic content from canvas (keep pill background)."""
        self._cancel_anim()
        for tag in ("dots", "text", "spinner", "icon"):
            self._canvas.delete(tag)

    def _draw_dots(self, count=12, color=DOT_IDLE, spacing=12):
        """Draw a row of dots in the center of the pill."""
        total_w = (count - 1) * spacing
        start_x = (PILL_WIDTH - total_w) / 2
        cy = PILL_HEIGHT / 2
        for i in range(count):
            x = start_x + i * spacing
            r = 2.5
            self._canvas.create_oval(
                x - r, cy - r, x + r, cy + r, fill=color, outline="", tags="dots"
            )

    def _draw_idle_dots(self):
        """Draw dim dots for idle state."""
        self._clear_content()
        self._draw_dots(12, DOT_IDLE)
        # Translate indicator on the right
        self._draw_mode_icon()

    def _draw_mode_icon(self):
        """Draw a small mode indicator icon on the right side of the pill."""
        cx = PILL_WIDTH - 30
        cy = PILL_HEIGHT / 2
        color = TRANSLATE_ON if self._current_mode == "translate" else "#2A2A2A"

        # Small diamond/star shape
        size = 5
        points = []
        for i in range(8):
            angle = math.pi * i / 4
            r = size if i % 2 == 0 else size * 0.4
            points.append(cx + r * math.cos(angle))
            points.append(cy + r * math.sin(angle))
        self._canvas.create_polygon(points, fill=color, outline="", tags="icon")

    # ── State renderers ──

    def _set_idle(self):
        self._current_state = "idle"
        self._cancel_result_timer()
        self._ensure_full()
        self._draw_idle_dots()
        self._start_hide_timer()

    def _set_recording(self):
        self._current_state = "recording"
        self._cancel_result_timer()
        self._ensure_full()
        self._clear_content()
        self._anim_index = 0
        self._anim_recording()

    def _anim_recording(self):
        """Animate recording: wave of golden dots pulsing left to right."""
        if self._current_state != "recording":
            return

        self._canvas.delete("dots")
        count = 14
        spacing = 12
        total_w = (count - 1) * spacing
        start_x = (PILL_WIDTH - total_w) / 2
        cy = PILL_HEIGHT / 2

        for i in range(count):
            x = start_x + i * spacing
            # Wave effect: dots near the "active" position are brighter and larger
            dist = abs(i - (self._anim_index % count))
            dist = min(dist, count - dist)  # Wrap around

            if dist == 0:
                r, color = 4, DOT_RECORDING
            elif dist == 1:
                r, color = 3.5, "#C9952A"
            elif dist == 2:
                r, color = 3, "#8B6914"
            else:
                r, color = 2.5, "#3D3020"

            self._canvas.create_oval(
                x - r, cy - r, x + r, cy + r, fill=color, outline="", tags="dots"
            )

        self._draw_mode_icon()
        self._anim_index += 1
        self._anim_id = self._root.after(80, self._anim_recording)

    def _set_processing(self):
        self._current_state = "processing"
        self._cancel_result_timer()
        self._ensure_full()
        self._clear_content()
        self._anim_index = 0
        self._anim_processing()

    def _anim_processing(self):
        """Animate processing: rotating spinner dots."""
        if self._current_state != "processing":
            return

        self._canvas.delete("spinner")
        cx = PILL_WIDTH / 2
        cy = PILL_HEIGHT / 2
        dot_count = 8
        radius = 10

        for i in range(dot_count):
            angle = (2 * math.pi * i / dot_count) - (self._anim_index * 0.3)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)

            # Fade effect
            brightness = ((i + self._anim_index) % dot_count) / dot_count
            r = 2 + brightness * 2
            gray = int(40 + brightness * 140)
            color = f"#{gray:02x}{int(gray * 0.9):02x}{int(gray * 1.1):02x}"

            self._canvas.create_oval(
                x - r, y - r, x + r, y + r, fill=color, outline="", tags="spinner"
            )

        self._draw_mode_icon()
        self._anim_index += 1
        self._anim_id = self._root.after(60, self._anim_processing)

    def _set_result(self, text: str):
        self._current_state = "result"
        self._cancel_result_timer()
        self._ensure_full()
        self._clear_content()

        # Show text briefly in the pill
        display = text if len(text) <= 35 else text[:32] + "..."
        self._canvas.create_text(
            PILL_WIDTH / 2,
            PILL_HEIGHT / 2,
            text=display,
            fill=DOT_RESULT,
            font=("Segoe UI", 10),
            tags="text",
        )

        self._result_timer_id = self._root.after(3000, self._set_idle)

    def _set_error(self, msg: str):
        self._current_state = "error"
        self._cancel_result_timer()
        self._ensure_full()
        self._clear_content()

        display = msg if len(msg) <= 35 else msg[:32] + "..."
        self._canvas.create_text(
            PILL_WIDTH / 2,
            PILL_HEIGHT / 2,
            text=display,
            fill=DOT_ERROR,
            font=("Segoe UI", 10),
            tags="text",
        )

        self._result_timer_id = self._root.after(4000, self._set_idle)

    def _set_mode(self, mode: str):
        self._current_mode = mode
        self._ensure_full()
        # Redraw to update icon color
        if self._current_state == "idle":
            self._draw_idle_dots()
        else:
            self._draw_mode_icon()

        # Update mini dot
        color = TRANSLATE_ON if mode == "translate" else DOT_IDLE
        self._mini_canvas.itemconfig(self._mini_dot, fill=color)

        self._start_hide_timer()
