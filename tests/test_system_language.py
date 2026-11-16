"""First start: the UI language follows Windows (Ukrainian, English), anything else becomes English."""
import json
import re

from core.config_manager import ConfigManager
from core.i18n import LocalizationManager, pick_language, system_language_code

AVAILABLE = ["en", "uk"]


def test_pick_language():
    assert pick_language("uk", AVAILABLE) == "uk"
    assert pick_language("en", AVAILABLE) == "en"
    for other in ("de", "ru", "ja", "", "xx-yy"):
        assert pick_language(other, AVAILABLE) == "en"


def test_system_language_code_is_a_plain_lowercase_code():
    code = system_language_code()
    assert code == code.lower() and "-" not in code and "_" not in code


def test_system_language_survives_a_broken_system_call(monkeypatch):
    import ctypes

    class Boom:
        def __getattr__(self, name):
            raise OSError("no windll")

    monkeypatch.setattr(ctypes, "windll", Boom(), raising=False)
    assert isinstance(system_language_code(), str)


def test_first_start_is_detected_and_a_saved_language_is_kept(tmp_path):
    fresh = ConfigManager(str(tmp_path / "new.json"))
    assert fresh.language_chosen is False
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"ui_language": "uk"}), encoding="utf-8")
    assert ConfigManager(str(old)).language_chosen is True
    no_lang = tmp_path / "nolang.json"
    no_lang.write_text(json.dumps({"overlay_opacity": 0.5}), encoding="utf-8")
    assert ConfigManager(str(no_lang)).language_chosen is False


def test_both_shipped_languages_are_discovered():
    codes = [c for c, _ in LocalizationManager().available_locales()]
    assert "en" in codes and "uk" in codes


def test_qt_own_texts_follow_the_language():
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication

    from ui import qt_translation

    app = QApplication.instance() or QApplication([])
    assert app is not None
    qt_translation._active_code = ""
    qt_translation.apply_qt_language("en")
    english = QCoreApplication.translate("QPlatformTheme", "Cancel")
    qt_translation.apply_qt_language("uk")
    ukrainian = QCoreApplication.translate("QPlatformTheme", "Cancel")
    assert english == "Cancel" and re.search(r"[А-Яа-я]", ukrainian), ukrainian
    assert qt_translation.apply_qt_language("xx") is False          # no file for it: English stays, no crash
    qt_translation.apply_qt_language("en")
