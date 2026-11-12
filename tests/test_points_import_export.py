"""Tests for waypoint import / export."""

import json

import pytest

from core.coordinate_parser import MapPoint
from core.points_manager import PointsManager


def make_point(pid: str, name: str, x: float = 100.0, y: float = 200.0) -> MapPoint:
    return MapPoint(id=pid, name=name, date_time="10.11 20:00:00", raw_coord="{X=%s Y=%s Z=1|P=0 Y=0 R=0}" % (x, y),
                    x=x, y=y, z=1.0, sector="C2", keypad="k5", norm_x=0.5, norm_y=0.5,
                    created_timestamp=1700000000.0 + x)


@pytest.fixture
def manager(tmp_path):
    pm = PointsManager(str(tmp_path / "points.json"))
    pm.add_point(make_point("a", "Base", 100))
    pm.add_point(make_point("b", "Car", 200))
    return pm


def test_export_then_import_round_trip(manager, tmp_path):
    out = tmp_path / "export.json"
    assert manager.export_to_file(str(out)) == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["format"] == "scum-waypoints" and len(payload["points"]) == 2

    other = PointsManager(str(tmp_path / "other.json"))
    result = other.import_from_file(str(out))
    assert (result.added, result.duplicates, result.invalid) == (2, 0, 0)
    assert {p.name for p in other.get_points()} == {"Base", "Car"}


def test_merge_skips_duplicates(manager, tmp_path):
    out = tmp_path / "export.json"
    manager.export_to_file(str(out))
    result = manager.import_from_file(str(out))
    assert (result.added, result.duplicates) == (0, 2)
    assert len(manager.get_points()) == 2


def test_replace_swaps_list_and_keeps_backup(manager, tmp_path):
    src = tmp_path / "in.json"
    src.write_text(json.dumps([make_point("z", "Cache", 900).to_dict()]), encoding="utf-8")  # legacy list format
    result = manager.import_from_file(str(src), replace=True)
    assert result.added == 1 and [p.name for p in manager.get_points()] == ["Cache"]
    assert (tmp_path / "points.before_import.json").exists()
    assert json.loads((tmp_path / "points.json").read_text(encoding="utf-8"))[0]["name"] == "Cache"


def test_invalid_entries_are_counted_not_fatal(manager, tmp_path):
    src = tmp_path / "in.json"
    good = make_point("n", "New", 555).to_dict()
    src.write_text(json.dumps({"points": [good, {"name": "no coords"}, "junk", {"x": "abc", "y": 1}]}), encoding="utf-8")
    result = manager.import_from_file(str(src))
    assert (result.added, result.invalid) == (1, 3)


@pytest.mark.parametrize("content", ["{broken", '{"hello": 1}', '"text"'])
def test_unrecognised_files_raise(manager, tmp_path, content):
    src = tmp_path / "bad.json"
    src.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        manager.import_from_file(str(src))
    assert len(manager.get_points()) == 2  # nothing was changed


def test_save_is_atomic_no_tmp_left(manager, tmp_path):
    manager.save()
    assert not (tmp_path / "points.json.tmp").exists()
