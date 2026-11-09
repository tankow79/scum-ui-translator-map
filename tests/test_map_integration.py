import pytest
from PyQt6.QtWidgets import QApplication
import sys

from core.config_manager import ConfigManager
from core.translator import GoogleTranslatorEngine
from core.points_manager import PointsManager
from core.coordinate_parser import parse_chat_coordinate
from ui.map_window import MapWindow
from ui.points_window import PointsWindow
from main import AppController

app = QApplication.instance() or QApplication(sys.argv)


def test_end_to_end_chat_coordinate_flow(tmp_path):
    cfg_file = str(tmp_path / "cfg.json")
    pts_file = str(tmp_path / "pts.json")
    cfg = ConfigManager(cfg_file)
    translator = GoogleTranslatorEngine(target_lang="uk")
    controller = AppController(cfg, translator)
    points_mgr = PointsManager(pts_file)

    map_win = MapWindow(cfg, points_mgr)
    points_win = PointsWindow(cfg, points_mgr)

    # Wire up exactly as in main.py
    points_win.point_focus_requested.connect(map_win.focus_point)
    map_win.point_selected.connect(map_win.focus_point)

    detected_points = []
    def on_coord(pt):
        points_mgr.add_point(pt)
        detected_points.append(pt)
        map_win.focus_point(pt)

    controller.coordinate_detected.connect(on_coord)

    # Simulate in-game chat messages
    # 1. Message with label before
    controller.raw_message_received.emit(
        "14:20:00", "Player1",
        "машина{X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}",
        "player"
    )

    # 2. Message with label after
    controller.raw_message_received.emit(
        "14:21:00", "Player2",
        "{X=91149.500 Y=-162011.531 Z=31172.863|P=357.522491 Y=354.508392 R=0.000000} база",
        "player"
    )

    # 3. Message without label
    controller.raw_message_received.emit(
        "14:22:00", "Player3",
        "{X=-142861.000 Y=-142348.000 Z=15000.000|P=0.0 Y=0.0 R=0.0}",
        "player"
    )

    # 4. Normal message without coordinates
    controller.raw_message_received.emit(
        "14:23:00", "Player4",
        "Hello everyone on the server!",
        "player"
    )

    assert len(detected_points) == 3

    # Check order in PointsManager: newest first
    all_pts = points_mgr.get_points()
    assert len(all_pts) == 3
    assert all_pts[0].name == "None"
    assert all_pts[1].name == "база"
    assert all_pts[2].name == "машина"

    # Check UI rows in points window
    assert len(points_win._row_widgets) == 3

    # Check sectors
    assert all_pts[2].sector == "D3"
    assert all_pts[1].sector == "B3"

    # Check map focus
    assert map_win.canvas.active_point_id == all_pts[0].id

    # Test clicking "Open on Map" on the oldest point (машина)
    points_win._row_widgets[all_pts[2].id].btn_map.click()
    assert map_win.canvas.active_point_id == all_pts[2].id

    # Test Escape closing windows
    map_win.show()
    points_win.show()
    assert not map_win.isHidden()
    assert not points_win.isHidden()

    def on_escape_pressed():
        if map_win.isVisible(): map_win.hide()
        if points_win.isVisible(): points_win.hide()

    controller.hotkey_escape_pressed.connect(on_escape_pressed)
    controller.hotkey_escape_pressed.emit()
    assert map_win.isHidden()
    assert points_win.isHidden()

    # 5. Check category auto-detection in integration flow
    # all_pts[2] was 'машина' -> category 'car'
    assert all_pts[2].category == "car"
    assert points_win._row_widgets[all_pts[2].id].btn_category.text() == "🚗 Машина ▾"
    assert points_win._row_widgets[all_pts[2].id].txt_players.isHidden()

    # all_pts[1] was 'база' -> category 'base'
    assert all_pts[1].category == "base"
    assert points_win._row_widgets[all_pts[1].id].btn_category.text() == "🏠 База ▾"
    assert not points_win._row_widgets[all_pts[1].id].txt_players.isHidden()

    # Add players to base
    points_win._row_widgets[all_pts[1].id].txt_players.setText("Player2, Player3, Valkyrie")
    points_win._row_widgets[all_pts[1].id]._on_players_edited()
    assert points_mgr.get_point_by_id(all_pts[1].id).players == "Player2, Player3, Valkyrie"

    # Test filtering by player nickname
    points_win.txt_filter.setText("Valkyrie")
    assert not points_win._row_widgets[all_pts[1].id].isHidden()
    assert points_win._row_widgets[all_pts[2].id].isHidden()

    # Clear filter
    points_win.txt_filter.setText("")
    assert not points_win._row_widgets[all_pts[2].id].isHidden()
