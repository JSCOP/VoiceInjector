"""Floating overlay renderer and state orchestrator."""

import collections
import ctypes
import logging
import queue
import threading
import time
import tkinter as tk
import winsound

from PIL import Image, ImageDraw, ImageFont

# Request 1ms timer resolution for smooth animations on high-refresh monitors
try:
    _winmm = ctypes.WinDLL("winmm")
except Exception:
    _winmm = None

from .animation import (
    ANIM_INTERVAL_MS,
    MORPH_DURATION,
    TRANS_FAST,
    TRANS_MEDIUM,
    TRANS_SLOW,
    MorphTransition,
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
        self._morph = MorphTransition()
        self._is_mini = False
        self._ai = 0.0  # float: time-based spinner accumulator
        self._anim_id = None
        self._hide_id = None
        self._result_id = None
        self._deferred_result_id = None
        self._result_text = ""
        self._last_tick = time.monotonic()
        self._processing_start = 0.0
        self._result_gen = 0  # generation token for deferred results

        self._sw = self._sh = 0
        self._mon_x = self._mon_y = 0  # monitor work area origin
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

    def move_to_active_monitor(self):
        """Reposition overlay to the monitor containing the foreground window."""
        self._cmd("move_monitor")

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
        if _winmm:
            _winmm.timeBeginPeriod(1)
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            self._setup()
            self._capture_desktop()
            self._build_glass_cache()
            self._root.deiconify()
            self._make_layered()
            self._render_and_push()
            self._root.after(ANIM_INTERVAL_MS, self._poll)
            self._start_hide()
            self._ready.set()
            self._root.mainloop()
        except Exception as e:
            logger.error(f"Overlay error: {e}", exc_info=True)
            self._ready.set()
        finally:
            if _winmm:
                _winmm.timeEndPeriod(1)

    def _setup(self):
        r = self._root
        r.title("VI")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        self._sw = r.winfo_screenwidth()
        self._sh = r.winfo_screenheight()
        self._mon_x = 0
        self._mon_y = 0
        self._win_x = self._mon_x + (self._sw - WIN_W) // 2
        self._win_y = self._mon_y + self._sh - WIN_H - 60
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

    def _render_morph(self, ep, cx, cy, cw, ch):
        """Render an intermediate frame during mini↔full morphing.
        Uses BILINEAR for speed during animation (LANCZOS only on final frame)."""
        if self._is_mini:
            # Shrinking: full → mini. Render full pill, scale down, fade to dot.
            full_img = self._render_full()
            if cw > 0 and ch > 0:
                morph_img = full_img.resize((cw, ch), Image.BILINEAR)
                # Fade out the pill as it shrinks
                alpha_mult = 1.0 - ep
                if alpha_mult < 1.0:
                    a = morph_img.split()[3]
                    a = a.point(lambda p: int(p * alpha_mult))
                    morph_img.putalpha(a)
                # Blend with mini dot fading in
                mini_img = self._render_mini()
                canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                canvas = Image.alpha_composite(canvas, morph_img)
                if ep > 0.3:
                    dot_alpha = min(1.0, (ep - 0.3) / 0.7)
                    dot = mini_img.copy()
                    da = dot.split()[3]
                    da = da.point(lambda p: int(p * dot_alpha))
                    dot.putalpha(da)
                    dx = (cw - MINI_SIZE) // 2
                    dy = (ch - MINI_SIZE) // 2
                    canvas.paste(dot, (max(0, dx), max(0, dy)), dot)
                self._layer.push_image(canvas, cx, cy)
        else:
            # Expanding: mini → full. Start from dot, morph to full pill.
            if cw > 0 and ch > 0:
                full_img = self._render_full()
                morph_img = full_img.resize((cw, ch), Image.BILINEAR)
                if ep < 1.0:
                    a = morph_img.split()[3]
                    a = a.point(lambda p: int(p * ep))
                    morph_img.putalpha(a)
                self._layer.push_image(morph_img, cx, cy)

    def _finalize_morph(self):
        """Finalize after morph completes — set final geometry."""
        if self._is_mini:
            self._win_x = self._morph.to_rect[0]
            self._win_y = self._morph.to_rect[1]
            self._root.geometry(f"{MINI_SIZE}x{MINI_SIZE}+{self._win_x}+{self._win_y}")
            self._render_and_push()
        else:
            self._win_x = self._morph.to_rect[0]
            self._win_y = self._morph.to_rect[1]
            self._render_and_push()

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
        self._root.after(ANIM_INTERVAL_MS, self._poll)

    def _handle(self, cmd, data):
        handlers = {
            "quit": lambda: (setattr(self, "_running", False), self._root.quit()),
            "idle": self._set_idle,
            "recording": self._set_recording,
            "processing": self._set_processing,
            "result": lambda: self._set_result(data),
            "error": lambda: self._set_error(data),
            "mode": lambda: self._set_mode(data),
            "move_monitor": self._move_to_monitor,
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
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        if self._state == "processing":
            self._ai += dt * 30.0  # equivalent to +1 per frame at original 30fps

        if self._morph.active:
            ep, (cx, cy, cw, ch) = self._morph.update()
            self._render_morph(ep, cx, cy, cw, ch)
            if self._morph.active:
                self._anim_id = self._root.after(ANIM_INTERVAL_MS, self._anim_tick)
            else:
                # Morph complete — finalize geometry
                self._finalize_morph()
                # Continue animation if content needs it
                if self._transition.active or self._state in (
                    "recording",
                    "processing",
                ):
                    self._anim_id = self._root.after(ANIM_INTERVAL_MS, self._anim_tick)
                else:
                    self._anim_id = None
        else:
            self._render_and_push()
            if self._transition.active or self._state in ("recording", "processing"):
                self._anim_id = self._root.after(ANIM_INTERVAL_MS, self._anim_tick)
            else:
                self._anim_id = None

    def _set_idle(self):
        self._cancel_result()
        self._cancel_deferred_result()
        self._ensure_full()
        self._begin_transition("idle", TRANS_SLOW)
        self._start_hide()

    def _set_recording(self):
        self._cancel_result()
        self._cancel_deferred_result()
        self._ensure_full()
        with self._level_lock:
            self._audio_levels.clear()
            self._audio_levels.extend([0.0] * LEVEL_BUF)
        self._smooth = [0.0] * WAVE_POINTS
        self._begin_transition("recording", TRANS_FAST)

    def _set_processing(self):
        self._cancel_result()
        self._cancel_deferred_result()
        self._ensure_full()
        self._ai = 0.0
        self._processing_start = time.monotonic()
        self._begin_transition("processing", TRANS_FAST)

    _MIN_PROCESSING_DISPLAY = 0.35  # seconds — minimum spinner visibility

    def _set_result(self, text):
        self._result_text = text
        self._cancel_result()
        self._cancel_deferred_result()

        # Ensure spinner is visible for minimum duration before showing result
        elapsed = time.monotonic() - self._processing_start
        if elapsed < self._MIN_PROCESSING_DISPLAY and self._state == "processing":
            delay_ms = int((self._MIN_PROCESSING_DISPLAY - elapsed) * 1000)
            self._result_gen += 1
            gen = self._result_gen
            self._deferred_result_id = self._root.after(
                delay_ms, lambda: self._finish_result(text, gen)
            )
            return

        self._finish_result(text, self._result_gen)

    def _finish_result(self, text, gen):
        """Actually display result. Guarded by generation token to prevent stale results."""
        if gen != self._result_gen:
            return  # stale deferred callback — a new recording started
        self._result_text = text
        self._ensure_full()
        self._begin_transition("result", TRANS_MEDIUM)
        self._result_id = self._root.after(3000, self._set_idle)

    def _set_error(self, msg):
        self._result_text = msg
        self._cancel_result()
        self._cancel_deferred_result()
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

    def _move_to_monitor(self):
        """Reposition overlay onto the monitor with the foreground window."""
        rect = self._layer.get_active_monitor_rect()
        if not rect:
            return
        mx, my, mw, mh = rect
        if (
            mx == self._mon_x
            and my == self._mon_y
            and mw == self._sw
            and mh == self._sh
        ):
            return  # already on this monitor
        self._mon_x, self._mon_y = mx, my
        self._sw, self._sh = mw, mh
        if self._is_mini:
            self._win_x = mx + (mw - MINI_SIZE) // 2
            self._win_y = my + mh - MINI_SIZE - 68
            self._root.geometry(f"{MINI_SIZE}x{MINI_SIZE}+{self._win_x}+{self._win_y}")
        else:
            self._win_x = mx + (mw - WIN_W) // 2
            self._win_y = my + mh - WIN_H - 60
            self._root.geometry(f"{WIN_W}x{WIN_H}+{self._win_x}+{self._win_y}")
        self._capture_desktop()
        self._build_glass_cache()
        self._render_and_push()
        logger.debug(f"Overlay moved to monitor at ({mx},{my}) {mw}x{mh}")

    def _to_full(self):
        if not self._is_mini:
            return
        self._is_mini = False
        # Capture glass for the full-size position before morphing
        new_x = self._mon_x + (self._sw - WIN_W) // 2
        new_y = self._mon_y + self._sh - WIN_H - 60
        self._capture_desktop()
        self._build_glass_cache()
        from_rect = (self._win_x, self._win_y, MINI_SIZE, MINI_SIZE)
        to_rect = (new_x, new_y, WIN_W, WIN_H)
        self._win_x, self._win_y = new_x, new_y
        # Set tkinter geometry to full size so HWND is large enough
        self._root.geometry(f"{WIN_W}x{WIN_H}+{new_x}+{new_y}")
        self._morph.begin(from_rect, to_rect, MORPH_DURATION)
        self._cancel_anim()
        self._anim_tick()

    def _to_mini(self):
        if self._is_mini or self._state != "idle":
            return
        self._is_mini = True
        new_x = self._mon_x + (self._sw - MINI_SIZE) // 2
        new_y = self._mon_y + self._sh - MINI_SIZE - 68
        from_rect = (self._win_x, self._win_y, WIN_W, WIN_H)
        to_rect = (new_x, new_y, MINI_SIZE, MINI_SIZE)
        self._morph.begin(from_rect, to_rect, MORPH_DURATION)
        self._cancel_anim()
        self._anim_tick()

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

    def _cancel_deferred_result(self):
        self._result_gen += 1  # invalidate any pending deferred callback
        if self._deferred_result_id:
            try:
                self._root.after_cancel(self._deferred_result_id)
            except Exception:
                pass
            self._deferred_result_id = None

    def _cancel_anim(self):
        if self._anim_id:
            try:
                self._root.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
