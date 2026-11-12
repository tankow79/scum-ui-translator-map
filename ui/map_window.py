import logging
import math
import os
import sys
from typing import Optional

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
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
            self.map_images["tactical"] = QImage(tact_path)

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

        self.update()
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
            self.update()
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

                    QToolTip.showText(
                        event.globalPosition().toPoint(),
                        "\n".join(lines),
                        self
                    )
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. Dark background around the map
        painter.fillRect(self.rect(), QColor("#090d16"))

        cur_img = self.map_images.get(self.current_variant)
        if not cur_img or cur_img.isNull():
            painter.setPen(QColor("#38bdf8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("map_window.loading"))
            return

        img_w = cur_img.width()
        img_h = cur_img.height()
        map_rect = QRectF(self.pan_x, self.pan_y, img_w * self.zoom, img_h * self.zoom)

        # 2. Draw the map itself
        painter.drawImage(map_rect, cur_img)

        # 3. Sector and keypad grid
        if self.show_grid:
            self._draw_grid(painter, map_rect)

        # 4. Points and markers
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

        font = QFont("Segoe UI", max(9, int(11 * min(self.zoom, 2.0))))
        font.setBold(True)
        painter.setFont(font)

        cell_w = mw / 5.0
        cell_h = mh / 5.0

        for r_idx, r_name in enumerate(rows):
            for c_idx, c_name in enumerate(cols):
                label = f"{r_name}{c_name}"
                cx = x0 + c_idx * cell_w + 8
                cy = y0 + r_idx * cell_h + 18

                # Shadow for readability
                painter.setPen(QColor(0, 0, 0, 200))
                painter.drawText(QPointF(cx + 1, cy + 1), label)

                painter.setPen(QColor("#38bdf8"))
                painter.drawText(QPointF(cx, cy), label)

    def _draw_markers(self, painter: QPainter, rect: QRectF):
        mw = rect.width()
        mh = rect.height()
        x0 = rect.x()
        y0 = rect.y()

        points = self.points_mgr.get_points()
        if not points:
            return

        # Draw markers oldest to newest (newest on top)
        for pt in reversed(points):
            sx = x0 + pt.norm_x * mw
            sy = y0 + pt.norm_y * mh

            # Skip markers outside the visible area
            if not (0 <= sx <= self.width() and 0 <= sy <= self.height()):
                continue

            is_active = (pt.id == self.active_point_id)
            cur_cat = getattr(pt, "category", "default")
            cat_info = get_category_info(cur_cat)
            pt_color_str = getattr(pt, "color", None) or cat_info["default_color"]
            pin_color = QColor(pt_color_str)

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
            pin_path.moveTo(sx, sy)  # sharp tip exactly on the coordinate
            pin_path.quadTo(sx + 10.0, sy - 8.0, sx + 10.0, sy - 16.0)
            pin_path.arcTo(sx - 10.0, sy - 26.0, 20.0, 20.0, 0, 180)
            pin_path.quadTo(sx - 10.0, sy - 8.0, sx, sy)
            pin_path.closeSubpath()

            # Fill with the chosen color and a contrasting outline
            painter.setBrush(QBrush(pin_color))
            border_color = QColor("#ffffff") if is_active else QColor("#090d16")
            border_width = 1.8 if is_active else 1.2
            painter.setPen(QPen(border_color, border_width))
            painter.drawPath(pin_path)

            # 4. Pin content (emoji, or a white dot for the classic marker)
            if cur_cat == "default":
                # Classic pin: small white inner dot
                painter.setBrush(QBrush(QColor("#ffffff")))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(sx, sy - 16.0), 2.8, 2.8)
            else:
                # Category emoji (🚗, ✈️, 🏍️, 🚤, 📦, 🏠)
                painter.setFont(QFont("Segoe UI Emoji", 10))
                painter.setPen(QColor("#ffffff"))
                emoji_rect = QRectF(sx - 10.0, sy - 26.0, 20.0, 20.0)
                painter.drawText(emoji_rect, Qt.AlignmentFlag.AlignCenter, cat_info["emoji"])

            # 5. Compact name tag above the pin
            emoji_tag = f"{cat_info['emoji']} " if cur_cat != "default" else ""
            if pt.name != "None":
                label_text = f"{emoji_tag}{pt.name} [{pt.sector}]"
            else:
                label_text = f"{emoji_tag}[{pt.sector} {pt.keypad}]"

            tag_font = QFont("Segoe UI Emoji", 9)
            tag_font.setBold(True)
            painter.setFont(tag_font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label_text) + 12
            th = fm.height() + 4

            tag_rect = QRectF(sx - tw / 2.0, sy - 34.0 - th, tw, th)

            # Tag background
            painter.setBrush(QBrush(QColor(11, 15, 25, 230)))
            painter.setPen(QPen(pin_color, 1))
            painter.drawRoundedRect(tag_rect, 4, 4)

            # Name text
            painter.setPen(QColor("#ffffff") if is_active else QColor("#f1f5f9"))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, label_text)


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

        btn_close = _icon_btn("\u2715", tr("map_window.tip_close"), self.close)
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
        self.cfg.set("map_x", self.x())
        self.cfg.set("map_y", self.y())
        self.cfg.set("map_width", self.width())
        self.cfg.set("map_height", self.height())

    def showEvent(self, event):
        super().showEvent(event)
        # Initialize the view on first show
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
