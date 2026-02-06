"""
Text injection module using Win32 SendInput API.
Injects text at the current cursor position in any application.
Supports Unicode (Korean, English, symbols, etc.)
"""

import ctypes
import ctypes.wintypes
import logging
import time

logger = logging.getLogger(__name__)

# Win32 constants
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002

# ULONG_PTR type (8 bytes on x64, 4 bytes on x86)
ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


# Win32 structures - must match exact Windows layout for SendInput to work
class MOUSEINPUT(ctypes.Structure):
    """Required in the union so sizeof(INPUT) matches Windows' expectation (40 bytes on x64)."""

    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


class TextInjector:
    """
    Injects text at the current cursor position using Win32 SendInput.

    Uses KEYEVENTF_UNICODE flag to send Unicode characters directly,
    which works with Korean, Japanese, Chinese, emoji, and all other
    Unicode text in any application.
    """

    def __init__(
        self,
        keystroke_delay: float = 0.005,
        add_trailing_space: bool = True,
        add_trailing_newline: bool = False,
    ):
        self.keystroke_delay = keystroke_delay
        self.add_trailing_space = add_trailing_space
        self.add_trailing_newline = add_trailing_newline

        # Get SendInput function
        self._send_input = ctypes.windll.user32.SendInput
        self._send_input.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        self._send_input.restype = ctypes.c_uint

        # Verify struct size (should be 40 on x64 Windows)
        input_size = ctypes.sizeof(INPUT)
        logger.info(f"INPUT struct size: {input_size} bytes")
        if input_size not in (28, 40):  # 28 for x86, 40 for x64
            logger.warning(
                f"INPUT struct size {input_size} looks wrong! "
                f"Expected 28 (x86) or 40 (x64). SendInput may fail."
            )

    def _make_unicode_input(self, char: str, key_up: bool = False) -> INPUT:
        """Create an INPUT structure for a Unicode character."""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = ord(char)
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = None
        return inp

    def _make_vk_input(self, vk_code: int, key_up: bool = False) -> INPUT:
        """Create an INPUT structure for a virtual key code."""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk_code
        inp.union.ki.wScan = 0
        inp.union.ki.dwFlags = KEYEVENTF_KEYUP if key_up else 0
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = None
        return inp

    def _send_char(self, char: str):
        """Send a single Unicode character (key down + key up)."""
        inputs = (INPUT * 2)()
        inputs[0] = self._make_unicode_input(char, key_up=False)
        inputs[1] = self._make_unicode_input(char, key_up=True)

        result = self._send_input(2, inputs, ctypes.sizeof(INPUT))
        if result != 2:
            err = ctypes.get_last_error()
            logger.warning(
                f"SendInput returned {result} (expected 2) for char '{char}', "
                f"last error={err}"
            )

    def inject_text(self, text: str):
        """
        Inject text at the current cursor position.

        Each character is sent as a Unicode keystroke event,
        making this work in any application regardless of input method.

        Args:
            text: The text to inject (any Unicode string)
        """
        if not text:
            return

        # Append trailing space/newline if configured
        if self.add_trailing_space and not text.endswith(" "):
            text += " "
        if self.add_trailing_newline and not text.endswith("\n"):
            text += "\n"

        logger.info(
            f"Injecting {len(text)} characters: "
            f"'{text[:50]}{'...' if len(text) > 50 else ''}'"
        )

        for char in text:
            if char == "\n":
                self._send_enter()
            else:
                self._send_char(char)

            if self.keystroke_delay > 0:
                time.sleep(self.keystroke_delay)

        logger.debug("Text injection complete")

    def inject_text_fast(self, text: str):
        """
        Inject text using batch SendInput for maximum speed.
        Sends all characters in a single SendInput call.

        Args:
            text: The text to inject
        """
        if not text:
            return

        if self.add_trailing_space and not text.endswith(" "):
            text += " "
        if self.add_trailing_newline and not text.endswith("\n"):
            text += "\n"

        logger.info(f"Fast-injecting {len(text)} characters")

        # Build all input events (2 per char: down + up)
        events = []
        for char in text:
            if char == "\n":
                events.append(self._make_vk_input(0x0D, key_up=False))
                events.append(self._make_vk_input(0x0D, key_up=True))
            else:
                events.append(self._make_unicode_input(char, key_up=False))
                events.append(self._make_unicode_input(char, key_up=True))

        if not events:
            return

        # Send all at once
        input_array = (INPUT * len(events))(*events)
        result = self._send_input(len(events), input_array, ctypes.sizeof(INPUT))

        if result != len(events):
            err = ctypes.get_last_error()
            logger.warning(
                f"SendInput returned {result} (expected {len(events)}), "
                f"last error={err}"
            )
        else:
            logger.debug(f"Fast text injection complete ({result} events sent)")

    def _send_enter(self):
        """Send the Enter key."""
        inputs = (INPUT * 2)()
        inputs[0] = self._make_vk_input(0x0D, key_up=False)
        inputs[1] = self._make_vk_input(0x0D, key_up=True)
        self._send_input(2, inputs, ctypes.sizeof(INPUT))

    @staticmethod
    def clipboard_inject(text: str):
        """
        Alternative injection method using clipboard (Ctrl+V).
        Faster for long texts but overwrites clipboard content.
        """
        import subprocess

        # Use clip.exe for reliable clipboard copy
        process = subprocess.Popen(
            ["clip.exe"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.communicate(input=text.encode("utf-16-le"))

        time.sleep(0.05)

        # Send Ctrl+V
        VK_CONTROL = 0x11
        VK_V = 0x56

        user32 = ctypes.windll.user32
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_V, 0, 2, 0)
        user32.keybd_event(VK_CONTROL, 0, 2, 0)

        logger.info(f"Clipboard injection complete ({len(text)} chars)")
