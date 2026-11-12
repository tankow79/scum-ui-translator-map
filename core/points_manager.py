import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.config_manager import get_portable_config_path
from core.coordinate_parser import POINT_CATEGORIES, MapPoint, detect_category_from_name

log = logging.getLogger("scum.points")

EXPORT_FORMAT = "scum-waypoints"
EXPORT_VERSION = 1


@dataclass
class ImportResult:
    added: int = 0
    duplicates: int = 0
    invalid: int = 0


class PointsManager(QObject):
    """
    Manager of saved coordinate points:
    - Stores points in points.json (next to config.json or the .exe)
    - Persists them across game and app restarts
    - Sorts points from newest to oldest
    - Notifies the UI via PyQt signals
    """
    point_added = pyqtSignal(object)      # MapPoint
    point_updated = pyqtSignal(object)    # MapPoint
    point_deleted = pyqtSignal(str)       # point_id
    points_cleared = pyqtSignal()
    points_reloaded = pyqtSignal()        # whole list replaced (import)

    def __init__(self, file_path: Optional[str] = None):
        super().__init__()
        if file_path is None:
            file_path = get_portable_config_path("points.json")
        self.file_path = file_path
        self._points: List[MapPoint] = []
        self.load()

    def load(self):
        self._points = []
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            try:
                                pt = MapPoint.from_dict(item)
                                self._points.append(pt)
                            except Exception as pe:
                                log.warning("Failed to read point: %s", pe)
            except Exception as e:
                log.error("Failed to load %s: %s", self.file_path, e)

        # Sort from newest to oldest
        self._points.sort(key=lambda p: p.created_timestamp, reverse=True)

    def save(self):
        """Write points.json atomically (temp file + replace) so a crash never corrupts it."""
        tmp_path = self.file_path + ".tmp"
        try:
            parent_dir = os.path.dirname(self.file_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump([p.to_dict() for p in self._points], f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.file_path)
        except OSError as e:
            log.error("Could not save %s: %s", self.file_path, e)

    # ── import / export ──────────────────────────────────────────────
    def export_to_file(self, path: str, points: Optional[List[MapPoint]] = None) -> int:
        """Export waypoints (all, or the given subset) to a portable JSON file. Returns the count."""
        items = self._points if points is None else points
        payload = {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "points": [p.to_dict() for p in items],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return len(items)

    @staticmethod
    def _extract_point_dicts(data: Any) -> List[Any]:
        if isinstance(data, list):                      # legacy points.json
            return data
        if isinstance(data, dict) and isinstance(data.get("points"), list):
            return data["points"]
        raise ValueError("Unrecognised waypoint file format")

    def import_from_file(self, path: str, replace: bool = False) -> ImportResult:
        """Import waypoints from JSON. ``replace=True`` swaps the whole list (a .bak copy is kept).

        Raises ``ValueError`` / ``OSError`` for unreadable or unrecognised files; individual bad
        entries are skipped and counted in ``ImportResult.invalid``.
        """
        with open(path, encoding="utf-8") as f:
            raw_items = self._extract_point_dicts(json.load(f))

        result = ImportResult()
        parsed: List[MapPoint] = []
        for item in raw_items:
            try:
                if not isinstance(item, dict) or "x" not in item or "y" not in item:
                    raise ValueError("missing coordinates")
                parsed.append(MapPoint.from_dict(item))
            except (ValueError, TypeError, KeyError):
                result.invalid += 1

        if replace and os.path.exists(self.file_path):
            try:
                shutil.copy2(self.file_path, self.file_path + ".bak")
            except OSError as exc:
                log.warning("Could not back up points before import: %s", exc)

        existing = [] if replace else list(self._points)
        known_ids = {p.id for p in existing}
        known_coords = {(round(p.x, 1), round(p.y, 1), round(p.z, 1), p.name) for p in existing}
        for pt in parsed:
            key = (round(pt.x, 1), round(pt.y, 1), round(pt.z, 1), pt.name)
            if pt.id in known_ids or key in known_coords:
                result.duplicates += 1
                continue
            known_ids.add(pt.id)
            known_coords.add(key)
            existing.append(pt)
            result.added += 1

        existing.sort(key=lambda p: p.created_timestamp, reverse=True)
        self._points = existing
        self.save()
        self.points_reloaded.emit()
        return result

    def add_point(self, point: MapPoint) -> bool:
        # Duplicate guard (same coordinates within 2 seconds)
        if self._points:
            first = self._points[0]
            if first.raw_coord == point.raw_coord and abs(first.created_timestamp - point.created_timestamp) < 2.0:
                return False

        # Insert at the start of the list (newest point on top)
        self._points.insert(0, point)
        self.save()
        self.point_added.emit(point)
        return True

    def update_point_name(self, point_id: str, new_name: str) -> bool:
        clean_name = new_name.strip() if new_name.strip() else "None"
        for pt in self._points:
            if pt.id == point_id:
                pt.name = clean_name
                # If the category is still default, try to detect it from the new name
                if pt.category == "default":
                    detected = detect_category_from_name(clean_name)
                    if detected != "default":
                        pt.category = detected
                        pt.color = POINT_CATEGORIES[detected]["default_color"]
                self.save()
                self.point_updated.emit(pt)
                return True
        return False

    def update_point_category(self, point_id: str, new_category: str) -> bool:
        if new_category not in POINT_CATEGORIES:
            new_category = "default"
        for pt in self._points:
            if pt.id == point_id:
                old_cat = pt.category
                pt.category = new_category
                # If the color was the default for the old category, update it to the new one
                old_default = POINT_CATEGORIES.get(old_cat, {}).get("default_color")
                if not pt.color or pt.color == old_default:
                    pt.color = POINT_CATEGORIES[new_category]["default_color"]
                self.save()
                self.point_updated.emit(pt)
                return True
        return False

    def update_point_players(self, point_id: str, new_players: str) -> bool:
        clean_players = new_players.strip()
        for pt in self._points:
            if pt.id == point_id:
                pt.players = clean_players
                self.save()
                self.point_updated.emit(pt)
                return True
        return False

    def update_point_color(self, point_id: str, new_color: str) -> bool:
        clean_color = new_color.strip() if new_color.strip() else "#38bdf8"
        for pt in self._points:
            if pt.id == point_id:
                pt.color = clean_color
                self.save()
                self.point_updated.emit(pt)
                return True
        return False

    def delete_point(self, point_id: str) -> bool:
        idx = -1
        for i, pt in enumerate(self._points):
            if pt.id == point_id:
                idx = i
                break
        if idx != -1:
            self._points.pop(idx)
            self.save()
            self.point_deleted.emit(point_id)
            return True
        return False

    def clear_all(self):
        self._points.clear()
        self.save()
        self.points_cleared.emit()

    def get_points(self) -> List[MapPoint]:
        return list(self._points)

    def get_point_by_id(self, point_id: str) -> Optional[MapPoint]:
        for pt in self._points:
            if pt.id == point_id:
                return pt
        return None
