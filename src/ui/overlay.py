"""
Floating overlay — Apple Liquid Glass design.

All rendering via Pillow + Win32 UpdateLayeredWindow for true per-pixel alpha.
Desktop captured & blurred for real frosted glass effect.
2x supersampling for full anti-aliasing on everything.
No tkinter Canvas — tkinter only used for event loop & timers.
"""

import collections
import ctypes
import ctypes.wintypes as wt
import io
import logging
import math
import queue
import random
import threading
import tkinter as tk
import wave
import winsound
from typing import Optional

import numpy as np
from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageGrab,
)

logger = logging.getLogger(__name__)

# ── Win32 ──
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# ── Win32 function signatures (critical on 64-bit: default restype=c_int truncates handles) ──
_PTR = ctypes.c_void_p

user32.GetParent.argtypes = [_PTR]
user32.GetParent.restype = _PTR

user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = _PTR

user32.GetWindowLongW.argtypes = [_PTR, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.SetWindowLongW.argtypes = [_PTR, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

user32.GetDC.argtypes = [_PTR]
user32.GetDC.restype = _PTR

user32.ReleaseDC.argtypes = [_PTR, _PTR]
user32.ReleaseDC.restype = ctypes.c_int

user32.UpdateLayeredWindow.argtypes = [
    _PTR,
    _PTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    _PTR,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
]
user32.UpdateLayeredWindow.restype = wt.BOOL

gdi32.CreateCompatibleDC.argtypes = [_PTR]
gdi32.CreateCompatibleDC.restype = _PTR

gdi32.CreateDIBSection.argtypes = [
    _PTR,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p),
    _PTR,
    wt.DWORD,
]
gdi32.CreateDIBSection.restype = _PTR

gdi32.SelectObject.argtypes = [_PTR, _PTR]
gdi32.SelectObject.restype = _PTR

gdi32.DeleteObject.argtypes = [_PTR]
gdi32.DeleteObject.restype = wt.BOOL

gdi32.DeleteDC.argtypes = [_PTR]
gdi32.DeleteDC.restype = wt.BOOL


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


# ── Design tokens ──
PILL_W, PILL_H, PILL_R = 280, 40, 20
PAD = 8  # Extra padding for drop shadow
WIN_W = PILL_W + PAD * 2
WIN_H = PILL_H + PAD * 2
MINI_SIZE = 14
SS = 2  # Supersample

# Glass material — neutral, lets background show through
REFRACTION_ZOOM = 0.10  # 10% magnification (convex lens effect)
GLASS_BLUR = 18
GLASS_SATURATION = 1.15
GLASS_TINT = (255, 255, 255, 22)  # Nearly invisible white overlay

# Shadow (beneath pill, not glow around)
SHADOW_COLOR = (0, 0, 0, 70)
SHADOW_OFFSET_Y = 3
SHADOW_BLUR = 5

# Waveform
WAVE_POINTS = 12
WAVE_MAX_H = 12
WAVE_MIN_H = 0.4
WAVE_WIDTH = 175
WAVE_FILL_HI = (255, 255, 255, 50)
WAVE_FILL_LO = (255, 255, 255, 15)
WAVE_LINE_HI = (255, 255, 255, 190)
WAVE_LINE_LO = (255, 255, 255, 60)
WAVE_GLOW_HI = (255, 255, 255, 30)

DOT_COLOR = (255, 255, 255, 60)

BADGE_ON_BG = (255, 255, 255, 35)
BADGE_ON_FG = (255, 255, 255, 210)
BADGE_OFF_BG = (255, 255, 255, 12)
BADGE_OFF_FG = (255, 255, 255, 70)

COLOR_RESULT = (255, 255, 255, 230)
COLOR_ERROR = (255, 120, 120, 230)

LEVEL_BUF = 48
AUTO_HIDE_MS = 1000


# ── Sound ──


def _np_to_wav(data, sr=44100):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(np.clip(data * 32767, -32768, 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def _make_start_snd():
    sr, d = 44100, 0.055
    t = np.linspace(0, d, int(sr * d), False)
    w1 = np.sin(2 * np.pi * 660 * t) * np.exp(-t * 30) * 0.15
    w2 = np.sin(2 * np.pi * 880 * t) * np.exp(-t * 30) * 0.15
    return _np_to_wav(
        np.concatenate([w1, np.zeros(int(sr * 0.015)), w2]).astype(np.float32)
    )


def _make_stop_snd():
    sr, d = 44100, 0.055
    t = np.linspace(0, d, int(sr * d), False)
    w1 = np.sin(2 * np.pi * 880 * t) * np.exp(-t * 30) * 0.12
    w2 = np.sin(2 * np.pi * 580 * t) * np.exp(-t * 35) * 0.10
    return _np_to_wav(
        np.concatenate([w1, np.zeros(int(sr * 0.015)), w2]).astype(np.float32)
    )


def _make_blip(freq, dur=0.06, vol=0.12):
    sr = 44100
    t = np.linspace(0, dur, int(sr * dur), False)
    e = np.exp(-t * 40)
    d = np.sin(2 * np.pi * freq * t) * e * vol
    d += np.sin(2 * np.pi * freq * 1.5 * t) * e * vol * 0.3
    return _np_to_wav(d.astype(np.float32))


# ── Helpers ──


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _premultiply_alpha(img):
    """Convert RGBA to premultiplied alpha (required by UpdateLayeredWindow with AC_SRC_ALPHA)."""
    arr = np.array(img, dtype=np.uint16)
    a = arr[:, :, 3:4]
    arr[:, :, :3] = arr[:, :, :3] * a // 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _capture_bg(x, y, w, h):
    """Capture desktop behind window, apply refraction zoom + frosted blur + saturation boost."""
    try:
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        iw, ih = img.size

        # Refraction: crop center and scale up → convex lens magnification
        mx = int(iw * REFRACTION_ZOOM / 2)
        my = int(ih * REFRACTION_ZOOM / 2)
        if mx > 0 and my > 0:
            img = img.crop((mx, my, iw - mx, ih - my))
            img = img.resize((iw, ih), Image.LANCZOS)

        # Frosted glass blur
        img = img.filter(ImageFilter.GaussianBlur(radius=GLASS_BLUR))

        # Saturation boost (glass makes colors richer)
        img = ImageEnhance.Color(img).enhance(GLASS_SATURATION)

        return img
    except Exception:
        return None


def _draw_glass_pill(img, bg_blur, s):
    """Draw Apple Liquid Glass pill — refraction, specular highlights, drop shadow."""
    pad = PAD * s
    pw, ph, pr = PILL_W * s, PILL_H * s, PILL_R * s
    iw, ih = img.size

    # Pill shape mask (reused for all layers)
    pill_mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(pill_mask).rounded_rectangle(
        [0, 0, pw - 1, ph - 1], radius=pr, fill=255
    )

    # ── 1. Drop shadow (beneath pill — creates floating depth) ──
    shadow = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    sh_y = pad + int(SHADOW_OFFSET_Y * s)
    sh_fill = Image.new("RGBA", (pw, ph), SHADOW_COLOR)
    shadow.paste(sh_fill, (pad, sh_y), pill_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(SHADOW_BLUR * s)))
    img.paste(Image.alpha_composite(img.copy(), shadow), (0, 0))

    # ── 2. Glass body (refracted + blurred background) ──
    if bg_blur:
        glass = bg_blur.resize((pw, ph), Image.LANCZOS).convert("RGBA")
    else:
        glass = Image.new("RGBA", (pw, ph), (50, 52, 60, 255))

    # Very subtle white tint (lets background color dominate)
    glass = Image.alpha_composite(glass, Image.new("RGBA", (pw, ph), GLASS_TINT))

    # Paste through pill mask
    img.paste(glass, (pad, pad), pill_mask)

    # ── 3. Top specular glow (overhead light through glass volume) ──
    glow = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    # Wide, flat ellipse extending above pill — only lower portion visible
    ew = int(pw * 0.6)
    eh = int(ph * 1.0)
    gd.ellipse(
        [(pw - ew) // 2, -int(eh * 0.55), (pw + ew) // 2, int(eh * 0.45)],
        fill=(255, 255, 255, 35),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(int(5 * s)))

    # Composite glow through pill mask
    glow_full = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    glow_full.paste(glow, (pad, pad), pill_mask)
    img.paste(Image.alpha_composite(img.copy(), glow_full), (0, 0))

    # ── 4. Fresnel edge (bright at top, dims toward bottom) ──
    edge = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        [0, 0, pw - 1, ph - 1],
        radius=pr,
        outline=(255, 255, 255, 140),
        width=max(1, s),
    )

    # Gradient mask: top = bright, bottom = subtle (not zero — keeps rim visible)
    grad = Image.new("L", (pw, ph), 0)
    for row in range(ph):
        t = 1.0 - (row / ph)
        val = int((0.12 + 0.88 * (t**1.3)) * 255)
        grad.paste(val, (0, row, pw, row + 1))

    edge_alpha = edge.split()[3]
    edge_alpha = ImageChops.multiply(edge_alpha, grad)
    edge.putalpha(edge_alpha)

    edge_full = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    edge_full.paste(edge, (pad, pad))
    img.paste(Image.alpha_composite(img.copy(), edge_full), (0, 0))


class OverlayWindow:
    def __init__(self):
        self._root = None
        self._thread = None
        self._queue = queue.Queue()
        self._running = False
        self._ready = threading.Event()

        self._mode = "transcribe"
        self._state = "idle"
        self._is_mini = False
        self._ai = 0
        self._anim_id = None
        self._hide_id = None
        self._result_id = None
        self._result_text = ""
        self._hwnd = None

        self._sw = self._sh = 0
        self._win_x = self._win_y = 0
        self._bg_blur = None
        self._glass_cache = None

        self._ulw_warned = False
        self._font_cache = {}
        self._audio_levels = collections.deque([0.0] * LEVEL_BUF, maxlen=LEVEL_BUF)
        self._level_lock = threading.Lock()
        self._smooth = [0.0] * WAVE_POINTS

        self._wav_start = _make_start_snd()
        self._wav_stop = _make_stop_snd()
        self._wav_mode_on = _make_blip(880)
        self._wav_mode_off = _make_blip(520)

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
        """Get font with Korean support. Cached to avoid reload every frame."""
        key = (bold, size)
        if key not in self._font_cache:
            # Malgun Gothic = Windows standard Korean font, Segoe UI = fallback
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

    # ── Tkinter (event loop only) ──

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
        self._root.update_idletasks()

        # Get top-level HWND — try multiple methods for robustness
        hwnd = None

        # Method 1: wm_frame() — returns the OS-level frame HWND
        try:
            frame = self._root.wm_frame()
            if frame:
                val = int(str(frame), 16) if isinstance(frame, str) else int(frame)
                if val:
                    hwnd = val
        except Exception:
            pass

        # Method 2: GetParent of internal Tk widget
        if not hwnd:
            hwnd = user32.GetParent(self._root.winfo_id())

        # Method 3: winfo_id itself (overrideredirect may make this the top-level)
        if not hwnd:
            hwnd = self._root.winfo_id()

        self._hwnd = hwnd
        logger.info(f"Overlay HWND: {hwnd:#x}")

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        ret = user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        if not ret and style:
            logger.warning(
                f"SetWindowLongW returned 0, last error: {ctypes.get_last_error()}"
            )

    def _capture_desktop(self):
        self._bg_blur = _capture_bg(self._win_x, self._win_y, WIN_W, WIN_H)

    def _build_glass_cache(self):
        s = SS
        img = Image.new("RGBA", (WIN_W * s, WIN_H * s), (0, 0, 0, 0))
        _draw_glass_pill(img, self._bg_blur, s)
        self._glass_cache = img

    # ── Win32 ──

    def _push_image(self, pil_img):
        if not self._hwnd:
            return

        # Premultiply alpha (mandatory for UpdateLayeredWindow + AC_SRC_ALPHA)
        pil_img = _premultiply_alpha(pil_img)

        w, h = pil_img.size
        raw = pil_img.tobytes("raw", "BGRA")

        hdc_scr = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_scr)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # negative = top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32

        ppv = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_scr, ctypes.byref(bmi), 0, ctypes.byref(ppv), None, 0
        )
        if not hbmp:
            logger.warning("CreateDIBSection failed")
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_scr)
            return

        ctypes.memmove(ppv, raw, len(raw))
        old = gdi32.SelectObject(hdc_mem, hbmp)

        sz = wt.SIZE(w, h)
        pt_src = wt.POINT(0, 0)
        pt_dst = wt.POINT(self._win_x, self._win_y)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        ok = user32.UpdateLayeredWindow(
            self._hwnd,
            hdc_scr,
            ctypes.byref(pt_dst),
            ctypes.byref(sz),
            hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )
        if not ok and not self._ulw_warned:
            self._ulw_warned = True
            logger.error(
                f"UpdateLayeredWindow failed, last error: {ctypes.get_last_error()}"
            )

        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_scr)

    # ── Rendering ──

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
        draw = ImageDraw.Draw(img)
        cx = (WIN_W / 2 - 14) * s
        cy = (PAD + PILL_H / 2) * s

        if self._state == "idle":
            self._draw_dots(draw, s, cx, cy)
        elif self._state == "recording":
            self._draw_waveform(img, s, cx, cy)
        elif self._state == "processing":
            self._draw_spinner(draw, s, cx, cy)
        elif self._state in ("result", "error"):
            self._draw_text(draw, s, cx, cy)

        self._draw_badge(draw, s)
        return img.resize((WIN_W, WIN_H), Image.LANCZOS)

    def _render_mini(self):
        s = 4
        sz = MINI_SIZE * s
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        c = (70, 180, 255, 200) if self._mode == "translate" else (50, 55, 70, 160)
        draw.ellipse([s, s, sz - s, sz - s], fill=c)
        return img.resize((MINI_SIZE, MINI_SIZE), Image.LANCZOS)

    # ── Content drawers ──

    def _draw_dots(self, draw, s, cx, cy):
        count, sp = 10, 14 * s
        sx = cx - (count - 1) * sp / 2
        for i in range(count):
            x, r = sx + i * sp, 2.5 * s
            draw.ellipse([x - r, cy - r, x + r, cy + r], fill=DOT_COLOR)

    def _draw_waveform(self, img, s, cx, cy):
        """Draw waveform on separate layer with blur for anti-aliased edges."""
        levels = self._downsample_levels()
        ww = WAVE_WIDTH * s
        sx = cx - ww / 2
        step = ww / max(1, WAVE_POINTS - 1)

        for i in range(WAVE_POINTS):
            self._smooth[i] = self._smooth[i] * 0.3 + levels[i] * 0.7

        avg = sum(self._smooth) / len(self._smooth)
        t = min(1.0, avg * 2.5)

        top, bot = [], []
        for i in range(WAVE_POINTS):
            x = sx + i * step
            lv = max(self._smooth[i], 0.01)  # Minimal baseline, no random noise
            h = (WAVE_MIN_H + lv * (WAVE_MAX_H - WAVE_MIN_H)) * s
            top.append((x, cy - h))
            bot.append((x, cy + h))

        # Draw on separate layer — Pillow polygons have NO anti-aliasing,
        # so we blur the layer slightly to soften jagged edges
        wave = Image.new("RGBA", img.size, (0, 0, 0, 0))
        wd = ImageDraw.Draw(wave)

        # Fill polygon
        poly = top + bot[::-1]
        if len(poly) >= 3:
            wd.polygon(poly, fill=_lerp(WAVE_FILL_LO, WAVE_FILL_HI, t))

        # Edge lines
        lc = _lerp(WAVE_LINE_LO, WAVE_LINE_HI, t)
        lw = max(2, int(2.0 * s))
        if len(top) >= 2:
            wd.line(top, fill=lc, width=lw, joint="curve")
            wd.line(bot, fill=lc, width=lw, joint="curve")

        # Soften aliased polygon/line edges
        wave = wave.filter(ImageFilter.GaussianBlur(max(1, int(0.6 * s))))

        # Composite onto glass
        result = Image.alpha_composite(img, wave)
        img.paste(result, (0, 0))

    def _draw_spinner(self, draw, s, cx, cy):
        n, rad = 8, 10 * s
        for i in range(n):
            angle = (2 * math.pi * i / n) - (self._ai * 0.35)
            x = cx + rad * math.cos(angle)
            y = cy + rad * math.sin(angle)
            bright = ((i + self._ai) % n) / n
            r = (1.5 + bright * 2) * s
            a = int(25 + bright * 210)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))

    def _draw_text(self, draw, s, cx, cy):
        txt = self._result_text
        if len(txt) > 28:
            txt = txt[:25] + "..."
        color = COLOR_RESULT if self._state == "result" else COLOR_ERROR
        font = self._get_font(int(10 * s), bold=False)
        bb = draw.textbbox((0, 0), txt, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text((cx - tw / 2, cy - th / 2 - bb[1]), txt, fill=color, font=font)

    def _draw_badge(self, draw, s):
        bx = (PAD + PILL_W - 34) * s
        by = (PAD + PILL_H / 2) * s
        bw, bh, r = 28 * s, 16 * s, 5 * s
        x1, y1 = bx - bw / 2, by - bh / 2
        x2, y2 = bx + bw / 2, by + bh / 2
        bg, fg = (
            (BADGE_ON_BG, BADGE_ON_FG)
            if self._mode == "translate"
            else (BADGE_OFF_BG, BADGE_OFF_FG)
        )
        draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=bg)
        font = self._get_font(int(7.5 * s), bold=True)
        bb = draw.textbbox((0, 0), "TR", font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text((bx - tw / 2, by - th / 2 - bb[1]), "TR", fill=fg, font=font)

    def _downsample_levels(self):
        with self._level_lock:
            raw = list(self._audio_levels)
        n = len(raw)
        chunk = max(1, n // WAVE_POINTS)
        out = []
        for i in range(WAVE_POINTS):
            start = i * chunk
            end = min(start + chunk, n)
            out.append(
                sum(raw[start:end]) / max(1, end - start) if start < end else 0.0
            )
        return out

    # ── State machine ──

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
        h = {
            "quit": lambda: (setattr(self, "_running", False), self._root.quit()),
            "idle": self._set_idle,
            "recording": self._set_recording,
            "processing": self._set_processing,
            "result": lambda: self._set_result(data),
            "error": lambda: self._set_error(data),
            "mode": lambda: self._set_mode(data),
        }
        fn = h.get(cmd)
        if fn:
            fn()

    def _set_idle(self):
        self._state = "idle"
        self._cancel_anim()
        self._cancel_result()
        self._ensure_full()
        self._render_and_push()
        self._start_hide()

    def _set_recording(self):
        self._state = "recording"
        self._cancel_anim()
        self._cancel_result()
        self._ensure_full()
        with self._level_lock:
            self._audio_levels.clear()
            self._audio_levels.extend([0.0] * LEVEL_BUF)
        self._smooth = [0.0] * WAVE_POINTS
        self._anim_wave()

    def _anim_wave(self):
        if self._state != "recording":
            return
        self._render_and_push()
        self._anim_id = self._root.after(40, self._anim_wave)

    def _set_processing(self):
        self._state = "processing"
        self._cancel_anim()
        self._cancel_result()
        self._ensure_full()
        self._ai = 0
        self._anim_spin()

    def _anim_spin(self):
        if self._state != "processing":
            return
        self._render_and_push()
        self._ai += 1
        self._anim_id = self._root.after(55, self._anim_spin)

    def _set_result(self, text):
        self._state = "result"
        self._result_text = text
        self._cancel_anim()
        self._cancel_result()
        self._ensure_full()
        self._render_and_push()
        self._result_id = self._root.after(3000, self._set_idle)

    def _set_error(self, msg):
        self._state = "error"
        self._result_text = msg
        self._cancel_anim()
        self._cancel_result()
        self._ensure_full()
        self._render_and_push()
        self._result_id = self._root.after(4000, self._set_idle)

    def _set_mode(self, mode):
        self._mode = mode
        self._ensure_full()
        wav = self._wav_mode_on if mode == "translate" else self._wav_mode_off
        threading.Thread(
            target=lambda: winsound.PlaySound(wav, winsound.SND_MEMORY), daemon=True
        ).start()
        self._render_and_push()
        self._start_hide()

    # ── Full / Mini ──

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

    # ── Timers ──

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
