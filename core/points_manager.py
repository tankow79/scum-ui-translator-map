import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from core.config_manager import get_portable_config_path
from core.coordinate_parser import POINT_CATEGORIES, MapPoint, detect_category_from_name
from core.players import PlayerRegistry, parse_steam_ref, split_players

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

    def __init__(self, file_path: Optional[str] = None, registry: Optional[PlayerRegistry] = None):
        super().__init__()
        if file_path is None:
            file_path = get_portable_config_path("points.json")
        self.file_path = file_path
        self.registry = registry
        if registry is not None:
            registry.player_changed.connect(self.apply_player_update)
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
        """Import waypoints from JSON. ``replace=True`` swaps the whole list (the previous list is kept as points.before_import.json).

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
                shutil.copy2(self.file_path, os.path.join(os.path.dirname(self.file_path), "points.before_import.json"))
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
        """Set a base's players from free text.

        Each comma-separated entry may be a nickname, a SteamID64 or a steamcommunity.com/profiles
        link. IDs (and nicknames already known to the registry) are linked to the base, so later
        nickname changes are applied automatically.
        """
        for pt in self._points:
            if pt.id == point_id:
                pt.players, pt.player_ids = self._resolve_players(new_players)
                self.save()
                self.point_updated.emit(pt)
                return True
        return False

    def _resolve_players(self, text: str):
        tokens: List[str] = []
        ids: List[str] = []
        for raw in split_players(text):
            sid = parse_steam_ref(raw)
            if sid is None and self.registry is not None:
                sid = self.registry.find_by_nick(raw)
            if sid is None:
                tokens.append(raw)
                continue
            if sid in ids:
                continue
            ids.append(sid)
            known = self.registry.nick_of(sid) if self.registry is not None else None
            tokens.append(known or sid)
        return ", ".join(tokens), ids

    def apply_player_update(self, steam_id: str, old_name: str, new_nick: str, is_new: bool = False):
        """Follow a player's rename on every linked base (slot for ``PlayerRegistry.player_changed``).

        ``old_name`` is the previous nickname, or the SteamID while the nickname was still unknown.
        A newly seen nickname also links bases whose free-text players already contain it.
        """
        changed: List[MapPoint] = []
        for pt in self._points:
            tokens = split_players(pt.players)
            linked = steam_id in pt.player_ids
            if not linked and is_new:
                if any(t.casefold() == new_nick.casefold() for t in tokens):
                    pt.player_ids.append(steam_id)
                    linked = True
                    changed.append(pt)
            if not linked:
                continue
            old_keys = {old_name.casefold(), steam_id}
            new_tokens = [new_nick if t.casefold() in old_keys else t for t in tokens]
            if new_nick not in new_tokens:
                new_tokens.append(new_nick)
            deduped: List[str] = []
            for t in new_tokens:
                if t.casefold() not in {d.casefold() for d in deduped}:
                    deduped.append(t)
            text = ", ".join(deduped)
            if text != pt.players:
                pt.players = text
                if pt not in changed:
                    changed.append(pt)
        if changed:
            self.save()
            for pt in changed:
                self.point_updated.emit(pt)

    def describe_players(self, point: MapPoint) -> List[Tuple[str, Optional[str]]]:
        """[(label, steam_id or None)] for a base: linked players first, then plain-text names."""
        result: List[Tuple[str, Optional[str]]] = []
        seen = set()
        for sid in point.player_ids:
            nick = (self.registry.nick_of(sid) if self.registry is not None else None) or sid
            result.append((nick, sid))
            seen.update({nick.casefold(), sid})
        for token in split_players(point.players):
            if token.casefold() not in seen:
                result.append((token, None))
        return result

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
