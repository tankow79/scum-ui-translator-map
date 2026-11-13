"""Settings sections with their own load/save logic: language, filters, history and profiles.

Each section exposes ``load(cfg)`` and ``save(cfg)`` so ``SettingsDialog`` treats them uniformly.
"""

import logging
import os
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.i18n import LocalizationManager, tr
from core.message_filter import split_list
from core.profiles import DEFAULT_PROFILE, ProfileManager
from ui.dialogs import ask, notify
from ui.flow_layout import button_row
from ui.settings_widgets import Section, WrapCheck, make_button, muted_label

log = logging.getLogger("scum.settings_tabs")


def _profile_error_text(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    return tr(f"settings.profile_err_{code}", default=str(exc)) if code else str(exc)


class LanguageSelector(Section):
    """Interface language picker. Scales to any number of installed locales."""

    def __init__(self, parent=None):
        super().__init__(tr("settings.sec_language"), parent)
        self.combo = QComboBox()
        self.combo.setMaxVisibleItems(15)
        for code, name in LocalizationManager.get_instance().available_locales():
            self.combo.addItem(f"{name}  ({code})", code)
        self.add_field(tr("settings.ui_language"), self.combo, tr("settings.language_hint"))

        btn = make_button(tr("settings.language_open_folder"))
        btn.clicked.connect(self._open_folder)
        self.add_layout(button_row(btn))

    @staticmethod
    def _open_folder():
        folder = LocalizationManager.get_instance()._get_locales_dir()
        if os.path.isdir(folder):
            os.startfile(folder)  # noqa: S606 - local folder, Windows-only app

    def load(self, cfg: ConfigManager):
        idx = self.combo.findData(cfg.get("ui_language", "en"))
        self.combo.setCurrentIndex(max(0, idx))

    def selected_code(self) -> str:
        return self.combo.currentData() or "en"

    def save(self, cfg: ConfigManager):
        code = self.selected_code()
        cfg.set("ui_language", code)
        LocalizationManager.get_instance().set_locale(code)


class WordFilterSection(Section):
    def __init__(self, parent=None):
        super().__init__(tr("settings.words_group"), parent)
        self.chk_words = self.add_check(WrapCheck(tr("settings.words_enable")))
        self.txt_words = QPlainTextEdit()
        self.txt_words.setPlaceholderText(tr("settings.words_placeholder"))
        self.txt_words.setFixedHeight(70)
        self.add_widget(self.txt_words)
        self.combo_action = QComboBox()
        self.combo_action.addItem(tr("settings.words_action_mask"), "mask")
        self.combo_action.addItem(tr("settings.words_action_hide"), "hide")
        self.combo_action.addItem(tr("settings.words_action_original"), "no_translate")
        self.add_field(tr("settings.words_action"), self.combo_action)
        self.chk_whole = self.add_check(WrapCheck(tr("settings.words_whole")))
        self.chk_case = self.add_check(WrapCheck(tr("settings.words_case")))
        self.chk_words.toggled.connect(self._sync)

    def _sync(self, *_):
        for w in (self.txt_words, self.combo_action, self.chk_whole, self.chk_case):
            w.setEnabled(self.chk_words.isChecked())

    def load(self, cfg: ConfigManager):
        self.chk_words.setChecked(bool(cfg.get("blacklist_words_enabled", False)))
        self.txt_words.setPlainText(", ".join(split_list(cfg.get("blacklist_words", []))))
        self.combo_action.setCurrentIndex(max(0, self.combo_action.findData(cfg.get("blacklist_words_action", "mask"))))
        self.chk_whole.setChecked(bool(cfg.get("blacklist_words_whole_word", True)))
        self.chk_case.setChecked(bool(cfg.get("blacklist_words_case_sensitive", False)))
        self._sync()

    def save(self, cfg: ConfigManager):
        cfg.set("blacklist_words_enabled", self.chk_words.isChecked())
        cfg.set("blacklist_words", split_list(self.txt_words.toPlainText()))
        cfg.set("blacklist_words_action", self.combo_action.currentData())
        cfg.set("blacklist_words_whole_word", self.chk_whole.isChecked())
        cfg.set("blacklist_words_case_sensitive", self.chk_case.isChecked())


class AutoDetectSection(Section):
    def __init__(self, parent=None):
        super().__init__(tr("settings.detect_group"), parent)
        self.chk_detect = self.add_check(WrapCheck(tr("settings.detect_enable")))
        self.chk_skip_target = self.add_check(WrapCheck(tr("settings.detect_skip_target")))
        self.txt_skip_langs = QLineEdit()
        self.txt_skip_langs.setPlaceholderText("ru, de")
        self.add_field(tr("settings.detect_skip_langs"), self.txt_skip_langs)
        self.spin_min = QSpinBox()
        self.spin_min.setRange(1, 50)
        self.spin_min.setMaximumWidth(110)
        self.add_field(tr("settings.detect_min_len"), self.spin_min)
        self.chk_detect.toggled.connect(self._sync)

    def _sync(self, *_):
        for w in (self.chk_skip_target, self.txt_skip_langs, self.spin_min):
            w.setEnabled(self.chk_detect.isChecked())

    def load(self, cfg: ConfigManager):
        self.chk_detect.setChecked(bool(cfg.get("autodetect_enabled", True)))
        self.chk_skip_target.setChecked(bool(cfg.get("autodetect_skip_target_language", True)))
        self.txt_skip_langs.setText(", ".join(split_list(cfg.get("autodetect_skip_languages", []))))
        self.spin_min.setValue(int(cfg.get("autodetect_min_length", 3)))
        self._sync()

    def save(self, cfg: ConfigManager):
        cfg.set("autodetect_enabled", self.chk_detect.isChecked())
        cfg.set("autodetect_skip_target_language", self.chk_skip_target.isChecked())
        cfg.set("autodetect_skip_languages", split_list(self.txt_skip_langs.text()))
        cfg.set("autodetect_min_length", self.spin_min.value())


class HistorySection(Section):
    def __init__(self, parent=None):
        super().__init__(tr("settings.history_group"), parent)
        self.chk_hist = self.add_check(WrapCheck(tr("settings.history_enable")))
        self.chk_hist_disk = self.add_check(WrapCheck(tr("settings.history_disk")))
        self.spin_hist = QSpinBox()
        self.spin_hist.setRange(100, 100000)
        self.spin_hist.setSingleStep(500)
        self.spin_hist.setMaximumWidth(130)
        self.add_field(tr("settings.history_max"), self.spin_hist)
        self.chk_hist.toggled.connect(self._sync)

    def _sync(self, *_):
        for w in (self.chk_hist_disk, self.spin_hist):
            w.setEnabled(self.chk_hist.isChecked())

    def load(self, cfg: ConfigManager):
        self.chk_hist.setChecked(bool(cfg.get("history_enabled", True)))
        self.chk_hist_disk.setChecked(bool(cfg.get("history_save_to_disk", True)))
        self.spin_hist.setValue(int(cfg.get("history_max_entries", 5000)))
        self._sync()

    def save(self, cfg: ConfigManager):
        cfg.set("history_enabled", self.chk_hist.isChecked())
        cfg.set("history_save_to_disk", self.chk_hist_disk.isChecked())
        cfg.set("history_max_entries", self.spin_hist.value())


class ProfilesTab(QWidget):
    """Create, apply, update, rename and delete named presets of the chat/HUD settings."""
    profile_applied = pyqtSignal()
    profiles_changed = pyqtSignal()    # created / renamed: the tray menu lists them
    # Emitted just before a snapshot is taken so the dialog can flush unsaved widget values.
    snapshot_requested = pyqtSignal()

    def __init__(self, profiles: Optional[ProfileManager], parent=None):
        super().__init__(parent)
        self.profiles = profiles
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        section = Section(tr("settings.profiles_title"))
        section.add_widget(muted_label(tr("settings.profiles_hint")))

        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        self.list.itemDoubleClicked.connect(lambda *_: self._apply())
        section.add_widget(self.list)

        # Buttons wrap onto several rows when a translation makes them long.
        self.btn_apply = make_button(tr("settings.profile_apply"), "primary")
        self.btn_new = make_button(tr("settings.profile_new"))
        self.btn_save = make_button(tr("settings.profile_save"))
        self.btn_rename = make_button(tr("settings.profile_rename"))
        self.btn_delete = make_button(tr("settings.profile_delete"), "danger")
        for b, handler in ((self.btn_apply, self._apply), (self.btn_new, self._new), (self.btn_save, self._save_into),
                           (self.btn_rename, self._rename), (self.btn_delete, self._delete)):
            b.clicked.connect(handler)
        section.add_layout(button_row(self.btn_apply, self.btn_new, self.btn_save, self.btn_rename, self.btn_delete))

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setProperty("role", "muted")
        section.add_widget(self.lbl_status)
        root.addWidget(section)
        self._reload()

    def _reload(self):
        self.list.clear()
        if not self.profiles:
            return
        for name in self.profiles.names():
            marker = "●  " if name == self.profiles.active else "     "
            item = QListWidgetItem(marker + name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == self.profiles.active:
                self.list.setCurrentItem(item)

    def _selected(self) -> Optional[str]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _say(self, text: str):
        self.lbl_status.setText(text)

    def _apply(self):
        name = self._selected()
        if name and self.profiles and self.profiles.apply(name):
            self._reload()
            self.profile_applied.emit()
            self._say(tr("settings.profile_applied", profile=name))

    def _new(self):
        if not self.profiles:
            return
        name, ok = QInputDialog.getText(self, tr("settings.profile_new"), tr("settings.profile_name_prompt"))
        if not ok or not name.strip():
            return
        self.snapshot_requested.emit()
        try:
            created = self.profiles.create(name)
        except ValueError as exc:
            notify(self, tr("settings.profiles_title"), _profile_error_text(exc), "warning")
            return
        self._reload()
        self.profiles_changed.emit()
        self._say(tr("settings.profile_created", profile=created))

    def _save_into(self):
        name = self._selected()
        if name and self.profiles:
            self.snapshot_requested.emit()
            self.profiles.save_current(name)
            self._say(tr("settings.profile_saved", profile=name))

    def _rename(self):
        name = self._selected()
        if not name or not self.profiles:
            return
        new, ok = QInputDialog.getText(self, tr("settings.profile_rename"), tr("settings.profile_name_prompt"), text=name)
        if not ok or not new.strip():
            return
        try:
            self.profiles.rename(name, new)
        except ValueError as exc:
            notify(self, tr("settings.profiles_title"), _profile_error_text(exc), "warning")
            return
        self._reload()
        self.profiles_changed.emit()

    def _delete(self):
        name = self._selected()
        if not name or not self.profiles:
            return
        if name == DEFAULT_PROFILE:
            notify(self, tr("settings.profiles_title"), tr("settings.profile_default_locked"))
            return
        if ask(self, tr("settings.profiles_title"), tr("settings.profile_delete_confirm", profile=name), danger=True):
            active_before = self.profiles.active
            self.profiles.delete(name)
            self._reload()
            if active_before == name:
                self.profile_applied.emit()
