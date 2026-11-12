"""Controller pipeline: filtering -> language auto-detect -> translation -> history."""

import time

import pytest
from PyQt6.QtWidgets import QApplication

from core.chat_history import ChatHistory
from core.config_manager import ConfigManager
from core.controller import AppController


class FakeTranslator:
    target_lang = "en"

    def __init__(self, src="de"):
        self.src = src
        self.calls = []

    def translate(self, text):
        self.calls.append(text)
        return f"EN({text})", self.src


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, tmp_path):
    cfg = ConfigManager(str(tmp_path / "config.json"))
    cfg.set("target_language", "en")
    translator = FakeTranslator()
    history = ChatHistory()
    controller = AppController(cfg, translator, history=history)
    received = []
    controller.translated_ready.connect(lambda *a: received.append(a))
    return cfg, translator, history, controller, received


def wait_for(qapp, received, count=1, timeout=2.0):
    end = time.time() + timeout
    while len(received) < count and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def test_message_is_translated_and_recorded(qapp, setup):
    cfg, translator, history, controller, received = setup
    controller._handle_raw_message("10:00:00", "Hans", "Hallo Welt", "player")
    wait_for(qapp, received)
    assert received[0][3] == "EN(Hallo Welt)"
    assert history.query()[0].translated == "EN(Hallo Welt)"


def test_history_can_be_disabled(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("history_enabled", False)
    controller._handle_raw_message("t", "A", "Hallo Welt", "player")
    wait_for(qapp, received)
    assert received and len(history) == 0


def test_blacklisted_nickname_is_shown_untranslated(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("blacklist_nicknames", ["Troll"])
    controller._handle_raw_message("t", "Troll", "Hallo Welt", "player")
    assert received[0][3] == "Hallo Welt" and received[0][4] == "orig"
    assert translator.calls == []


def test_blocked_word_modes(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("blacklist_words_enabled", True)
    cfg.set("blacklist_words", ["scam"])

    cfg.set("blacklist_words_action", "hide")
    controller._handle_raw_message("t", "A", "this is a scam", "player")
    qapp.processEvents()
    assert received == [] and translator.calls == []

    cfg.set("blacklist_words_action", "mask")
    controller._handle_raw_message("t", "A", "this is a scam", "player")
    wait_for(qapp, received)
    assert translator.calls == ["this is a ****"]


def test_autodetect_skips_network_when_already_target_language(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("target_language", "uk")
    translator.target_lang = "uk"
    controller._handle_raw_message("t", "A", "Привіт, їжак", "player")
    assert translator.calls == []
    assert received[0][3] == "Привіт, їжак"


def test_autodetect_post_check_hides_redundant_translation(qapp, setup):
    cfg, translator, history, controller, received = setup
    translator.src = "en"  # service says the text was already English
    controller._handle_raw_message("t", "A", "hello there", "player")
    wait_for(qapp, received)
    assert received[0][3] == "hello there"


def test_autodetect_can_be_turned_off(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("autodetect_enabled", False)
    translator.src = "en"
    controller._handle_raw_message("t", "A", "hello there", "player")
    wait_for(qapp, received)
    assert received[0][3] == "EN(hello there)"


def test_map_only_mode_drops_chat_but_keeps_coordinates(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("enable_chat_translator", False)
    coords = []
    controller.coordinate_detected.connect(coords.append)
    controller._handle_raw_message("t", "A", "base{X=1000.000 Y=2000.000 Z=300.000|P=0.0 Y=0.0 R=0.0}", "player")
    qapp.processEvents()
    assert received == [] and len(coords) == 1


def test_own_messages_can_be_ignored(qapp, setup):
    cfg, translator, history, controller, received = setup
    cfg.set("own_nickname", "Me")
    cfg.set("ignore_own_messages", True)
    controller._handle_raw_message("t", "me", "Hallo Welt", "player")
    qapp.processEvents()
    assert received == []
