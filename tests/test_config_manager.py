import os
import pytest
from core.config_manager import ConfigManager, DEFAULT_CONFIG

def test_config_defaults(tmp_path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(str(cfg_file))
    cfg = mgr.load()

    assert cfg["target_language"] == "uk"
    assert cfg["outgoing_my_lang"] == "uk"
    assert cfg["outgoing_target_lang"] == "en"
    assert cfg["hotkey_toggle_lock"] == "F9"
    assert cfg["hotkey_quick_chat"] == "T"
    assert cfg["message_fade_timeout"] == 10
    assert cfg["font_bold"] is False
    assert cfg["text_outline"] is True
    assert cfg["blacklist_nicknames"] == []
    assert cfg["ui_display_mode"] == "both"
    assert cfg["quick_chat_x"] == -1
    assert cfg["quick_chat_y"] == -1

def test_config_set_and_save(tmp_path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(str(cfg_file))
    mgr.set("target_language", "de")
    mgr.set("font_bold", True)
    mgr.set("message_fade_timeout", 15)
    mgr.set("quick_chat_x", 350)
    mgr.set("quick_chat_y", 420)

    mgr2 = ConfigManager(str(cfg_file))
    assert mgr2.get("target_language") == "de"
    assert mgr2.get("font_bold") is True
    assert mgr2.get("message_fade_timeout") == 15
    assert mgr2.get("quick_chat_x") == 350
    assert mgr2.get("quick_chat_y") == 420

def test_resolved_log_path(tmp_path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(str(cfg_file))
    resolved = mgr.get_resolved_log_path()
    assert "%LOCALAPPDATA%" not in resolved
    assert resolved.endswith(os.path.join("SCUM", "Saved", "Logs", "SCUM.log"))
