from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QPoint, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont

from core.config_manager import ConfigManager
from utils.win_api import set_click_through, keep_on_top


class StatusBadge(QWidget):
    """
    Компактний HUD-індикатор статусу оверлею в стилі NVIDIA GeForce Overlay.
    - Зелена капсула [● ON], коли оверлей чату увімкнений (F8).
    - Червона капсула [● OFF], коли оверлей чату прихований (F8).
    - Безпечне розташування, яке не накладається на інші оверлеї (NVIDIA, Steam, RTSS).
    - Можливість вільного перетягування мишкою в режимі налаштування (F9).
    - Наскрізний для кліків миші під час гри.
    """
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.is_on = self.cfg.get("overlay_enabled", True)
        self.is_locked = True
        self._drag_pos = QPoint()

        self.setFixedSize(86, 28)
        self.init_window_flags()
        self.apply_geometry()
        self.update_lock_state()

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def apply_geometry(self):
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None

        screen_w = screen_geo.width() if screen_geo else 1920
        screen_h = screen_geo.height() if screen_geo else 1080
        screen_x = screen_geo.x() if screen_geo else 0
        screen_y = screen_geo.y() if screen_geo else 0

        saved_x = self.cfg.get("status_badge_x", -1)
        saved_y = self.cfg.get("status_badge_y", -1)

        # Безпечна позиція за замовчуванням:
        # У верхній частині праворуч, але з відступом від кута (щоб не перекривати лічильник FPS гри та значок NVIDIA)
        default_x = screen_x + screen_w - self.width() - 140
        default_y = screen_y + 42

        if saved_x is None or saved_x < 0 or saved_y is None or saved_y < 0:
            x = default_x
            y = default_y
        else:
            x = saved_x
            y = saved_y

        # Захист від вильоту за межі екрана
        x = max(screen_x + 5, min(x, screen_x + screen_w - self.width() - 5))
        y = max(screen_y + 5, min(y, screen_y + screen_h - self.height() - 5))

        self.setGeometry(x, y, self.width(), self.height())

    def save_position(self):
        self.cfg.set("status_badge_x", self.x())
        self.cfg.set("status_badge_y", self.y())

    def set_status(self, is_on: bool):
        """Зміна стану індикатора (ON / OFF)."""
        self.is_on = is_on
        self.cfg.set("overlay_enabled", is_on)
        self.update()

    def set_locked(self, locked: bool):
        if self.is_locked != locked:
            self.is_locked = locked
            self.update_lock_state()

    def update_lock_state(self):
        hwnd = int(self.winId())
        if self.is_locked:
            set_click_through(hwnd, True)
            keep_on_top(hwnd)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.save_position()
        else:
            set_click_through(hwnd, False)
            keep_on_top(hwnd)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        radius = 13.0

        # Фон капсули (напівпрозоре темне скло)
        bg_color = QColor(15, 23, 42, 220)
        painter.setBrush(QBrush(bg_color))

        if not self.is_locked:
            # У режимі редагування (F9) - пунктирна рамка редагування
            painter.setPen(QPen(QColor("#38bdf8"), 1.8, Qt.PenStyle.DashLine))
        elif self.is_on:
            # Стан ON - неоновий смарагдовий контур
            painter.setPen(QPen(QColor(16, 185, 129, 210), 1.5, Qt.PenStyle.SolidLine))
        else:
            # Стан OFF - неоновий червоний контур
            painter.setPen(QPen(QColor(239, 68, 68, 220), 1.5, Qt.PenStyle.SolidLine))

        painter.drawRoundedRect(rect, radius, radius)

        # Малювання неонового світлодіода (LED dot)
        if self.is_on:
            dot_color = QColor("#10b981")
            text_color = QColor("#34d399")
            status_text = "ON"
        else:
            dot_color = QColor("#ef4444")
            text_color = QColor("#f87171")
            status_text = "OFF"

        # М'яке світіння навколо точки
        glow_color = QColor(dot_color)
        glow_color.setAlpha(60)
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(17, self.height() // 2), 6, 6)

        # Сама яскрава точка світлодіода
        painter.setBrush(QBrush(dot_color))
        painter.drawEllipse(QPoint(17, self.height() // 2), 4, 4)

        # Текст статусу (ON / OFF)
        painter.setPen(QPen(text_color))
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)

        # Центруємо напис поруч із точкою
        text_rect = QRectF(28.0, 0.0, self.width() - 32.0, float(self.height()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, status_text)

    # ──────────────── Перетягування мишкою у режимі F9 ────────────────
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
            self.save_position()
            event.accept()
