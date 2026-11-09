import os
from typing import Optional, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizeGrip, QApplication,
    QMenu, QColorDialog
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QTimer
from PyQt6.QtGui import QMouseEvent, QColor, QKeyEvent

from core.config_manager import ConfigManager
from core.coordinate_parser import (
    MapPoint, POINT_CATEGORIES, get_category_info, detect_category_from_name
)
from core.points_manager import PointsManager


class PointRowWidget(QFrame):
    """
    Рядок окремої збереженої точки:
    - Дата та час появи в чаті
    - Сектор та кейпад (напр. D3 k2)
    - Інлайн-поле редагування назви прямо в рядку з автозбереженням
    - Кнопка "🗺 На карті" для миттєвого показу точки
    - Кнопка "📋 Копіювати" для копіювання координат у буфер
    - Кнопка "🗑" для видалення точки
    """
    open_on_map_requested = pyqtSignal(object)  # MapPoint

    def __init__(self, point: MapPoint, points_manager: PointsManager, parent=None):
        super().__init__(parent)
        self.point = point
        self.mgr = points_manager

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            PointRowWidget {
                background-color: #111827;
                border: 1px solid #1f2937;
                border-radius: 6px;
            }
            PointRowWidget:hover {
                border-color: #38bdf8;
                background-color: #172033;
            }
        """)

        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # 1. Дата та час
        self.lbl_time = QLabel(f"🕒 {self.point.date_time}")
        self.lbl_time.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: 'Consolas', monospace; min-width: 105px;")
        layout.addWidget(self.lbl_time)

        # 2. Сектор та кейпад
        self.lbl_sector = QLabel(f"📍 {self.point.sector} ({self.point.keypad})")
        self.lbl_sector.setStyleSheet("""
            QLabel {
                background-color: #0369a1;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
                padding: 2px 6px;
                min-width: 75px;
            }
        """)
        self.lbl_sector.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_sector)

        # 3. Вибір типу / категорії мітки
        self.btn_category = QPushButton()
        self.btn_category.setFixedHeight(26)
        self.btn_category.setToolTip("Обрати тип мітки: Машина, База, Літак, Схрон тощо")
        self.btn_category.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #f1f5f9;
                font-size: 11px;
                font-weight: 600;
                padding: 3px 8px;
                min-width: 95px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38bdf8;
            }
        """)
        self._update_category_button_style()
        self.btn_category.clicked.connect(self._open_category_picker_menu)
        layout.addWidget(self.btn_category)

        # 4. Вибір кольору шпильки на карті
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(22, 22)
        self.btn_color.setToolTip("Змінити колір шпильки на карті")
        self._update_color_button_style()
        self.btn_color.clicked.connect(self._open_color_picker_menu)
        layout.addWidget(self.btn_color)

        # 5. Інлайн-редагування назви точки
        self.txt_name = QLineEdit(self.point.name)
        self.txt_name.setPlaceholderText("Назва точки...")
        self.txt_name.setToolTip("Клікніть, щоб змінити назву точки (зберігається автоматично)")
        self.txt_name.setStyleSheet("""
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #f8fafc;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 8px;
                min-width: 120px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
                background-color: #0f172a;
            }
        """)
        self.txt_name.editingFinished.connect(self._on_name_edited)
        layout.addWidget(self.txt_name, 2)

        # 6. Інлайн-редагування нікнеймів гравців (тільки для бази)
        self.txt_players = QLineEdit(getattr(self.point, "players", ""))
        self.txt_players.setPlaceholderText("👥 Гравці бази (через кому)...")
        self.txt_players.setToolTip("Нікнейми гравців, які живуть на цій базі (відображаються при наведенні на карту)")
        self.txt_players.setStyleSheet("""
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #818cf8;
                border-radius: 4px;
                color: #e0e7ff;
                font-size: 11px;
                padding: 4px 8px;
                min-width: 140px;
            }
            QLineEdit:focus {
                border: 1px solid #a5b4fc;
                background-color: #0f172a;
            }
        """)
        self.txt_players.editingFinished.connect(self._on_players_edited)
        is_base = (getattr(self.point, "category", "default") == "base")
        self.txt_players.setVisible(is_base)
        layout.addWidget(self.txt_players, 2)

        # 7. Координати (скорочений вигляд)
        coord_preview = f"X={self.point.x:.0f} Y={self.point.y:.0f}"
        self.lbl_coords = QLabel(coord_preview)
        self.lbl_coords.setStyleSheet("color: #64748b; font-size: 11px; font-family: 'Consolas', monospace; min-width: 120px;")
        self.lbl_coords.setToolTip(self.point.raw_coord)
        layout.addWidget(self.lbl_coords)

        # Спільний стиль кнопок дій
        btn_action_style = """
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #0284c7;
                border-color: #38bdf8;
                color: white;
            }
        """

        # 5. Кнопка "🗺 На карті"
        self.btn_map = QPushButton("🗺 На карті")
        self.btn_map.setStyleSheet(btn_action_style)
        self.btn_map.setToolTip("Відкрити та сфокусувати цю точку на карті")
        self.btn_map.clicked.connect(lambda: self.open_on_map_requested.emit(self.point))
        layout.addWidget(self.btn_map)

        # 6. Кнопка "📋 Копіювати"
        self.btn_copy = QPushButton("📋 Копіювати")
        self.btn_copy.setStyleSheet(btn_action_style)
        self.btn_copy.setToolTip("Скопіювати повні ігрові координати в буфер обміну")
        self.btn_copy.clicked.connect(self._copy_coordinates)
        layout.addWidget(self.btn_copy)

        # 7. Кнопка видалення "🗑"
        self.btn_del = QPushButton("🗑")
        self.btn_del.setFixedSize(26, 26)
        self.btn_del.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #94a3b8;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #ef4444;
                border-color: #f87171;
                color: white;
            }
        """)
        self.btn_del.setToolTip("Видалити цю точку")
        self.btn_del.clicked.connect(lambda: self.mgr.delete_point(self.point.id))
        layout.addWidget(self.btn_del)

    def _update_color_button_style(self):
        c = self.point.color if getattr(self.point, "color", None) else "#38bdf8"
        self.btn_color.setStyleSheet(f"""
            QPushButton {{
                background-color: {c};
                border: 2px solid #ffffff;
                border-radius: 11px;
            }}
            QPushButton:hover {{
                border: 2px solid #38bdf8;
            }}
        """)

    def _update_category_button_style(self):
        cur_cat = getattr(self.point, "category", "default")
        cat_info = get_category_info(cur_cat)
        emoji = cat_info["emoji"]
        name = cat_info["name"]
        self.btn_category.setText(f"{emoji} {name} ▾")

    def _open_category_picker_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                color: #f8fafc;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 16px 6px 10px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: white;
            }
        """)
        cur_cat = getattr(self.point, "category", "default")
        for cid, cdata in POINT_CATEGORIES.items():
            mark = "✓ " if cur_cat == cid else ""
            act = menu.addAction(f"{mark}{cdata['emoji']} {cdata['name']}")
            act.triggered.connect(lambda checked=False, c=cid: self._set_category(c))

        menu.exec(self.btn_category.mapToGlobal(QPoint(0, self.btn_category.height() + 2)))

    def _set_category(self, cid: str):
        self.mgr.update_point_category(self.point.id, cid)

    def _on_players_edited(self):
        new_players = self.txt_players.text().strip()
        if new_players != getattr(self.point, "players", ""):
            self.mgr.update_point_players(self.point.id, new_players)

    def update_from_point(self, point: MapPoint):
        self.point = point
        self._update_color_button_style()
        self._update_category_button_style()
        if self.txt_name.text() != point.name:
            self.txt_name.setText(point.name)
        if self.txt_players.text() != getattr(point, "players", ""):
            self.txt_players.setText(getattr(point, "players", ""))
        is_base = (getattr(point, "category", "default") == "base")
        self.txt_players.setVisible(is_base)

    def _open_color_picker_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                color: #f8fafc;
                padding: 4px;
            }
            QMenu::item {
                padding: 5px 18px 5px 10px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: white;
            }
        """)

        colors = [
            ("🔴 Червона шпилька", "#ef4444"),
            ("🔵 Блакитна шпилька", "#38bdf8"),
            ("🟢 Смарагдова шпилька", "#10b981"),
            ("🟡 Золота шпилька", "#f59e0b"),
            ("🟣 Фіолетова шпилька", "#a855f7"),
            ("🌸 Рожева шпилька", "#ec4899"),
            ("🟠 Помаранчева шпилька", "#f97316"),
            ("⚪ Світла шпилька", "#f8fafc"),
        ]

        for label, hex_code in colors:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, c=hex_code: self._set_color(c))

        menu.addSeparator()
        action_custom = menu.addAction("🎨 Обрати власний колір...")
        action_custom.triggered.connect(self._pick_custom_color)

        menu.exec(self.btn_color.mapToGlobal(QPoint(0, self.btn_color.height() + 2)))

    def _set_color(self, c: str):
        self.point.color = c
        self._update_color_button_style()
        self.mgr.update_point_color(self.point.id, c)

    def _pick_custom_color(self):
        initial = QColor(self.point.color if getattr(self.point, "color", None) else "#38bdf8")
        col = QColorDialog.getColor(initial, self, "Оберіть колір шпильки для карти")
        if col.isValid():
            self._set_color(col.name())

    def _on_name_edited(self):
        new_name = self.txt_name.text().strip()
        if not new_name:
            new_name = "None"
            self.txt_name.setText("None")
        if new_name != self.point.name:
            self.mgr.update_point_name(self.point.id, new_name)

    def _copy_coordinates(self):
        QApplication.clipboard().setText(self.point.raw_coord)
        self.btn_copy.setText("✅ Скопійовано!")
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                border: 1px solid #10b981;
                border-radius: 4px;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 10px;
            }
        """)
        QTimer.singleShot(1500, self._restore_copy_button)

    def _restore_copy_button(self):
        self.btn_copy.setText("📋 Копіювати")
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #0284c7;
                border-color: #38bdf8;
                color: white;
            }
        """)


class PointsWindow(QWidget):
    """
    Нижнє вікно списку збережених координат із чату гри SCUM:
    - Розташоване під картою
    - Список від нових до старих
    - Пошук / фільтрація точок
    - Перетягування та зміна розмірів
    """
    closed = pyqtSignal()
    point_focus_requested = pyqtSignal(object)  # MapPoint

    def __init__(self, config_manager: ConfigManager, points_manager: PointsManager):
        super().__init__()
        self.cfg = config_manager
        self.points_mgr = points_manager
        self._drag_pos = QPoint()
        self._row_widgets: Dict[str, PointRowWidget] = {}

        self.init_window_flags()
        self.init_ui()
        self.apply_config_geometry()
        self._connect_signals()
        self.refresh_list()

    def init_window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("map_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame#points_card {
                background-color: #0b0f19;
                border: 2px solid #38bdf8;
                border-radius: 10px;
            }
        """)
        self.container.setObjectName("points_card")

        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(8, 8, 8, 8)
        c_layout.setSpacing(6)

        # 1. Верхній бар
        self._build_top_bar(c_layout)

        # 2. Область прокрутки списку
        self.scroll_area = QScrollArea(self.container)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(15, 23, 42, 0.4);
                width: 6px;
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
        """)

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch()

        self.scroll_area.setWidget(self.list_container)
        c_layout.addWidget(self.scroll_area, 1)

        # 3. Нижній бар
        self._build_bottom_bar(c_layout)

        self.main_layout.addWidget(self.container)

    def _build_top_bar(self, layout: QVBoxLayout):
        top_bar = QWidget()
        top_bar.setFixedHeight(34)
        top_bar.setStyleSheet("background: transparent;")
        h = QHBoxLayout(top_bar)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(8)

        self.lbl_title = QLabel("📌 <b>Точки чату SCUM</b>")
        self.lbl_title.setStyleSheet("color: #38bdf8; font-size: 13px;")
        h.addWidget(self.lbl_title)

        self.lbl_count = QLabel("(0)")
        self.lbl_count.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")
        h.addWidget(self.lbl_count)

        h.addStretch()

        # Поле швидкого пошуку
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("🔍 Пошук за назвою або сектором...")
        self.txt_filter.setFixedWidth(240)
        self.txt_filter.setFixedHeight(26)
        self.txt_filter.setStyleSheet("""
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #ffffff;
                font-size: 11px;
                padding: 2px 8px;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
            }
        """)
        self.txt_filter.textChanged.connect(self._apply_filter)
        h.addWidget(self.txt_filter)

        # Кнопка очищення
        btn_clear = QPushButton("🧹 Очистити")
        btn_clear.setFixedHeight(26)
        btn_clear.setToolTip("Видалити всі збережені точки")
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38bdf8;
            }
        """)
        btn_clear.clicked.connect(self.points_mgr.clear_all)
        h.addWidget(btn_clear)

        # Закрити
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #ef4444;
                border-radius: 4px;
                color: #f87171;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #ef4444;
                color: white;
            }
        """)
        btn_close.clicked.connect(self.close)
        h.addWidget(btn_close)

        layout.addWidget(top_bar)

    def _build_bottom_bar(self, layout: QVBoxLayout):
        bottom_bar = QWidget()
        bottom_bar.setFixedHeight(20)
        bottom_bar.setStyleSheet("background: transparent;")
        h = QHBoxLayout(bottom_bar)
        h.setContentsMargins(4, 0, 0, 0)
        h.setSpacing(6)

        lbl_hint = QLabel("💡 <i>Назву можна змінювати прямо в рядку. Координати зберігаються автоматично.</i>")
        lbl_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        h.addWidget(lbl_hint)

        h.addStretch()

        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background: transparent; color: #38bdf8;")
        h.addWidget(grip)

        layout.addWidget(bottom_bar)

    def _connect_signals(self):
        self.points_mgr.point_added.connect(self._on_point_added)
        self.points_mgr.point_updated.connect(self._on_point_updated)
        self.points_mgr.point_deleted.connect(self._on_point_deleted)
        self.points_mgr.points_cleared.connect(self._on_points_cleared)

    def refresh_list(self):
        # Очищуємо існуючі віджети
        for row in self._row_widgets.values():
            row.deleteLater()
        self._row_widgets.clear()

        points = self.points_mgr.get_points()
        self.lbl_count.setText(f"({len(points)})")

        for pt in points:
            self._create_row_widget(pt, prepend=False)

    def _create_row_widget(self, point: MapPoint, prepend: bool = False) -> PointRowWidget:
        row = PointRowWidget(point, self.points_mgr, self.list_container)
        row.open_on_map_requested.connect(self.point_focus_requested.emit)
        self._row_widgets[point.id] = row

        if prepend:
            self.list_layout.insertWidget(0, row)
        else:
            # Перед stretch
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

        self._check_row_visibility(row)
        return row

    def _on_point_added(self, point: MapPoint):
        self.lbl_count.setText(f"({len(self.points_mgr.get_points())})")
        self._create_row_widget(point, prepend=True)

    def _on_point_updated(self, point: MapPoint):
        row = self._row_widgets.get(point.id)
        if row:
            row.update_from_point(point)
            self._check_row_visibility(row)

    def _on_point_deleted(self, point_id: str):
        if point_id in self._row_widgets:
            widget = self._row_widgets.pop(point_id)
            widget.deleteLater()
        self.lbl_count.setText(f"({len(self.points_mgr.get_points())})")

    def _on_points_cleared(self):
        for row in self._row_widgets.values():
            row.deleteLater()
        self._row_widgets.clear()
        self.lbl_count.setText("(0)")

    def _apply_filter(self, query: str):
        query = query.strip().lower()
        for row in self._row_widgets.values():
            pt = row.point
            cur_cat = getattr(pt, "category", "default")
            cat_name = get_category_info(cur_cat)["name"].lower()
            players = getattr(pt, "players", "").lower()
            visible = (
                not query or
                query in pt.name.lower() or
                query in pt.sector.lower() or
                query in pt.keypad.lower() or
                query in cat_name or
                query in players or
                query in pt.raw_coord.lower()
            )
            row.setVisible(visible)

    def _check_row_visibility(self, row: PointRowWidget):
        query = self.txt_filter.text().strip().lower()
        if not query:
            row.show()
            return
        pt = row.point
        cur_cat = getattr(pt, "category", "default")
        cat_name = get_category_info(cur_cat)["name"].lower()
        players = getattr(pt, "players", "").lower()
        visible = (
            query in pt.name.lower() or
            query in pt.sector.lower() or
            query in pt.keypad.lower() or
            query in cat_name or
            query in players or
            query in pt.raw_coord.lower()
        )
        row.setVisible(visible)

    # ──────────────────────── Переміщення вікна ────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() <= 40:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self.save_geometry()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = QPoint()
        self.save_geometry()
        super().mouseReleaseEvent(event)

    def apply_config_geometry(self):
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None
        sw = screen_geo.width() if screen_geo else 1920
        sh = screen_geo.height() if screen_geo else 1080
        sx = screen_geo.x() if screen_geo else 0
        sy = screen_geo.y() if screen_geo else 0

        w = self.cfg.get("points_width", 1000)
        h = self.cfg.get("points_height", 240)
        saved_x = self.cfg.get("points_x", -1)
        saved_y = self.cfg.get("points_y", -1)

        w = max(500, min(w, sw - 40))
        h = max(160, min(h, sh - 40))

        if saved_x is None or saved_x < 0 or saved_y is None or saved_y < 0:
            # Розташовуємо по центру знизу монітора
            x = sx + (sw - w) // 2
            # Під картою
            map_y = self.cfg.get("map_y", -1)
            map_h = self.cfg.get("map_height", 660)
            if map_y is not None and map_y > 0:
                y = min(map_y + map_h + 8, sy + sh - h - 10)
            else:
                y = sy + sh - h - 20
        else:
            x = max(sx, min(saved_x, sx + sw - w))
            y = max(sy, min(saved_y, sy + sh - h))

        self.setGeometry(x, y, w, h)

    def save_geometry(self):
        self.cfg.set("points_x", self.x())
        self.cfg.set("points_y", self.y())
        self.cfg.set("points_width", self.width())
        self.cfg.set("points_height", self.height())

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            from utils.win_api import restore_game_focus
            restore_game_focus()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.save_geometry()
        self.closed.emit()
        super().closeEvent(event)
