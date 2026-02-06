"""
Global hotkey system using pynput.
Handles push-to-talk and mode toggle hotkeys.

Special handling for Win key combinations:
- Suppresses Win key start menu when used as a hotkey modifier
"""

import logging
import threading
from typing import Callable, Dict, Optional, Set

from pynput import keyboard

logger = logging.getLogger(__name__)


def parse_hotkey(hotkey_str: str) -> Set[str]:
    """
    Parse a hotkey string like 'ctrl+shift+space' into a set of key names.
    Returns a set of normalized key identifiers.
    """
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    keys = set()
    for part in parts:
        if part in ("ctrl", "control"):
            keys.add("ctrl")
        elif part in ("shift",):
            keys.add("shift")
        elif part in ("alt",):
            keys.add("alt")
        elif part in ("win", "super", "cmd"):
            keys.add("cmd")
        else:
            keys.add(part)
    return keys


def key_to_name(key) -> Optional[str]:
    """Convert a pynput key object to a normalized name string."""
    try:
        if hasattr(key, "char") and key.char is not None:
            return key.char.lower()
        elif hasattr(key, "name"):
            name = key.name.lower()
            if name in ("ctrl_l", "ctrl_r"):
                return "ctrl"
            elif name in ("shift_l", "shift_r", "shift"):
                return "shift"
            elif name in ("alt_l", "alt_r", "alt_gr"):
                return "alt"
            elif name in ("cmd", "cmd_l", "cmd_r"):
                return "cmd"
            elif name == "space":
                return "space"
            elif name == "enter":
                return "enter"
            elif name == "tab":
                return "tab"
            elif name in ("esc", "escape"):
                return "esc"
            else:
                return name
        return None
    except Exception:
        return None


class HotkeyManager:
    """
    Manages global hotkeys with support for:
    - Push-to-talk (hold key combination)
    - Toggle actions (press key combination once)
    """

    def __init__(self):
        self._pressed_keys: Set[str] = set()
        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()

        # Registered hotkeys: name -> (key_set, on_press_callback, on_release_callback)
        self._hotkeys: Dict[str, tuple] = {}

        # Track which hotkeys are currently active (all keys pressed)
        self._active_hotkeys: Set[str] = set()

        # Track if Win key was used as part of a hotkey (to suppress start menu)
        self._win_used_in_hotkey = False

    def _uses_win_key(self) -> bool:
        """Check if any registered hotkey uses the Win key."""
        return any("cmd" in keys for keys, _, _ in self._hotkeys.values())

    def register_push_to_talk(
        self,
        name: str,
        hotkey_str: str,
        on_press: Callable,
        on_release: Callable,
    ):
        """
        Register a push-to-talk hotkey.
        on_press is called when all keys are held down.
        on_release is called when any key is released.
        """
        keys = parse_hotkey(hotkey_str)
        self._hotkeys[name] = (keys, on_press, on_release)
        logger.info(f"Registered push-to-talk hotkey '{name}': {hotkey_str} -> {keys}")

    def register_toggle(
        self,
        name: str,
        hotkey_str: str,
        on_toggle: Callable,
    ):
        """
        Register a toggle hotkey.
        on_toggle is called once when all keys are pressed simultaneously.
        """
        keys = parse_hotkey(hotkey_str)
        self._hotkeys[name] = (keys, on_toggle, None)
        logger.info(f"Registered toggle hotkey '{name}': {hotkey_str} -> {keys}")

    def _on_press(self, key):
        """Handle key press events."""
        name = key_to_name(key)
        if name is None:
            return

        with self._lock:
            self._pressed_keys.add(name)

            # Check all registered hotkeys
            for hk_name, (hk_keys, on_press, on_release) in self._hotkeys.items():
                if hk_keys.issubset(self._pressed_keys):
                    if hk_name not in self._active_hotkeys:
                        self._active_hotkeys.add(hk_name)

                        # Track Win key usage to suppress start menu later
                        if "cmd" in hk_keys:
                            self._win_used_in_hotkey = True

                        logger.debug(f"Hotkey '{hk_name}' activated")
                        if on_press:
                            try:
                                threading.Thread(target=on_press, daemon=True).start()
                            except Exception as e:
                                logger.error(f"Hotkey press callback error: {e}")

    def _on_release(self, key):
        """Handle key release events."""
        name = key_to_name(key)
        if name is None:
            return

        with self._lock:
            # If Win key is being released and was used in a hotkey,
            # suppress the Start menu by sending a dummy key
            if name == "cmd" and self._win_used_in_hotkey:
                self._win_used_in_hotkey = False
                self._suppress_win_start_menu()

            self._pressed_keys.discard(name)

            # Check which hotkeys should be deactivated
            for hk_name in list(self._active_hotkeys):
                hk_keys, on_press, on_release = self._hotkeys[hk_name]
                if not hk_keys.issubset(self._pressed_keys):
                    self._active_hotkeys.discard(hk_name)
                    logger.debug(f"Hotkey '{hk_name}' deactivated")
                    if on_release:
                        try:
                            threading.Thread(target=on_release, daemon=True).start()
                        except Exception as e:
                            logger.error(f"Hotkey release callback error: {e}")

    @staticmethod
    def _suppress_win_start_menu():
        """
        Suppress the Windows Start menu from opening when Win key is released.

        The trick: send a no-op key event (VK_NONAME = 0xFC) while Win is still
        logically held, which prevents Windows from interpreting the Win release
        as a Start menu toggle.
        """
        try:
            import ctypes

            # Send a harmless virtual key to break the Win key sequence
            # This prevents the Start Menu from popping up
            ctypes.windll.user32.keybd_event(0xFF, 0, 0, 0)  # VK_NONAME down
            ctypes.windll.user32.keybd_event(0xFF, 0, 2, 0)  # VK_NONAME up
        except Exception as e:
            logger.debug(f"Win key suppression failed: {e}")

    def start(self):
        """Start listening for hotkeys."""
        if self._listener is not None:
            logger.warning("Hotkey listener already running")
            return

        # Use win32_event_filter to suppress Win key if needed
        kwargs = {}
        if self._uses_win_key():
            logger.info("Win key detected in hotkeys, enabling start menu suppression")
            kwargs["win32_event_filter"] = self._win32_filter

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            **kwargs,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Hotkey listener started")

    def _win32_filter(self, msg, data):
        """
        Win32 low-level keyboard hook filter.
        Suppresses Win key default behavior when used as part of our hotkey.
        """
        # WM_KEYUP = 0x0101, WM_SYSKEYUP = 0x0105
        # VK_LWIN = 0x5B, VK_RWIN = 0x5C
        try:
            vk = data.vkCode
            is_win = vk in (0x5B, 0x5C)

            if is_win and self._win_used_in_hotkey:
                # Suppress the key by calling suppress on the listener
                self._listener.suppress_event()
        except Exception:
            pass

    def stop(self):
        """Stop listening for hotkeys."""
        if self._listener:
            self._listener.stop()
            self._listener = None
            self._pressed_keys.clear()
            self._active_hotkeys.clear()
            logger.info("Hotkey listener stopped")
