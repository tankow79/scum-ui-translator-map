import html
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QImage, QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.chat_color import (
    GAME_FONT_STACK,
    SQUAD_COLOR,
    extract_text_color,
    game_timestamp,
    is_squad_member,
    parse_nick_list,
    pick_color,
)
from core.config_manager import ConfigManager
from core.i18n import tr
from core.languages import ALL_LANGUAGES
from utils.win_api import (
    force_foreground_window,
    keep_on_top,
    restore_game_focus,
    set_click_through,
    set_last_game_hwnd,
    user32,
)


class OutlinedChatBrowser(QTextBrowser):
    """
    Chat text browser with a black outline in the SCUM / Unreal Engine HUD style.
    Keeps text fully readable on any game background (snow, water, sun, rocks, grass).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.outline_enabled = True
        self.font_bold = False
        self.font_size = 22
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Type.Paint:
            if not self.outline_enabled:
                return super().eventFilter(obj, event)

            vp = self.viewport()
            w, h = vp.width(), vp.height()
            if w <= 0 or h <= 0:
                return True

            # 1. Render the document text into a transparent image, accounting for scrolling
            text_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            text_img.fill(0)
            p1 = QPainter(text_img)
            p1.translate(-self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
            self.document().drawContents(p1)
            p1.end()

            # 2. Take the exact text silhouette and fill it with black
            black_img = text_img.copy()
            p2 = QPainter(black_img)
            p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            p2.fillRect(black_img.rect(), QColor(0, 0, 0, 255))
            p2.end()

            # 3. Draw the outline on the viewport with an offset adapted to the font size
            p = QPainter(vp)
            # The in-game outline is a partial one: black only on the right and bottom edges of the glyphs
            offsets = [(1, 0), (0, 1), (1, 1)]
            if self.font_size >= 28:
                offsets += [(2, 1), (1, 2), (2, 2)]

            for dx, dy in offsets:
                p.drawImage(dx, dy, black_img)

            # 4. Draw the bright colored text over the outline
            p.drawImage(0, 0, text_img)
            p.end()
            return True

        return super().eventFilter(obj, event)


@dataclass
class ChatEntry:
    time_str: str
    sender: str
    original: str
    translated: str
    src_lang: str
    msg_type: str
    created_time: float


class ChatOverlay(QWidget):
    """
    Unified HUD overlay and quick-translation window:
    - High-contrast colors with shadow for readability on any game background.
    - Built-in quick chat translation panel, no extra windows.
    - Drag & resize support in adjust mode (F9).
    """
    open_settings_requested = pyqtSignal()
    open_map_requested = pyqtSignal()
    test_requested = pyqtSignal()
    translate_and_copy = pyqtSignal(str, str)  # (original, translated)
    live_translation_ready = pyqtSignal(int, str)  # (request_id, translated_text)

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.cfg = config_manager
        self.is_locked = True
        self.in_chat_mode = False   # Whether the in-game chat is open
        self._drag_pos = QPoint()
        self._entries: List[ChatEntry] = []
        self._current_translation: str = ""
        self._translator = None

        # Async background translation that never blocks typing
        self._live_executor = ThreadPoolExecutor(max_workers=1)
        self._live_req_id = 0
        self.live_translation_ready.connect(self._on_live_translation_ready)

        # Live translation debounce
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._do_live_translate)

        # Message fade timer (every 500 ms)
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._refresh_rendered_chat)
        self._fade_timer.start(500)

        self.init_window_flags()
        self.init_ui()
        self.apply_config_geometry()
        self.update_lock_state(initial=True)

    # ──────────────────────── Window init ────────────────────────

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(6)

        self._build_header_bar()
        self._build_chat_view()
        self._build_input_bar()
        self._build_resize_grip()

        self.update_style()

    def set_translator(self, translator):
        """Attach the translator module."""
        self._translator = translator

    def _build_header_bar(self):
        """Top control bar (visible in adjust mode, F9)."""
        self.header_bar = QWidget(self)
        self.header_bar.setStyleSheet("""
            QWidget {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        h = QHBoxLayout(self.header_bar)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        hotkey = self.cfg.get("hotkey_toggle_lock", "F9")
        self.title_label = QLabel(tr("overlay.header_title", hotkey=hotkey, lock_text=tr("overlay.lock")))
        self.title_label.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(60)
        h.addWidget(self.title_label, 1)

        # Test button
        self.btn_test = QPushButton(f"🧪 {tr('overlay.test_btn')}")
        self.btn_test.setMinimumHeight(28)
        self.btn_test.setToolTip(tr("tray.test_msg"))
        self.btn_test.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                border: 1px solid #38bdf8;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                padding: 2px 10px;
            }
            QPushButton:hover { background-color: #0369a1; }
        """)
        self.btn_test.clicked.connect(self.test_requested.emit)
        h.addWidget(self.btn_test)

        # Clear history
        self.btn_clear = QPushButton("🧹")
        self.btn_clear.setMinimumSize(28, 28)
        self.btn_clear.setToolTip(tr("overlay.clear_history"))
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 4px;
                font-family: 'Segoe UI Emoji', 'Segoe UI Symbol', 'Segoe UI', sans-serif;
                font-size: 13px;
                padding: 0px 4px;
            }
            QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
        """)
        self.btn_clear.clicked.connect(self.clear_chat)
        h.addWidget(self.btn_clear)

        # Map and points (Ctrl+M)
        self.btn_map = QPushButton("🗺")
        self.btn_map.setMinimumSize(28, 28)
        map_hotkey = self.cfg.get("hotkey_toggle_map", "Ctrl+M")
        self.btn_map.setToolTip(tr("overlay.open_map", hotkey=map_hotkey))
        self.btn_map.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 4px;
                font-family: 'Segoe UI Emoji', 'Segoe UI Symbol', 'Segoe UI', sans-serif;
                font-size: 13px;
                padding: 0px 4px;
            }
            QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
        """)
        self.btn_map.clicked.connect(self.open_map_requested.emit)
        h.addWidget(self.btn_map)

        # Settings
        self.btn_settings = QPushButton("🛠")
        self.btn_settings.setMinimumSize(28, 28)
        self.btn_settings.setToolTip(tr("overlay.open_settings"))
        self.btn_settings.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 4px;
                font-family: 'Segoe UI Emoji', 'Segoe UI Symbol', 'Segoe UI', sans-serif;
                font-size: 13px;
                padding: 0px 4px;
            }
            QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
        """)
        self.btn_settings.clicked.connect(self.open_settings_requested.emit)
        h.addWidget(self.btn_settings)

        # Lock
        self.btn_lock = QPushButton(tr("overlay.lock"))
        self.btn_lock.setMinimumHeight(28)
        self.btn_lock.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                border: 1px solid #10b981;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
                padding: 2px 10px;
            }
            QPushButton:hover { background-color: #10b981; }
        """)
        self.btn_lock.clicked.connect(self.toggle_lock)
        h.addWidget(self.btn_lock)

        self.main_layout.addWidget(self.header_bar)

    def _build_chat_view(self):
        """Chat display area with a black text outline."""
        self.chat_view = OutlinedChatBrowser(self)
        self.chat_view.setOpenExternalLinks(True)
        self.chat_view.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_view.viewport().setAutoFillBackground(False)
        self.chat_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.chat_view.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.main_layout.addWidget(self.chat_view)

    def _build_input_bar(self):
        """
        Built-in quick chat translation panel (Midnight Cyan style).
        Shown in adjust mode (F9) or when the chat is open (T).
        """
        self.input_bar = QWidget(self)
        self.input_bar.setStyleSheet("""
            QWidget#cyber_input_card {
                background-color: #0f172a;
                border: 1px solid #38bdf8;
                border-radius: 8px;
            }
            QLabel {
                color: #f1f5f9;
                font-family: 'Segoe UI', sans-serif;
            }
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 5px;
                color: #ffffff;
                font-size: 13px;
                padding: 6px 10px;
                selection-background-color: #0284c7;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
            QComboBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #38bdf8;
                font-size: 11px;
                font-weight: bold;
                padding: 3px 6px;
                min-height: 20px;
            }
            QComboBox:hover {
                border-color: #38bdf8;
            }
            QComboBox::drop-down {
                border: none;
                width: 16px;
            }
            QComboBox QAbstractItemView {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #38bdf8;
                selection-background-color: #0284c7;
                selection-color: #ffffff;
                padding: 4px;
            }
        """)
        self.input_bar.setObjectName("cyber_input_card")

        v = QVBoxLayout(self.input_bar)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        # 1. Top row: language 1 <-> language 2 + hint
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.combo_src = QComboBox()
        self._setup_lang_combo(self.combo_src)
        self.combo_src.currentIndexChanged.connect(self._on_languages_changed)
        top_row.addWidget(self.combo_src, 1)

        self.btn_swap = QPushButton("\u21C4")
        self.btn_swap.setMinimumSize(32, 28)
        self.btn_swap.setToolTip(tr("overlay_ui.swap_languages"))
        self.btn_swap.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #38bdf8;
                font-family: 'Segoe UI Symbol', 'Segoe UI', sans-serif;
                font-size: 15px;
                font-weight: bold;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: #0284c7;
                border-color: #38bdf8;
                color: white;
            }
        """)
        self.btn_swap.clicked.connect(self.swap_languages)
        top_row.addWidget(self.btn_swap)

        self.combo_tgt = QComboBox()
        self._setup_lang_combo(self.combo_tgt)
        self.combo_tgt.currentIndexChanged.connect(self._on_languages_changed)
        top_row.addWidget(self.combo_tgt, 1)

        v.addLayout(top_row)

        self.lbl_input_hint = QLabel(tr("overlay.hint_input"))
        self.lbl_input_hint.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent; border: none;")
        self.lbl_input_hint.setWordWrap(True)
        self.lbl_input_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_input_hint.setMinimumHeight(QFontMetrics(self.lbl_input_hint.font()).height() + 2)
        v.addWidget(self.lbl_input_hint)

        # 2. Input field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(tr("overlay.placeholder_type"))
        self.input_field.textChanged.connect(self._on_input_text_changed)
        self.input_field.installEventFilter(self)
        v.addWidget(self.input_field)

        # 3. Live translation result
        self.lbl_translation = QLabel(f"<i>{tr('overlay.placeholder_input')}</i>")
        self.lbl_translation.setStyleSheet("""
            QLabel {
                background-color: rgba(2, 6, 23, 0.75);
                border: 1px solid rgba(56, 189, 248, 0.3);
                border-radius: 5px;
                color: #34d399;
                font-size: 13px;
                font-weight: 600;
                padding: 6px 10px;
            }
        """)
        self.lbl_translation.setWordWrap(True)
        v.addWidget(self.lbl_translation)

        # 4. Copy translation button
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_copy = QPushButton(tr("overlay.copy_btn_enter"))
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                border: 1px solid #10b981;
                border-radius: 5px;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 5px 14px;
            }
            QPushButton:hover { background-color: #10b981; }
        """)
        self.btn_copy.setMinimumHeight(28)
        self.btn_copy.clicked.connect(self._copy_translation)
        btn_row.addWidget(self.btn_copy)
        v.addLayout(btn_row)

        self.main_layout.addWidget(self.input_bar)
        self._sync_combos_from_config()

    @staticmethod
    def _setup_lang_combo(combo: QComboBox):
        """Fill a language combo; it sizes to a sane width, elides long names and shows full names in the popup."""
        combo.setMaxVisibleItems(20)
        for name, code in ALL_LANGUAGES:
            combo.addItem(name, code)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        fm = QFontMetrics(combo.font())
        widest = max((fm.horizontalAdvance(n) for n, _ in ALL_LANGUAGES), default=0)
        combo.view().setMinimumWidth(widest + 48)

    def _build_resize_grip(self):
        """Bottom corner window resize grip."""
        self.bottom_bar = QWidget(self)
        bl = QHBoxLayout(self.bottom_bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(14, 14)
        bl.addWidget(self.size_grip)
        self.main_layout.addWidget(self.bottom_bar)

    # ──────────────────────── Built-in translator ─────────────────────

    def _sync_combos_from_config(self):
        my_l = self.cfg.get("outgoing_my_lang", "uk")
        tgt_l = self.cfg.get("outgoing_target_lang", "en")

        self.combo_src.blockSignals(True)
        self.combo_tgt.blockSignals(True)

        idx_src = self.combo_src.findData(my_l)
        if idx_src >= 0:
            self.combo_src.setCurrentIndex(idx_src)

        idx_tgt = self.combo_tgt.findData(tgt_l)
        if idx_tgt >= 0:
            self.combo_tgt.setCurrentIndex(idx_tgt)

        self.combo_src.blockSignals(False)
        self.combo_tgt.blockSignals(False)

    def _on_languages_changed(self):
        self.cfg.set("outgoing_my_lang", self.combo_src.currentData())
        self.cfg.set("outgoing_target_lang", self.combo_tgt.currentData())
        self._do_live_translate()

    def swap_languages(self):
        src_idx = self.combo_src.currentIndex()
        tgt_idx = self.combo_tgt.currentIndex()

        self.combo_src.blockSignals(True)
        self.combo_tgt.blockSignals(True)
        self.combo_src.setCurrentIndex(tgt_idx)
        self.combo_tgt.setCurrentIndex(src_idx)
        self.combo_src.blockSignals(False)
        self.combo_tgt.blockSignals(False)

        self._on_languages_changed()

    def _on_input_text_changed(self, text: str):
        if not text.strip():
            self._current_translation = ""
            self._live_req_id += 1
            self._debounce_timer.stop()
            self.lbl_translation.setText(f"<i>{tr('overlay.placeholder_input')}</i>")
            return
        # 450 ms timer keeps typing from causing UI stalls
        self._debounce_timer.start(450)

    def _do_live_translate(self):
        text = self.input_field.text().strip()
        if not text:
            return
        if self._translator is not None:
            self._live_req_id += 1
            req_id = self._live_req_id
            my_lang = self.combo_src.currentData() or "uk"
            target_lang = self.combo_tgt.currentData() or "en"
            self.lbl_translation.setText(f"<i>{tr('overlay.translating')}</i>")

            def _async_worker(rid: int, txt: str, src: str, tgt: str):
                try:
                    trans, _ = self._translator.translate_custom(txt, target=tgt, source=src)
                    self.live_translation_ready.emit(rid, trans)
                except Exception:
                    self.live_translation_ready.emit(rid, "")

            self._live_executor.submit(_async_worker, req_id, text, my_lang, target_lang)

    def _on_live_translation_ready(self, req_id: int, translation: str):
        if req_id != self._live_req_id:
            return  # Ignore a stale response from an earlier text state
        if translation:
            self._current_translation = translation
            self.lbl_translation.setText(translation)
        else:
            self.lbl_translation.setText(f"<i>{tr('overlay.translate_fail')}</i>")

    def _copy_translation(self):
        orig = self.input_field.text().strip()
        if not orig:
            self.set_in_chat_mode(False)
            return

        # If Enter was pressed before the debounce finished, translate immediately
        if not self._current_translation or self.lbl_translation.text() in (f"<i>{tr('overlay.translating')}</i>", f"<i>{tr('overlay.placeholder_input')}</i>"):
            if self._translator:
                my_lang = self.combo_src.currentData() or "uk"
                target_lang = self.combo_tgt.currentData() or "en"
                trans, _ = self._translator.translate_custom(orig, target=target_lang, source=my_lang)
                self._current_translation = trans
                self.lbl_translation.setText(trans)

        if self._current_translation:
            QApplication.clipboard().setText(self._current_translation)
            self.translate_and_copy.emit(orig, self._current_translation)

        # Hide chat mode right away and return focus to the SCUM game
        self.set_in_chat_mode(False)

    def focus_input(self):
        """Activate the window and focus the input field."""
        # Remember the game window before giving focus to our overlay
        try:
            fg = user32.GetForegroundWindow()
            if fg and fg != int(self.winId()):
                set_last_game_hwnd(fg)
        except Exception:
            pass

        self._sync_combos_from_config()
        self.input_field.clear()
        self._current_translation = ""
        self.lbl_translation.setText(f"<i>{tr('overlay.placeholder_input')}</i>")
        self.lbl_input_hint.setText(tr("overlay.hint_input"))

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.show()
        self.raise_()
        self.activateWindow()

        hwnd = int(self.winId())
        set_click_through(hwnd, False)
        force_foreground_window(hwnd)

        self.input_field.setFocus()

    def close_input(self):
        """Clear the input, restore click-through and return focus to the game."""
        self._live_req_id += 1
        self._debounce_timer.stop()
        self.input_field.clear()
        self._current_translation = ""
        self.lbl_translation.setText(f"<i>{tr('overlay.placeholder_input')}</i>")

        self.input_field.clearFocus()
        self.clearFocus()

        if self.is_locked:
            hwnd = int(self.winId())
            set_click_through(hwnd, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Instantly return focus and mouse to the SCUM window (like NVIDIA/Steam overlays)
        restore_game_focus()

    # ──────────────────────── Chat mode and controls ──────────────────

    def apply_config_geometry(self):
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None

        screen_w = screen_geo.width() if screen_geo else 1920
        screen_h = screen_geo.height() if screen_geo else 1080
        screen_x = screen_geo.x() if screen_geo else 0
        screen_y = screen_geo.y() if screen_geo else 0

        saved_x = self.cfg.get("overlay_x", -1)
        saved_y = self.cfg.get("overlay_y", -1)
        saved_w = self.cfg.get("overlay_width", -1)
        saved_h = self.cfg.get("overlay_height", -1)

        # 1. Adaptive proportional sizes for any screen (1366x768 to 1440p / 4K)
        default_w = max(520, min(int(screen_w * 0.36), 850))
        default_h = max(260, min(int(screen_h * 0.30), 450))

        w = saved_w if (saved_w and saved_w > 0) else default_w
        h = saved_h if (saved_h and saved_h > 0) else default_h

        # 2. Position: default is the lower-left area above the in-game SCUM chat line
        default_x = screen_x + max(25, int(screen_w * 0.025))
        default_y = screen_y + screen_h - h - max(60, int(screen_h * 0.08))

        if saved_x is None or saved_x < 0 or saved_y is None or saved_y < 0:
            x = default_x
            y = default_y
        else:
            x = saved_x
            y = saved_y

        # 3. Keep the window on screen (different resolution / monitor change)
        w = max(380, min(w, screen_w - 20))
        h = max(180, min(h, screen_h - 20))
        x = max(screen_x + 5, min(x, screen_x + screen_w - w - 5))
        y = max(screen_y + 5, min(y, screen_y + screen_h - h - 5))

        self.setGeometry(x, y, w, h)

    def save_geometry(self):
        self.cfg.set("overlay_x", self.x())
        self.cfg.set("overlay_y", self.y())
        self.cfg.set("overlay_width", self.width())
        self.cfg.set("overlay_height", self.height())

    def set_in_chat_mode(self, in_chat: bool):
        """
        In-game chat open mode (T / Escape).
        in_chat=True: show all messages + open the built-in translator.
        in_chat=False: back to HUD mode (messages fade, translator hidden).
        """
        if self.in_chat_mode == in_chat:
            return

        self.in_chat_mode = in_chat
        self._update_panels_visibility()
        self._refresh_rendered_chat()

        if in_chat:
            self.focus_input()
        else:
            self.close_input()

    def _update_panels_visibility(self):
        """Control panel visibility."""
        if not self.is_locked:
            self.header_bar.show()
            self.input_bar.show()
            self.bottom_bar.show()
        else:
            self.header_bar.hide()
            self.bottom_bar.hide()
            if self.in_chat_mode:
                self.input_bar.show()
            else:
                self.input_bar.hide()

    def update_style(self):
        mode = self.cfg.get("ui_display_mode", "none")

        show_scrollbar = (mode in ("scrollbar_only", "both"))
        if show_scrollbar:
            self.chat_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scrollbar_css = """
                QScrollBar:vertical {
                    background: rgba(15, 23, 42, 0.4);
                    width: 6px;
                    margin: 0;
                    border-radius: 3px;
                }
                QScrollBar::handle:vertical {
                    background: #334155;
                    border-radius: 3px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #38bdf8;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        else:
            self.chat_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scrollbar_css = "QScrollBar:vertical { width: 0; }"

        self.chat_view.setStyleSheet(f"""
            QTextBrowser {{
                background: transparent;
                border: none;
                color: #f1f5f9;
            }}
            {scrollbar_css}
        """)

        self._update_panels_visibility()
        self._refresh_rendered_chat()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        opacity = self.cfg.get("bg_opacity", 0.5)
        mode = self.cfg.get("ui_display_mode", "none")
        alpha = int(opacity * 255)
        rect = self.rect().adjusted(1, 1, -1, -1)

        if not self.is_locked:
            # Adjust mode (F9): #0f172a background with a dashed Electric Sky Blue #38bdf8 border
            bg = QColor(15, 23, 42, max(alpha, 220))
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(QColor("#38bdf8"), 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(rect, 8, 8)
        else:
            visible = self._get_visible_entries()
            has_content = len(visible) > 0 or self.in_chat_mode

            if alpha > 0 and has_content:
                painter.setBrush(QBrush(QColor(11, 15, 25, alpha)))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)

            show_border = (mode in ("border_only", "both")) and has_content
            if show_border:
                painter.setPen(QPen(QColor(56, 189, 248, 50), 1, Qt.PenStyle.SolidLine))
            else:
                painter.setPen(Qt.PenStyle.NoPen)

            painter.drawRoundedRect(rect, 6, 6)

    def toggle_lock(self):
        self.is_locked = not self.is_locked
        self.update_lock_state()

    def set_locked(self, locked: bool):
        if self.is_locked != locked:
            self.is_locked = locked
            self.update_lock_state()

    def update_lock_state(self, initial: bool = False):
        self.update_style()
        hwnd = int(self.winId())

        hotkey = self.cfg.get("hotkey_toggle_lock", "F9")
        if hasattr(self, 'title_label'):
            self.title_label.setText(tr("overlay.header_title", hotkey=hotkey, lock_text=tr("overlay.lock") if not self.is_locked else tr("overlay.unlock")))
        if hasattr(self, 'btn_lock'):
            self.btn_lock.setText(tr("overlay.lock") if not self.is_locked else tr("overlay.unlock"))

        if self.is_locked:
            # Clickable only while chat input mode is open
            clickthrough = not self.in_chat_mode
            set_click_through(hwnd, clickthrough)
            keep_on_top(hwnd)
            self.save_geometry()
        else:
            set_click_through(hwnd, False)
            keep_on_top(hwnd)

        self.update()

    # ──────────────────────── Chat messages ─────────────────────────

    def add_message(self, time_str: str, sender: str, original: str,
                    translated: str, src_lang: str, msg_type: str):
        entry = ChatEntry(
            time_str=time_str,
            sender=sender,
            original=original,
            translated=translated,
            src_lang=src_lang,
            msg_type=msg_type,
            created_time=time.time()
        )
        self._entries.append(entry)

        max_msgs = self.cfg.get("max_messages", 20)
        if len(self._entries) > max_msgs:
            self._entries = self._entries[-max_msgs:]

        self._refresh_rendered_chat()

    def _get_visible_entries(self) -> List[ChatEntry]:
        fade_timeout = self.cfg.get("message_fade_timeout", 10)
        now = time.time()

        if (not self.is_locked) or self.in_chat_mode or (fade_timeout <= 0):
            return self._entries

        return [e for e in self._entries if (now - e.created_time) < fade_timeout]

    def _refresh_rendered_chat(self):
        visible_entries = self._get_visible_entries()
        if not visible_entries:
            if self.chat_view.toPlainText():
                self.chat_view.clear()
                self.update()
            return

        target_lang = self.cfg.get("target_language", "uk")
        show_orig = self.cfg.get("show_original", True)
        font_size = self.cfg.get("font_size", 22)
        font_bold = self.cfg.get("font_bold", False)
        text_outline = self.cfg.get("text_outline", True)
        own_nick = self.cfg.get("own_nickname", "").lower()
        squad_nicks = parse_nick_list(self.cfg.get("squad_nicknames", []))
        weight_css = "font-weight: 700;" if font_bold else "font-weight: 400;"

        self.chat_view.outline_enabled = text_outline
        self.chat_view.font_size = font_size
        self.chat_view.font_bold = font_bold

        html_parts = []
        for e in visible_entries:
            # Colours: squadmates (and yourself) green, a colour given in the message wins, the rest blue
            orig_text, explicit_color = extract_text_color(e.original)
            trans_text, _ = extract_text_color(e.translated)
            is_squad = (
                (own_nick and e.sender.lower() == own_nick) or
                e.msg_type in ("squad", "team") or
                is_squad_member(e.sender, squad_nicks) or
                any(tag in e.sender.lower() for tag in (
                    "(squad)", "[squad]", "(team)", "[team]",
                    "(сквад)", "[сквад]", "(отряд)", "[отряд]",
                    "(загін)", "[загін]", "(команда)", "[команда]"
                ))
            )
            is_server = e.msg_type == "server" or any(
                k in e.sender.lower()
                for k in ("message of the day", "announcement", "welcome", "sunhouse", "admin", "server")
            )
            if is_squad and not explicit_color:
                color = SQUAD_COLOR
            else:
                color = pick_color(e.sender, squad_nicks, explicit_color, server=is_server)

            safe_sender = html.escape(e.sender)
            safe_orig = html.escape(orig_text)
            safe_trans = html.escape(trans_text)
            is_same = (safe_orig.strip() == safe_trans.strip()) or (e.src_lang == target_lang) or (e.src_lang in ("orig", "blacklist"))

            # In-game look: the whole line (date, nickname, text) shares one colour and one font
            stamp = html.escape(game_timestamp(e.time_str))
            body = safe_orig if is_same else safe_trans
            part = (
                f'<div style="margin-bottom:4px; font-family:{GAME_FONT_STACK};'
                f' font-size:{font_size}px; line-height:1.15; color:{color}; {weight_css}">'
                f'[{stamp}] {safe_sender}: {body}'
            )
            if not is_same and show_orig:
                part += (
                    f'<br><span style="color:#cbd5e1; font-size:{max(10, font_size - 4)}px; padding-left:10px;">'
                    f'↳ <i>{tr("overlay.original_prefix")} {safe_orig}</i></span>'
                )

            part += '</div>'
            html_parts.append(part)

        self.chat_view.setHtml("".join(html_parts))
        self.chat_view.verticalScrollBar().setValue(
            self.chat_view.verticalScrollBar().maximum()
        )
        self.chat_view.viewport().update()
        self.update()

    def clear_chat(self):
        self._entries.clear()
        self.chat_view.clear()
        self.update()

    # ──────────────────────── Key and mouse events ───────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self.in_chat_mode:
                self.set_in_chat_mode(False)
                event.accept()
                return
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.in_chat_mode:
                self._copy_translation()
                event.accept()
                return
        super().keyPressEvent(event)

    def eventFilter(self, source, event):
        """Intercept Enter and Escape directly in the input field."""
        if source is self.input_field and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._copy_translation()
                return True
            elif key == Qt.Key.Key_Escape:
                self.set_in_chat_mode(False)
                return True
        return super().eventFilter(source, event)

    def mousePressEvent(self, event):
        if not self.is_locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.is_locked and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if not self.is_locked:
            self.save_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.is_locked:
            self.save_geometry()

    def closeEvent(self, event):
        try:
            self._live_executor.shutdown(wait=False)
        except Exception:
            pass
        super().closeEvent(event)
