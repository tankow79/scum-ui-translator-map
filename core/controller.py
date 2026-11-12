"""Application controller: routes chat messages through filtering, translation and history."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.chat_history import ChatHistory
from core.config_manager import ConfigManager
from core.coordinate_parser import parse_chat_coordinate
from core.language_detect import base_lang, is_same_language, quick_detect
from core.message_filter import ChatFilter, FilterAction, split_list
from core.translator import GoogleTranslatorEngine

log = logging.getLogger("scum.controller")


class AppController(QObject):
    raw_message_received = pyqtSignal(str, str, str, str)  # time, sender, msg, msg_type
    translated_ready = pyqtSignal(str, str, str, str, str, str)  # time, sender, orig, trans, src, type
    coordinate_detected = pyqtSignal(object)  # MapPoint
    hotkey_toggle_lock = pyqtSignal()
    hotkey_toggle_visibility = pyqtSignal()
    hotkey_chat_opened = pyqtSignal()
    hotkey_escape_pressed = pyqtSignal()
    hotkey_enter_pressed = pyqtSignal()
    hotkey_toggle_map = pyqtSignal()

    def __init__(self, cfg: ConfigManager, translator: GoogleTranslatorEngine,
                 history: Optional[ChatHistory] = None, chat_filter: Optional[ChatFilter] = None):
        super().__init__()
        self.cfg = cfg
        self.translator = translator
        self.history = history
        self.chat_filter = chat_filter or ChatFilter(cfg.config)
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="translate")

        self.raw_message_received.connect(self._handle_raw_message)

    # ── incoming messages ────────────────────────────────────────────
    def _handle_raw_message(self, time_str: str, sender: str, msg: str, msg_type: str):
        # 1. Coordinates are always harvested for the map, even from own messages.
        point = parse_chat_coordinate(msg, time_str)
        if point:
            self.coordinate_detected.emit(point)

        # 2. "Map only" mode: no chat output at all.
        if not self.cfg.get("enable_chat_translator", True):
            return

        own_nick = str(self.cfg.get("own_nickname", "")).lower()
        if self.cfg.get("ignore_own_messages", False) and own_nick and sender.lower() == own_nick:
            return

        # 3. Blacklists (nicknames and blocked words).
        result = self.chat_filter.evaluate(sender, msg)
        if result.action is FilterAction.HIDE:
            return
        if result.action is FilterAction.ORIGINAL:
            self._publish(time_str, sender, result.message, result.message, "orig", msg_type)
            return
        msg = result.message  # masked text for FilterAction.MASK, unchanged otherwise

        # 4. Offline pre-check: skip the network round-trip when the text is already in the target language.
        if self.cfg.get("autodetect_enabled", True):
            min_len = int(self.cfg.get("autodetect_min_length", 3))
            detected = quick_detect(msg, min_len)
            skip = split_list(self.cfg.get("autodetect_skip_languages", []))
            if self.cfg.get("autodetect_skip_target_language", True):
                skip.append(self.translator.target_lang)
            if is_same_language(detected, skip):
                self._publish(time_str, sender, msg, msg, detected or "orig", msg_type)
                return

        self.executor.submit(self._async_translate, time_str, sender, msg, msg_type)

    def _async_translate(self, time_str: str, sender: str, msg: str, msg_type: str):
        try:
            translated, src_lang = self.translator.translate(msg)
        except Exception:  # never let a worker thread die silently
            log.exception("Translation failed")
            translated, src_lang = msg, "unknown"

        # Post-check with the language reported by the translation service.
        if self.cfg.get("autodetect_enabled", True) and src_lang not in ("", "unknown", "auto"):
            skip = split_list(self.cfg.get("autodetect_skip_languages", []))
            if self.cfg.get("autodetect_skip_target_language", True):
                skip.append(self.translator.target_lang)
            if is_same_language(base_lang(src_lang), skip):
                translated = msg

        self._publish(time_str, sender, msg, translated, src_lang, msg_type)

    def _publish(self, time_str: str, sender: str, original: str, translated: str,
                 src_lang: str, msg_type: str):
        if self.history is not None and self.cfg.get("history_enabled", True):
            self.history.add(time_str, sender, original, translated, src_lang, msg_type)
        self.translated_ready.emit(time_str, sender, original, translated, src_lang, msg_type)
