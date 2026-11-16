"""Settings window: switching the language translates it in place (it stays open), Save keeps it open, Save and close closes."""
import pytest
from PyQt6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from core.i18n import LocalizationManager, tr
from ui.settings_window import SettingsDialog

app = QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(tmp_path):
    LocalizationManager.get_instance().set_locale("en")
    cfg = ConfigManager(str(tmp_path / "c.json"))
    cfg.update({"ui_language": "en", "sync_enabled": False, "sync_code": ""})
    dlg = SettingsDialog(cfg)
    dlg.show()
    app.processEvents()
    yield dlg
    dlg.close()
    LocalizationManager.get_instance().set_locale("en")


def _pick(dlg, code):
    combo = dlg.tab_language.combo
    combo.setCurrentIndex(combo.findData(code))
    dlg.tab_language.language_picked.emit(code)         # what a click in the list does
    for _ in range(5):
        app.processEvents()


def test_switching_language_keeps_the_window_open_and_translates_it(dialog):
    dialog.nav.setCurrentRow(2)
    old_nav = dialog.nav.item(0).text()
    _pick(dialog, "uk")
    assert dialog.isVisible()
    assert dialog.cfg.get("ui_language") == "uk"
    assert dialog.nav.item(0).text() != old_nav and dialog.nav.item(0).text() == tr("settings.nav_general")
    assert dialog.windowTitle() == tr("settings.title")
    assert dialog.btn_save.text() == tr("settings.save_btn") and dialog.btn_cancel.text() == tr("settings.cancel_btn")
    assert dialog.nav.currentRow() == 2                  # the same page is still shown
    assert dialog.tab_language.combo.currentData() == "uk"
    _pick(dialog, "en")                                  # and back, several times, without trouble
    _pick(dialog, "uk")
    _pick(dialog, "en")
    assert dialog.isVisible() and dialog.nav.item(0).text() == tr("settings.nav_general")
    assert dialog.nav.item(0).text() == old_nav


def test_unsaved_edits_survive_a_language_switch(dialog):
    dialog.txt_nickname.setText("Hunter")
    _pick(dialog, "uk")
    assert dialog.txt_nickname.text() == "Hunter" and dialog.isVisible()


def test_language_switch_tells_the_application(dialog):
    seen = []
    dialog.settings_changed.connect(lambda: seen.append(1))
    _pick(dialog, "uk")
    assert seen and LocalizationManager.get_instance().current_locale == "uk"


def test_save_keeps_the_window_open_and_save_and_close_closes_it(dialog):
    seen = []
    dialog.settings_changed.connect(lambda: seen.append(1))
    dialog.txt_nickname.setText("Wolf")
    dialog.btn_save.click()
    app.processEvents()
    assert dialog.isVisible() and dialog.cfg.get("own_nickname") == "Wolf" and len(seen) == 1
    dialog.txt_nickname.setText("Fox")
    dialog.btn_save_close.click()
    app.processEvents()
    assert not dialog.isVisible() and dialog.cfg.get("own_nickname") == "Fox" and len(seen) == 2
    assert dialog.btn_save.text() != dialog.btn_save_close.text()


def test_old_pages_are_cut_off_from_the_engine_after_a_switch(dialog):
    old_sync, old_players = dialog.tab_sync, dialog.tab_players
    _pick(dialog, "uk")
    assert dialog.tab_sync is not old_sync and dialog.tab_players is not old_players
    assert old_sync._links == []


def test_both_languages_have_the_new_buttons():
    for code in ("en", "uk"):
        data = LocalizationManager().translations[code]["settings"]
        assert data["save_btn"] and data["save_close_btn"] and data["save_btn"] != data["save_close_btn"]
