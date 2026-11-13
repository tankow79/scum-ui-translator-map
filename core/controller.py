"""Application controller: routes chat messages through filtering, translation and history."""

import logging
import threading
import time
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

        # Messages are shown in chat order even though translations finish at different times
        self._order_lock = threading.Lock()
        self._next_ticket = 0          # next ticket handed out
        self._next_to_show = 0         # next ticket allowed to be shown
        self._ticket_times = {}        # ticket -> creation time
        self._finished = {}            # ticket -> publish arguments waiting for earlier tickets
        self._flush_pending = False

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
            self._publish_in_order(self._take_ticket(), time_str, sender, result.message, result.message, "orig", msg_type)
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
                self._publish_in_order(self._take_ticket(), time_str, sender, msg, msg, detected or "orig", msg_type)
                return

        self.executor.submit(self._async_translate, self._take_ticket(), time_str, sender, msg, msg_type)

    # A translation that hangs must not hold back the whole chat: later messages wait at most this long.
    ORDER_WAIT_SECONDS = 6.0

    def _take_ticket(self) -> int:
        with self._order_lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._ticket_times[ticket] = time.monotonic()
            return ticket

    def _publish_in_order(self, ticket: int, *args):
        """Show a finished message once every earlier message has been shown (or has waited too long)."""
        with self._order_lock:
            self._ticket_times.pop(ticket, None)
            if ticket < self._next_to_show:
                ready, waiting = [args], False           # it was skipped as too slow: show it now
            else:
                self._finished[ticket] = args
                ready, waiting = self._drain()
            # Publish while still holding the lock: two threads must not show neighbouring tickets crosswise
            for item in ready:
                self._publish(*item)
            self._schedule_flush(waiting, self.ORDER_WAIT_SECONDS + 0.2)

    def _schedule_flush(self, waiting: bool, delay: float):
        """At most one pending timer; must be called with ``_order_lock`` held."""
        if not waiting or self._flush_pending:
            return
        self._flush_pending = True
        timer = threading.Timer(delay, self._flush_stale)
        timer.daemon = True
        timer.start()

    def _drain(self):
        """(messages now allowed to be shown, whether finished ones are still waiting for a slow earlier one).

        Must be called with ``_order_lock`` held.
        """
        ready = []
        while self._finished:
            if self._next_to_show in self._finished:
                ready.append(self._finished.pop(self._next_to_show))
                self._next_to_show += 1
            elif time.monotonic() - self._ticket_times.get(self._next_to_show, 0.0) > self.ORDER_WAIT_SECONDS:
                self._next_to_show += 1                  # give up waiting for the slow one in front
            else:
                break
        return ready, bool(self._finished)

    def _flush_stale(self):
        with self._order_lock:
            self._flush_pending = False
            ready, waiting = self._drain()
            for item in ready:
                self._publish(*item)
            self._schedule_flush(waiting, 1.0)

    def _async_translate(self, ticket: int, time_str: str, sender: str, msg: str, msg_type: str):
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

        self._publish_in_order(ticket, time_str, sender, msg, translated, src_lang, msg_type)

    def _publish(self, time_str: str, sender: str, original: str, translated: str,
                 src_lang: str, msg_type: str):
        if self.history is not None and self.cfg.get("history_enabled", True):
            self.history.add(time_str, sender, original, translated, src_lang, msg_type)
        self.translated_ready.emit(time_str, sender, original, translated, src_lang, msg_type)
