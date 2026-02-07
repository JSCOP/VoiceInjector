import ctypes
import ctypes.wintypes as wt
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
MONITOR_DEFAULTTONEAREST = 2

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

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

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = _PTR

user32.MonitorFromWindow.argtypes = [_PTR, wt.DWORD]
user32.MonitorFromWindow.restype = _PTR

user32.GetMonitorInfoW.argtypes = [_PTR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wt.BOOL

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


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


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


def _premultiply_alpha(img):
    arr = np.array(img, dtype=np.uint16)
    a = arr[:, :, 3:4]
    arr[:, :, :3] = arr[:, :, :3] * a // 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


class LayeredWindow:
    def __init__(self):
        self.hwnd = None
        self.win_x = 0
        self.win_y = 0
        self.ulw_warned = False

    def setup_hwnd(self, root):
        root.update_idletasks()
        hwnd = None
        try:
            frame = root.wm_frame()
            if frame:
                val = int(str(frame), 16) if isinstance(frame, str) else int(frame)
                if val:
                    hwnd = val
        except Exception:
            pass

        if not hwnd:
            hwnd = user32.GetParent(root.winfo_id())

        if not hwnd:
            hwnd = root.winfo_id()

        self.hwnd = hwnd
        logger.info(f"Overlay HWND: {hwnd:#x}")

    def set_layered_style(self):
        if not self.hwnd:
            return
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        ret = user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        if not ret and style:
            logger.warning(
                f"SetWindowLongW returned 0, last error: {ctypes.get_last_error()}"
            )

    @staticmethod
    def get_active_monitor_rect():
        """Get the work area (left, top, width, height) of the monitor
        containing the current foreground window."""
        try:
            fg = user32.GetForegroundWindow()
            if not fg:
                return None
            hmon = user32.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST)
            if not hmon:
                return None
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                return None
            rc = mi.rcWork  # work area excludes taskbar
            return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
        except Exception:
            return None

    def push_image(self, pil_img, win_x, win_y):
        if not self.hwnd:
            return

        self.win_x = win_x
        self.win_y = win_y
        pil_img = _premultiply_alpha(pil_img)
        w, h = pil_img.size
        raw = pil_img.tobytes("raw", "BGRA")

        hdc_scr = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_scr)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
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
        pt_dst = wt.POINT(self.win_x, self.win_y)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        ok = user32.UpdateLayeredWindow(
            self.hwnd,
            hdc_scr,
            ctypes.byref(pt_dst),
            ctypes.byref(sz),
            hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )
        if not ok and not self.ulw_warned:
            self.ulw_warned = True
            logger.error(
                f"UpdateLayeredWindow failed, last error: {ctypes.get_last_error()}"
            )

        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_scr)
