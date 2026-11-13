from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.config_manager import ConfigManager
from ui.screen_utils import has_saved_position, screen_geometry_for
from utils.win_api import keep_on_top, set_click_through


class StatusBadge(QWidget):
    """
    Compact HUD overlay status indicator in the style of NVIDIA GeForce Overlay.
    - Green [● ON] capsule when the chat overlay is enabled (F8).
    - Red [● OFF] capsule when the chat overlay is hidden (F8).
    - Safe placement that does not overlap other overlays (NVIDIA, Steam, RTSS).
    - Freely draggable with the mouse in setup mode (F9).
    - Click-through for the mouse during gameplay.
    """
    _STATUS_TEXTS = ("ON", "OFF")

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.is_on = self.cfg.get("overlay_enabled", True)
        self.is_locked = True
        self._drag_pos = QPoint()

        self._font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self._fit_size()
        self.init_window_flags()
        self.apply_geometry()
        self.update_lock_state()

    def _fit_size(self):
        """Size the capsule from the widest status text so nothing is clipped."""
        fm = QFontMetrics(self._font)
        text_w = max(fm.horizontalAdvance(t) for t in self._STATUS_TEXTS)
        self.setFixedSize(max(86, 28 + text_w + 14), max(28, fm.height() + 10))

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def apply_geometry(self):
        saved_x = self.cfg.get("status_badge_x", -1)
        saved_y = self.cfg.get("status_badge_y", -1)
        screen_geo = screen_geometry_for(saved_x, saved_y, self.width(), self.height())
        screen_w, screen_h = screen_geo.width(), screen_geo.height()
        screen_x, screen_y = screen_geo.x(), screen_geo.y()

        # Safe default position:
        # Top right, inset from the corner (to avoid covering the game FPS counter and NVIDIA icon)
        default_x = screen_x + screen_w - self.width() - 140
        default_y = screen_y + 42

        if not has_saved_position(saved_x, saved_y):
            x = default_x
            y = default_y
        else:
            x = saved_x
            y = saved_y

        # Keep the badge within screen bounds
        x = max(screen_x + 5, min(x, screen_x + screen_w - self.width() - 5))
        y = max(screen_y + 5, min(y, screen_y + screen_h - self.height() - 5))

        self.setGeometry(x, y, self.width(), self.height())

    def save_position(self):
        self.cfg.set("status_badge_x", self.x())
        self.cfg.set("status_badge_y", self.y())

    def set_status(self, is_on: bool):
        """Change the indicator state (ON / OFF)."""
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
        radius = self.height() / 2.0 - 1.0

        # Capsule background (translucent dark glass)
        bg_color = QColor(15, 23, 42, 220)
        painter.setBrush(QBrush(bg_color))

        if not self.is_locked:
            # In edit mode (F9): dashed edit border
            painter.setPen(QPen(QColor("#38bdf8"), 1.8, Qt.PenStyle.DashLine))
        elif self.is_on:
            # ON state: neon emerald outline
            painter.setPen(QPen(QColor(16, 185, 129, 210), 1.5, Qt.PenStyle.SolidLine))
        else:
            # OFF state: neon red outline
            painter.setPen(QPen(QColor(239, 68, 68, 220), 1.5, Qt.PenStyle.SolidLine))

        painter.drawRoundedRect(rect, radius, radius)

        # Draw the neon LED dot
        if self.is_on:
            dot_color = QColor("#10b981")
            text_color = QColor("#34d399")
            status_text = "ON"
        else:
            dot_color = QColor("#ef4444")
            text_color = QColor("#f87171")
            status_text = "OFF"

        # Soft glow around the dot
        glow_color = QColor(dot_color)
        glow_color.setAlpha(60)
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(17, self.height() // 2), 6, 6)

        # The bright LED dot itself
        painter.setBrush(QBrush(dot_color))
        painter.drawEllipse(QPoint(17, self.height() // 2), 4, 4)

        # Status text (ON / OFF)
        painter.setPen(QPen(text_color))
        painter.setFont(self._font)

        # Center the label next to the dot
        text_rect = QRectF(28.0, 0.0, self.width() - 28.0, float(self.height()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, status_text)

    # ──────────────── Mouse dragging in F9 mode ────────────────
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
