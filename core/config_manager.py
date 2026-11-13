import copy
import json
import logging
import math
import os
import sys
import threading
from contextlib import contextmanager
from typing import Any, Dict, Optional

from core.fileio import atomic_write_json, quarantine_corrupt

log = logging.getLogger("scum.config")

DEFAULT_CONFIG: Dict[str, Any] = {
    "log_file_path": r"%LOCALAPPDATA%\SCUM\Saved\Logs\SCUM.log",
    "target_language": "uk",
    "source_language": "auto",
    "outgoing_my_lang": "uk",
    "outgoing_target_lang": "en",
    "ui_display_mode": "both",  # "none", "border_only", "scrollbar_only", "both"
    "overlay_x": -1,            # -1: automatic adaptive positioning for the player's screen
    "overlay_y": -1,
    "overlay_width": 640,
    "overlay_height": 340,
    "quick_chat_x": -1,
    "quick_chat_y": -1,
    "font_size": 22,  # matches the in-game chat size at 1080p
    "font_bold": False,
    "text_outline": True,       # Black text outline for maximum readability on any background
    "message_fade_timeout": 10,  # Seconds a message stays on screen (0 = never fade)
    "game_chat_key": "T",        # Key that opens the chat in SCUM
    "bg_opacity": 0.5,
    "max_messages": 20,
    "show_original": True,
    "slang_mode": "translate",   # chat abbreviations (GG, BRB ...): "translate", "expand" (English) or "keep"
    "show_timestamp": True,
    "ignore_own_messages": False,
    "own_nickname": "",
    "blacklist_nicknames": [],  # Players whose messages are not translated (kept in the original language)
    "collect_steam_ids": True,  # Read SteamIDs/nicknames from the game logs (Settings -> Players)
    "squad_nicknames": [],  # Squadmates shown in green in the overlay chat
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
    "auto_check_updates": True,
    "enable_chat_translator": True,   # Allows fully disabling chat and log parser ("Map only" mode)
    "ui_language": "en",              # UI language code; any assets/locales/<code>.json file
    "auto_start": True,               # Launch with Windows
    # Updates
    "update_check_interval_hours": 6, # Background re-check interval (0 = only at startup)
    # Word blacklist
    "blacklist_words_enabled": False,
    "blacklist_words": [],
    "blacklist_words_action": "mask",  # "mask" | "hide" | "no_translate"
    "blacklist_words_whole_word": True,
    "blacklist_words_case_sensitive": False,
    # Language auto-detection
    "autodetect_enabled": True,
    "autodetect_skip_target_language": True,
    "autodetect_skip_languages": [],
    "autodetect_min_length": 3,
    # Chat history
    "history_enabled": True,
    "history_save_to_disk": True,
    "history_max_entries": 5000
}


def get_portable_config_path(filename: str = "config.json") -> str:
    """
    Returns the absolute path to config.json next to the executable (.exe)
    or next to the project root when running from Python.
    This keeps the app fully portable across computers.
    """
    override = os.environ.get("SCUM_DATA_DIR")
    if override:
        base_dir = override
    elif getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        # Project folder (one level above core/)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not override and not _is_writable_dir(base_dir):
        # The program sits in a read-only place (Program Files, a write-protected drive): keep the settings and
        # waypoints in the user's own data folder instead of losing them silently at every restart.
        from core.paths import get_user_data_dir
        base_dir = get_user_data_dir()
    return os.path.join(base_dir, filename)


_WRITABLE_CACHE: Dict[str, bool] = {}


def _is_writable_dir(path: str) -> bool:
    """True when a file can be created in ``path`` (checked once per folder; os.access is unreliable on Windows)."""
    cached = _WRITABLE_CACHE.get(path)
    if cached is not None:
        return cached
    probe = os.path.join(path, f".write_test_{os.getpid()}")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
        ok = True
    except OSError:
        ok = False
    _WRITABLE_CACHE[path] = ok
    return ok


class ConfigManager:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = get_portable_config_path("config.json")
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()   # snapshot + write happen together, so an older snapshot never lands last
        self._batch_depth = 0
        self._dirty = False
        self.load()

    def load(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        raise ValueError("config.json is not a JSON object")
                    self.config = self._sanitize({**copy.deepcopy(DEFAULT_CONFIG), **data})
            except Exception as e:
                log.warning("Failed to load %s: %s; using default settings.", self.config_path, e)
                quarantine_corrupt(self.config_path)  # keep the unreadable file; the next save must not erase it
                self.config = copy.deepcopy(DEFAULT_CONFIG)
        else:
            self.config = copy.deepcopy(DEFAULT_CONFIG)
            self.save()
        return self.config

    @staticmethod
    def sanitize_values(values: Dict[str, Any]) -> Dict[str, Any]:
        """The given settings with every wrong-typed value replaced by its default (used for stored profiles)."""
        clean = ConfigManager._sanitize({**copy.deepcopy(DEFAULT_CONFIG), **values})
        return {k: clean[k] for k in values if k in DEFAULT_CONFIG}

    @staticmethod
    def _sanitize(config: Dict[str, Any]) -> Dict[str, Any]:
        """Replace a hand-edited value of the wrong type by the default (a bad value must not crash start-up)."""
        for key, default in DEFAULT_CONFIG.items():
            value = config.get(key, default)
            ok = True
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, (int, float)):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                if ok and isinstance(default, int) and isinstance(value, float):
                    value = int(value)
            elif isinstance(default, str):
                ok = isinstance(value, str)
            elif isinstance(default, list):
                ok = isinstance(value, (list, str))   # nickname/word lists may also be comma separated text
            elif isinstance(default, dict):
                ok = isinstance(value, dict)
            if ok:
                config[key] = value
            else:
                log.warning("config.json: %r has an invalid value %r; using the default", key, value)
                config[key] = copy.deepcopy(default)
        return config

    def save(self):
        try:
            with self._save_lock:
                with self._lock:
                    snapshot = copy.deepcopy(self.config)
                atomic_write_json(self.config_path, snapshot)
        except Exception as e:
            log.error("Failed to save config.json: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any, save: bool = True):
        with self._lock:
            self.config[key] = value
            if not save:
                return
            if self._batch_depth > 0:
                self._dirty = True
                return
        self.save()

    @contextmanager
    def batch(self):
        """Group many ``set`` calls into a single write of config.json."""
        with self._lock:
            self._batch_depth += 1
        try:
            yield self
        finally:
            with self._lock:
                self._batch_depth -= 1
                flush = self._batch_depth == 0 and self._dirty
                if flush:
                    self._dirty = False
            if flush:
                self.save()

    def update(self, values: Dict[str, Any]):
        """Set several keys and write the file once."""
        with self._lock:
            self.config.update(values)
        self.save()

    def get_resolved_log_path(self) -> str:
        raw_path = self.get("log_file_path", r"%LOCALAPPDATA%\SCUM\Saved\Logs\SCUM.log")
        expanded = os.path.expandvars(raw_path)
        return os.path.normpath(expanded)
