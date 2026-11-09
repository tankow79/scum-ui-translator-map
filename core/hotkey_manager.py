import ctypes
import threading
from typing import Callable, Dict, Tuple, Optional, Set
from pynput import keyboard

user32 = ctypes.windll.user32

# Віртуальні коди клавіш-модифікаторів у Windows
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
    Отримує апаратний Virtual Key (VK) код для клавіші незалежно від поточної мовної розкладки.
    """
    if hasattr(key, 'vk') and key.vk is not None:
        return key.vk
    if hasattr(key, 'value') and hasattr(key.value, 'vk') and key.value.vk is not None:
        return key.value.vk
    return None

def parse_hotkey_string(hotkey_str: str) -> Optional[Tuple[bool, bool, bool, int]]:
    """
    Парсить рядок типу 'Ctrl+T', 'F9', 'Ctrl+Shift+T', 'Alt+F8', 'Escape', 'Enter'.
    Повертає кортеж: (req_ctrl, req_alt, req_shift, target_vk).
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
    Менеджер глобальних гарячих клавіш для Windows.
    Працює на рівні Virtual Key (VK) кодів — клавіші спрацьовують однаково,
    незалежно від того, яка розкладка увімкнена (українська, англійська тощо).
    """
    def __init__(self):
        # (ctrl, alt, shift, vk) -> callback
        self._handlers: Dict[Tuple[bool, bool, bool, int], Callable[[], None]] = {}
        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        self._active = False

    def register(self, hotkey_str: str, callback: Callable[[], None]):
        parsed = parse_hotkey_string(hotkey_str)
        if parsed:
            with self._lock:
                self._handlers[parsed] = callback
                print(f"[Hotkeys] Зареєстровано гарячу клавішу: {hotkey_str} -> {parsed}")

    def clear(self):
        with self._lock:
            self._handlers.clear()

    def start(self):
        if self._active:
            return
        self._active = True
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()

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

        # Пропускаємо натискання самих лише модифікаторів
        if vk in (VK_CONTROL, 162, 163, VK_SHIFT, 160, 161, VK_MENU, 164, 165):
            return

        # Опитуємо реальний стан модифікаторів через WinAPI GetAsyncKeyState
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
                print(f"[Hotkeys] Помилка виклику обробника: {e}")
