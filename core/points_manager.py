import json
import os
from typing import List, Optional, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal

from core.coordinate_parser import MapPoint, POINT_CATEGORIES, detect_category_from_name
from core.config_manager import get_portable_config_path


class PointsManager(QObject):
    """
    Менеджер збережених точок координат:
    - Зберігає точки у файлі points.json (поряд із config.json або .exe)
    - Гарантує збереження між перезапусками гри та додатку
    - Сортує точки від нових до старих
    - Сповіщає інтерфейс через PyQt сигнали
    """
    point_added = pyqtSignal(object)      # MapPoint
    point_updated = pyqtSignal(object)    # MapPoint
    point_deleted = pyqtSignal(str)       # point_id
    points_cleared = pyqtSignal()

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
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            try:
                                pt = MapPoint.from_dict(item)
                                self._points.append(pt)
                            except Exception as pe:
                                print(f"[PointsManager] Помилка читання точки: {pe}")
            except Exception as e:
                print(f"[PointsManager] Помилка завантаження {self.file_path}: {e}")

        # Сортуємо від найновіших до найстаріших
        self._points.sort(key=lambda p: p.created_timestamp, reverse=True)

    def save(self):
        try:
            parent_dir = os.path.dirname(self.file_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            data = [p.to_dict() for p in self._points]
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[PointsManager] Помилка збереження {self.file_path}: {e}")

    def add_point(self, point: MapPoint) -> bool:
        # Захист від дублікатів (однакові координати менше ніж за 2 секунди)
        if self._points:
            first = self._points[0]
            if first.raw_coord == point.raw_coord and abs(first.created_timestamp - point.created_timestamp) < 2.0:
                return False

        # Додаємо на початок списку (найновіша точка зверху)
        self._points.insert(0, point)
        self.save()
        self.point_added.emit(point)
        return True

    def update_point_name(self, point_id: str, new_name: str) -> bool:
        clean_name = new_name.strip() if new_name.strip() else "None"
        for pt in self._points:
            if pt.id == point_id:
                pt.name = clean_name
                # Якщо категорія ще стандартна, спробуємо визначити її з нової назви
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
                # Якщо колір був за замовчуванням для старої категорії, оновимо до нової
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
