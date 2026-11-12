"""Chat history store with filtering, optional on-disk persistence and export."""

import csv
import json
import logging
import os
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Deque, Dict, Iterable, List, Optional

log = logging.getLogger("scum.history")

EXPORT_FORMATS = ("txt", "csv", "json")


@dataclass
class HistoryEntry:
    timestamp: str      # ISO-8601 local time
    time_str: str       # HH:MM:SS as shown in game
    sender: str
    original: str
    translated: str
    src_lang: str
    msg_type: str       # player | squad | server

    @property
    def was_translated(self) -> bool:
        return bool(self.translated) and self.translated != self.original


class ChatHistory:
    """Thread-safe bounded history. ``revision`` increments on every change so UIs can poll cheaply."""

    def __init__(self, max_entries: int = 5000, path: Optional[str] = None):
        self.max_entries = max(1, int(max_entries))
        self.path = path
        self._entries: Deque[HistoryEntry] = deque(maxlen=self.max_entries)
        self._lock = threading.Lock()
        self.revision = 0
        self._lines_on_disk = 0
        if self.path:
            self._load()

    # ── mutation ─────────────────────────────────────────────────────
    def add(self, time_str: str, sender: str, original: str, translated: str,
            src_lang: str, msg_type: str) -> HistoryEntry:
        entry = HistoryEntry(datetime.now().isoformat(timespec="seconds"), time_str, sender,
                             original, translated, src_lang, msg_type)
        with self._lock:
            self._entries.append(entry)
            self.revision += 1
            self._append_to_disk(entry)
        return entry

    def clear(self):
        with self._lock:
            self._entries.clear()
            self.revision += 1
            if self.path:
                try:
                    if os.path.exists(self.path):
                        os.remove(self.path)
                except OSError as exc:
                    log.warning("Could not delete history file: %s", exc)
                self._lines_on_disk = 0

    def set_max_entries(self, value: int):
        value = max(1, int(value))
        with self._lock:
            if value != self.max_entries:
                self.max_entries = value
                self._entries = deque(self._entries, maxlen=value)
                self.revision += 1

    # ── queries ──────────────────────────────────────────────────────
    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def senders(self) -> List[str]:
        with self._lock:
            return sorted({e.sender for e in self._entries}, key=str.lower)

    def query(self, text: str = "", sender: str = "", msg_type: str = "",
              translated_only: bool = False) -> List[HistoryEntry]:
        needle = text.strip().lower()
        with self._lock:
            snapshot = list(self._entries)
        result = []
        for e in snapshot:
            if sender and e.sender != sender:
                continue
            if msg_type and e.msg_type != msg_type:
                continue
            if translated_only and not e.was_translated:
                continue
            if needle and needle not in e.original.lower() and needle not in e.translated.lower() \
                    and needle not in e.sender.lower():
                continue
            result.append(e)
        return result

    # ── export ───────────────────────────────────────────────────────
    def export(self, path: str, entries: Optional[Iterable[HistoryEntry]] = None,
               fmt: Optional[str] = None) -> int:
        """Write entries to ``path``. Format is taken from ``fmt`` or the file extension. Returns the row count."""
        rows = list(entries) if entries is not None else self.query()
        fmt = (fmt or os.path.splitext(path)[1].lstrip(".") or "txt").lower()
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"Unsupported export format: {fmt}")

        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump([asdict(e) for e in rows], f, ensure_ascii=False, indent=2)
        elif fmt == "csv":
            with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM: Excel-friendly
                writer = csv.writer(f)
                writer.writerow(["timestamp", "type", "sender", "original", "translated", "language"])
                for e in rows:
                    writer.writerow([e.timestamp, e.msg_type, e.sender, e.original, e.translated, e.src_lang])
        else:
            with open(path, "w", encoding="utf-8") as f:
                for e in rows:
                    line = f"[{e.timestamp}] [{e.msg_type}] {e.sender}: {e.original}"
                    if e.was_translated:
                        line += f"  =>  {e.translated}"
                    f.write(line + "\n")
        return len(rows)

    # ── persistence ──────────────────────────────────────────────────
    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    self._lines_on_disk += 1
                    try:
                        data: Dict = json.loads(line)
                        self._entries.append(HistoryEntry(**data))
                    except (ValueError, TypeError):
                        continue
        except OSError as exc:
            log.warning("Could not read history file: %s", exc)
        if self._lines_on_disk > self.max_entries * 2:
            self._rewrite_disk()

    def _append_to_disk(self, entry: HistoryEntry):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
            self._lines_on_disk += 1
            if self._lines_on_disk > self.max_entries * 2:
                self._rewrite_disk()
        except OSError as exc:
            log.warning("Could not write history file: %s", exc)

    def _rewrite_disk(self):
        """Compact the JSONL file to the entries currently kept in memory (atomic replace)."""
        if not self.path:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for e in self._entries:
                    f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
            self._lines_on_disk = len(self._entries)
        except OSError as exc:
            log.warning("Could not compact history file: %s", exc)
