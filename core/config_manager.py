import json
import os
import sys
from typing import Any, Dict, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "log_file_path": r"%LOCALAPPDATA%\SCUM\Saved\Logs\SCUM.log",
    "target_language": "uk",
    "source_language": "auto",
    "outgoing_my_lang": "uk",
    "outgoing_target_lang": "en",
    "ui_display_mode": "both",  # "none", "border_only", "scrollbar_only", "both"
    "overlay_x": -1,            # -1: автоматичне адаптивне позиціонування під екран гравця
    "overlay_y": -1,
    "overlay_width": 640,
    "overlay_height": 340,
    "quick_chat_x": -1,
    "quick_chat_y": -1,
    "font_size": 13,
    "font_bold": False,
    "text_outline": True,       # Чорна обводка тексту для максимальної читабельності на будь-якому фоні
    "message_fade_timeout": 10,  # Секунди життя повідомлення в грі (0 - ніколи не зникати)
    "game_chat_key": "T",        # Клавіша відкриття чату в SCUM
    "bg_opacity": 0.5,
    "max_messages": 20,
    "show_original": True,
    "show_timestamp": True,
    "ignore_own_messages": False,
    "own_nickname": "",
    "blacklist_nicknames": [],  # Список гравців, повідомлення яких не перекладаються (мовою оригіналу)
    "hotkey_toggle_lock": "F9",
    "hotkey_toggle_visibility": "F8",
    "hotkey_quick_chat": "T",
    "quick_chat_auto_copy": True,
    "overlay_enabled": True,
    "status_badge_enabled": True,
    "status_badge_x": -1,
    "status_badge_y": -1,
    "hotkey_toggle_map": "Ctrl+M",
    "map_variant": "regular",   # "regular" or "tactical"
    "map_show_grid": True,
    "map_show_keypads": True,
    "auto_focus_new_point": True,
    "map_on_top": True,
    "map_x": -1,
    "map_y": -1,
    "map_width": 960,
    "map_height": 660,
    "points_x": -1,
    "points_y": -1,
    "points_width": 960,
    "points_height": 240,
    "auto_check_updates": True
}


def get_portable_config_path(filename: str = "config.json") -> str:
    """
    Повертає абсолютний шлях до config.json поруч із виконуваним файлом (.exe)
    або поруч із коренем проєкту при запуску з Python.
    Це гарантує 100% портативність при перенесенні на інший комп'ютер.
    """
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        # Папка проєкту (на рівень вище core/)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, filename)


class ConfigManager:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = get_portable_config_path("config.json")
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.config = {**DEFAULT_CONFIG, **data}
            except Exception as e:
                print(f"[Config] Помилка завантаження {self.config_path}: {e}, використовуються стандартні налаштування.")
                self.config = DEFAULT_CONFIG.copy()
        else:
            self.config = DEFAULT_CONFIG.copy()
            self.save()
        return self.config

    def save(self):
        try:
            # Створюємо директорію, якщо вона ще не існує
            parent_dir = os.path.dirname(self.config_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Помилка збереження config.json: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        self.config[key] = value
        self.save()

    def get_resolved_log_path(self) -> str:
        raw_path = self.get("log_file_path", r"%LOCALAPPDATA%\SCUM\Saved\Logs\SCUM.log")
        expanded = os.path.expandvars(raw_path)
        return os.path.normpath(expanded)
