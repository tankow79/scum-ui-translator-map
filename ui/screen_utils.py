"""Where to put a window that was saved on some monitor (multi-monitor setups, monitors left of the primary one)."""
from typing import Optional

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QGuiApplication


def has_saved_position(x, y) -> bool:
    """-1/-1 means "never saved". Other negative numbers are real positions: a monitor left of the primary one."""
    return isinstance(x, (int, float)) and isinstance(y, (int, float)) and not (x == -1 and y == -1)


def screen_geometry_for(x: Optional[float], y: Optional[float], w: int = 0, h: int = 0) -> QRect:
    """Usable area of the monitor that holds the saved window; the primary monitor when none does (it was unplugged)
    or when nothing was saved yet."""
    screens = QGuiApplication.screens()
    if has_saved_position(x, y):
        center = QPoint(int(x + w // 2), int(y + h // 2))
        for screen in screens:
            if screen.geometry().contains(center):
                return screen.availableGeometry()
        best, best_area = None, 0
        rect = QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
        for screen in screens:
            inter = screen.geometry().intersected(rect)
            area = inter.width() * inter.height()
            if area > best_area:
                best, best_area = screen, area
        if best is not None:
            return best.availableGeometry()
    primary = QGuiApplication.primaryScreen()
    return primary.availableGeometry() if primary else QRect(0, 0, 1920, 1080)
