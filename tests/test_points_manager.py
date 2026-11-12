import sys

from PyQt6.QtWidgets import QApplication

from core.coordinate_parser import parse_chat_coordinate
from core.points_manager import PointsManager

# Ensure QApplication exists for signals
app = QApplication.instance() or QApplication(sys.argv)

SAMPLE_COORD = "{X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}"


def test_points_manager_lifecycle(tmp_path):
    json_file = str(tmp_path / "test_points.json")
    mgr = PointsManager(json_file)
    assert len(mgr.get_points()) == 0

    p1 = parse_chat_coordinate(f"Машина {SAMPLE_COORD}")
    mgr.add_point(p1)
    assert len(mgr.get_points()) == 1
    assert mgr.get_points()[0].name == "Машина"

    # Add second point
    p2 = parse_chat_coordinate("{X=100000 Y=200000 Z=10000}")
    mgr.add_point(p2)
    pts = mgr.get_points()
    assert len(pts) == 2
    # Newest is first
    assert pts[0].id == p2.id

    # Update name
    mgr.update_point_name(p1.id, "Броньовик")
    assert mgr.get_point_by_id(p1.id).name == "Броньовик"

    # Update color
    mgr.update_point_color(p1.id, "#ef4444")
    assert mgr.get_point_by_id(p1.id).color == "#ef4444"

    # Update category to base
    mgr.update_point_category(p1.id, "base")
    assert mgr.get_point_by_id(p1.id).category == "base"

    # Update players
    mgr.update_point_players(p1.id, "Ghost, Reaper, Alex")
    assert mgr.get_point_by_id(p1.id).players == "Ghost, Reaper, Alex"

    # Reload from disk
    mgr2 = PointsManager(json_file)
    pts2 = mgr2.get_points()
    assert len(pts2) == 2
    assert pts2[1].name == "Броньовик"
    assert pts2[1].color == "#ef4444"
    assert pts2[1].category == "base"
    assert pts2[1].players == "Ghost, Reaper, Alex"

    # Delete point
    mgr.delete_point(p2.id)
    assert len(mgr.get_points()) == 1

    # Clear all
    mgr.clear_all()
    assert len(mgr.get_points()) == 0
