import logging
import math
import os
import sys
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.coordinate_parser import (
    POINT_CATEGORIES,
    MapPoint,
    convert_norm_to_scum,
    get_category_info,
    get_category_label,
    get_sector_info,
)
from core.i18n import tr
from core.players import steam_profile_url
from core.points_manager import PointsManager
from ui.color_picker import open_safe_color_dialog

log = logging.getLogger("scum.map")


class _ElidedLabel(QLabel):
    """Single-line label that elides its text to the available width (full text in the tooltip)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._full = ""
        self.setText(text)

    def setText(self, text: str):  # noqa: N802
        self._full = text.replace("<b>", "").replace("</b>", "")
        self.setToolTip(self._full)
        self._apply_elide()

    def _apply_elide(self):
        m = self.contentsMargins()
        avail = max(20, self.width() - m.left() - m.right() - 18)
        QLabel.setText(self, QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, avail))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def minimumSizeHint(self):  # noqa: N802
        sh = super().minimumSizeHint()
        sh.setWidth(40)
        return sh


_CARD_QSS = (
    "QFrame#markerCard, QFrame#markerFlyout { background-color: #0f172a; border: 1px solid #38bdf8; border-radius: 6px; }"
    "QLabel { color: #e2e8f0; font-size: 12px; background: transparent; border: none; }"
    "QToolButton { color: #e2e8f0; font-size: 12px; background: transparent; border: none; padding: 1px 2px; }"
    "QToolButton:hover { background-color: #1e293b; border-radius: 4px; }"
    "QToolButton#steamLink { color: #38bdf8; font-size: 12px; padding: 1px 0px; }"
)


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") if ts else "—"


class _MarkerCard(QFrame):
    """Hover card for a base. Child widget of the map (not a tooltip) so it can be clicked and the
    game never loses focus.

    Every linked player gets a 🔗 button that opens the Steam profile. A player who renamed shows
    the nickname as a drop-down (▾); clicking it opens a small flyout to the right with the date of
    each change and the old nickname.
    """
    entered = pyqtSignal()
    left = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("markerCard")
        self.setStyleSheet(_CARD_QSS)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(10, 8, 10, 8)
        self._lay.setSpacing(2)
        self._flyout = QFrame(parent)
        self._flyout.setObjectName("markerFlyout")
        self._flyout.setStyleSheet(_CARD_QSS)
        self._fly_lay = QVBoxLayout(self._flyout)
        self._fly_lay.setContentsMargins(10, 8, 10, 8)
        self._fly_lay.setSpacing(2)
        self._flyout.hide()
        self._flyout.installEventFilter(self)
        self._open_row: Optional[QWidget] = None
        self.hide()

    def is_under_mouse(self) -> bool:
        return self.underMouse() or self._flyout.underMouse()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._flyout:
            if event.type() == QEvent.Type.Enter:
                self.entered.emit()
            elif event.type() == QEvent.Type.Leave:
                self.left.emit()
        return super().eventFilter(obj, event)

    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_content(self, head: list, players: list, foot: list):
        """players: [(label, steam_id or None, [(old_nick, changed_at), ...])]"""
        self._flyout.hide()
        self._clear(self._lay)
        for text in head:
            self._lay.addWidget(self._label(text))
        if players:
            self._lay.addWidget(self._label(tr("map_window.card_players")))
        for label, sid, history in players:
            self._lay.addWidget(self._player_row(label, sid, history))
        for text in foot:
            self._lay.addWidget(self._label(text))
        self.adjustSize()

    @staticmethod
    def _label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        return lbl

    def _player_row(self, label: str, sid: Optional[str], history: list) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 0, 0, 0)
        hl.setSpacing(0)
        if sid:
            link = QToolButton()
            link.setObjectName("steamLink")
            link.setText("🔗")
            link.setFixedWidth(18)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip(tr("map_window.open_steam"))
            link.clicked.connect(lambda _=False, s=sid: QDesktopServices.openUrl(QUrl(steam_profile_url(s))))
            hl.addWidget(link)
        else:
            spacer = QWidget()
            spacer.setFixedWidth(18)
            hl.addWidget(spacer)
        if history:
            name = QToolButton()
            name.setText(f"{label} ▾")
            name.setCursor(Qt.CursorShape.PointingHandCursor)
            name.setToolTip(tr("map_window.old_nicks"))
            name.clicked.connect(lambda _=False, r=row, h=history: self._toggle_flyout(r, h))
            hl.addWidget(name)
        else:
            plain = self._label(label)
            plain.setContentsMargins(2, 0, 2, 0)  # same inset as the drop-down button text
            hl.addWidget(plain)
        hl.addStretch(1)
        return row

    def _toggle_flyout(self, row: QWidget, history: list):
        if self._flyout.isVisible() and self._open_row is row:
            self._flyout.hide()
            return
        self._clear(self._fly_lay)
        self._fly_lay.addWidget(self._label(tr("map_window.old_nicks")))
        for old_nick, changed_at in history:
            self._fly_lay.addWidget(self._label(f"{_fmt_date(changed_at)}  —  {old_nick}"))
        self._flyout.adjustSize()
        parent = self.parentWidget()
        top = row.mapTo(parent, QPoint(0, 0)).y()
        fw = self._flyout.width()
        x = self.x() + self.width() + 4
        y = max(2, min(top, parent.height() - self._flyout.height() - 2))
        if x + fw > parent.width():
            if self.x() - fw - 4 >= 2:
                x = self.x() - fw - 4
            else:  # no room at either side: open below the card so no name is covered
                x = max(2, min(self.x(), parent.width() - fw - 2))
                y = max(2, min(self.y() + self.height() + 4, parent.height() - self._flyout.height() - 2))
        self._flyout.move(x, y)
        self._flyout.raise_()
        self._flyout.show()
        self._open_row = row

    def hideEvent(self, event):  # noqa: N802
        self._flyout.hide()
        super().hideEvent(event)

    def enterEvent(self, event):  # noqa: N802
        self.entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.left.emit()
        super().leaveEvent(event)


class MapCanvasWidget(QWidget):
    """
    Interactive SCUM Island map canvas:
    - Smooth panning (mouse drag)
    - Smooth zoom on mouse wheel (focused under the cursor)
    - Satellite and tactical map variants
    - Sector grid (D0..D4, C0..C4, B0..B4, A0..A4, Z0..Z4) and keypads (k1..k9) rendering
    - Saved chat markers (active one highlighted)
    - Hover tooltips and live cursor coordinates
    """
    cursor_coords_changed = pyqtSignal(float, float, str, str)  # x, y, sector, keypad
    point_clicked = pyqtSignal(object)  # MapPoint

    def __init__(self, config_manager: ConfigManager, points_manager: PointsManager, parent=None):
        super().__init__(parent)
        self.cfg = config_manager
        self.points_mgr = points_manager

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Map
        self.current_variant = self.cfg.get("map_variant", "regular")
        self.map_images = {}
        self._load_base_maps()

        # View transform
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._dragging = False
        self._drag_start = QPoint()

        # Display settings
        self.show_grid = self.cfg.get("map_show_grid", True)
        self.show_keypads = self.cfg.get("map_show_keypads", True)
        self.active_point_id: Optional[str] = None

        # Rendering performance: the map is a cached pixmap, only the visible part is drawn, frames are limited
        # to ~60 per second while panning/zooming, and the cheap (non-smoothed) scaler is used until the view
        # has settled for a moment. Without this every mouse-move repainted a huge scaled image at full quality.
        self._pixmaps: dict = {}
        self._interacting = False
        self._frame_timer = QTimer(self)
        self._frame_timer.setSingleShot(True)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self.update)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(140)
        self._settle_timer.timeout.connect(self._on_view_settled)
        self._tag_font = QFont("Segoe UI Emoji", 9)
        self._tag_font.setBold(True)
        self._emoji_font = QFont("Segoe UI Emoji", 10)
        self._grid_font_cache: dict = {}
        self._hover_id: Optional[str] = None
        self._sprites: dict = {}   # rendered pins, see _draw_markers

        # Hover card with clickable Steam links (bases with players)
        self._card = _MarkerCard(self)
        self._card_point_id: Optional[str] = None
        self._card_hide_timer = QTimer(self)
        self._card_hide_timer.setSingleShot(True)
        self._card_hide_timer.setInterval(600)
        self._card_hide_timer.timeout.connect(self._hide_card)
        self._card.entered.connect(self._card_hide_timer.stop)
        self._card.left.connect(self._card_hide_timer.start)

        # Subscribe to point updates
        self.points_mgr.point_added.connect(self._on_point_added)
        self.points_mgr.point_updated.connect(lambda _: self.update())
        self.points_mgr.point_deleted.connect(lambda _: self.update())
        self.points_mgr.points_cleared.connect(lambda: self.update())
        self.points_mgr.points_reloaded.connect(lambda: self.update())

    def _load_base_maps(self):
        candidates = []
        if getattr(sys, "frozen", False):
            if hasattr(sys, "_MEIPASS"):
                candidates.append(os.path.join(sys._MEIPASS, "assets"))
            candidates.append(os.path.join(os.path.dirname(sys.executable), "assets"))
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates.append(os.path.join(base_dir, "assets"))

        for assets_dir in candidates:
            if not os.path.exists(assets_dir):
                continue
            reg_path = os.path.join(assets_dir, "map_regular_2560.jpg")
            tact_path = os.path.join(assets_dir, "map_tactical_2560.jpg")

            if "regular" not in self.map_images and os.path.exists(reg_path):
                self.map_images["regular"] = QImage(reg_path)
            if "tactical" not in self.map_images and os.path.exists(tact_path):
                self.map_images["tactical"] = QImage(tact_path)

    def _current_pixmap(self):
        """The current map as a (cached) QPixmap: much cheaper to draw repeatedly than a QImage."""
        img = self.map_images.get(self.current_variant)
        if not img or img.isNull():
            return None
        pix = self._pixmaps.get(self.current_variant)
        if pix is None or pix.size() != img.size():
            pix = QPixmap.fromImage(img)
            self._pixmaps[self.current_variant] = pix
        return pix

    def _request_frame(self):
        """Redraw soon (coalesced to ~60 fps) while the user pans or zooms."""
        self._interacting = True
        self._settle_timer.start()
        if not self._frame_timer.isActive():
            self._frame_timer.start()

    def _on_view_settled(self):
        self._interacting = False
        self.update()   # one high-quality frame once the movement stops

    def set_variant(self, variant: str):
        if variant in ("regular", "tactical"):
            self.current_variant = variant
            self.cfg.set("map_variant", variant)
            self.update()

    def toggle_grid(self, enabled: bool):
        self.show_grid = enabled
        self.cfg.set("map_show_grid", enabled)
        self.update()

    def toggle_keypads(self, enabled: bool):
        self.show_keypads = enabled
        self.cfg.set("map_show_keypads", enabled)
        self.update()

    def reset_view(self):
        """Reset zoom and center the map in the widget."""
        cur_img = self.map_images.get(self.current_variant)
        if not cur_img or cur_img.isNull():
            return

        w_view = self.width()
        h_view = self.height()
        img_w = cur_img.width()
        img_h = cur_img.height()

        # Scale so the whole map fits with small margins
        scale_x = w_view / img_w
        scale_y = h_view / img_h
        self.zoom = min(scale_x, scale_y) * 0.95

        # Centering
        rendered_w = img_w * self.zoom
        rendered_h = img_h * self.zoom
        self.pan_x = (w_view - rendered_w) / 2.0
        self.pan_y = (h_view - rendered_h) / 2.0
        self.update()

    def focus_point(self, point: MapPoint, target_zoom: float = 2.5):
        """Center the map on the selected point."""
        cur_img = self.map_images.get(self.current_variant)
        if not cur_img or cur_img.isNull():
            return

        self.active_point_id = point.id
        img_w = cur_img.width()
        img_h = cur_img.height()

        self.zoom = max(self.zoom, target_zoom)

        # Point position on the map in pixels
        pt_x = point.norm_x * img_w
        pt_y = point.norm_y * img_h

        # Place the point exactly at the view center
        w_view = self.width()
        h_view = self.height()
        self.pan_x = (w_view / 2.0) - (pt_x * self.zoom)
        self.pan_y = (h_view / 2.0) - (pt_y * self.zoom)

        self.update()

    def _on_point_added(self, point: MapPoint):
        if self.cfg.get("auto_focus_new_point", True):
            self.focus_point(point)
        else:
            self.active_point_id = point.id
            self.update()

    # ──────────────────────── Mouse events ────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        """Zoom in/out with the mouse wheel around the cursor."""
        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = 1.15 if delta > 0 else 1.0 / 1.15
        new_zoom = max(0.2, min(self.zoom * factor, 8.0))

        if new_zoom == self.zoom:
            return

        # Cursor position relative to the widget
        mx = event.position().x()
        my = event.position().y()

        # Keep the map point under the cursor stable
        map_x = (mx - self.pan_x) / self.zoom
        map_y = (my - self.pan_y) / self.zoom

        self.zoom = new_zoom
        self.pan_x = mx - (map_x * self.zoom)
        self.pan_y = my - (map_y * self.zoom)

        self._request_frame()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            clicked_point = self._find_marker_at(event.pos())
            if clicked_point:
                self.active_point_id = clicked_point.id
                self.update()
                self._open_marker_context_menu(clicked_point, event.globalPosition().toPoint())
                event.accept()
                return

        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            # Check whether a marker was clicked
            clicked_point = self._find_marker_at(event.pos())
            if clicked_point:
                self.active_point_id = clicked_point.id
                self.point_clicked.emit(clicked_point)
                self.update()
                event.accept()
                return

            self._dragging = True
            self._drag_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def _open_marker_context_menu(self, point: MapPoint, global_pos: QPoint):
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
                padding: 6px 18px 6px 10px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: white;
            }
        """)

        cur_cat = getattr(point, "category", "default")
        cat_info = get_category_info(cur_cat)
        title_act = menu.addAction(f"{cat_info['emoji']} {point.name} [{point.sector} {point.keypad}]")
        title_act.setEnabled(False)
        menu.addSeparator()

        # 1. Marker type submenu
        type_menu = menu.addMenu(tr("map_window.menu_type", name=get_category_label(cur_cat)))
        type_menu.setStyleSheet(menu.styleSheet())
        for cid, cdata in POINT_CATEGORIES.items():
            mark = "✓ " if cur_cat == cid else ""
            act = type_menu.addAction(f"{mark}{cdata['emoji']} {get_category_label(cid)}")
            act.triggered.connect(lambda checked=False, c=cid: self._set_point_category(point, c))

        # 2. For a base: edit player nicknames
        if cur_cat == "base":
            act_players = menu.addAction(tr("map_window.menu_base_players"))
            act_players.triggered.connect(lambda: self._edit_base_players(point))
            linked = [(n, s) for n, s in self.points_mgr.describe_players(point) if s]
            if linked:
                steam_menu = menu.addMenu(tr("map_window.menu_steam_profiles"))
                steam_menu.setStyleSheet(menu.styleSheet())
                for nick, sid in linked:
                    act = steam_menu.addAction(nick.replace("&", "&&"))
                    act.triggered.connect(
                        lambda checked=False, s=sid: QDesktopServices.openUrl(QUrl(steam_profile_url(s)))
                    )

        # 3. Rename the point
        act_rename = menu.addAction(tr("map_window.menu_rename"))
        act_rename.triggered.connect(lambda: self._rename_point(point))
        menu.addSeparator()

        colors = [
            (tr("map_window.pin_red"), "#ef4444"),
            (tr("map_window.pin_blue"), "#38bdf8"),
            (tr("map_window.pin_emerald"), "#10b981"),
            (tr("map_window.pin_gold"), "#f59e0b"),
            (tr("map_window.pin_purple"), "#a855f7"),
            (tr("map_window.pin_pink"), "#ec4899"),
            (tr("map_window.pin_orange"), "#f97316"),
            (tr("map_window.pin_light"), "#f8fafc"),
        ]

        color_menu = menu.addMenu(tr("map_window.menu_change_color"))
        color_menu.setStyleSheet(menu.styleSheet())
        for label, hex_code in colors:
            act = color_menu.addAction(label)
            act.triggered.connect(lambda checked=False, c=hex_code: self.points_mgr.update_point_color(point.id, c))

        act_custom = color_menu.addAction(tr("map.custom_color"))
        def pick_custom():
            col = open_safe_color_dialog(
                self,
                getattr(point, "color", None) or "#38bdf8",
                tr("map_window.pin_color_dialog", name=point.name)
            )
            if col:
                self.points_mgr.update_point_color(point.id, col)
        act_custom.triggered.connect(pick_custom)

        menu.addSeparator()
        act_copy = menu.addAction(tr("map_window.menu_copy_coords"))
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(point.raw_coord))

        act_del = menu.addAction(tr("map_window.menu_delete"))
        act_del.triggered.connect(lambda: self.points_mgr.delete_point(point.id))

        menu.exec(global_pos)

    def _set_point_category(self, point: MapPoint, category: str):
        self.points_mgr.update_point_category(point.id, category)
        self.update()
        if category == "base" and not getattr(point, "players", ""):
            self._edit_base_players(point)

    def _edit_base_players(self, point: MapPoint):
        dialog = QInputDialog(self)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowTitle(tr("map_window.dlg_players_title"))
        dialog.setLabelText(tr("map_window.dlg_players_label", name=point.name, sector=point.sector, keypad=point.keypad))
        dialog.setTextValue(getattr(point, "players", ""))
        dialog.setStyleSheet("""
            QInputDialog { background-color: #0f172a; color: #f8fafc; }
            QLabel { color: #f1f5f9; font-size: 12px; }
            QLineEdit { background-color: #1e293b; border: 1px solid #38bdf8; border-radius: 4px; color: #ffffff; padding: 6px; font-size: 13px; }
            QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; color: #e2e8f0; padding: 5px 15px; font-weight: 600; }
            QPushButton:hover { background-color: #0284c7; color: white; }
        """)
        if dialog.exec():
            new_players = dialog.textValue().strip()
            self.points_mgr.update_point_players(point.id, new_players)
            self.update()

    def _rename_point(self, point: MapPoint):
        dialog = QInputDialog(self)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowTitle(tr("map_window.dlg_rename_title"))
        dialog.setLabelText(tr("map_window.dlg_rename_label"))
        dialog.setTextValue("" if point.name == "None" else point.name)
        dialog.setStyleSheet("""
            QInputDialog { background-color: #0f172a; color: #f8fafc; }
            QLabel { color: #f1f5f9; font-size: 12px; }
            QLineEdit { background-color: #1e293b; border: 1px solid #38bdf8; border-radius: 4px; color: #ffffff; padding: 6px; font-size: 13px; }
            QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; color: #e2e8f0; padding: 5px 15px; font-weight: 600; }
            QPushButton:hover { background-color: #0284c7; color: white; }
        """)
        if dialog.exec():
            new_name = dialog.textValue().strip()
            self.points_mgr.update_point_name(point.id, new_name if new_name else "None")
            self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.window():
                self.window().close()
            from utils.win_api import restore_game_focus
            restore_game_focus()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.pos() - self._drag_start
            self._drag_start = event.pos()
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self._request_frame()
            event.accept()
            return

        cur_img = self.map_images.get(self.current_variant)
        if cur_img and not cur_img.isNull():
            img_w = cur_img.width()
            img_h = cur_img.height()

            # Normalized coordinates under the cursor
            mx = (event.pos().x() - self.pan_x) / (img_w * self.zoom)
            my = (event.pos().y() - self.pan_y) / (img_h * self.zoom)

            if 0.0 <= mx <= 1.0 and 0.0 <= my <= 1.0:
                game_x, game_y = convert_norm_to_scum(mx, my)
                sec, k = get_sector_info(mx, my)
                self.cursor_coords_changed.emit(game_x, game_y, sec, k)

                # Cursor change and tooltip over a marker
                hovered = self._find_marker_at(event.pos())
                hovered_id = hovered.id if hovered else None
                if hovered_id is not None and hovered_id == self._hover_id and (QToolTip.isVisible() or self._card.isVisible()):
                    super().mouseMoveEvent(event)   # still over the same marker: nothing to rebuild
                    return
                self._hover_id = hovered_id
                if hovered:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                    cur_cat = getattr(hovered, "category", "default")
                    cat_info = get_category_info(cur_cat)
                    lines = [
                        f"{cat_info['emoji']} {hovered.name}",
                        tr("map_window.tip_type", name=get_category_label(cur_cat))
                    ]
                    if cur_cat == "base":
                        pl = getattr(hovered, "players", "")
                        if pl and pl.strip():
                            lines.append(tr("map_window.tip_players", players=pl.strip()))
                        else:
                            lines.append(tr("map_window.tip_players_none"))

                    lines.append(tr("map_window.tip_sector", sector=hovered.sector, keypad=hovered.keypad))
                    lines.append(tr("map_window.tip_time", time=hovered.date_time))
                    lines.append(f"🌐 X={hovered.x:.1f} Y={hovered.y:.1f} Z={hovered.z:.1f}")

                    if cur_cat == "base" and hovered.player_ids:
                        QToolTip.hideText()
                        self._card_hide_timer.stop()
                        self._show_card(hovered, lines, event.pos())
                    else:
                        self._hide_card()
                        QToolTip.showText(
                            event.globalPosition().toPoint(),
                            "\n".join(lines),
                            self
                        )
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
                    if self._card.isVisible() and not self._card_hide_timer.isActive():
                        self._card_hide_timer.start()
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()

    def _hide_card(self):
        if self._card.isVisible() and self._card.is_under_mouse():
            return  # the user is reading/clicking the card
        self._card.hide()
        self._card_point_id = None

    def _show_card(self, point: MapPoint, lines: list, cursor_pos: QPoint):
        """Show (or keep) the hover card for a base."""
        if self._card_point_id == point.id and self._card.isVisible():
            return
        players = []
        for label, sid in self.points_mgr.describe_players(point):
            history = [(h["nick"], h["changed_at"]) for h in self.points_mgr.player_history(sid)] if sid else []
            players.append((label, sid, history))
        self._card.set_content(lines[:2], players, lines[-3:-1])
        # Place the card so the cursor lands inside it: the user can then click a nickname without
        # having to cross a gap that would make the card disappear.
        x = cursor_pos.x() - 14
        y = cursor_pos.y() - 10
        x = max(2, min(x, self.width() - self._card.width() - 2))
        y = max(2, min(y, self.height() - self._card.height() - 2))
        self._card.move(x, y)
        self._card.raise_()
        self._card.show()
        self._card_point_id = point.id

    def leaveEvent(self, event):  # noqa: N802
        if self._card.isVisible() and not self._card.is_under_mouse():
            self._card_hide_timer.start()
        super().leaveEvent(event)

    def _find_marker_at(self, pos: QPoint) -> Optional[MapPoint]:
        cur_img = self.map_images.get(self.current_variant)
        if not cur_img or cur_img.isNull():
            return None

        img_w = cur_img.width()
        img_h = cur_img.height()

        # Marker hit radius
        hit_radius = 18.0

        for pt in self.points_mgr.get_points():
            sx = self.pan_x + pt.norm_x * img_w * self.zoom
            sy = self.pan_y + pt.norm_y * img_h * self.zoom
            # Check both the pin head (sy - 16) and the tip (sy)
            dist_head = math.hypot(pos.x() - sx, pos.y() - (sy - 16.0))
            dist_tip = math.hypot(pos.x() - sx, pos.y() - sy)
            if min(dist_head, dist_tip) <= hit_radius:
                return pt
        return None

    # ──────────────────────── Rendering ────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)

        # 1. Dark background around the map
        painter.fillRect(self.rect(), QColor("#090d16"))

        pixmap = self._current_pixmap()
        if pixmap is None:
            painter.setPen(QColor("#38bdf8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("map_window.loading"))
            return

        map_rect = QRectF(self.pan_x, self.pan_y, pixmap.width() * self.zoom, pixmap.height() * self.zoom)

        # 2. Draw only the part of the map that is on screen (at 8x zoom the full scaled image is 20 000 px wide)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not self._interacting)
        visible = QRectF(0, 0, self.width(), self.height()).intersected(map_rect)
        if not visible.isEmpty():
            source = QRectF((visible.x() - self.pan_x) / self.zoom, (visible.y() - self.pan_y) / self.zoom,
                            visible.width() / self.zoom, visible.height() / self.zoom)
            painter.drawPixmap(visible, pixmap, source)

        # 3. Sector and keypad grid (straight lines: no antialiasing needed)
        if self.show_grid:
            self._draw_grid(painter, map_rect)

        # 4. Points and markers
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_markers(painter, map_rect)

    def _draw_grid(self, painter: QPainter, rect: QRectF):
        mw = rect.width()
        mh = rect.height()
        x0 = rect.x()
        y0 = rect.y()

        # Keypad subgrid (3x3 inside each sector)
        if self.show_keypads and self.zoom >= 0.8:
            keypad_pen = QPen(QColor(56, 189, 248, 40), 1, Qt.PenStyle.DotLine)
            painter.setPen(keypad_pen)
            for i in range(1, 15):
                if i % 3 != 0:
                    px = x0 + mw * (i / 15.0)
                    py = y0 + mh * (i / 15.0)
                    painter.drawLine(QPointF(px, y0), QPointF(px, y0 + mh))
                    painter.drawLine(QPointF(x0, py), QPointF(x0 + mw, py))

        # Main 5x5 sector grid (D0..D4 .. Z0..Z4)
        grid_pen = QPen(QColor(56, 189, 248, 120), 1.5, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)

        for i in range(1, 5):
            px = x0 + mw * (i / 5.0)
            py = y0 + mh * (i / 5.0)
            painter.drawLine(QPointF(px, y0), QPointF(px, y0 + mh))
            painter.drawLine(QPointF(x0, py), QPointF(x0 + mw, py))

        # Map border
        painter.setPen(QPen(QColor("#38bdf8"), 2, Qt.PenStyle.SolidLine))
        painter.drawRect(rect)

        # Sector labels (D4..D0, C4..C0, B4..B0, A4..A0, Z4..Z0)
        rows = ["D", "C", "B", "A", "Z"]
        cols = ["4", "3", "2", "1", "0"]

        size = max(9, int(11 * min(self.zoom, 2.0)))
        font = self._grid_font_cache.get(size)
        if font is None:
            font = QFont("Segoe UI", size)
            font.setBold(True)
            self._grid_font_cache[size] = font
        painter.setFont(font)

        cell_w = mw / 5.0
        cell_h = mh / 5.0

        for r_idx, r_name in enumerate(rows):
            for c_idx, c_name in enumerate(cols):
                label = f"{r_name}{c_name}"
                cx = x0 + c_idx * cell_w + 8
                cy = y0 + r_idx * cell_h + 18
                if not (-60 <= cx <= self.width() + 60 and -30 <= cy <= self.height() + 30):
                    continue   # label is off screen

                # Shadow for readability
                painter.setPen(QColor(0, 0, 0, 200))
                painter.drawText(QPointF(cx + 1, cy + 1), label)

                painter.setPen(QColor("#38bdf8"))
                painter.drawText(QPointF(cx, cy), label)

    MARKER_CACHE_LIMIT = 800

    def _draw_markers(self, painter: QPainter, rect: QRectF):
        """Draw the visible pins. Each distinct pin (+ name tag) is rendered once into a small pixmap and then
        only blitted, so panning with many markers on screen costs a few microseconds per marker."""
        points = self.points_mgr.get_points()
        if not points:
            return

        mw, mh, x0, y0 = rect.width(), rect.height(), rect.x(), rect.y()
        dpr = self.devicePixelRatioF()
        width, height = self.width(), self.height()

        # Oldest to newest (newest on top)
        for pt in reversed(points):
            sx = x0 + pt.norm_x * mw
            sy = y0 + pt.norm_y * mh
            if not (-80 <= sx <= width + 80 and -20 <= sy <= height + 80):
                continue   # the pin and its name tag are drawn above/around the point: keep a margin

            cur_cat = getattr(pt, "category", "default")
            cat_info = get_category_info(cur_cat)
            emoji_tag = f"{cat_info['emoji']} " if cur_cat != "default" else ""
            if pt.name != "None":
                label_text = f"{emoji_tag}{pt.name} [{pt.sector}]"
            else:
                label_text = f"{emoji_tag}[{pt.sector} {pt.keypad}]"
            color = getattr(pt, "color", None) or cat_info["default_color"]
            is_active = pt.id == self.active_point_id

            key = (label_text, cur_cat, color, is_active, dpr)
            sprite = self._sprites.get(key)
            if sprite is None:
                if len(self._sprites) >= self.MARKER_CACHE_LIMIT:
                    self._sprites.clear()
                sprite = self._build_marker_sprite(label_text, cur_cat, cat_info, color, is_active, dpr)
                self._sprites[key] = sprite
            pixmap, tip_x, tip_y = sprite
            painter.drawPixmap(QPointF(sx - tip_x, sy - tip_y), pixmap)

    def _build_marker_sprite(self, label_text: str, cur_cat: str, cat_info: dict, color: str,
                             is_active: bool, dpr: float):
        """Render one pin with its name tag. Returns (pixmap, tip_x, tip_y): where the pin tip is inside it."""
        pin_color = QColor(color)
        fm = QFontMetrics(self._tag_font)
        tw = fm.horizontalAdvance(label_text) + 12
        th = fm.height() + 4

        glow = 24.0
        sprite_w = int(max(tw, 2 * glow) + 8)
        top = 34.0 + th + 4.0                      # tip y inside the sprite: room for the tag above the pin
        sprite_h = int(top + 8)
        tip_x, tip_y = sprite_w / 2.0, top

        pixmap = QPixmap(int(sprite_w * dpr), int(sprite_h * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sx, sy = tip_x, tip_y

        # 1. Shadow under the pin tip on the map surface
        painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(sx, sy + 0.5), 4.5, 2.0)

        # 2. Outer glow for the active pin
        if is_active:
            glow_col = QColor(pin_color)
            glow_col.setAlpha(60)
            painter.setBrush(QBrush(glow_col))
            painter.drawEllipse(QPointF(sx, sy - 16.0), 22.0, 22.0)
            glow_col.setAlpha(120)
            painter.setBrush(QBrush(glow_col))
            painter.drawEllipse(QPointF(sx, sy - 16.0), 14.0, 14.0)

        # 3. Pin (vector path: round head on top, sharp tip exactly on the point)
        pin_path = QPainterPath()
        pin_path.moveTo(sx, sy)
        pin_path.quadTo(sx + 10.0, sy - 8.0, sx + 10.0, sy - 16.0)
        pin_path.arcTo(sx - 10.0, sy - 26.0, 20.0, 20.0, 0, 180)
        pin_path.quadTo(sx - 10.0, sy - 8.0, sx, sy)
        pin_path.closeSubpath()
        painter.setBrush(QBrush(pin_color))
        painter.setPen(QPen(QColor("#ffffff") if is_active else QColor("#090d16"), 1.8 if is_active else 1.2))
        painter.drawPath(pin_path)

        # 4. Pin content (category emoji, or a white dot for the classic marker)
        if cur_cat == "default":
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(sx, sy - 16.0), 2.8, 2.8)
        else:
            painter.setFont(self._emoji_font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(sx - 10.0, sy - 26.0, 20.0, 20.0), Qt.AlignmentFlag.AlignCenter, cat_info["emoji"])

        # 5. Compact name tag above the pin
        painter.setFont(self._tag_font)
        tag_rect = QRectF(sx - tw / 2.0, sy - 34.0 - th, tw, th)
        painter.setBrush(QBrush(QColor(11, 15, 25, 230)))
        painter.setPen(QPen(pin_color, 1))
        painter.drawRoundedRect(tag_rect, 4, 4)
        painter.setPen(QColor("#ffffff") if is_active else QColor("#f1f5f9"))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, label_text)
        painter.end()
        return pixmap, tip_x, tip_y


class MapWindow(QWidget):
    """
    Main interactive SCUM map window:
    - Midnight Cyan style
    - Top toolbar (satellite/tactical switch, grid, zoom)
    - Badge with the current cursor coordinates
    - Drag to move and resize
    - Ctrl+M hotkey to open
    """
    closed = pyqtSignal()
    point_selected = pyqtSignal(object)  # MapPoint

    def __init__(self, config_manager: ConfigManager, points_manager: PointsManager):
        super().__init__()
        self.cfg = config_manager
        self.points_mgr = points_manager
        self._drag_pos = QPoint()

        self.init_window_flags()
        self.init_ui()
        self.apply_config_geometry()

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

        # Card container
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame#map_card {
                background-color: #0b0f19;
                border: 2px solid #38bdf8;
                border-radius: 10px;
            }
        """)
        self.container.setObjectName("map_card")
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(6, 6, 6, 6)
        c_layout.setSpacing(4)

        # 1. Map canvas (created first)
        self.canvas = MapCanvasWidget(self.cfg, self.points_mgr, self.container)
        self.canvas.cursor_coords_changed.connect(self._on_cursor_coords_changed)
        self.canvas.point_clicked.connect(self.point_selected.emit)

        # 2. Top bar
        self._build_top_bar(c_layout)
        c_layout.addWidget(self.canvas, 1)

        # 3. Bottom status bar and resize grip
        self._build_bottom_bar(c_layout)

        self.main_layout.addWidget(self.container)

    def _build_top_bar(self, layout: QVBoxLayout):
        top_bar = QWidget()
        top_bar.setStyleSheet("background: transparent;")
        h = QHBoxLayout(top_bar)
        h.setContentsMargins(6, 2, 6, 2)
        h.setSpacing(6)

        # Title
        lbl_title = QLabel(f"<b>{tr('map_window.title', default='SCUM Island Map')}</b>")
        lbl_title.setStyleSheet("color: #38bdf8; font-size: 13px;")
        lbl_title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        h.addWidget(lbl_title)

        # Cursor info (elided when space is short, full text in the tooltip)
        self.lbl_cursor = _ElidedLabel(tr("map_window.cursor_hint"))
        self.lbl_cursor.setStyleSheet("""
            QLabel {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                font-family: 'Consolas', 'Segoe UI', monospace;
                padding: 3px 8px;
            }
        """)
        h.addWidget(self.lbl_cursor, 1)

        btn_style = """
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
            QPushButton:checked {
                border-color: #38bdf8;
                color: #38bdf8;
            }
        """
        icon_style = btn_style + """
            QPushButton {
                font-family: 'Segoe UI Symbol', 'Segoe UI', sans-serif;
                font-size: 14px;
                padding: 0px 4px;
            }
        """

        def _icon_btn(text: str, tip: str, slot) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setMinimumSize(28, 28)
            b.setStyleSheet(icon_style)
            b.clicked.connect(slot)
            return b

        self.btn_var = QPushButton(tr("map_window.variant_satellite") if self.canvas.current_variant == "regular" else tr("map_window.variant_tactical"))
        self.btn_var.setMinimumHeight(28)
        self.btn_var.setStyleSheet(btn_style)
        self.btn_var.clicked.connect(self._toggle_variant)
        h.addWidget(self.btn_var)

        self.btn_grid = QPushButton(tr("map_window.grid"))
        self.btn_grid.setMinimumHeight(28)
        self.btn_grid.setCheckable(True)
        self.btn_grid.setChecked(self.canvas.show_grid)
        self.btn_grid.setStyleSheet(btn_style)
        self.btn_grid.clicked.connect(self.canvas.toggle_grid)
        h.addWidget(self.btn_grid)

        h.addWidget(_icon_btn("+", tr("map_window.tip_zoom_in", default="Zoom in"), lambda: self._step_zoom(1.25)))
        h.addWidget(_icon_btn("\u2212", tr("map_window.tip_zoom_out", default="Zoom out"), lambda: self._step_zoom(0.8)))
        h.addWidget(_icon_btn("\u27F2", tr("map_window.tip_reset"), self.canvas.reset_view))

        btn_close = _icon_btn("\u2715", tr("map_window.tip_close", hotkey=self.cfg.get("hotkey_toggle_map", "Ctrl+M")), self.close)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #ef4444;
                border-radius: 4px;
                color: #f87171;
                font-family: 'Segoe UI Symbol', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 13px;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: #ef4444;
                color: white;
            }
        """)
        h.addWidget(btn_close)

        layout.addWidget(top_bar)

    def _build_bottom_bar(self, layout: QVBoxLayout):
        bottom_bar = QWidget()
        bottom_bar.setStyleSheet("background: transparent;")
        h = QHBoxLayout(bottom_bar)
        h.setContentsMargins(6, 0, 0, 0)
        h.setSpacing(6)

        lbl_hint = QLabel(tr("map_window.hint"))
        lbl_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        lbl_hint.setWordWrap(True)
        lbl_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lbl_hint.setMinimumHeight(QFontMetrics(lbl_hint.font()).height() * 2 + 4)
        h.addWidget(lbl_hint, 1)

        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background: transparent; color: #38bdf8;")
        h.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom)

        layout.addWidget(bottom_bar)

    def _toggle_variant(self):
        new_v = "tactical" if self.canvas.current_variant == "regular" else "regular"
        self.canvas.set_variant(new_v)
        self.btn_var.setText(tr("map_window.variant_satellite") if new_v == "regular" else tr("map_window.variant_tactical"))

    def _step_zoom(self, factor: float):
        w_view = self.canvas.width()
        h_view = self.canvas.height()
        mx = w_view / 2.0
        my = h_view / 2.0

        map_x = (mx - self.canvas.pan_x) / self.canvas.zoom
        map_y = (my - self.canvas.pan_y) / self.canvas.zoom

        self.canvas.zoom = max(0.2, min(self.canvas.zoom * factor, 8.0))
        self.canvas.pan_x = mx - (map_x * self.canvas.zoom)
        self.canvas.pan_y = my - (map_y * self.canvas.zoom)
        self.canvas.update()

    def _on_cursor_coords_changed(self, x: float, y: float, sec: str, keypad: str):
        self.lbl_cursor.setText(tr("map_window.cursor_info", sector=sec, keypad=keypad, x=int(x), y=int(y)))

    def focus_point(self, point: MapPoint):
        self.canvas.focus_point(point)

    # ──────────────────────── Window dragging ────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() <= 45:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
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

        w = self.cfg.get("map_width", 960)
        h = self.cfg.get("map_height", 660)
        saved_x = self.cfg.get("map_x", -1)
        saved_y = self.cfg.get("map_y", -1)

        w = max(self.minimumSizeHint().width(), 500, min(w, sw - 40))
        h = max(self.minimumSizeHint().height(), 400, min(h, sh - 40))

        if saved_x is None or saved_x < 0 or saved_y is None or saved_y < 0:
            x = sx + (sw - w) // 2
            # Shift slightly up so the points list fits below
            y = sy + max(20, (sh - h - 250) // 2)
        else:
            x = max(sx, min(saved_x, sx + sw - w))
            y = max(sy, min(saved_y, sy + sh - h))

        self.setGeometry(x, y, w, h)

    def save_geometry(self):
        with self.cfg.batch():
            self.cfg.set("map_x", self.x())
            self.cfg.set("map_y", self.y())
            self.cfg.set("map_width", self.width())
            self.cfg.set("map_height", self.height())

    def showEvent(self, event):
        super().showEvent(event)
        # Initialize the view on the first show only (re-showing must keep the user's zoom/pan and focus)
        if not getattr(self, "_view_initialized", False):
            self._view_initialized = True
            self.canvas.reset_view()

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
