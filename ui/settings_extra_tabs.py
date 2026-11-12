"""Additional settings tabs: Language, Filters & History, Profiles.

Each tab exposes ``load(cfg)`` and ``save(cfg)`` so ``SettingsDialog`` can treat them uniformly.
"""

import logging
import os
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.i18n import LocalizationManager, tr
from core.message_filter import split_list
from core.profiles import DEFAULT_PROFILE, ProfileManager

log = logging.getLogger("scum.settings_tabs")

EXTRA_STYLE = """
QPlainTextEdit, QListWidget, QSpinBox {
    background-color: #0f172a; border: 1px solid #334155; border-radius: 5px; color: #f8fafc; padding: 4px;
}
QPlainTextEdit:focus, QListWidget:focus, QSpinBox:focus { border: 1px solid #38bdf8; }
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:selected { background-color: #0284c7; color: #ffffff; }
QGroupBox { color: #38bdf8; font-weight: 600; border: 1px solid #334155; border-radius: 8px;
            margin-top: 10px; padding: 12px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
"""

BUTTON_STYLE = """
QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 5px; color: #38bdf8;
              font-weight: 600; padding: 5px 12px; }
QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
QPushButton:disabled { color: #64748b; }
"""


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
    return lbl


def _button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(BUTTON_STYLE)
    btn.setFixedHeight(28)
    return btn


# ─────────────────────────── Language ───────────────────────────

class LanguageTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(10)

        title = QLabel(tr("settings.language_title"))
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        lay.addWidget(title)

        self.list = QListWidget()
        mgr = LocalizationManager.get_instance()
        for code, name in mgr.available_locales():
            item = QListWidgetItem(f"{name}  ({code})")
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.list.addItem(item)
        lay.addWidget(self.list, 1)

        lay.addWidget(_hint(tr("settings.language_hint")))

        row = QHBoxLayout()
        btn_folder = _button(tr("settings.language_open_folder"))
        btn_folder.clicked.connect(self._open_folder)
        row.addWidget(btn_folder)
        row.addStretch()
        lay.addLayout(row)

    def _open_folder(self):
        folder = LocalizationManager.get_instance()._get_locales_dir()
        if os.path.isdir(folder):
            os.startfile(folder)  # noqa: S606 - local folder, Windows only app

    def load(self, cfg: ConfigManager):
        code = cfg.get("ui_language", "en")
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == code:
                self.list.setCurrentRow(i)
                return
        self.list.setCurrentRow(0)

    def selected_code(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else "en"

    def save(self, cfg: ConfigManager):
        code = self.selected_code()
        cfg.set("ui_language", code)
        LocalizationManager.get_instance().set_locale(code)


# ─────────────────────── Filters & History ───────────────────────

class FiltersTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Word blacklist
        g_words = QGroupBox(tr("settings.words_group"))
        v = QVBoxLayout(g_words)
        self.chk_words = QCheckBox(tr("settings.words_enable"))
        v.addWidget(self.chk_words)
        self.txt_words = QPlainTextEdit()
        self.txt_words.setPlaceholderText(tr("settings.words_placeholder"))
        self.txt_words.setFixedHeight(64)
        v.addWidget(self.txt_words)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("settings.words_action")))
        self.combo_action = QComboBox()
        self.combo_action.addItem(tr("settings.words_action_mask"), "mask")
        self.combo_action.addItem(tr("settings.words_action_hide"), "hide")
        self.combo_action.addItem(tr("settings.words_action_original"), "no_translate")
        row.addWidget(self.combo_action, 1)
        v.addLayout(row)
        self.chk_whole = QCheckBox(tr("settings.words_whole"))
        self.chk_case = QCheckBox(tr("settings.words_case"))
        v.addWidget(self.chk_whole)
        v.addWidget(self.chk_case)
        self.chk_words.toggled.connect(self._sync_enabled)
        lay.addWidget(g_words)

        # Auto-detect
        g_detect = QGroupBox(tr("settings.detect_group"))
        v = QVBoxLayout(g_detect)
        self.chk_detect = QCheckBox(tr("settings.detect_enable"))
        self.chk_skip_target = QCheckBox(tr("settings.detect_skip_target"))
        v.addWidget(self.chk_detect)
        v.addWidget(self.chk_skip_target)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("settings.detect_skip_langs")))
        self.txt_skip_langs = QLineEdit()
        self.txt_skip_langs.setPlaceholderText("ru, de")
        row.addWidget(self.txt_skip_langs, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("settings.detect_min_len")))
        self.spin_min = QSpinBox()
        self.spin_min.setRange(1, 50)
        row.addWidget(self.spin_min)
        row.addStretch()
        v.addLayout(row)
        self.chk_detect.toggled.connect(self._sync_enabled)
        lay.addWidget(g_detect)

        # History
        g_hist = QGroupBox(tr("settings.history_group"))
        v = QVBoxLayout(g_hist)
        self.chk_hist = QCheckBox(tr("settings.history_enable"))
        self.chk_hist_disk = QCheckBox(tr("settings.history_disk"))
        v.addWidget(self.chk_hist)
        v.addWidget(self.chk_hist_disk)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("settings.history_max")))
        self.spin_hist = QSpinBox()
        self.spin_hist.setRange(100, 100000)
        self.spin_hist.setSingleStep(500)
        row.addWidget(self.spin_hist)
        row.addStretch()
        v.addLayout(row)
        self.chk_hist.toggled.connect(self._sync_enabled)
        lay.addWidget(g_hist)
        lay.addStretch()

    def _sync_enabled(self, *_):
        words_on = self.chk_words.isChecked()
        for w in (self.txt_words, self.combo_action, self.chk_whole, self.chk_case):
            w.setEnabled(words_on)
        detect_on = self.chk_detect.isChecked()
        for w in (self.chk_skip_target, self.txt_skip_langs, self.spin_min):
            w.setEnabled(detect_on)
        hist_on = self.chk_hist.isChecked()
        for w in (self.chk_hist_disk, self.spin_hist):
            w.setEnabled(hist_on)

    def load(self, cfg: ConfigManager):
        self.chk_words.setChecked(bool(cfg.get("blacklist_words_enabled", False)))
        self.txt_words.setPlainText(", ".join(split_list(cfg.get("blacklist_words", []))))
        idx = self.combo_action.findData(cfg.get("blacklist_words_action", "mask"))
        self.combo_action.setCurrentIndex(max(0, idx))
        self.chk_whole.setChecked(bool(cfg.get("blacklist_words_whole_word", True)))
        self.chk_case.setChecked(bool(cfg.get("blacklist_words_case_sensitive", False)))

        self.chk_detect.setChecked(bool(cfg.get("autodetect_enabled", True)))
        self.chk_skip_target.setChecked(bool(cfg.get("autodetect_skip_target_language", True)))
        self.txt_skip_langs.setText(", ".join(split_list(cfg.get("autodetect_skip_languages", []))))
        self.spin_min.setValue(int(cfg.get("autodetect_min_length", 3)))

        self.chk_hist.setChecked(bool(cfg.get("history_enabled", True)))
        self.chk_hist_disk.setChecked(bool(cfg.get("history_save_to_disk", True)))
        self.spin_hist.setValue(int(cfg.get("history_max_entries", 5000)))
        self._sync_enabled()

    def save(self, cfg: ConfigManager):
        cfg.set("blacklist_words_enabled", self.chk_words.isChecked())
        cfg.set("blacklist_words", split_list(self.txt_words.toPlainText()))
        cfg.set("blacklist_words_action", self.combo_action.currentData())
        cfg.set("blacklist_words_whole_word", self.chk_whole.isChecked())
        cfg.set("blacklist_words_case_sensitive", self.chk_case.isChecked())

        cfg.set("autodetect_enabled", self.chk_detect.isChecked())
        cfg.set("autodetect_skip_target_language", self.chk_skip_target.isChecked())
        cfg.set("autodetect_skip_languages", split_list(self.txt_skip_langs.text()))
        cfg.set("autodetect_min_length", self.spin_min.value())

        cfg.set("history_enabled", self.chk_hist.isChecked())
        cfg.set("history_save_to_disk", self.chk_hist_disk.isChecked())
        cfg.set("history_max_entries", self.spin_hist.value())


# ───────────────────────────── Profiles ─────────────────────────────

class ProfilesTab(QWidget):
    """Create, apply, update, rename and delete named presets of the chat/HUD settings."""
    profile_applied = pyqtSignal()
    # Emitted just before a profile snapshot is taken so the dialog can flush unsaved widget values.
    snapshot_requested = pyqtSignal()

    def __init__(self, profiles: Optional[ProfileManager], parent=None):
        super().__init__(parent)
        self.profiles = profiles
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(10)

        title = QLabel(tr("settings.profiles_title"))
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        lay.addWidget(title)
        lay.addWidget(_hint(tr("settings.profiles_hint")))

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._apply())
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.btn_apply = _button(tr("settings.profile_apply"))
        self.btn_new = _button(tr("settings.profile_new"))
        self.btn_save = _button(tr("settings.profile_save"))
        self.btn_rename = _button(tr("settings.profile_rename"))
        self.btn_delete = _button(tr("settings.profile_delete"))
        self.btn_apply.clicked.connect(self._apply)
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save_into)
        self.btn_rename.clicked.connect(self._rename)
        self.btn_delete.clicked.connect(self._delete)
        for b in (self.btn_apply, self.btn_new, self.btn_save, self.btn_rename, self.btn_delete):
            row.addWidget(b)
        lay.addLayout(row)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #86efac; font-size: 11px;")
        lay.addWidget(self.lbl_status)
        self._reload()

    def _reload(self):
        self.list.clear()
        if not self.profiles:
            return
        for name in self.profiles.names():
            marker = "●  " if name == self.profiles.active else "    "
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
            QMessageBox.warning(self, tr("settings.profiles_title"), str(exc))
            return
        self._reload()
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
            QMessageBox.warning(self, tr("settings.profiles_title"), str(exc))
            return
        self._reload()

    def _delete(self):
        name = self._selected()
        if not name or not self.profiles:
            return
        if name == DEFAULT_PROFILE:
            QMessageBox.information(self, tr("settings.profiles_title"), tr("settings.profile_default_locked"))
            return
        answer = QMessageBox.question(self, tr("settings.profiles_title"), tr("settings.profile_delete_confirm", profile=name),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            active_before = self.profiles.active
            self.profiles.delete(name)
            self._reload()
            if active_before == name:
                self.profile_applied.emit()
