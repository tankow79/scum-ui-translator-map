import ctypes
import logging
import threading
from typing import Callable, Dict, Optional, Tuple

from pynput import keyboard

log = logging.getLogger("scum.hotkeys")

user32 = ctypes.windll.user32

# Windows virtual key codes for modifier keys
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt

VK_NAMES: Dict[int, str] = {
    112: "F1", 113: "F2", 114: "F3", 115: "F4", 116: "F5", 117: "F6",
    118: "F7", 119: "F8", 120: "F9", 121: "F10", 122: "F11", 123: "F12",
    45: "Insert", 46: "Delete", 36: "Home", 35: "End",
    33: "PageUp", 34: "PageDown", 19: "Pause", 32: "Space",
    9: "Tab", 27: "Esc", 13: "Enter", 192: "~"
}
for c in range(ord('A'), ord('Z') + 1):
    VK_NAMES[c] = chr(c)
for c in range(ord('0'), ord('9') + 1):
    VK_NAMES[c] = chr(c)

NAME_TO_VK = {v.lower(): k for k, v in VK_NAMES.items()}
NAME_TO_VK["esc"] = 27
NAME_TO_VK["escape"] = 27
NAME_TO_VK["enter"] = 13
NAME_TO_VK["return"] = 13
NAME_TO_VK["space"] = 32

def key_to_vk(key) -> Optional[int]:
    """
    Gets the hardware Virtual Key (VK) code for a key regardless of the current keyboard layout.
    """
    if hasattr(key, 'vk') and key.vk is not None:
        return key.vk
    if hasattr(key, 'value') and hasattr(key.value, 'vk') and key.value.vk is not None:
        return key.value.vk
    return None

def parse_hotkey_string(hotkey_str: str) -> Optional[Tuple[bool, bool, bool, int]]:
    """
    Parses strings like 'Ctrl+T', 'F9', 'Ctrl+Shift+T', 'Alt+F8', 'Escape', 'Enter'.
    Returns a tuple: (req_ctrl, req_alt, req_shift, target_vk).
    """
    if not hotkey_str:
        return None

    parts = [p.strip().lower() for p in hotkey_str.split('+')]
    req_ctrl = False
    req_alt = False
    req_shift = False
    target_vk = None

    for p in parts:
        if p in ('ctrl', 'control'):
            req_ctrl = True
        elif p in ('alt',):
            req_alt = True
        elif p in ('shift',):
            req_shift = True
        else:
            if p in NAME_TO_VK:
                target_vk = NAME_TO_VK[p]
            elif p.startswith("vk_") and p[3:].isdigit() and 0 < int(p[3:]) < 256:
                target_vk = int(p[3:])       # keys without a name of their own (numpad, F13, Pause ...) are stored as VK_<n>
            elif len(p) == 1 and ('a' <= p <= 'z' or '0' <= p <= '9'):
                target_vk = ord(p.upper())

    if target_vk is None:
        return None

    return (req_ctrl, req_alt, req_shift, target_vk)

def format_hotkey(req_ctrl: bool, req_alt: bool, req_shift: bool, vk: int) -> str:
    parts = []
    if req_ctrl:
        parts.append("Ctrl")
    if req_alt:
        parts.append("Alt")
    if req_shift:
        parts.append("Shift")
    key_name = VK_NAMES.get(vk, f"VK_{vk}")
    parts.append(key_name)
    return "+".join(parts)


class GlobalHotkeyManager:
    """
    Global hotkey manager for Windows.
    Works on Virtual Key (VK) codes, so hotkeys fire the same
    regardless of the active keyboard layout (Ukrainian, English, etc.).
    """
    def __init__(self):
        # (ctrl, alt, shift, vk) -> callback
        self._handlers: Dict[Tuple[bool, bool, bool, int], Callable[[], None]] = {}
        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        self._active = False
        self._held: set = set()      # keys physically held down, to ignore the keyboard auto-repeat

    def register(self, hotkey_str: str, callback: Callable[[], None]) -> bool:
        """Bind a hotkey. Returns False (and logs why) when the string cannot be read or is already taken."""
        parsed = parse_hotkey_string(hotkey_str)
        if not parsed:
            log.warning("Hotkey %r cannot be read and was not registered", hotkey_str)
            return False
        with self._lock:
            if parsed in self._handlers:
                log.warning("Hotkey %r is already used by another action; the new binding replaces it", hotkey_str)
            self._handlers[parsed] = callback
            log.info("Registered hotkey: %s -> %s", hotkey_str, parsed)
        return True

    def clear(self):
        with self._lock:
            self._handlers.clear()

    def start(self):
        if self._active:
            return
        self._active = True
        self._held.clear()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def ensure_alive(self) -> bool:
        """Restart the keyboard listener if Windows or an error ended it (hotkeys would silently stop working)."""
        if not self._active:
            return False
        listener = self._listener
        if listener is not None and listener.is_alive():
            return False
        log.warning("The keyboard listener had stopped; restarting it")
        self._active = False
        self.start()
        return True

    def stop(self):
        self._active = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _on_press(self, key):
        if not self._active:
            return

        vk = key_to_vk(key)
        if vk is None:
            return

        # Skip presses of bare modifiers
        if vk in (VK_CONTROL, 162, 163, VK_SHIFT, 160, 161, VK_MENU, 164, 165):
            return

        # A held key repeats ~30 times a second: act on the first press only. (If the release was ever missed the
        # key is no longer physically down, so a fresh press is recognised again.)
        if vk in self._held and user32.GetAsyncKeyState(vk) & 0x8000:
            return
        self._held.add(vk)

        # Poll the real modifier state via WinAPI GetAsyncKeyState
        is_ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        is_alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        is_shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)

        sig = (is_ctrl, is_alt, is_shift, vk)

        with self._lock:
            handler = self._handlers.get(sig)

        if handler:
            try:
                handler()
            except Exception as e:
                log.error("Hotkey handler failed: %s", e)

    def _on_release(self, key):
        vk = key_to_vk(key)
        if vk is not None:
            self._held.discard(vk)
