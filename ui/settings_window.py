import os
import webbrowser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QCheckBox, QComboBox, QFileDialog,
    QWidget, QTabWidget, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent

from core.config_manager import ConfigManager
from core.languages import ALL_LANGUAGES
from core.version import __version__, GITHUB_REPO_URL
from core.updater import UpdateChecker, UpdateInfo
from ui.update_dialog import UpdateDialog


class HotkeyButton(QPushButton):
    """
    Інтерактивна кнопка запису гарячої клавіші (F9, F8, T, Ctrl+T тощо).
    Надійно працює незалежно від активної мовної розкладки.
    """
    hotkey_changed = pyqtSignal(str)

    def __init__(self, current_hotkey: str = "F9", parent=None):
        super().__init__(parent)
        self.current_hotkey = current_hotkey
        self.is_recording = False
        self.setText(current_hotkey)
        self.setFixedWidth(140)
        self.setFixedHeight(30)
        self.update_style()
        self.clicked.connect(self.start_recording)

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
        self.setText("[ Натисніть клавішу... ]")
        self.update_style()
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent):
        if not self.is_recording:
            super().keyPressEvent(event)
            return

        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.is_recording = False
            self.setText(self.current_hotkey)
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
    settings_changed = pyqtSignal()

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.setWindowTitle("Налаштування перекладача SCUM Chat")
        self.setMinimumWidth(560)
        self.resize(580, 520)

        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                background-color: #1e293b;
                border-radius: 8px;
                top: -1px;
                padding: 12px;
            }
            QTabBar::tab {
                background-color: #0f172a;
                color: #94a3b8;
                border: 1px solid #334155;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 12px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #1e293b;
                color: #38bdf8;
                border-color: #334155;
            }
            QTabBar::tab:hover:!selected {
                color: #f1f5f9;
                background-color: #1a2234;
            }
            QLineEdit, QComboBox {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 5px;
                color: #f8fafc;
                padding: 5px 8px;
                font-size: 12px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #38bdf8;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #38bdf8;
                selection-background-color: #0284c7;
                selection-color: #ffffff;
                padding: 4px;
            }
            QCheckBox {
                color: #e2e8f0;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #0f172a;
            }
            QCheckBox::indicator:checked {
                background-color: #38bdf8;
                border-color: #38bdf8;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #0284c7;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #38bdf8;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #7dd3fc;
            }
        """)

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        self.tabs = QTabWidget(self)

        # ────────── ТАБ 1: Основні налаштування ──────────
        tab_general = QWidget()
        v_general = QVBoxLayout(tab_general)
        v_general.setContentsMargins(8, 12, 8, 12)
        v_general.setSpacing(12)

        # 1. Шлях до логів SCUM
        r_log = QHBoxLayout()
        lbl_log = QLabel("Файл логів (SCUM.log):")
        lbl_log.setFixedWidth(170)
        self.txt_log_path = QLineEdit()
        self.btn_browse = QPushButton("Огляд...")
        self.btn_browse.setFixedHeight(28)
        self.btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 5px;
                color: #38bdf8;
                font-weight: 600;
                padding: 4px 12px;
            }
            QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
        """)
        self.btn_browse.clicked.connect(self.browse_log_file)
        r_log.addWidget(lbl_log)
        r_log.addWidget(self.txt_log_path)
        r_log.addWidget(self.btn_browse)
        v_general.addLayout(r_log)

        # 2. Мова чату
        r_lang = QHBoxLayout()
        lbl_lang = QLabel("Мова перекладу чату:")
        lbl_lang.setFixedWidth(170)
        self.combo_in_lang = QComboBox()
        self.combo_in_lang.setMaxVisibleItems(20)
        for name, code in ALL_LANGUAGES:
            self.combo_in_lang.addItem(name, code)
        r_lang.addWidget(lbl_lang)
        r_lang.addWidget(self.combo_in_lang)
        v_general.addLayout(r_lang)

        # 3. Нікнейм гравця
        r_nick = QHBoxLayout()
        lbl_nick = QLabel("Ваш ігровий нікнейм:")
        lbl_nick.setFixedWidth(170)
        self.txt_nickname = QLineEdit()
        self.txt_nickname.setPlaceholderText("Survivor")
        r_nick.addWidget(lbl_nick)
        r_nick.addWidget(self.txt_nickname)
        v_general.addLayout(r_nick)

        # 4. Чорний список нікнеймів
        r_bl = QHBoxLayout()
        lbl_bl = QLabel("Чорний список гравців:")
        lbl_bl.setFixedWidth(170)
        self.txt_blacklist = QLineEdit()
        self.txt_blacklist.setPlaceholderText("Нікнейми через кому: BadPlayer, Spammer1, TrollBot")
        self.txt_blacklist.setToolTip("Повідомлення від цих гравців не перекладаються, а відображаються мовою оригіналу")
        r_bl.addWidget(lbl_bl)
        r_bl.addWidget(self.txt_blacklist)
        v_general.addLayout(r_bl)

        lbl_bl_hint = QLabel("💡 <i>Повідомлення від гравців із чорного списку зберігатимуть мову оригіналу без перекладу.</i>")
        lbl_bl_hint.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 175px;")
        v_general.addWidget(lbl_bl_hint)

        # Розділювач
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet("border: none; border-top: 1px solid #334155;")
        v_general.addWidget(line1)

        # 4. Чекбокси
        self.chk_show_orig = QCheckBox("Показувати оригінал тексту під перекладом")
        v_general.addWidget(self.chk_show_orig)

        self.chk_ignore_own = QCheckBox("Не перекладати власні повідомлення (свій нікнейм)")
        v_general.addWidget(self.chk_ignore_own)

        v_general.addStretch()
        self.tabs.addTab(tab_general, "🎮 SCUM та Чат")

        # ────────── ТАБ 2: Вигляд та HUD ──────────
        tab_hud = QWidget()
        v_hud = QVBoxLayout(tab_hud)
        v_hud.setContentsMargins(8, 12, 8, 12)
        v_hud.setSpacing(10)

        # 1. Стиль рамки та скролбару
        r_mode = QHBoxLayout()
        lbl_mode = QLabel("Стиль рамки / скролу:")
        lbl_mode.setFixedWidth(170)
        self.combo_display_mode = QComboBox()
        self.combo_display_mode.addItem("Без рамки і без скролбару", "none")
        self.combo_display_mode.addItem("Тільки рамка", "border_only")
        self.combo_display_mode.addItem("Тільки скролбар", "scrollbar_only")
        self.combo_display_mode.addItem("Рамка та скролбар", "both")
        r_mode.addWidget(lbl_mode)
        r_mode.addWidget(self.combo_display_mode)
        v_hud.addLayout(r_mode)

        # Спільний стиль для інформаційних бейджів значень
        badge_style = """
            QLabel {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #38bdf8;
                font-weight: 600;
                font-size: 11px;
                padding: 3px;
            }
        """

        # 2. Час показу (Fade)
        r_fade = QHBoxLayout()
        lbl_fade = QLabel("Час показу повідомлення:")
        lbl_fade.setFixedWidth(170)
        self.slider_fade = QSlider(Qt.Orientation.Horizontal)
        self.slider_fade.setRange(0, 60)
        self.badge_fade = QLabel("10 сек")
        self.badge_fade.setFixedWidth(90)
        self.badge_fade.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_fade.setStyleSheet(badge_style)
        self.slider_fade.valueChanged.connect(self._on_fade_slider_changed)
        r_fade.addWidget(lbl_fade)
        r_fade.addWidget(self.slider_fade)
        r_fade.addWidget(self.badge_fade)
        v_hud.addLayout(r_fade)

        # 3. Прозорість фону
        r_op = QHBoxLayout()
        lbl_op = QLabel("Прозорість фону:")
        lbl_op.setFixedWidth(170)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.badge_opacity = QLabel("50%")
        self.badge_opacity.setFixedWidth(90)
        self.badge_opacity.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_opacity.setStyleSheet(badge_style)
        self.slider_opacity.valueChanged.connect(lambda v: self.badge_opacity.setText(f"{v}%"))
        r_op.addWidget(lbl_op)
        r_op.addWidget(self.slider_opacity)
        r_op.addWidget(self.badge_opacity)
        v_hud.addLayout(r_op)

        # 4. Розмір шрифту
        r_font = QHBoxLayout()
        lbl_font = QLabel("Розмір шрифту:")
        lbl_font.setFixedWidth(170)
        self.slider_font = QSlider(Qt.Orientation.Horizontal)
        self.slider_font.setRange(10, 24)
        self.badge_font = QLabel("13 px")
        self.badge_font.setFixedWidth(90)
        self.badge_font.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_font.setStyleSheet(badge_style)
        self.slider_font.valueChanged.connect(lambda v: self.badge_font.setText(f"{v} px"))
        r_font.addWidget(lbl_font)
        r_font.addWidget(self.slider_font)
        r_font.addWidget(self.badge_font)
        v_hud.addLayout(r_font)

        # 5. Кількість рядків
        r_msgs = QHBoxLayout()
        lbl_msgs = QLabel("Історія повідомлень:")
        lbl_msgs.setFixedWidth(170)
        self.slider_msgs = QSlider(Qt.Orientation.Horizontal)
        self.slider_msgs.setRange(5, 40)
        self.badge_msgs = QLabel("20 рядків")
        self.badge_msgs.setFixedWidth(90)
        self.badge_msgs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_msgs.setStyleSheet(badge_style)
        self.slider_msgs.valueChanged.connect(lambda v: self.badge_msgs.setText(f"{v} рядків"))
        r_msgs.addWidget(lbl_msgs)
        r_msgs.addWidget(self.slider_msgs)
        r_msgs.addWidget(self.badge_msgs)
        v_hud.addLayout(r_msgs)

        # 6. Жирний шрифт
        self.chk_font_bold = QCheckBox("Жирний шрифт для перекладеного тексту (Bold)")
        v_hud.addWidget(self.chk_font_bold)

        # 7. Чорна обводка тексту
        self.chk_text_outline = QCheckBox("Чорна обводка тексту (Text Outline) — для чіткості на будь-якому фоні")
        v_hud.addWidget(self.chk_text_outline)

        v_hud.addStretch()
        self.tabs.addTab(tab_hud, "🎨 Вигляд та HUD")

        # ────────── ТАБ 3: Гарячі клавіші ──────────
        tab_keys = QWidget()
        v_keys = QVBoxLayout(tab_keys)
        v_keys.setContentsMargins(8, 14, 8, 14)
        v_keys.setSpacing(12)

        # Клавіша чату
        r_k_chat = QHBoxLayout()
        lbl_k_chat = QLabel("💬 Відкриття чату SCUM:")
        lbl_k_chat.setFixedWidth(200)
        self.btn_k_chat = HotkeyButton(self.cfg.get("hotkey_quick_chat", "T"))
        r_k_chat.addWidget(lbl_k_chat)
        r_k_chat.addWidget(self.btn_k_chat)
        r_k_chat.addStretch()
        v_keys.addLayout(r_k_chat)

        # Блокування F9
        r_k_lock = QHBoxLayout()
        lbl_k_lock = QLabel("🔒 Налаштування положення (F9):")
        lbl_k_lock.setFixedWidth(200)
        self.btn_k_lock = HotkeyButton(self.cfg.get("hotkey_toggle_lock", "F9"))
        r_k_lock.addWidget(lbl_k_lock)
        r_k_lock.addWidget(self.btn_k_lock)
        r_k_lock.addStretch()
        v_keys.addLayout(r_k_lock)

        # Видимість F8
        r_k_vis = QHBoxLayout()
        lbl_k_vis = QLabel("👁 Показати / Сховати (F8):")
        lbl_k_vis.setFixedWidth(200)
        self.btn_k_vis = HotkeyButton(self.cfg.get("hotkey_toggle_visibility", "F8"))
        r_k_vis.addWidget(lbl_k_vis)
        r_k_vis.addWidget(self.btn_k_vis)
        r_k_vis.addStretch()
        v_keys.addLayout(r_k_vis)

        # Карта та список точок Ctrl+M
        r_k_map = QHBoxLayout()
        lbl_k_map = QLabel("🗺 Відкрити Карту та Точки:")
        lbl_k_map.setFixedWidth(200)
        self.btn_k_map = HotkeyButton(self.cfg.get("hotkey_toggle_map", "Ctrl+M"))
        r_k_map.addWidget(lbl_k_map)
        r_k_map.addWidget(self.btn_k_map)
        r_k_map.addStretch()
        v_keys.addLayout(r_k_map)

        # Підказка безпеки
        lbl_hint = QLabel(
            "💡 <b>Розумний захист:</b> оверлей та клавіша чату реагують тільки тоді, коли вікно гри SCUM відкрите й активне. Якщо гра згорнута або закрита — оверлей автоматично приховується і не перехоплює натискання клавіш."
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("""
            background-color: rgba(2, 132, 199, 0.15);
            border: 1px solid #0284c7;
            border-radius: 6px;
            color: #bae6fd;
            padding: 10px;
            font-size: 11px;
            line-height: 1.4;
        """)
        v_keys.addWidget(lbl_hint)

        v_keys.addStretch()
        self.tabs.addTab(tab_keys, "⌨ Гарячі клавіші")

        # ────────── ТАБ 4: Карта та Координати ──────────
        tab_map = QWidget()
        v_map = QVBoxLayout(tab_map)
        v_map.setContentsMargins(8, 12, 8, 12)
        v_map.setSpacing(12)

        # 1. Розділ: Інтерактивна Карта SCUM
        lbl_sec_map = QLabel("🗺 <b>Параметри інтерактивної карти</b>")
        lbl_sec_map.setStyleSheet("color: #38bdf8; font-size: 13px;")
        v_map.addWidget(lbl_sec_map)

        r_var = QHBoxLayout()
        lbl_var = QLabel("Стиль мапи:")
        lbl_var.setFixedWidth(170)
        self.combo_map_variant = QComboBox()
        self.combo_map_variant.addItem("🛰 Супутникова (Regular Satellite)", "regular")
        self.combo_map_variant.addItem("🎯 Тактична (Tactical Contour)", "tactical")
        r_var.addWidget(lbl_var)
        r_var.addWidget(self.combo_map_variant)
        v_map.addLayout(r_var)

        self.chk_map_grid = QCheckBox("Відображати основну сітку секторів (D0..Z4)")
        v_map.addWidget(self.chk_map_grid)

        self.chk_map_keypads = QCheckBox("Відображати детальну сітку кейпадів (k1..k9) при наближенні")
        v_map.addWidget(self.chk_map_keypads)

        self.chk_map_ontop = QCheckBox("Тримати вікна карти та списку поверх вікна гри (Always On Top)")
        v_map.addWidget(self.chk_map_ontop)

        # Розділювач
        line_map = QFrame()
        line_map.setFrameShape(QFrame.Shape.HLine)
        line_map.setStyleSheet("border: none; border-top: 1px solid #334155;")
        v_map.addWidget(line_map)

        # 2. Розділ: Точки та координати з чату
        lbl_sec_points = QLabel("📍 <b>Автоматичний збір координат із чату</b>")
        lbl_sec_points.setStyleSheet("color: #38bdf8; font-size: 13px;")
        v_map.addWidget(lbl_sec_points)

        self.chk_auto_focus = QCheckBox("Автоматично фокусувати карту на новій точці з чату")
        v_map.addWidget(self.chk_auto_focus)

        # Кнопка скидання геометрії вікон
        btn_reset_geo = QPushButton("🔄 Скинути положення та розміри вікна карти й списку")
        btn_reset_geo.setFixedHeight(28)
        btn_reset_geo.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 5px;
                color: #38bdf8;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 12px;
            }
            QPushButton:hover { background-color: #334155; border-color: #38bdf8; }
        """)
        btn_reset_geo.clicked.connect(self._reset_map_windows_geometry)
        v_map.addWidget(btn_reset_geo)

        v_map.addStretch()
        self.tabs.addTab(tab_map, "🗺 Карта та Координати")

        # ────────── ТАБ 5: Оновлення ──────────
        tab_update = QWidget()
        v_update = QVBoxLayout(tab_update)
        v_update.setContentsMargins(12, 16, 12, 16)
        v_update.setSpacing(14)

        lbl_up_title = QLabel("SCUM Chat Translator & Tactical Map")
        lbl_up_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        v_update.addWidget(lbl_up_title)

        lbl_up_ver = QLabel(f"Поточна версія: <span style='color: #22c55e; font-weight: bold;'>v{__version__}</span>")
        lbl_up_ver.setStyleSheet("font-size: 13px;")
        v_update.addWidget(lbl_up_ver)

        self.chk_auto_update = QCheckBox("Автоматично перевіряти оновлення при запуску програми")
        v_update.addWidget(self.chk_auto_update)

        up_shield = QFrame()
        up_shield.setStyleSheet("""
            QFrame {
                background-color: rgba(34, 197, 94, 0.1);
                border: 1px solid rgba(34, 197, 94, 0.3);
                border-radius: 6px;
                padding: 6px 10px;
            }
        """)
        h_up_shield = QHBoxLayout(up_shield)
        h_up_shield.setContentsMargins(6, 4, 6, 4)
        lbl_up_shield_text = QLabel(
            "🛡️ <b>Гарантія збереження даних:</b> Оновлення програми ніколи не перезаписує "
            "ваші налаштування (config.json) та збережені мітки карти (points.json)."
        )
        lbl_up_shield_text.setStyleSheet("color: #86efac; font-size: 11px;")
        lbl_up_shield_text.setWordWrap(True)
        h_up_shield.addWidget(lbl_up_shield_text)
        v_update.addWidget(up_shield)

        h_btn_check = QHBoxLayout()
        self.btn_check_update = QPushButton("🔍 Перевірити наявність оновлень")
        self.btn_check_update.setFixedHeight(34)
        self.btn_check_update.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: white;
                border: 1px solid #0ea5e9;
                border-radius: 6px;
                padding: 4px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #0369a1; }
            QPushButton:disabled { background-color: #334155; color: #64748b; }
        """)
        self.btn_check_update.clicked.connect(self._manual_check_updates)
        h_btn_check.addWidget(self.btn_check_update)

        btn_open_repo = QPushButton("🌐 GitHub Репозиторій")
        btn_open_repo.setFixedHeight(34)
        btn_open_repo.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #334155; color: white; }
        """)
        btn_open_repo.clicked.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        h_btn_check.addWidget(btn_open_repo)
        h_btn_check.addStretch()
        v_update.addLayout(h_btn_check)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setStyleSheet("font-size: 12px; color: #94a3b8;")
        v_update.addWidget(self.lbl_update_status)

        v_update.addStretch()
        self.tabs.addTab(tab_update, "🔄 Оновлення")

        main_layout.addWidget(self.tabs)

        # Нижні кнопки дій
        bottom_buttons = QHBoxLayout()
        bottom_buttons.addStretch()

        self.btn_save = QPushButton("💾 Зберегти налаштування")
        self.btn_save.setFixedHeight(32)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                border: 1px solid #10b981;
                border-radius: 6px;
                color: white;
                padding: 4px 18px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #10b981; }
        """)
        self.btn_save.clicked.connect(self.save_settings)
        bottom_buttons.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("Скасувати")
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 6px;
                color: #e2e8f0;
                padding: 4px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        bottom_buttons.addWidget(self.btn_cancel)

        main_layout.addLayout(bottom_buttons)

    def _on_fade_slider_changed(self, v: int):
        if v == 0:
            self.badge_fade.setText("Завжди видно")
        else:
            self.badge_fade.setText(f"{v} сек")

    def load_settings(self):
        self.txt_log_path.setText(self.cfg.get("log_file_path", r"%LOCALAPPDATA%\SCUM\Saved\Logs\SCUM.log"))

        in_lang = self.cfg.get("target_language", "uk")
        idx = self.combo_in_lang.findData(in_lang)
        if idx >= 0:
            self.combo_in_lang.setCurrentIndex(idx)

        self.chk_show_orig.setChecked(self.cfg.get("show_original", True))
        self.txt_nickname.setText(self.cfg.get("own_nickname", ""))
        blacklist = self.cfg.get("blacklist_nicknames", [])
        if isinstance(blacklist, list):
            self.txt_blacklist.setText(", ".join(blacklist))
        else:
            self.txt_blacklist.setText(str(blacklist))
        self.chk_ignore_own.setChecked(self.cfg.get("ignore_own_messages", False))
        self.chk_font_bold.setChecked(self.cfg.get("font_bold", False))
        self.chk_text_outline.setChecked(self.cfg.get("text_outline", True))

        mode = self.cfg.get("ui_display_mode", "none")
        idx_mode = self.combo_display_mode.findData(mode)
        if idx_mode >= 0:
            self.combo_display_mode.setCurrentIndex(idx_mode)

        fade_val = self.cfg.get("message_fade_timeout", 10)
        self.slider_fade.setValue(fade_val)
        self._on_fade_slider_changed(fade_val)

        opacity_val = int(self.cfg.get("bg_opacity", 0.5) * 100)
        self.slider_opacity.setValue(opacity_val)
        self.badge_opacity.setText(f"{opacity_val}%")

        font_val = self.cfg.get("font_size", 13)
        self.slider_font.setValue(font_val)
        self.badge_font.setText(f"{font_val} px")

        msgs_val = self.cfg.get("max_messages", 20)
        self.slider_msgs.setValue(msgs_val)
        self.badge_msgs.setText(f"{msgs_val} рядків")

        self.btn_k_lock.setText(self.cfg.get("hotkey_toggle_lock", "F9"))
        self.btn_k_lock.current_hotkey = self.cfg.get("hotkey_toggle_lock", "F9")

        self.btn_k_vis.setText(self.cfg.get("hotkey_toggle_visibility", "F8"))
        self.btn_k_vis.current_hotkey = self.cfg.get("hotkey_toggle_visibility", "F8")

        self.btn_k_chat.setText(self.cfg.get("hotkey_quick_chat", "T"))
        self.btn_k_chat.current_hotkey = self.cfg.get("hotkey_quick_chat", "T")

        self.btn_k_map.setText(self.cfg.get("hotkey_toggle_map", "Ctrl+M"))
        self.btn_k_map.current_hotkey = self.cfg.get("hotkey_toggle_map", "Ctrl+M")

        # Налаштування карти
        m_var = self.cfg.get("map_variant", "regular")
        idx_var = self.combo_map_variant.findData(m_var)
        if idx_var >= 0:
            self.combo_map_variant.setCurrentIndex(idx_var)

        self.chk_map_grid.setChecked(self.cfg.get("map_show_grid", True))
        self.chk_map_keypads.setChecked(self.cfg.get("map_show_keypads", True))
        self.chk_map_ontop.setChecked(self.cfg.get("map_on_top", True))
        self.chk_auto_focus.setChecked(self.cfg.get("auto_focus_new_point", True))
        self.chk_auto_update.setChecked(self.cfg.get("auto_check_updates", True))

    def _manual_check_updates(self):
        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setText("⏳ Перевірка оновлень на GitHub...")
        self.lbl_update_status.setStyleSheet("color: #38bdf8; font-size: 12px;")

        checker = UpdateChecker()

        def on_update_available(info):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText(f"🔥 Доступна нова версія: v{info.version}!")
            self.lbl_update_status.setStyleSheet("color: #22c55e; font-size: 12px; font-weight: bold;")
            dlg = UpdateDialog(info, self)
            dlg.exec()

        def on_no_update(curr_ver):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText(f"✅ У вас встановлено найновішу версію (v{curr_ver}).")
            self.lbl_update_status.setStyleSheet("color: #22c55e; font-size: 12px;")

        def on_error(err_msg):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText(f"❌ Помилка: {err_msg}")
            self.lbl_update_status.setStyleSheet("color: #ef4444; font-size: 12px;")

        checker.update_available.connect(on_update_available)
        checker.no_update_found.connect(on_no_update)
        checker.check_error.connect(on_error)
        # Зберігаємо посилання на чекер щоб його не зібрав GC
        self._active_checker = checker
        checker.check_for_updates_async()

    def _reset_map_windows_geometry(self):
        self.cfg.set("map_x", -1)
        self.cfg.set("map_y", -1)
        self.cfg.set("map_width", 960)
        self.cfg.set("map_height", 660)
        self.cfg.set("points_x", -1)
        self.cfg.set("points_y", -1)
        self.cfg.set("points_width", 960)
        self.cfg.set("points_height", 240)

    def browse_log_file(self):
        default_dir = os.path.expandvars(r"%LOCALAPPDATA%\SCUM\Saved\Logs")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Виберіть файл SCUM.log",
            default_dir if os.path.exists(default_dir) else "",
            "Log Files (*.log);;All Files (*)"
        )
        if file_path:
            self.txt_log_path.setText(file_path)

    def save_settings(self):
        self.cfg.set("log_file_path", self.txt_log_path.text().strip())
        self.cfg.set("target_language", self.combo_in_lang.currentData())
        self.cfg.set("show_original", self.chk_show_orig.isChecked())
        self.cfg.set("own_nickname", self.txt_nickname.text().strip())
        raw_bl = self.txt_blacklist.text().strip()
        bl_list = [n.strip() for n in raw_bl.split(",") if n.strip()]
        self.cfg.set("blacklist_nicknames", bl_list)
        self.cfg.set("ignore_own_messages", self.chk_ignore_own.isChecked())
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

        # Налаштування карти
        self.cfg.set("map_variant", self.combo_map_variant.currentData())
        self.cfg.set("map_show_grid", self.chk_map_grid.isChecked())
        self.cfg.set("map_show_keypads", self.chk_map_keypads.isChecked())
        self.cfg.set("map_on_top", self.chk_map_ontop.isChecked())
        self.cfg.set("auto_focus_new_point", self.chk_auto_focus.isChecked())
        self.cfg.set("auto_check_updates", self.chk_auto_update.isChecked())

        self.settings_changed.emit()
        self.accept()
