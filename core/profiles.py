"""Settings profiles: named presets of the chat/HUD configuration that can be switched on demand.

A profile stores only the keys listed in ``PROFILE_KEYS`` (translation, filtering and HUD look).
Personal data such as hotkeys, window positions and the log path are never part of a profile.
Profiles live in ``profiles.json`` next to ``config.json``.
"""

import copy
import json
import logging
import os
from typing import Any, Dict, List, Optional

from core.config_manager import ConfigManager, get_portable_config_path

log = logging.getLogger("scum.profiles")

DEFAULT_PROFILE = "Default"

PROFILE_KEYS = (
    "target_language", "source_language", "enable_chat_translator", "overlay_enabled",
    "show_original", "show_timestamp", "ignore_own_messages",
    "ui_display_mode", "font_size", "font_bold", "text_outline",
    "bg_opacity", "max_messages", "message_fade_timeout",
    "blacklist_nicknames", "squad_nicknames", "blacklist_words_enabled", "blacklist_words",
    "blacklist_words_action", "blacklist_words_whole_word", "blacklist_words_case_sensitive",
    "autodetect_enabled", "autodetect_skip_target_language", "autodetect_skip_languages",
    "autodetect_min_length",
)


class ProfileManager:
    def __init__(self, cfg: ConfigManager, path: Optional[str] = None):
        self.cfg = cfg
        self.path = path or get_portable_config_path("profiles.json")
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.active: str = DEFAULT_PROFILE
        self._load()
        if DEFAULT_PROFILE not in self.profiles:
            self.profiles[DEFAULT_PROFILE] = self._snapshot()
            self._save()

    # ── helpers ──────────────────────────────────────────────────────
    def _snapshot(self) -> Dict[str, Any]:
        return {k: copy.deepcopy(self.cfg.get(k)) for k in PROFILE_KEYS if k in self.cfg.config}

    def names(self) -> List[str]:
        return list(self.profiles.keys())

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", {})
            if isinstance(profiles, dict):
                self.profiles = {str(n): {k: v for k, v in p.items() if k in PROFILE_KEYS}
                                 for n, p in profiles.items() if isinstance(p, dict)}
            active = data.get("active")
            if isinstance(active, str) and active in self.profiles:
                self.active = active
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Could not load profiles (%s); starting fresh.", exc)

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"active": self.active, "profiles": self.profiles}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("Could not save profiles: %s", exc)

    @staticmethod
    def _clean_name(name: str) -> str:
        return " ".join(name.split())[:40]

    # ── operations ───────────────────────────────────────────────────
    def create(self, name: str) -> str:
        """Create a profile from the current settings. Returns the stored name."""
        name = self._clean_name(name)
        if not name:
            raise ValueError("Profile name is empty")
        if name in self.profiles:
            raise ValueError(f"Profile '{name}' already exists")
        self.profiles[name] = self._snapshot()
        self.active = name
        self._save()
        return name

    def save_current(self, name: Optional[str] = None):
        """Store the live settings into profile ``name`` (default: the active one)."""
        name = name or self.active
        if name not in self.profiles:
            raise KeyError(name)
        self.profiles[name] = self._snapshot()
        self._save()

    def apply(self, name: str) -> bool:
        """Load a profile into the live configuration. The previously active profile is saved first."""
        if name not in self.profiles:
            return False
        if self.active in self.profiles and name != self.active:
            self.profiles[self.active] = self._snapshot()
        for key, value in self.profiles[name].items():
            self.cfg.config[key] = copy.deepcopy(value)
        self.cfg.save()
        self.active = name
        self._save()
        return True

    def delete(self, name: str):
        if name == DEFAULT_PROFILE:
            raise ValueError("The default profile cannot be deleted")
        self.profiles.pop(name, None)
        if self.active == name:
            self.apply(DEFAULT_PROFILE)
        else:
            self._save()

    def rename(self, old: str, new: str) -> str:
        new = self._clean_name(new)
        if old == DEFAULT_PROFILE:
            raise ValueError("The default profile cannot be renamed")
        if not new or new in self.profiles:
            raise ValueError("Invalid or duplicate profile name")
        self.profiles[new] = self.profiles.pop(old)
        if self.active == old:
            self.active = new
        self._save()
        return new

    def cycle(self) -> str:
        """Switch to the next profile (used by the hotkey/tray). Returns the new active name."""
        names = self.names()
        nxt = names[(names.index(self.active) + 1) % len(names)] if self.active in names else names[0]
        self.apply(nxt)
        return nxt
