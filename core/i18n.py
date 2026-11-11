import json
import os
import sys
from typing import Dict, Any, Optional

DEFAULT_LOCALE = "uk"
FALLBACK_LOCALE = "en"

class LocalizationManager:
    """
    Керує багатомовністю додатку (i18n).
    Підтримує 'uk', 'en', 'ru' з авто-фолбеком на англійську та українську.
    Підтримує динамічну зміну мови без перезапуску.
    """
    _instance: Optional['LocalizationManager'] = None

    def __init__(self, current_locale: str = DEFAULT_LOCALE):
        self.current_locale = current_locale
        self.translations: Dict[str, Dict[str, Any]] = {}
        self._load_locales()

    @classmethod
    def get_instance(cls, current_locale: str = DEFAULT_LOCALE) -> 'LocalizationManager':
        if cls._instance is None:
            cls._instance = LocalizationManager(current_locale)
        return cls._instance

    def _get_locales_dir(self) -> str:
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        locales_dir = os.path.join(base_dir, "assets", "locales")
        return locales_dir

    def _load_locales(self):
        locales_dir = self._get_locales_dir()
        for lang in ("uk", "en", "ru"):
            file_path = os.path.join(locales_dir, f"{lang}.json")
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations[lang] = json.load(f)
                except Exception as e:
                    print(f"[i18n] Помилка завантаження {file_path}: {e}")
                    self.translations[lang] = {}
            else:
                self.translations[lang] = {}

    def set_locale(self, locale: str):
        if locale in ("uk", "en", "ru"):
            self.current_locale = locale

    def tr(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        Отримати переклад за ключем виду 'tray.open_map', 'settings.general.title'.
        """
        val = self._lookup(self.current_locale, key)
        if val is None and self.current_locale != FALLBACK_LOCALE:
            val = self._lookup(FALLBACK_LOCALE, key)
        if val is None and self.current_locale != DEFAULT_LOCALE:
            val = self._lookup(DEFAULT_LOCALE, key)

        if val is None:
            val = default if default is not None else key

        if kwargs:
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return val

    def _lookup(self, lang: str, key_path: str) -> Optional[str]:
        data = self.translations.get(lang, {})
        parts = key_path.split(".")
        for part in parts:
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return None
        return str(data) if data is not None else None


def tr(key: str, default: Optional[str] = None, **kwargs) -> str:
    """Глобальна функція-скорочення для перекладу."""
    return LocalizationManager.get_instance().tr(key, default=default, **kwargs)
