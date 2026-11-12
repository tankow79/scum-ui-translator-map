"""User-interface localisation.

Every ``assets/locales/<code>.json`` file is discovered automatically, so adding a language is just
dropping a new file into that folder (copy ``en.json``, translate the values, keep the keys).
Optional metadata inside a file::

    "_meta": {"name": "Deutsch"}      # label shown in the Language tab (defaults to the code)

Missing keys fall back to English.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("scum.i18n")

DEFAULT_LOCALE = "en"
FALLBACK_LOCALE = "en"


class LocalizationManager:
    _instance: Optional["LocalizationManager"] = None

    def __init__(self, current_locale: str = DEFAULT_LOCALE, locales_dir: Optional[str] = None):
        self.current_locale = current_locale
        self._locales_dir = locales_dir
        self.translations: Dict[str, Dict[str, Any]] = {}
        self._load_locales()
        if self.current_locale not in self.translations:
            self.current_locale = DEFAULT_LOCALE

    @classmethod
    def get_instance(cls, current_locale: str = DEFAULT_LOCALE) -> "LocalizationManager":
        if cls._instance is None:
            cls._instance = LocalizationManager(current_locale)
        return cls._instance

    def _get_locales_dir(self) -> str:
        if self._locales_dir:
            return self._locales_dir
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base_dir, "assets", "locales")

    def _load_locales(self):
        locales_dir = self._get_locales_dir()
        self.translations = {}
        if not os.path.isdir(locales_dir):
            return
        for fname in sorted(os.listdir(locales_dir)):
            code, ext = os.path.splitext(fname)
            if ext.lower() != ".json" or code.startswith("_"):
                continue
            try:
                with open(os.path.join(locales_dir, fname), encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.translations[code] = data
            except (OSError, ValueError) as exc:
                log.warning("Could not load locale %s: %s", fname, exc)

    def available_locales(self) -> List[Tuple[str, str]]:
        """Return ``[(code, display_name)]`` for every installed language, English first."""
        result = []
        for code, data in self.translations.items():
            meta = data.get("_meta", {}) if isinstance(data.get("_meta"), dict) else {}
            result.append((code, str(meta.get("name") or code)))
        result.sort(key=lambda item: (item[0] != DEFAULT_LOCALE, item[1].lower()))
        return result

    def set_locale(self, locale: str) -> bool:
        if locale in self.translations:
            self.current_locale = locale
            return True
        return False

    def tr(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """Translate a dotted key such as ``tray.settings``; falls back to English, then to ``default``/key."""
        val = self._lookup(self.current_locale, key)
        if val is None and self.current_locale != FALLBACK_LOCALE:
            val = self._lookup(FALLBACK_LOCALE, key)
        if val is None:
            val = default if default is not None else key
        if kwargs:
            try:
                return val.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return val
        return val

    def _lookup(self, lang: str, key_path: str) -> Optional[str]:
        data: Any = self.translations.get(lang, {})
        for part in key_path.split("."):
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return None
        return str(data) if data is not None else None


def tr(key: str, default: Optional[str] = None, **kwargs) -> str:
    """Shortcut for :meth:`LocalizationManager.tr` on the global instance."""
    return LocalizationManager.get_instance().tr(key, default=default, **kwargs)
