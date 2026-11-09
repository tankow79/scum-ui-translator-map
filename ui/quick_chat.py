from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QApplication, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QKeyEvent

from core.config_manager import ConfigManager
from core.translator import GoogleTranslatorEngine
from core.languages import ALL_LANGUAGES
from utils.win_api import force_foreground_window

class QuickChatDialog(QWidget):
    """
    Вікно швидкого введення та перекладу тексту для чату гри.
    Підтримує:
    - Перетягування мишкою у будь-яке зручне місце екрана із збереженням позиції.
    - Два красиві спадні списки вибору мов (З якої мови ➔ На яку мову) та кнопку швидкої зміни місцями (⇄).
    - Автоматичне копіювання перекладу в буфер при натисканні Enter.
    - Надійне закриття по Escape.
    """
    message_translated = pyqtSignal(str, str)  # (original, translated)

    def __init__(self, config_manager: ConfigManager, translator: GoogleTranslatorEngine, parent=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.translator = translator
        self._drag_pos = QPoint()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._do_live_translate)
        self._current_translation = ""

        self.init_window_flags()
        self.init_ui()

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(580, 205)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        self.card = QWidget(self)
        self.card.setStyleSheet("""
            QWidget#quick_card {
                background-color: rgba(18, 22, 30, 0.96);
                border: 2px solid #00d2ff;
                border-radius: 8px;
            }
            QLabel {
                color: #e0e0e0;
                font-family: 'Segoe UI', sans-serif;
            }
            QLineEdit {
                background-color: #242a38;
                border: 1px solid #3e4c66;
                border-radius: 5px;
                color: white;
                font-size: 14px;
                padding: 7px 10px;
                selection-background-color: #007acc;
            }
            QLineEdit:focus {
                border: 1px solid #00d2ff;
            }
            QComboBox {
                background-color: #242a38;
                border: 1px solid #3e4c66;
                border-radius: 4px;
                color: #00d2ff;
                font-size: 11px;
                font-weight: bold;
                padding: 3px 6px;
                min-width: 130px;
            }
            QComboBox:hover {
                border-color: #00d2ff;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1e27;
                color: white;
                border: 1px solid #00d2ff;
                selection-background-color: #0284c7;
                selection-color: white;
                padding: 4px;
            }
            QScrollBar:vertical {
                background: rgba(0,0,0,0.3);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 210, 255, 0.5);
                border-radius: 3px;
                min-height: 20px;
            }
            QPushButton {
                background-color: #0284c7;
                border: none;
                border-radius: 4px;
                color: white;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #039be5;
            }
        """)
        self.card.setObjectName("quick_card")

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        # 1. Верхня панель (Заголовок, вибір двох мов, кнопка swap, закрити)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self.lbl_title = QLabel("💬 Переклад у чат")
        self.lbl_title.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 12px;")
        top_bar.addWidget(self.lbl_title)

        top_bar.addStretch()

        self.combo_src = QComboBox()
        for name, code in ALL_LANGUAGES:
            self.combo_src.addItem(name, code)
        self.combo_src.currentIndexChanged.connect(self._on_languages_changed)
        top_bar.addWidget(self.combo_src)

        self.btn_swap = QPushButton("⇄")
        self.btn_swap.setFixedSize(26, 24)
        self.btn_swap.setToolTip("Поміняти мови місцями")
        self.btn_swap.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #0284c7;
                border-color: #00d2ff;
            }
        """)
        self.btn_swap.clicked.connect(self.swap_languages)
        top_bar.addWidget(self.btn_swap)

        self.combo_tgt = QComboBox()
        for name, code in ALL_LANGUAGES:
            self.combo_tgt.addItem(name, code)
        self.combo_tgt.currentIndexChanged.connect(self._on_languages_changed)
        top_bar.addWidget(self.combo_tgt)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setStyleSheet("background-color: #4b5563; border-radius: 11px; font-weight: bold;")
        self.btn_close.clicked.connect(self.hide)
        top_bar.addWidget(self.btn_close)

        card_layout.addLayout(top_bar)

        # 2. Поле введення повідомлення
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Введіть текст... (Enter для копіювання перекладу)")
        self.input_field.textChanged.connect(self._on_text_changed)
        card_layout.addWidget(self.input_field)

        # 3. Поле відображення результату перекладу
        self.lbl_translation = QLabel("<i>Тут з'явиться переклад...</i>")
        self.lbl_translation.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 4px;
            color: #00ffcc;
            font-size: 14px;
            font-weight: 500;
            padding: 7px 10px;
        """)
        self.lbl_translation.setWordWrap(True)
        card_layout.addWidget(self.lbl_translation)

        # 4. Нижня панель дій та підказок
        bottom_bar = QHBoxLayout()
        self.lbl_status = QLabel("💡 <b>Enter</b> — скопіювати | <b>Esc</b> — закрити | <i>Перетягуйте вікно мишкою</i>")
        self.lbl_status.setStyleSheet("color: #8899aa; font-size: 10px;")
        bottom_bar.addWidget(self.lbl_status)

        bottom_bar.addStretch()

        self.btn_copy = QPushButton("📋 Скопіювати (Enter)")
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                border: 1px solid #22c55e;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #22c55e; }
        """)
        self.btn_copy.clicked.connect(self.copy_and_close)
        bottom_bar.addWidget(self.btn_copy)

        card_layout.addLayout(bottom_bar)
        main_layout.addWidget(self.card)

        self.sync_combos_from_config()

    def sync_combos_from_config(self):
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
        new_src = self.combo_src.currentData()
        new_tgt = self.combo_tgt.currentData()
        self.cfg.set("outgoing_my_lang", new_src)
        self.cfg.set("outgoing_target_lang", new_tgt)
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

    def show_and_focus(self):
        self.sync_combos_from_config()
        self.input_field.clear()
        self._current_translation = ""
        self.lbl_translation.setText("<i>Тут з'явиться переклад...</i>")
        self.lbl_status.setText("💡 <b>Enter</b> — скопіювати | <b>Esc</b> — закрити | <i>Перетягуйте вікно мишкою</i>")

        saved_x = self.cfg.get("quick_chat_x", -1)
        saved_y = self.cfg.get("quick_chat_y", -1)

        if saved_x >= 0 and saved_y >= 0:
            self.move(saved_x, saved_y)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.geometry()
                x = (screen_geo.width() - self.width()) // 2
                y = screen_geo.height() - self.height() - 120
                self.move(x, y)

        self.show()
        self.raise_()
        self.activateWindow()

        # Примусово передаємо фокус через Windows API
        hwnd = int(self.winId())
        force_foreground_window(hwnd)

        self.input_field.setFocus()

    def _on_text_changed(self, text: str):
        if not text.strip():
            self._current_translation = ""
            self.lbl_translation.setText("<i>Тут з'явиться переклад...</i>")
            return
        self.lbl_translation.setText("<i>Перекладаємо...</i>")
        self._debounce_timer.start(250)

    def _do_live_translate(self):
        text = self.input_field.text().strip()
        if not text:
            return

        my_lang = self.combo_src.currentData() or "uk"
        target_lang = self.combo_tgt.currentData() or "en"

        trans, _ = self.translator.translate_custom(text, target=target_lang, source=my_lang)
        self._current_translation = trans
        self.lbl_translation.setText(trans)

    def copy_and_close(self):
        orig_text = self.input_field.text().strip()
        if not orig_text:
            self.hide()
            return

        if not self._current_translation or self.lbl_translation.text() == "<i>Перекладаємо...</i>":
            my_lang = self.combo_src.currentData() or "uk"
            target_lang = self.combo_tgt.currentData() or "en"
            trans, _ = self.translator.translate_custom(orig_text, target=target_lang, source=my_lang)
            self._current_translation = trans

        clipboard = QApplication.clipboard()
        clipboard.setText(self._current_translation)

        self.lbl_status.setText("✅ <b>Скопійовано! Натисніть Ctrl+V у грі.</b>")
        self.message_translated.emit(orig_text, self._current_translation)

        QTimer.singleShot(350, self.hide)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.cfg.set("quick_chat_x", self.x())
        self.cfg.set("quick_chat_y", self.y())
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.copy_and_close()
            event.accept()
        else:
            super().keyPressEvent(event)
