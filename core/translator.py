import logging
import re
import threading
import time
from typing import Dict, Optional, Tuple

import requests

log = logging.getLogger("scum.translator")

class GoogleTranslatorEngine:
    """
    Reliable multi-host translation engine using the Google Translate API.
    Automatically rotates hosts on delays, caches results and is protected against timeouts.
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
        self._cache: Dict[str, Tuple[str, str]] = {}  # key -> (translated_text, src_lang); successes only
        self._lock = threading.Lock()
        self._host_index = 0
        self._fail_streak = 0          # consecutive messages for which every server failed
        self._blocked_until = 0.0      # circuit breaker: no network attempts until this monotonic time
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })

    # One message never spends more than this on the network, however many servers are tried: the chat keeps
    # its order only while translations finish before ``AppController.ORDER_WAIT_SECONDS``.
    TIME_BUDGET_SECONDS = 7.0

    def update_settings(self, target_lang: str, source_lang: str = "auto"):
        with self._lock:
            if self.target_lang != target_lang or self.source_lang != source_lang:
                self.target_lang = target_lang
                self.source_lang = source_lang
                self._cache.clear()

    def translate(self, text: str) -> Tuple[str, str]:
        """
        Translates incoming messages (default: source_lang -> target_lang).
        """
        return self.translate_custom(text, self.target_lang, self.source_lang)

    def translate_custom(self, text: str, target: str, source: str = "auto") -> Tuple[str, str]:
        """
        Universal translation of any text between any selected languages.
        """
        clean_text = text.strip()
        if not clean_text:
            return "", "unknown"

        # Cache check
        cache_key = f"{source}->{target}:{clean_text}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        # Do not translate pure links, coordinates or numbers
        if re.match(r"^https?://\S+$", clean_text) or clean_text.isdigit():
            return clean_text, "auto"

        # If an official API key is set
        if self.api_key:
            res = self._keep_coordinates(clean_text, self._translate_with_api_key(clean_text, target, source))
            self._cache_put(cache_key, res)
            return res

        # Rotation and fault-tolerant translation via Google servers
        res = self._keep_coordinates(clean_text, self._translate_with_fallbacks(clean_text, target, source))
        self._cache_put(cache_key, res)
        return res

    _COORD_BLOCK = re.compile(r"\{[^{}]*\bX\s*[=:][^{}]*\}", re.IGNORECASE)

    @staticmethod
    def _keep_coordinates(original: str, result: Tuple[str, str]) -> Tuple[str, str]:
        """The translation service localises numbers (``-100000.500`` -> ``-100000,500``). Coordinates must stay
        exactly as sent, so every ``{X=.. Y=.. Z=..}`` block of the translation is replaced by the original one."""
        blocks = GoogleTranslatorEngine._COORD_BLOCK.findall(original)
        if not blocks:
            return result
        text, lang = result
        found = iter(blocks)
        restored = GoogleTranslatorEngine._COORD_BLOCK.sub(lambda m: next(found, m.group(0)), text)
        return restored, lang

    CACHE_LIMIT = 2000

    def _cache_put(self, key: str, result: Tuple[str, str]):
        """Remember a translation. Failures ("unknown") are not cached so a network blip is not permanent."""
        if result[1] == "unknown":
            return
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > self.CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))

    def _translate_with_fallbacks(self, text: str, target: str, source: str) -> Tuple[str, str]:
        # Offline / blocked: after repeated failures stop hammering the network (each attempt can take up to
        # 30 s, so a long outage would otherwise queue minutes of stale messages). Originals are shown instead.
        if time.monotonic() < self._blocked_until:
            return text, "unknown"
        # Try the available Google hosts in order
        num_hosts = len(self.HOSTS)
        start_idx = self._host_index

        deadline = time.monotonic() + self.TIME_BUDGET_SECONDS
        for attempt in range(num_hosts):
            remaining = deadline - time.monotonic()
            if remaining < 0.3:
                break
            host = self.HOSTS[(start_idx + attempt) % num_hosts]
            url = f"https://{host}/translate_a/t"
            params = {
                "client": "dict-chrome-ex",
                "sl": source,
                "tl": target,
                "q": text
            }
            try:
                # Timeouts: at most 2.5 s to connect and 5 s to read, and never beyond the message's time budget
                r = self.session.get(url, params=params, timeout=(min(2.5, remaining), min(5.0, remaining)))
                if r.status_code == 200:
                    data = r.json()
                    # Remember the working host
                    self._host_index = (start_idx + attempt) % num_hosts

                    parsed = self._parse_response(data, text, source)
                    if parsed is not None:
                        self._fail_streak = 0
                        return parsed
            except Exception:
                # Silently move on to the next Google server
                continue

        # If all hosts failed, return the original without crashing
        self._fail_streak += 1
        if self._fail_streak >= 2:
            pause = min(60.0, 5.0 * 2 ** (self._fail_streak - 2))      # 5, 10, 20, 40, 60 s
            self._blocked_until = time.monotonic() + pause
        log.warning("Could not get a translation for: '%s...' (all servers busy)", text[:40])
        return text, "unknown"

    _LANG_CODE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")

    @staticmethod
    def _parse_response(data, original: str, source: str) -> Optional[Tuple[str, str]]:
        """Validate what the service sent. A reply that is not plain text (None, numbers, an empty string, a
        2 MB blob) or that carries a nonsense language code must never reach the chat; ``None`` means "try the
        next server"."""
        if not (isinstance(data, list) and data):
            return None
        first = data[0]
        lang = source
        if isinstance(first, list) and first:
            translated = first[0]
            if len(first) >= 2 and isinstance(first[1], str) and GoogleTranslatorEngine._LANG_CODE.match(first[1]):
                lang = first[1]
        elif isinstance(first, str):
            translated = first
        else:
            return None
        if not isinstance(translated, str) or not translated.strip():
            return None
        if len(translated) > max(2000, 8 * len(original)):
            return None
        return translated, lang

    def _translate_with_api_key(self, text: str, target: str, source: str) -> Tuple[str, str]:
        # The key travels in a header, not in the URL: URLs end up in exception messages and log files.
        url = "https://translation.googleapis.com/language/translate/v2"
        headers = {"X-Goog-Api-Key": str(self.api_key)}
        payload = {
            "q": text,
            "target": target,
            "format": "text"
        }
        if source != "auto":
            payload["source"] = source

        try:
            r = self.session.post(url, json=payload, headers=headers, timeout=(3.0, 6.0))
            if r.status_code == 200:
                trans_obj = r.json()["data"]["translations"][0]
                parsed = self._parse_response([[trans_obj["translatedText"], trans_obj.get("detectedSourceLanguage", source)]],
                                              text, source)
                if parsed is not None:
                    return parsed
        except Exception as e:
            log.error("Translation API error: %s", type(e).__name__)   # the message may contain the request URL
        return text, "unknown"
