import pytest
from core.hotkey_manager import parse_hotkey_string, format_hotkey

def test_hotkey_parsing():
    # Одиночні клавіші
    assert parse_hotkey_string("F9") == (False, False, False, 120)
    assert parse_hotkey_string("F8") == (False, False, False, 119)
    assert parse_hotkey_string("T") == (False, False, False, 84)

    # Комбінації
    assert parse_hotkey_string("Ctrl+T") == (True, False, False, 84)
    assert parse_hotkey_string("Ctrl+Shift+T") == (True, False, True, 84)
    assert parse_hotkey_string("Alt+F9") == (False, True, False, 120)
    assert parse_hotkey_string("Ctrl+Alt+F8") == (True, True, False, 119)

def test_hotkey_formatting():
    assert format_hotkey(False, False, False, 120) == "F9"
    assert format_hotkey(True, False, False, 84) == "Ctrl+T"
    assert format_hotkey(True, False, True, 84) == "Ctrl+Shift+T"
    assert format_hotkey(False, True, False, 119) == "Alt+F8"

def test_invalid_hotkeys():
    assert parse_hotkey_string("") is None
    assert parse_hotkey_string("UnknownInvalidKey123") is None
