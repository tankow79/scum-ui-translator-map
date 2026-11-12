"""Tests for the message filter, language detection, chat history and profiles."""

import csv
import json

import pytest

from core.chat_history import ChatHistory
from core.config_manager import ConfigManager
from core.language_detect import is_same_language, quick_detect
from core.message_filter import ChatFilter, FilterAction, split_list
from core.profiles import DEFAULT_PROFILE, ProfileManager

# ───────────── message filter ─────────────

def test_split_list_accepts_strings_and_lists():
    assert split_list("a, b;c\nd") == ["a", "b", "c", "d"]
    assert split_list(["x, y", " z "]) == ["x", "y", "z"]
    assert split_list(None) == []


def test_nickname_blacklist_returns_original():
    f = ChatFilter({"blacklist_nicknames": ["Spammer"]})
    assert f.evaluate("[Clan] Spammer", "hello").action is FilterAction.ORIGINAL
    assert f.evaluate("Friendly", "hello").action is FilterAction.ALLOW


def test_word_filter_disabled_by_default():
    f = ChatFilter({"blacklist_words": ["badword"]})
    assert f.evaluate("A", "this is badword").action is FilterAction.ALLOW


@pytest.mark.parametrize("action,expected", [
    ("mask", FilterAction.MASK), ("hide", FilterAction.HIDE), ("no_translate", FilterAction.ORIGINAL),
])
def test_word_filter_actions(action, expected):
    f = ChatFilter({"blacklist_words_enabled": True, "blacklist_words": ["badword"], "blacklist_words_action": action})
    assert f.evaluate("A", "you BadWord!").action is expected


def test_word_filter_masks_and_respects_whole_word():
    cfg = {"blacklist_words_enabled": True, "blacklist_words": ["cat"], "blacklist_words_whole_word": True}
    f = ChatFilter(cfg)
    assert f.evaluate("A", "a cat sat").message == "a *** sat"
    assert f.evaluate("A", "category").action is FilterAction.ALLOW
    cfg["blacklist_words_whole_word"] = False
    assert f.evaluate("A", "category").message == "***egory"


def test_word_filter_case_sensitivity_and_live_config_changes():
    cfg = {"blacklist_words_enabled": True, "blacklist_words": ["Foo"], "blacklist_words_case_sensitive": True}
    f = ChatFilter(cfg)
    assert f.evaluate("A", "foo").action is FilterAction.ALLOW
    cfg["blacklist_words_case_sensitive"] = False
    assert f.evaluate("A", "foo").action is FilterAction.MASK
    cfg["blacklist_words_enabled"] = False
    assert f.evaluate("A", "foo").action is FilterAction.ALLOW


def test_word_filter_escapes_regex_characters():
    f = ChatFilter({"blacklist_words_enabled": True, "blacklist_words": ["a+b", "(x"], "blacklist_words_whole_word": False})
    assert f.evaluate("A", "1 a+b 2").action is FilterAction.MASK


# ───────────── language detection ─────────────

@pytest.mark.parametrize("text,expected", [
    ("Привіт, як справи? їжак", "uk"),
    ("Привет, это ёлка", "ru"),
    ("こんにちは世界", "ja"),
    ("你好世界朋友", "zh"),
    ("안녕하세요", "ko"),
    ("Hello there friend", None),
    ("Привет", None),          # ambiguous Cyrillic: left to the translation service
    ("ok", None),              # too short
    ("https://example.com/привіт", None),
])
def test_quick_detect(text, expected):
    assert quick_detect(text) == expected


def test_is_same_language_handles_region_codes():
    assert is_same_language("zh", ["zh-CN"])
    assert is_same_language("uk", ["UK"])
    assert not is_same_language("ru", ["uk"])
    assert not is_same_language(None, ["uk"])


# ───────────── chat history ─────────────

def make_history(tmp_path=None, **kw) -> ChatHistory:
    path = str(tmp_path / "h.jsonl") if tmp_path else None
    return ChatHistory(path=path, **kw)


def test_history_is_bounded_and_queryable():
    h = ChatHistory(max_entries=3)
    for i in range(5):
        h.add("10:00:0%d" % i, "P%d" % (i % 2), "orig %d" % i, "trans %d" % i, "en", "player")
    assert len(h) == 3
    assert [e.original for e in h.query()] == ["orig 2", "orig 3", "orig 4"]
    assert len(h.query(sender="P0")) == 2
    assert len(h.query(text="TRANS 4")) == 1
    assert h.query(msg_type="squad") == []


def test_history_translated_only_filter():
    h = ChatHistory()
    h.add("t", "A", "same", "same", "orig", "player")
    h.add("t", "A", "hola", "hello", "es", "player")
    assert [e.original for e in h.query(translated_only=True)] == ["hola"]


def test_history_persists_and_clears(tmp_path):
    h = make_history(tmp_path)
    h.add("t", "A", "one", "uno", "en", "player")
    reloaded = make_history(tmp_path)
    assert [e.original for e in reloaded.query()] == ["one"]
    reloaded.clear()
    assert len(make_history(tmp_path)) == 0


def test_history_compacts_disk_file(tmp_path):
    h = make_history(tmp_path, max_entries=5)
    for i in range(30):
        h.add("t", "A", f"m{i}", f"m{i}", "en", "player")
    lines = (tmp_path / "h.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 5 * 2 + 1
    assert [e.original for e in make_history(tmp_path, max_entries=5).query()][-1] == "m29"


def test_history_export_formats(tmp_path):
    h = ChatHistory()
    h.add("10:00:00", "Tom", "hola, amigo", "hello, friend", "es", "squad")

    assert h.export(str(tmp_path / "a.json")) == 1
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))[0]["sender"] == "Tom"

    h.export(str(tmp_path / "a.csv"))
    rows = list(csv.reader((tmp_path / "a.csv").open(encoding="utf-8-sig")))
    assert rows[0][:3] == ["timestamp", "type", "sender"] and rows[1][3] == "hola, amigo"

    h.export(str(tmp_path / "a.txt"))
    assert "Tom: hola, amigo  =>  hello, friend" in (tmp_path / "a.txt").read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        h.export(str(tmp_path / "a.xml"))


# ───────────── profiles ─────────────

@pytest.fixture
def cfg(tmp_path):
    return ConfigManager(str(tmp_path / "config.json"))


def test_profiles_start_with_default_snapshot(cfg, tmp_path):
    pm = ProfileManager(cfg, str(tmp_path / "profiles.json"))
    assert pm.names() == [DEFAULT_PROFILE] and pm.active == DEFAULT_PROFILE


def test_profiles_switch_restores_settings_and_keeps_personal_keys(cfg, tmp_path):
    pm = ProfileManager(cfg, str(tmp_path / "profiles.json"))
    default_font = cfg.get("font_size")
    cfg.set("hotkey_toggle_map", "Ctrl+F10")
    cfg.set("font_size", 22)
    pm.create("Big text")               # becomes active, snapshot has font 22

    assert pm.apply(DEFAULT_PROFILE)
    assert cfg.get("font_size") == default_font
    assert cfg.get("hotkey_toggle_map") == "Ctrl+F10"      # never part of a profile
    cfg.set("font_size", 10)            # tweak while Default is active

    assert pm.apply("Big text") and cfg.get("font_size") == 22
    assert pm.apply(DEFAULT_PROFILE) and cfg.get("font_size") == 10   # outgoing profile was auto-saved


def test_profiles_persist_and_validate(cfg, tmp_path):
    path = str(tmp_path / "profiles.json")
    pm = ProfileManager(cfg, path)
    pm.create("Raid")
    assert "Raid" in ProfileManager(cfg, path).names()
    with pytest.raises(ValueError):
        pm.create("Raid")
    with pytest.raises(ValueError):
        pm.create("   ")
    with pytest.raises(ValueError):
        pm.delete(DEFAULT_PROFILE)
    pm.rename("Raid", "Raid night")
    pm.delete("Raid night")
    assert pm.names() == [DEFAULT_PROFILE] and pm.active == DEFAULT_PROFILE


def test_profiles_cycle_and_corrupt_file(cfg, tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{not json", encoding="utf-8")
    pm = ProfileManager(cfg, str(path))     # must not raise
    pm.create("B")
    assert pm.cycle() == DEFAULT_PROFILE
    assert pm.cycle() == "B"
