"""Registry of players seen in the SCUM logs, keyed by their permanent SteamID.

The log line ``Message from user: Nick (7656119...) (hash: ...)`` is the only place that ties a
nickname to a SteamID. The registry is filled automatically: all existing logs are scanned once
(old ones included), then every new line is applied as it is written. Users never type SteamIDs.
"""

import glob
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from core.config_manager import get_portable_config_path
from core.fileio import atomic_write_json, quarantine_corrupt

log = logging.getLogger("scum.players")

STEAM_PROFILE_URL = "https://steamcommunity.com/profiles/{steam_id}"
_STEAM_ID_RE = re.compile(r"(?<!\d)(7656119\d{10})(?!\d)")
_USER_LINE_RE = re.compile(
    r"\[(?P<time>\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}):\d+\]\[\s*\d+\]"
    r"LogSCUM:\s*Message from user:\s*(?P<nick>.+?)\s*\((?P<sid>\d{17})\)\s*\(hash:\s*(?P<hash>[0-9A-Fa-f]+)\)"
)
FORMAT_VERSION = 2
MAX_NICK_HISTORY = 50


def is_steam_id(value: str) -> bool:
    return bool(value) and _STEAM_ID_RE.fullmatch(value) is not None


def steam_profile_url(steam_id: str) -> str:
    return STEAM_PROFILE_URL.format(steam_id=steam_id)


def split_players(text: str) -> List[str]:
    """Split a comma/semicolon/newline separated players string into clean tokens."""
    return [t.strip() for t in re.split(r"[,;\n]", text or "") if t.strip()]


def parse_user_line(line: str) -> Optional[Tuple[str, str, str, float]]:
    """(steam_id, nick, hash, epoch_utc) from a ``Message from user:`` log line, else None."""
    if "Message from user:" not in line:
        return None
    m = _USER_LINE_RE.search(line)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("time"), "%Y.%m.%d-%H.%M.%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        ts = time.time()
    return m.group("sid"), m.group("nick").strip(), m.group("hash").upper(), ts


class PlayerRegistry(QObject):
    """steam_id -> {nick, hash, first_seen, last_seen, previous_nicks[{nick, changed_at}]}.

    Persisted in players.json. ``observe`` may run on the log-reader thread; signals reach
    main-thread slots queued.
    """

    # steam_id, old display name (previous nick or the SteamID itself), new nick, is_new
    player_changed = pyqtSignal(str, str, str, bool)
    data_changed = pyqtSignal()           # anything in the registry changed (UI refresh)
    player_removed = pyqtSignal(str)      # steam_id
    cleared = pyqtSignal()
    scan_finished = pyqtSignal(int)       # number of log files read

    def __init__(self, file_path: Optional[str] = None):
        super().__init__()
        if file_path is None:
            file_path = get_portable_config_path("players.json")
        self.file_path = file_path
        self._lock = threading.RLock()
        self._players: Dict[str, dict] = {}
        self._scanned: Dict[str, int] = {}   # log file name -> bytes already read
        self.enabled = True                  # False: nothing is read from the logs or stored
        self.load()

    # ── persistence ──────────────────────────────────────────────────
    @staticmethod
    def _clean_record(rec: dict) -> Optional[dict]:
        if not isinstance(rec, dict) or not rec.get("nick"):
            return None
        def number(value, default=0.0) -> float:
            try:
                result = float(value)
            except (TypeError, ValueError):
                return default
            return result if math.isfinite(result) else default

        history = []
        raw_history = rec.get("previous_nicks")
        for item in raw_history if isinstance(raw_history, list) else []:
            if isinstance(item, str):
                item = {"nick": item, "changed_at": 0}
            if isinstance(item, dict) and item.get("nick"):
                history.append({"nick": str(item["nick"]), "changed_at": number(item.get("changed_at"))})
        return {
            "nick": str(rec["nick"]),
            "hash": str(rec.get("hash") or ""),
            "first_seen": number(rec.get("first_seen")),
            "last_seen": number(rec.get("last_seen"), number(rec.get("first_seen"))),
            "previous_nicks": history,
        }

    def load(self):
        with self._lock:
            self._players, self._scanned = {}, {}
            if not os.path.exists(self.file_path):
                return
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                log.error("Failed to load %s: %s", self.file_path, e)
                quarantine_corrupt(self.file_path)
                return
            if not isinstance(data, dict):
                return
            players = data["players"] if isinstance(data.get("players"), dict) else data  # v1 was a bare dict
            for sid, rec in players.items():
                clean = self._clean_record(rec) if is_steam_id(sid) else None
                if clean:
                    self._players[sid] = clean
            scanned = data.get("scanned_logs")
            if isinstance(scanned, dict):
                self._scanned = {str(k): int(v) for k, v in scanned.items() if isinstance(v, int)}

    def save(self):
        with self._lock:
            try:
                atomic_write_json(
                    self.file_path,
                    {"version": FORMAT_VERSION, "players": self._players, "scanned_logs": self._scanned},
                )
            except OSError as e:
                log.error("Could not save %s: %s", self.file_path, e)

    # ── filling the registry ─────────────────────────────────────────
    def observe(self, steam_id: str, nick: str, hash_value: str = "",
                seen_at: Optional[float] = None, silent: bool = False) -> None:
        """Record that ``steam_id`` was seen as ``nick`` at ``seen_at`` (epoch, default now).

        Saves and signals only on a real change. ``silent`` skips saving and signals (bulk scans).
        Information older than what is already known is ignored.
        """
        nick = (nick or "").strip()
        if not self.enabled or not nick or not is_steam_id(steam_id):
            return
        ts = seen_at if seen_at is not None else time.time()
        old, is_new, changed = steam_id, False, False
        with self._lock:
            rec = self._players.get(steam_id)
            if rec is None:
                self._players[steam_id] = {
                    "nick": nick, "hash": hash_value, "first_seen": ts, "last_seen": ts, "previous_nicks": [],
                }
                is_new = changed = True
            else:
                if ts < rec["last_seen"]:
                    return
                rec["last_seen"] = ts
                if hash_value and rec.get("hash") != hash_value:
                    rec["hash"] = hash_value
                    changed = True
                old = rec["nick"]
                if old != nick:
                    rec["previous_nicks"] = ([{"nick": old, "changed_at": ts}] + rec["previous_nicks"])[:MAX_NICK_HISTORY]
                    rec["nick"] = nick
                    changed = True
            if not changed or silent:
                return
            self.save()
        self.data_changed.emit()
        if old != nick:
            log.info("Player %s is now %r (was %r)", steam_id, nick, old)
            self.player_changed.emit(steam_id, old, nick, is_new)

    def scan_logs(self, log_path: str) -> int:
        """Read every SCUM*.log next to ``log_path`` (backups first, the live log last).

        Each file is read once: the bytes already processed are remembered, so later starts only
        read what is new (and deleted data is not re-imported from old logs).
        """
        if not self.enabled:
            return 0
        folder = os.path.dirname(os.path.abspath(log_path))
        live = os.path.basename(log_path)
        names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, "SCUM*.log")))
        names.sort(key=lambda n: (n == live, n))
        read_files = 0
        for name in names:
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
                start = self._scanned.get(name, 0)
                if size < start:  # the file was replaced (game restart reuses SCUM.log)
                    start = 0
                if size == start:
                    continue
                with open(path, "rb") as f:
                    f.seek(start)
                    chunk = f.read(size - start)
                # A line still being written must not be consumed half-way: stop at the last newline
                complete = chunk.rfind(b"\n") + 1
                chunk, size = chunk[:complete], start + complete
                if not chunk:
                    continue
                for raw in chunk.splitlines():
                    parsed = parse_user_line(raw.decode("utf-8", errors="ignore"))
                    if parsed:
                        sid, nick, hash_value, ts = parsed
                        self.observe(sid, nick, hash_value, ts, silent=True)
                with self._lock:
                    self._scanned[name] = size
                read_files += 1
            except OSError as e:
                log.warning("Could not scan %s: %s", path, e)
        with self._lock:
            self.save()
        self.data_changed.emit()
        self.scan_finished.emit(read_files)
        return read_files

    def rescan_all(self, log_path: str) -> int:
        """Forget which log bytes were read and scan every current and old log again."""
        with self._lock:
            self._scanned = {}
        return self.scan_logs(log_path)

    # ── reading ──────────────────────────────────────────────────────
    def get(self, steam_id: str) -> Optional[dict]:
        with self._lock:
            rec = self._players.get(steam_id)
            return json.loads(json.dumps(rec)) if rec else None

    def nick_of(self, steam_id: str) -> Optional[str]:
        rec = self.get(steam_id)
        return rec["nick"] if rec else None

    def all_players(self) -> List[Tuple[str, dict]]:
        """[(steam_id, record)] sorted by current nickname."""
        with self._lock:
            items = [(sid, json.loads(json.dumps(rec))) for sid, rec in self._players.items()]
        return sorted(items, key=lambda it: it[1]["nick"].casefold())

    def find_by_nick(self, nick: str) -> Optional[str]:
        """SteamID for a nickname: a unique current nick, else a unique old nick; None if unknown/ambiguous."""
        key = (nick or "").strip().casefold()
        if not key:
            return None
        with self._lock:
            current = [s for s, r in self._players.items() if r["nick"].casefold() == key]
            if len(current) == 1:
                return current[0]
            if current:
                return None
            old = [s for s, r in self._players.items()
                   if any(h["nick"].casefold() == key for h in r["previous_nicks"])]
        return old[0] if len(old) == 1 else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._players)

    # ── editing (Settings -> Players) ────────────────────────────────
    def remove_old_nick(self, steam_id: str, index: int) -> bool:
        with self._lock:
            rec = self._players.get(steam_id)
            if not rec or not 0 <= index < len(rec["previous_nicks"]):
                return False
            del rec["previous_nicks"][index]
            self.save()
        self.data_changed.emit()
        return True

    def remove_old_nick_entry(self, steam_id: str, nick: str, changed_at: float) -> bool:
        """Delete one old nickname identified by its value (an index can shift while a rename is logged)."""
        with self._lock:
            rec = self._players.get(steam_id)
            if not rec:
                return False
            for i, item in enumerate(rec["previous_nicks"]):
                if item["nick"] == nick and item["changed_at"] == changed_at:
                    del rec["previous_nicks"][i]
                    self.save()
                    break
            else:
                return False
        self.data_changed.emit()
        return True

    def remove_player(self, steam_id: str) -> bool:
        with self._lock:
            if self._players.pop(steam_id, None) is None:
                return False
            self.save()
        self.player_removed.emit(steam_id)
        self.data_changed.emit()
        return True

    def clear(self) -> None:
        with self._lock:
            self._players.clear()
            self.save()
        self.cleared.emit()
        self.data_changed.emit()
