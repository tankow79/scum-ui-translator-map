"""Layout robustness: windows must stay readable when a translation is much longer than English."""

import copy

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

from core.chat_history import ChatHistory
from core.config_manager import ConfigManager
from core.i18n import LocalizationManager
from core.points_manager import PointsManager
from core.profiles import ProfileManager
from core.translator import GoogleTranslatorEngine


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def verbose_language():
    """Simulate a wordy language (about +45% text, German-like) by stretching every English string."""
    mgr = LocalizationManager.get_instance()
    original = copy.deepcopy(mgr.translations["en"])

    def stretch(value):
        if isinstance(value, dict):
            return {k: (v if k.startswith("_") else stretch(v)) for k, v in value.items()}
        if isinstance(value, str) and len(value) > 3:
            return value + " " + " ".join(["ßäöü"] * max(1, len(value) // 6))
        return value

    mgr.translations["en"] = stretch(original)
    yield
    mgr.translations["en"] = original


@pytest.fixture
def cfg(tmp_path):
    return ConfigManager(str(tmp_path / "config.json"))


def clipped_buttons(root):
    """Visible push buttons whose caption is wider than the button itself."""
    bad = []
    for btn in root.findChildren(QPushButton):
        text = btn.text()
        if btn.isVisibleTo(root) and text and btn.width() < btn.fontMetrics().horizontalAdvance(text):
            bad.append(text)
    return bad


def test_settings_pages_fit_without_horizontal_overflow(qapp, cfg, tmp_path, verbose_language):
    from ui.settings_window import SettingsDialog

    dlg = SettingsDialog(cfg, profiles=ProfileManager(cfg, str(tmp_path / "p.json")))
    dlg.show()
    for row in range(dlg.nav.count()):
        dlg.nav.setCurrentRow(row)
        qapp.processEvents()
        page = dlg.stack.currentWidget()
        assert page.widget().width() <= page.viewport().width() + 1, f"page {row} is wider than its viewport"
        assert not clipped_buttons(page), f"clipped buttons on page {row}: {clipped_buttons(page)}"
    assert not clipped_buttons(dlg)
    dlg.close()


def test_settings_navigation_is_bounded(qapp, cfg, verbose_language):
    from ui.settings_window import SettingsDialog

    dlg = SettingsDialog(cfg)
    assert dlg.nav.width() <= SettingsDialog.NAV_MAX_WIDTH
    dlg.close()


def test_other_windows_do_not_clip_buttons(qapp, cfg, tmp_path, verbose_language):
    from ui.history_window import HistoryWindow
    from ui.map_window import MapWindow
    from ui.points_window import PointsWindow
    from ui.quick_chat import QuickChatDialog

    points = PointsManager(str(tmp_path / "points.json"))
    windows = [
        HistoryWindow(ChatHistory()),
        PointsWindow(cfg, points),
        MapWindow(cfg, points),
        QuickChatDialog(cfg, GoogleTranslatorEngine("en")),
    ]
    for w in windows:
        w.show()
        qapp.processEvents()
        assert not clipped_buttons(w), f"{type(w).__name__}: {clipped_buttons(w)}"
        w.close()
