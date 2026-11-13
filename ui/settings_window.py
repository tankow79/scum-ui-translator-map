import logging
import os
import webbrowser

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
)

from core.chat_color import parse_nick_list
from core.config_manager import ConfigManager
from core.i18n import LocalizationManager, tr
from core.languages import ALL_LANGUAGES
from core.updater import UpdateChecker
from core.version import GITHUB_REPO_URL, __version__
from ui.flow_layout import button_row
from ui.settings_extra_tabs import (
    AutoDetectSection,
    HistorySection,
    LanguageSelector,
    ProfilesTab,
    WordFilterSection,
)
from ui.settings_widgets import Section, SettingsPage, SliderRow, WrapCheck, make_button, muted_label
from ui.theme import DIALOG_QSS
from ui.update_dialog import UpdateDialog

log = logging.getLogger("scum.settings")


class HotkeyButton(QPushButton):
    """
    Interactive hotkey capture button (F9, F8, T, Ctrl+T, etc.).
    Works reliably regardless of the active keyboard layout.
    """
    hotkey_changed = pyqtSignal(str)

    def __init__(self, current_hotkey: str = "F9", parent=None):
        super().__init__(parent)
        self.current_hotkey = current_hotkey or ""
        self.is_recording = False
        self.setMinimumWidth(140)
        self.setMinimumHeight(30)
        self.set_hotkey(self.current_hotkey)
        self.clicked.connect(self.start_recording)

    def set_hotkey(self, hotkey: str):
        self.current_hotkey = hotkey or ""
        self.is_recording = False
        self.setText(self.current_hotkey if self.current_hotkey else tr("settings.clear_bind"))
        self.update_style()
        self.hotkey_changed.emit(self.current_hotkey)

    def clear_hotkey(self):
        self.set_hotkey("")

    def update_style(self):
        if self.is_recording:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    border: 2px solid #f87171;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 11px;
                }
            """)
        elif not self.current_hotkey:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #0f172a;
                    color: #64748b;
                    border: 1px dashed #334155;
                    border-radius: 6px;
                    font-size: 11px;
                    font-style: italic;
                }
                QPushButton:hover {
                    background-color: #1e293b;
                    border-color: #38bdf8;
                    color: #94a3b8;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #38bdf8;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #334155;
                    border-color: #38bdf8;
                }
            """)

    def start_recording(self):
        self.is_recording = True
        self.setText(f"[ {tr('settings.press_key')} ]")
        self.update_style()
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent):
        if not self.is_recording:
            super().keyPressEvent(event)
            return

        key = event.key()

        # Delete or Backspace clears the binding
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.clear_hotkey()
            event.accept()
            return

        if key == Qt.Key.Key_Escape:
            self.is_recording = False
            self.setText(self.current_hotkey if self.current_hotkey else tr("settings.clear_bind"))
            self.update_style()
            event.accept()
            return

        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            event.accept()
            return

        modifiers = event.modifiers()
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")

        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            parts.append(f"F{key - Qt.Key.Key_F1 + 1}")
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            parts.append(chr(key))
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            parts.append(chr(key))
        elif key == Qt.Key.Key_Insert:
            parts.append("Insert")
        elif key == Qt.Key.Key_Delete:
            parts.append("Delete")
        elif key == Qt.Key.Key_Home:
            parts.append("Home")
        elif key == Qt.Key.Key_End:
            parts.append("End")
        elif key == Qt.Key.Key_PageUp:
            parts.append("PageUp")
        elif key == Qt.Key.Key_PageDown:
            parts.append("PageDown")
        elif key == Qt.Key.Key_Space:
            parts.append("Space")
        elif key == Qt.Key.Key_Tab:
            parts.append("Tab")
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            parts.append("Enter")
        elif key in (Qt.Key.Key_AsciiTilde, Qt.Key.Key_QuoteLeft):
            parts.append("~")
        else:
            text = event.text().upper()
            if text and text.isascii() and text.isalnum():
                parts.append(text)
            else:
                parts.append(f"Key_{key}")

        new_hotkey = "+".join(parts)
        self.current_hotkey = new_hotkey
        self.setText(new_hotkey)
        self.is_recording = False
        self.update_style()
        self.hotkey_changed.emit(new_hotkey)
        event.accept()


class SettingsDialog(QDialog):
    """Settings with a left navigation list (scales to long translations) and scrolling pages."""
    settings_changed = pyqtSignal()

    NAV_MAX_WIDTH = 230

    def __init__(self, config_manager: ConfigManager, parent=None, profiles=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.profiles = profiles
        LocalizationManager.get_instance().set_locale(self.cfg.get("ui_language", "en"))
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumSize(660, 460)
        self.resize(820, 600)
        self.setStyleSheet(DIALOG_QSS)

        self.init_ui()
        self.load_settings()

    # ── construction ─────────────────────────────────────────────────
    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        body.addWidget(self.nav, 0)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        pages = [
            (tr("settings.nav_general"), self._build_general_page()),
            (tr("settings.nav_chat"), self._build_chat_page()),
            (tr("settings.nav_appearance"), self._build_appearance_page()),
            (tr("settings.nav_hotkeys"), self._build_hotkeys_page()),
            (tr("settings.nav_profiles"), self._build_profiles_page()),
        ]
        for title, page in pages:
            item = QListWidgetItem(title)
            item.setToolTip(title)
            self.nav.addItem(item)
            self.stack.addWidget(page)
        fm = self.nav.fontMetrics()
        widest = max(fm.horizontalAdvance(title) for title, _ in pages)
        self.nav.setFixedWidth(min(self.NAV_MAX_WIDTH, max(150, widest + 56)))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        # Footer
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setStyleSheet("QFrame#footer { background-color: #111a2b; border-top: 1px solid #26344d; }")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 10, 18, 10)
        fl.setSpacing(10)
        self.lbl_version = QLabel(f"v{__version__}")
        self.lbl_version.setProperty("role", "muted")
        fl.addWidget(self.lbl_version)
        fl.addStretch(1)
        self.btn_cancel = make_button(tr("settings.cancel_btn"))
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = make_button(tr("settings.save_btn"), "primary")
        self.btn_save.clicked.connect(self.save_settings)
        fl.addWidget(self.btn_cancel)
        fl.addWidget(self.btn_save)
        root.addWidget(footer)

    def _row(self, *widgets, stretch_last: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in widgets:
            row.addWidget(w)
        if stretch_last:
            row.addStretch(1)
        return row

    # ── pages ────────────────────────────────────────────────────────
    def _build_general_page(self) -> SettingsPage:
        page = SettingsPage()

        self.tab_language = LanguageSelector()
        page.add_section(self.tab_language)

        s = Section(tr("settings.sec_startup"))
        self.chk_enable_chat = s.add_check(WrapCheck(tr("settings.enable_chat")))
        self.chk_autostart = s.add_check(WrapCheck(tr("settings.autostart")))
        page.add_section(s)

        s = Section(tr("settings.sec_game"))
        self.txt_log_path = QLineEdit()
        self.btn_browse = make_button(tr("settings.browse_btn"))
        self.btn_browse.clicked.connect(self.browse_log_file)
        box = QVBoxLayout()
        box.setSpacing(4)
        lbl = QLabel(tr("settings.log_file"))
        lbl.setWordWrap(True)
        box.addWidget(lbl)
        box.addLayout(self._row(self.txt_log_path, self.btn_browse))
        s.add_layout(box)
        self.txt_log_path.setMinimumWidth(120)
        self.txt_nickname = QLineEdit()
        self.txt_nickname.setPlaceholderText("Survivor")
        s.add_field(tr("settings.own_nickname"), self.txt_nickname)
        page.add_section(s)

        s = Section(tr("settings.sec_updates"))
        self.chk_auto_update = s.add_check(WrapCheck(tr("settings.update_autocheck")))
        self.spin_update_hours = QSpinBox()
        self.spin_update_hours.setRange(0, 168)
        self.spin_update_hours.setMaximumWidth(110)
        s.add_field(tr("settings.update_interval"), self.spin_update_hours)
        self.btn_check_update = make_button(tr("settings.update_check_btn"), "primary")
        self.btn_check_update.clicked.connect(self._manual_check_updates)
        btn_repo = make_button(tr("settings.update_github_btn"))
        btn_repo.clicked.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        s.add_layout(button_row(self.btn_check_update, btn_repo))
        self.lbl_update_status = QLabel(tr("settings.update_current_ver", version=__version__))
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setProperty("role", "muted")
        s.add_widget(self.lbl_update_status)
        s.add_widget(muted_label(tr("settings.update_guarantee")))
        page.add_section(s)

        page.finish()
        return page

    def _build_chat_page(self) -> SettingsPage:
        page = SettingsPage()

        s = Section(tr("settings.sec_translation"))
        self.combo_in_lang = QComboBox()
        self.combo_in_lang.setMaxVisibleItems(20)
        for name, code in ALL_LANGUAGES:
            self.combo_in_lang.addItem(name, code)
        s.add_field(tr("settings.target_lang"), self.combo_in_lang)
        self.chk_show_orig = s.add_check(WrapCheck(tr("settings.show_original")))
        self.chk_ignore_own = s.add_check(WrapCheck(tr("settings.ignore_own")))
        page.add_section(s)

        s = Section(tr("settings.sec_players"))
        self.txt_blacklist = QLineEdit()
        self.txt_blacklist.setPlaceholderText(tr("settings.blacklist_placeholder"))
        s.add_field(tr("settings.blacklist_title"), self.txt_blacklist, tr("settings.blacklist_hint"))
        self.txt_squad = QLineEdit()
        self.txt_squad.setPlaceholderText(tr("settings.squad_placeholder"))
        s.add_field(tr("settings.squad_title"), self.txt_squad, tr("settings.squad_hint"))
        page.add_section(s)

        self.section_words = page.add_section(WordFilterSection())
        self.section_detect = page.add_section(AutoDetectSection())
        self.section_history = page.add_section(HistorySection())
        page.finish()
        return page

    def _build_appearance_page(self) -> SettingsPage:
        page = SettingsPage()

        s = Section(tr("settings.sec_overlay"))
        self.combo_display_mode = QComboBox()
        self.combo_display_mode.addItem(tr("settings.display_mode_none"), "none")
        self.combo_display_mode.addItem(tr("settings.display_mode_border"), "border_only")
        self.combo_display_mode.addItem(tr("settings.display_mode_scrollbar"), "scrollbar_only")
        self.combo_display_mode.addItem(tr("settings.display_mode_both"), "both")
        s.add_field(tr("settings.display_mode"), self.combo_display_mode)

        row = SliderRow(tr("settings.fade_time"), 0, 60, tr("settings.fade_always"))
        self.slider_fade, self.badge_fade = row.slider, row.value_label
        self.slider_fade.valueChanged.connect(self._on_fade_slider_changed)
        s.add_widget(row)

        row = SliderRow(tr("settings.opacity"), 0, 100, "100%")
        self.slider_opacity, self.badge_opacity = row.slider, row.value_label
        self.slider_opacity.valueChanged.connect(lambda v: self.badge_opacity.setText(f"{v}%"))
        s.add_widget(row)

        row = SliderRow(tr("settings.font_size"), 10, 24, "24 px")
        self.slider_font, self.badge_font = row.slider, row.value_label
        self.slider_font.valueChanged.connect(lambda v: self.badge_font.setText(f"{v} px"))
        s.add_widget(row)

        row = SliderRow(tr("settings.max_messages"), 5, 40, tr("settings.msgs_count", count=40))
        self.slider_msgs, self.badge_msgs = row.slider, row.value_label
        self.slider_msgs.valueChanged.connect(lambda v: self.badge_msgs.setText(tr("settings.msgs_count", count=v)))
        s.add_widget(row)

        self.chk_font_bold = s.add_check(WrapCheck(tr("settings.font_bold")))
        self.chk_text_outline = s.add_check(WrapCheck(tr("settings.text_outline")))
        page.add_section(s)

        s = Section(tr("settings.sec_map"))
        self.combo_map_variant = QComboBox()
        self.combo_map_variant.addItem(tr("settings.map_variant_regular"), "regular")
        self.combo_map_variant.addItem(tr("settings.map_variant_tactical"), "tactical")
        s.add_field(tr("settings.map_style"), self.combo_map_variant)
        self.chk_map_grid = s.add_check(WrapCheck(tr("settings.map_grid")))
        self.chk_map_keypads = s.add_check(WrapCheck(tr("settings.map_keypads")))
        self.chk_map_ontop = s.add_check(WrapCheck(tr("settings.map_ontop")))
        self.chk_auto_focus = s.add_check(WrapCheck(tr("settings.map_auto_focus")))
        btn_reset_geo = make_button(tr("settings.map_reset_geo"))
        btn_reset_geo.clicked.connect(self._reset_map_windows_geometry)
        s.add_layout(button_row(btn_reset_geo))
        page.add_section(s)

        page.finish()
        return page

    def _build_hotkeys_page(self) -> SettingsPage:
        page = SettingsPage()
        s = Section(tr("settings.sec_hotkeys"))

        def hotkey_row(label: str, key: str, default: str):
            button = HotkeyButton(self.cfg.get(key, default))
            clear = make_button("✕", "icon", tr("settings.hotkey_clear_tip"))
            clear.clicked.connect(button.clear_hotkey)
            box = QVBoxLayout()
            box.setSpacing(4)
            lbl = QLabel(label)
            lbl.setWordWrap(True)
            box.addWidget(lbl)
            box.addLayout(self._row(button, clear, stretch_last=True))
            s.add_layout(box)
            return button

        self.btn_k_chat = hotkey_row(tr("settings.hotkey_chat"), "hotkey_quick_chat", "T")
        self.btn_k_lock = hotkey_row(tr("settings.hotkey_lock", hotkey="F9"), "hotkey_toggle_lock", "F9")
        self.btn_k_vis = hotkey_row(tr("settings.hotkey_vis", hotkey="F8"), "hotkey_toggle_visibility", "F8")
        self.btn_k_map = hotkey_row(tr("settings.hotkey_map"), "hotkey_toggle_map", "Ctrl+M")

        btn_reset_all = make_button(tr("settings.hotkey_reset_all"))

        def reset_hotkeys_to_defaults():
            self.btn_k_chat.set_hotkey("T")
            self.btn_k_lock.set_hotkey("F9")
            self.btn_k_vis.set_hotkey("F8")
            self.btn_k_map.set_hotkey("Ctrl+M")

        btn_reset_all.clicked.connect(reset_hotkeys_to_defaults)
        s.add_layout(button_row(btn_reset_all))
        s.add_widget(muted_label(tr("settings.hotkey_smart_guard")))
        page.add_section(s)
        page.finish()
        return page

    def _build_profiles_page(self) -> SettingsPage:
        page = SettingsPage()
        self.tab_profiles = ProfilesTab(self.profiles)
        self.tab_profiles.profile_applied.connect(self._on_profile_applied)
        self.tab_profiles.snapshot_requested.connect(self._write_to_cfg)
        page.add_section(self.tab_profiles)
        page.finish()
        return page

    # ── behaviour ────────────────────────────────────────────────────
    def _on_fade_slider_changed(self, v: int):
        self.badge_fade.setText(tr("settings.fade_always") if v == 0 else tr("settings.fade_seconds", seconds=v))

    def _on_profile_applied(self):
        """A profile changed the live config: refresh every widget and notify the app."""
        self.load_settings()
        self.settings_changed.emit()

    def load_settings(self):
        self.tab_language.load(self.cfg)
        self.section_words.load(self.cfg)
        self.section_detect.load(self.cfg)
        self.section_history.load(self.cfg)

        self.chk_enable_chat.setChecked(self.cfg.get("enable_chat_translator", True))
        self.chk_autostart.setChecked(self.cfg.get("auto_start", True))
        self.txt_log_path.setText(self.cfg.get("log_file_path", r"%LOCALAPPDATA%\SCUM\Saved\Logs\SCUM.log"))
        self.txt_nickname.setText(self.cfg.get("own_nickname", ""))
        self.chk_auto_update.setChecked(self.cfg.get("auto_check_updates", True))
        self.spin_update_hours.setValue(int(self.cfg.get("update_check_interval_hours", 6) or 0))

        self.combo_in_lang.setCurrentIndex(max(0, self.combo_in_lang.findData(self.cfg.get("target_language", "uk"))))
        self.chk_show_orig.setChecked(self.cfg.get("show_original", True))
        self.chk_ignore_own.setChecked(self.cfg.get("ignore_own_messages", False))
        blacklist = self.cfg.get("blacklist_nicknames", [])
        self.txt_blacklist.setText(", ".join(blacklist) if isinstance(blacklist, list) else str(blacklist))
        self.txt_squad.setText(", ".join(parse_nick_list(self.cfg.get("squad_nicknames", []))))

        self.chk_font_bold.setChecked(self.cfg.get("font_bold", False))
        self.chk_text_outline.setChecked(self.cfg.get("text_outline", True))
        self.combo_display_mode.setCurrentIndex(
            max(0, self.combo_display_mode.findData(self.cfg.get("ui_display_mode", "none"))))
        self.slider_fade.setValue(self.cfg.get("message_fade_timeout", 10))
        self._on_fade_slider_changed(self.slider_fade.value())
        opacity = int(self.cfg.get("bg_opacity", 0.5) * 100)
        self.slider_opacity.setValue(opacity)
        self.badge_opacity.setText(f"{opacity}%")
        font = self.cfg.get("font_size", 22)
        self.slider_font.setValue(font)
        self.badge_font.setText(f"{font} px")
        msgs = self.cfg.get("max_messages", 20)
        self.slider_msgs.setValue(msgs)
        self.badge_msgs.setText(tr("settings.msgs_count", count=msgs))

        self.btn_k_lock.set_hotkey(self.cfg.get("hotkey_toggle_lock", "F9"))
        self.btn_k_vis.set_hotkey(self.cfg.get("hotkey_toggle_visibility", "F8"))
        self.btn_k_chat.set_hotkey(self.cfg.get("hotkey_quick_chat", "T"))
        self.btn_k_map.set_hotkey(self.cfg.get("hotkey_toggle_map", "Ctrl+M"))

        self.combo_map_variant.setCurrentIndex(max(0, self.combo_map_variant.findData(self.cfg.get("map_variant", "regular"))))
        self.chk_map_grid.setChecked(self.cfg.get("map_show_grid", True))
        self.chk_map_keypads.setChecked(self.cfg.get("map_show_keypads", True))
        self.chk_map_ontop.setChecked(self.cfg.get("map_on_top", True))
        self.chk_auto_focus.setChecked(self.cfg.get("auto_focus_new_point", True))

    def _manual_check_updates(self):
        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setText(tr("settings.update_checking"))

        checker = UpdateChecker()

        def on_update_available(info):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText(tr("settings.update_available", version=info.version))
            UpdateDialog(info, self).exec()

        def on_no_update(curr_ver):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText(tr("settings.update_latest", version=curr_ver))

        def on_error(err_msg):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText(tr("settings.update_error", error=err_msg))

        checker.update_available.connect(on_update_available)
        checker.no_update_found.connect(on_no_update)
        checker.check_error.connect(on_error)
        self._active_checker = checker  # keep a reference so it is not garbage collected
        checker.check_for_updates_async()

    def _reset_map_windows_geometry(self):
        for key, value in (("map_x", -1), ("map_y", -1), ("map_width", 960), ("map_height", 660),
                           ("points_x", -1), ("points_y", -1), ("points_width", 960), ("points_height", 280)):
            self.cfg.set(key, value)

    def browse_log_file(self):
        default_dir = os.path.expandvars(r"%LOCALAPPDATA%\SCUM\Saved\Logs")
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.log_dialog_title"), default_dir if os.path.exists(default_dir) else "",
            "Log Files (*.log);;All Files (*)")
        if file_path:
            self.txt_log_path.setText(file_path)

    def save_settings(self):
        self._write_to_cfg()
        self.settings_changed.emit()
        self.accept()

    def _write_to_cfg(self):
        """Persist every widget value into the config (without closing the dialog)."""
        self.tab_language.save(self.cfg)
        self.section_words.save(self.cfg)
        self.section_detect.save(self.cfg)
        self.section_history.save(self.cfg)

        self.cfg.set("enable_chat_translator", self.chk_enable_chat.isChecked())
        autostart_val = self.chk_autostart.isChecked()
        self.cfg.set("auto_start", autostart_val)
        try:
            from utils.autostart import set_autostart
            set_autostart(autostart_val)
        except Exception as e:
            log.warning("Could not set autostart: %s", e)
        self.cfg.set("log_file_path", self.txt_log_path.text().strip())
        self.cfg.set("own_nickname", self.txt_nickname.text().strip())
        self.cfg.set("auto_check_updates", self.chk_auto_update.isChecked())
        self.cfg.set("update_check_interval_hours", self.spin_update_hours.value())

        self.cfg.set("target_language", self.combo_in_lang.currentData())
        self.cfg.set("show_original", self.chk_show_orig.isChecked())
        self.cfg.set("ignore_own_messages", self.chk_ignore_own.isChecked())
        self.cfg.set("blacklist_nicknames", [n.strip() for n in self.txt_blacklist.text().split(",") if n.strip()])
        self.cfg.set("squad_nicknames", parse_nick_list(self.txt_squad.text()))

        self.cfg.set("font_bold", self.chk_font_bold.isChecked())
        self.cfg.set("text_outline", self.chk_text_outline.isChecked())
        self.cfg.set("ui_display_mode", self.combo_display_mode.currentData())
        self.cfg.set("message_fade_timeout", self.slider_fade.value())
        self.cfg.set("bg_opacity", self.slider_opacity.value() / 100.0)
        self.cfg.set("font_size", self.slider_font.value())
        self.cfg.set("max_messages", self.slider_msgs.value())

        self.cfg.set("hotkey_toggle_lock", self.btn_k_lock.current_hotkey)
        self.cfg.set("hotkey_toggle_visibility", self.btn_k_vis.current_hotkey)
        self.cfg.set("hotkey_quick_chat", self.btn_k_chat.current_hotkey)
        self.cfg.set("game_chat_key", self.btn_k_chat.current_hotkey)
        self.cfg.set("hotkey_toggle_map", self.btn_k_map.current_hotkey)

        self.cfg.set("map_variant", self.combo_map_variant.currentData())
        self.cfg.set("map_show_grid", self.chk_map_grid.isChecked())
        self.cfg.set("map_show_keypads", self.chk_map_keypads.isChecked())
        self.cfg.set("map_on_top", self.chk_map_ontop.isChecked())
        self.cfg.set("auto_focus_new_point", self.chk_auto_focus.isChecked())
