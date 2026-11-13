import time

import pytest

from core import slang
from core.config_manager import ConfigManager
from core.controller import AppController
from core.translator import GoogleTranslatorEngine


def test_the_table_is_big_and_consistent():
    assert len(slang.STRONG) + len(slang.WEAK) >= 300
    assert not set(slang.STRONG) & set(slang.WEAK)
    for key in list(slang.STRONG) + list(slang.WEAK):
        assert key == key.lower() and slang.STRONG.get(key, slang.WEAK.get(key))
    # the ready Ukrainian phrases belong to known abbreviations, and the common ones all have one
    assert set(slang.UK) <= set(slang.STRONG) | set(slang.WEAK)
    assert len(slang.UK) >= 300


@pytest.mark.parametrize("text,english,ukrainian", [
    ("GG", "Good game", "Гарна гра"),
    ("gg!", "Good game!", "Гарна гра!"),
    ("GGNT", "Good game, nice try", "Гарна гра, непогана спроба"),
    ("gg wp", "Good game, well played", "Гарна гра, добре зіграно"),
    ("ggggg", "Good game", "Гарна гра"),
    ("ГГ", "Good game", "Гарна гра"),
    ("ty gg", "Thank you, good game", "Дякую, гарна гра"),
    ("looool", "Laughing out loud", "Ха-ха"),
    ("brb", "Be right back", "Зараз повернусь"),
    ("gjwp", "Good job, well played", "Гарна робота, добре зіграно"),
])
def test_abbreviation_only_messages(text, english, ukrainian):
    found = slang.analyse(text)
    assert found is not None and found.only_slang
    assert found.expanded == english
    assert found.ukrainian() == ukrainian


def test_abbreviations_inside_a_sentence_are_replaced_in_place():
    found = slang.analyse("ok gg guys, brb in 5")
    assert found is not None and not found.only_slang
    assert found.expanded == "ok good game guys, be right back in 5"


@pytest.mark.parametrize("text", [
    "ty za pomoc",          # Polish: "ty" is "you", not "thank you"
    "u mnie w bazie jest",  # Polish "u" = "at"
    "np. samochód",         # Polish "for example"
    "low hp now",           # weak abbreviations stay as typed in a real sentence
    "hello there",
    "5.56",
    "",
])
def test_ordinary_text_is_left_alone(text):
    assert slang.analyse(text) is None


def test_mode_values_are_validated():
    assert slang.normalize_mode("expand") == "expand"
    assert slang.normalize_mode("nonsense") == "translate"
    assert slang.normalize_mode(None) == "translate"


def _controller(tmp_path, mode, target="uk"):
    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    cfg.set("slang_mode", mode)
    cfg.set("target_language", target)
    ctrl = AppController(cfg, GoogleTranslatorEngine(target_lang=target))
    shown = []
    ctrl._publish = lambda t, s, orig, trans, lang, typ: shown.append((orig, trans, lang))
    return ctrl, shown


def _send(ctrl, shown, text, count=1, wait=3.0):
    ctrl._handle_raw_message("12:00", "Bob", text, "player")
    end = time.time() + wait
    while len(shown) < count and time.time() < end:
        time.sleep(0.02)


def test_controller_translates_abbreviations_to_the_chat_language(tmp_path):
    ctrl, shown = _controller(tmp_path, "translate")
    _send(ctrl, shown, "GGNT")
    assert shown == [("GGNT", "Гарна гра, непогана спроба", "slang")]


def test_controller_can_show_the_english_meaning(tmp_path):
    ctrl, shown = _controller(tmp_path, "expand")
    _send(ctrl, shown, "GGNT")
    assert shown == [("GGNT", "Good game, nice try", "slang")]


def test_controller_can_leave_abbreviations_alone(tmp_path):
    ctrl, shown = _controller(tmp_path, "keep")
    _send(ctrl, shown, "GG")
    assert shown and shown[0][2] != "slang"          # no expansion: it went through the normal path


def test_english_target_gets_the_full_phrase(tmp_path):
    ctrl, shown = _controller(tmp_path, "translate", target="en")
    _send(ctrl, shown, "ggwp")
    assert shown == [("ggwp", "Good game, well played", "slang")]


def test_other_languages_translate_the_english_meaning(tmp_path):
    ctrl, shown = _controller(tmp_path, "translate", target="de")
    _send(ctrl, shown, "gg")
    assert shown and shown[0][0] == "gg" and shown[0][2] == "slang"
    assert shown[0][1] == "[de] Good game"          # the (faked) translation service got the English meaning


def test_abbreviation_inside_a_sentence_is_expanded_before_translation(tmp_path):
    ctrl, shown = _controller(tmp_path, "translate", target="de")
    _send(ctrl, shown, "всім привіт, gg")
    assert shown and shown[0][0] == "всім привіт, gg"
    assert "good game" in shown[0][1]       # the (faked) translation service received the expanded text


def test_expanded_sentence_is_kept_even_if_the_service_reports_the_chat_language(tmp_path):
    ctrl, shown = _controller(tmp_path, "translate", target="uk")
    ctrl.translator.translate = lambda text: ("Дякую, гарна гра", "uk")     # Google detects Ukrainian in the mixed text
    _send(ctrl, shown, "дякую, gg ще раз")
    assert shown == [("дякую, gg ще раз", "Дякую, гарна гра", "uk")]
