"""The waypoint list as a drawer under the map: a handle bar that slides the list up and back down."""
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from core.config_manager import ConfigManager
from core.i18n import tr
from core.points_manager import PointsManager
from ui.points_window import PointsWindow

HANDLE_HEIGHT = 30
DRAWER_HEIGHT = 300
SLIDE_MS = 240


class PointsDrawer(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, config_manager: ConfigManager, points_manager: PointsManager, parent=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.points_mgr = points_manager
        self.open = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.handle = QPushButton()
        self.handle.setFixedHeight(HANDLE_HEIGHT)
        self.handle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.handle.setStyleSheet("""
            QPushButton {
                background-color: #111a2b; border: 1px solid #26344d; border-radius: 6px;
                color: #38bdf8; font-size: 12px; font-weight: 700; text-align: center; padding: 0 12px;
            }
            QPushButton:hover { background-color: #172033; border-color: #38bdf8; }
        """)
        self.handle.clicked.connect(self.toggle)
        layout.addWidget(self.handle)

        self.points = PointsWindow(config_manager, points_manager, self, embedded=True)
        self.points.setMaximumHeight(0)
        self.points.hide()
        layout.addWidget(self.points)

        self._anim = QPropertyAnimation(self.points, b"maximumHeight", self)
        self._anim.setDuration(SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._after_slide)

        for signal in (points_manager.point_added, points_manager.point_deleted, points_manager.points_cleared,
                       points_manager.points_reloaded):
            signal.connect(self._refresh_handle)
        self._refresh_handle()

    def _refresh_handle(self, *_):
        arrow = "\u25BC" if self.open else "\u25B2"
        title = tr("points.drawer_title")
        self.handle.setText(f"{arrow}  {title}  ({len(self.points_mgr.get_points())})")
        self.handle.setToolTip(tr("points.drawer_tip_close") if self.open else tr("points.drawer_tip_open"))

    def target_height(self) -> int:
        try:
            wanted = max(160, min(520, int(self.cfg.get("points_drawer_height", DRAWER_HEIGHT))))
        except (TypeError, ValueError):
            wanted = DRAWER_HEIGHT
        window = self.window()
        room = window.height() - 340 if window is not None and window is not self and window.height() > 0 else wanted
        return max(120, min(wanted, room))                  # never squash the map in a small window

    def set_open(self, value: bool, animate: bool = True):
        value = bool(value)
        if value == self.open and self._anim.state() != QAbstractAnimation.State.Running:
            return
        self.open = value
        self.cfg.set("points_drawer_open", value)
        self._refresh_handle()
        self._anim.stop()
        if value:
            self.points.show()
        if animate:
            self._anim.setStartValue(self.points.maximumHeight())
            self._anim.setEndValue(self.target_height() if value else 0)
            self._anim.start()
        else:
            self.points.setMaximumHeight(self.target_height() if value else 0)
            self._after_slide()
        self.toggled.emit(value)

    def _after_slide(self):
        if not self.open and self._anim.state() != QAbstractAnimation.State.Running:
            self.points.hide()                      # a collapsed drawer takes no space and no focus

    def toggle(self):
        self.set_open(not self.open)

    def restore_state(self):
        """Open or closed the way it was left (no animation at start-up)."""
        self.set_open(bool(self.cfg.get("points_drawer_open", False)), animate=False)
