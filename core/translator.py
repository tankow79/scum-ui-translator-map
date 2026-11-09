import requests
import re
import threading
from typing import Tuple, Dict, Optional, List

class GoogleTranslatorEngine:
    """
    Надійний багатосерверний двигун перекладу через Google Translate API.
    Автоматично ротує хости при затримках, кешує результати та захищений від таймаутів.
    """
    HOSTS = [
        "clients1.google.com",
        "clients2.google.com",
        "clients4.google.com",
        "clients5.google.com"
    ]

    def __init__(self, target_lang: str = "uk", source_lang: str = "auto", api_key: Optional[str] = None):
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.api_key = api_key
        self._cache: Dict[str, Tuple[str, str]] = {}  # key -> (translated_text, src_lang)
        self._lock = threading.Lock()
        self._host_index = 0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })

    def update_settings(self, target_lang: str, source_lang: str = "auto"):
        with self._lock:
            if self.target_lang != target_lang or self.source_lang != source_lang:
                self.target_lang = target_lang
                self.source_lang = source_lang
                self._cache.clear()

    def translate(self, text: str) -> Tuple[str, str]:
        """
        Переклад вхідних повідомлень (за замовчуванням: source_lang -> target_lang).
        """
        return self.translate_custom(text, self.target_lang, self.source_lang)

    def translate_custom(self, text: str, target: str, source: str = "auto") -> Tuple[str, str]:
        """
        Універсальний переклад будь-якого тексту між будь-якими обраними мовами.
        """
        clean_text = text.strip()
        if not clean_text:
            return "", "unknown"

        # Перевірка кешу
        cache_key = f"{source}->{target}:{clean_text}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        # Не перекладати суто посилання, координати або цифри
        if re.match(r"^https?://\S+$", clean_text) or clean_text.isdigit():
            return clean_text, "auto"

        # Якщо є офіційний API ключ
        if self.api_key:
            res = self._translate_with_api_key(clean_text, target, source)
            with self._lock:
                self._cache[cache_key] = res
            return res

        # Ротація та відмовостійкий переклад через сервери Google
        res = self._translate_with_fallbacks(clean_text, target, source)
        with self._lock:
            self._cache[cache_key] = res
        return res

    def _translate_with_fallbacks(self, text: str, target: str, source: str) -> Tuple[str, str]:
        # Спробуємо послідовно доступні хости Google
        num_hosts = len(self.HOSTS)
        start_idx = self._host_index

        for attempt in range(num_hosts):
            host = self.HOSTS[(start_idx + attempt) % num_hosts]
            url = f"https://{host}/translate_a/t"
            params = {
                "client": "dict-chrome-ex",
                "sl": source,
                "tl": target,
                "q": text
            }
            try:
                # Таймаут: 2.5с на з'єднання, 5с на читання
                r = self.session.get(url, params=params, timeout=(2.5, 5.0))
                if r.status_code == 200:
                    data = r.json()
                    # Запам'ятовуємо робочий хост
                    self._host_index = (start_idx + attempt) % num_hosts

                    if isinstance(data, list) and len(data) > 0:
                        first = data[0]
                        if isinstance(first, list) and len(first) >= 2:
                            return str(first[0]), str(first[1])
                        elif isinstance(first, list) and len(first) == 1:
                            return str(first[0]), source
                        elif isinstance(first, str):
                            return first, source
            except Exception as e:
                # Тихо переходимо до наступного сервера Google
                continue

        # Якщо всі хости не відповіли, повертаємо оригінал без аварійного завершення
        print(f"[Translator] Увага: Не вдалося отримати переклад для: '{text[:40]}...' (усі сервери зайняті)")
        return text, "unknown"

    def _translate_with_api_key(self, text: str, target: str, source: str) -> Tuple[str, str]:
        url = f"https://translation.googleapis.com/language/translate/v2?key={self.api_key}"
        payload = {
            "q": text,
            "target": target,
            "format": "text"
        }
        if source != "auto":
            payload["source"] = source

        try:
            r = self.session.post(url, json=payload, timeout=(3.0, 6.0))
            if r.status_code == 200:
                data = r.json()
                trans_obj = data["data"]["translations"][0]
                translated = trans_obj["translatedText"]
                src = trans_obj.get("detectedSourceLanguage", source)
                return translated, src
        except Exception as e:
            print(f"[Translator API] Помилка: {e}")
        return text, "unknown"
