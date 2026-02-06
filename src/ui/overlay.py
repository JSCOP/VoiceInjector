"""Floating overlay renderer and state orchestrator."""

import collections
import logging
import queue
import threading
import time
import tkinter as tk
import winsound

from PIL import Image, ImageDraw, ImageFont

from .animation import (
    ANIM_INTERVAL_MS,
    TRANS_FAST,
    TRANS_MEDIUM,
    TRANS_SLOW,
    TransitionState,
)
from .content_drawers import downsample_levels, draw_badge, draw_state_content
from .glass_renderer import (
    AUTO_HIDE_MS,
    LEVEL_BUF,
    MINI_SIZE,
    PAD,
    PILL_H,
    SS,
    WIN_H,
    WIN_W,
    WAVE_POINTS,
    capture_background,
    draw_glass_pill,
)
from .sounds import _make_blip, _make_start_snd, _make_stop_snd
from .win32_layer import LayeredWindow

logger = logging.getLogger(__name__)


class OverlayWindow:
    def __init__(self):
        self._root = None
        self._thread = None
        self._queue = queue.Queue()
        self._running = False
        self._ready = threading.Event()

        self._mode = "transcribe"
        self._state = "idle"
        self._transition = TransitionState()
        self._is_mini = False
        self._ai = 0
        self._anim_id = None
        self._hide_id = None
        self._result_id = None
        self._result_text = ""
        self._last_tick = time.monotonic()

        self._sw = self._sh = 0
        self._win_x = self._win_y = 0
        self._bg_blur = None
        self._glass_cache = None

        self._layer = LayeredWindow()
        self._font_cache = {}
        self._audio_levels = collections.deque([0.0] * LEVEL_BUF, maxlen=LEVEL_BUF)
        self._level_lock = threading.Lock()
        self._smooth = [0.0] * WAVE_POINTS

        self._wav_start = _make_start_snd()
        self._wav_stop = _make_stop_snd()
        self._wav_mode_on = _make_blip(880)
        self._wav_mode_off = _make_blip(520)

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

    def show_result(self, t):
        self._cmd("result", t)

    def show_error(self, m):
        self._cmd("error", m)

    def update_mode(self, m):
        self._mode = m
        self._cmd("mode", m)

    def push_audio_level(self, level):
        with self._level_lock:
            self._audio_levels.append(max(0.0, min(1.0, level)))

    def play_start_sound(self):
        try:
            winsound.PlaySound(self._wav_start, winsound.SND_MEMORY)
        except Exception:
            pass

    def play_stop_sound(self):
        threading.Thread(
            target=lambda: winsound.PlaySound(self._wav_stop, winsound.SND_MEMORY),
            daemon=True,
        ).start()

    def _get_font(self, size, bold=False):
        key = (bold, size)
        if key not in self._font_cache:
            names = (
                ("malgunbd.ttf", "segoeuib.ttf")
                if bold
                else ("malgun.ttf", "segoeui.ttf")
            )
            for name in names:
                try:
                    self._font_cache[key] = ImageFont.truetype(name, size)
                    break
                except Exception:
                    continue
            else:
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]

    def _cmd(self, c, d=""):
        try:
            self._queue.put_nowait((c, d))
        except queue.Full:
            pass

    def _run(self):
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            self._setup()
            self._capture_desktop()
            self._build_glass_cache()
            self._root.deiconify()
            self._make_layered()
            self._render_and_push()
            self._root.after(50, self._poll)
            self._start_hide()
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
        self._sw = r.winfo_screenwidth()
        self._sh = r.winfo_screenheight()
        self._win_x = (self._sw - WIN_W) // 2
        self._win_y = self._sh - WIN_H - 60
        r.geometry(f"{WIN_W}x{WIN_H}+{self._win_x}+{self._win_y}")

    def _make_layered(self):
        self._layer.setup_hwnd(self._root)
        self._layer.set_layered_style()

    def _capture_desktop(self):
        self._bg_blur = capture_background(self._win_x, self._win_y, WIN_W, WIN_H)

    def _build_glass_cache(self):
        s = SS
        img = Image.new("RGBA", (WIN_W * s, WIN_H * s), (0, 0, 0, 0))
        draw_glass_pill(img, self._bg_blur, s)
        self._glass_cache = img

    def _push_image(self, pil_img):
        self._layer.push_image(pil_img, self._win_x, self._win_y)

    def _render_and_push(self):
        img = self._render_mini() if self._is_mini else self._render_full()
        self._push_image(img)

    def _render_full(self):
        s = SS
        img = (
            self._glass_cache.copy()
            if self._glass_cache
            else Image.new("RGBA", (WIN_W * s, WIN_H * s), (0, 0, 0, 0))
        )
        cx = (WIN_W / 2 - 14) * s
        cy = (PAD + PILL_H / 2) * s

        ep = self._transition.update()
        if self._transition.active:
            self._smooth = draw_state_content(
                img,
                s,
                cx,
                cy,
                self._transition.from_state,
                1.0 - ep,
                self._ai,
                self._smooth,
                self._downsample_levels,
                self._result_text,
                self._get_font,
            )
            self._smooth = draw_state_content(
                img,
                s,
                cx,
                cy,
                self._transition.to_state,
                ep,
                self._ai,
                self._smooth,
                self._downsample_levels,
                self._result_text,
                self._get_font,
            )
        else:
            self._smooth = draw_state_content(
                img,
                s,
                cx,
                cy,
                self._state,
                1.0,
                self._ai,
                self._smooth,
                self._downsample_levels,
                self._result_text,
                self._get_font,
            )

        draw_badge(ImageDraw.Draw(img), s, self._mode, self._get_font)
        return img.resize((WIN_W, WIN_H), Image.LANCZOS)

    def _render_mini(self):
        s = 4
        sz = MINI_SIZE * s
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        c = (255, 255, 255, 210) if self._mode == "translate" else (255, 255, 255, 120)
        draw.ellipse([s, s, sz - s, sz - s], fill=c)
        return img.resize((MINI_SIZE, MINI_SIZE), Image.LANCZOS)

    def _downsample_levels(self):
        with self._level_lock:
            raw = list(self._audio_levels)
        return downsample_levels(raw, WAVE_POINTS)

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
        handlers = {
            "quit": lambda: (setattr(self, "_running", False), self._root.quit()),
            "idle": self._set_idle,
            "recording": self._set_recording,
            "processing": self._set_processing,
            "result": lambda: self._set_result(data),
            "error": lambda: self._set_error(data),
            "mode": lambda: self._set_mode(data),
        }
        fn = handlers.get(cmd)
        if fn:
            fn()

    def _begin_transition(self, to_state, duration):
        self._transition.begin(self._state, to_state, duration)
        self._state = to_state
        self._cancel_anim()
        self._anim_tick()

    def _anim_tick(self):
        if not self._running:
            return
        self._last_tick = time.monotonic()
        if self._state == "processing":
            self._ai += 1
        self._render_and_push()
        if self._transition.active or self._state in ("recording", "processing"):
            self._anim_id = self._root.after(ANIM_INTERVAL_MS, self._anim_tick)
        else:
            self._anim_id = None

    def _set_idle(self):
        self._cancel_result()
        self._ensure_full()
        self._begin_transition("idle", TRANS_SLOW)
        self._start_hide()

    def _set_recording(self):
        self._cancel_result()
        self._ensure_full()
        with self._level_lock:
            self._audio_levels.clear()
            self._audio_levels.extend([0.0] * LEVEL_BUF)
        self._smooth = [0.0] * WAVE_POINTS
        self._begin_transition("recording", TRANS_FAST)

    def _set_processing(self):
        self._cancel_result()
        self._ensure_full()
        self._ai = 0
        self._begin_transition("processing", TRANS_FAST)

    def _set_result(self, text):
        self._result_text = text
        self._cancel_result()
        self._ensure_full()
        self._begin_transition("result", TRANS_MEDIUM)
        self._result_id = self._root.after(3000, self._set_idle)

    def _set_error(self, msg):
        self._result_text = msg
        self._cancel_result()
        self._ensure_full()
        self._begin_transition("error", TRANS_MEDIUM)
        self._result_id = self._root.after(4000, self._set_idle)

    def _set_mode(self, mode):
        self._mode = mode
        self._ensure_full()
        wav = self._wav_mode_on if mode == "translate" else self._wav_mode_off
        threading.Thread(
            target=lambda: winsound.PlaySound(wav, winsound.SND_MEMORY),
            daemon=True,
        ).start()
        self._result_text = "번역 ON" if mode == "translate" else "Transcribe"
        self._begin_transition("result", TRANS_FAST)
        self._cancel_result()
        self._result_id = self._root.after(1500, self._set_idle)

    def _to_full(self):
        if not self._is_mini:
            return
        self._is_mini = False
        self._win_x = (self._sw - WIN_W) // 2
        self._win_y = self._sh - WIN_H - 60
        self._root.geometry(f"{WIN_W}x{WIN_H}+{self._win_x}+{self._win_y}")
        self._render_and_push()

    def _to_mini(self):
        if self._is_mini or self._state != "idle":
            return
        self._is_mini = True
        self._win_x = (self._sw - MINI_SIZE) // 2
        self._win_y = self._sh - MINI_SIZE - 68
        self._root.geometry(f"{MINI_SIZE}x{MINI_SIZE}+{self._win_x}+{self._win_y}")
        self._render_and_push()

    def _ensure_full(self):
        if self._is_mini:
            self._to_full()
        self._cancel_hide()

    def _start_hide(self):
        self._cancel_hide()
        self._hide_id = self._root.after(AUTO_HIDE_MS, self._to_mini)

    def _cancel_hide(self):
        if self._hide_id:
            try:
                self._root.after_cancel(self._hide_id)
            except Exception:
                pass
            self._hide_id = None

    def _cancel_result(self):
        if self._result_id:
            try:
                self._root.after_cancel(self._result_id)
            except Exception:
                pass
            self._result_id = None

    def _cancel_anim(self):
        if self._anim_id:
            try:
                self._root.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
