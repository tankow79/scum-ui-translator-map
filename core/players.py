"""Registry of players seen in the SCUM log, keyed by their permanent SteamID.

The log line ``Message from user: Nick (7656119...) (hash: ...)`` is the only place
that ties a nickname to a SteamID. The SteamID never changes, the nickname can, so the
registry is what lets saved bases follow a player through a rename.
"""

import json
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.config_manager import get_portable_config_path

log = logging.getLogger("scum.players")

STEAM_PROFILE_URL = "https://steamcommunity.com/profiles/{steam_id}"
_STEAM_ID_RE = re.compile(r"(?<!\d)(7656119\d{10})(?!\d)")
MAX_NICK_HISTORY = 20


def parse_steam_ref(text: str) -> Optional[str]:
    """Extract a 17-digit SteamID64 from a bare ID or a steamcommunity.com/profiles/<id> link."""
    m = _STEAM_ID_RE.search(text or "")
    return m.group(1) if m else None


def steam_profile_url(steam_id: str) -> str:
    return STEAM_PROFILE_URL.format(steam_id=steam_id)


def split_players(text: str) -> List[str]:
    """Split a comma/semicolon/newline separated players string into clean tokens."""
    return [t.strip() for t in re.split(r"[,;\n]", text or "") if t.strip()]


class PlayerRegistry(QObject):
    """steam_id -> {nick, hash, first_seen, last_seen, previous_nicks}, persisted in players.json.

    ``observe`` may be called from the log-reader thread; ``player_changed`` is a Qt signal,
    so connected slots on main-thread objects run on the main thread.
    """

    # steam_id, old display name (previous nick or the SteamID itself), new nick, is_new
    player_changed = pyqtSignal(str, str, str, bool)

    def __init__(self, file_path: Optional[str] = None):
        super().__init__()
        if file_path is None:
            file_path = get_portable_config_path("players.json")
        self.file_path = file_path
        self._lock = threading.RLock()
        self._players: Dict[str, dict] = {}
        self.load()

    def load(self):
        with self._lock:
            self._players = {}
            if not os.path.exists(self.file_path):
                return
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for sid, rec in data.items():
                        if isinstance(rec, dict) and parse_steam_ref(sid) == sid and rec.get("nick"):
                            self._players[sid] = rec
            except Exception as e:
                log.error("Failed to load %s: %s", self.file_path, e)

    def save(self):
        with self._lock:
            tmp_path = self.file_path + ".tmp"
            try:
                parent = os.path.dirname(self.file_path)
                if parent and not os.path.exists(parent):
                    os.makedirs(parent, exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._players, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self.file_path)
            except OSError as e:
                log.error("Could not save %s: %s", self.file_path, e)

    def observe(self, steam_id: str, nick: str, hash_value: str = "") -> None:
        """Record that ``steam_id`` was seen under ``nick``; saves and signals only on a change."""
        nick = (nick or "").strip()
        if not nick or parse_steam_ref(steam_id) != steam_id:
            return
        now = time.time()
        with self._lock:
            rec = self._players.get(steam_id)
            if rec is None:
                self._players[steam_id] = {
                    "nick": nick, "hash": hash_value, "first_seen": now,
                    "last_seen": now, "previous_nicks": [],
                }
                self.save()
                old, is_new = steam_id, True
            else:
                rec["last_seen"] = now
                changed = False
                if hash_value and rec.get("hash") != hash_value:
                    rec["hash"] = hash_value
                    changed = True
                old, is_new = rec["nick"], False
                if old != nick:
                    history = [n for n in rec.get("previous_nicks", []) if n != old]
                    rec["previous_nicks"] = ([old] + history)[:MAX_NICK_HISTORY]
                    rec["nick"] = nick
                    changed = True
                if not changed:
                    return
                self.save()
                if old == nick:
                    return
        log.info("Player %s is now %r (was %r)", steam_id, nick, old)
        self.player_changed.emit(steam_id, old, nick, is_new)

    def get(self, steam_id: str) -> Optional[dict]:
        with self._lock:
            rec = self._players.get(steam_id)
            return dict(rec) if rec else None

    def nick_of(self, steam_id: str) -> Optional[str]:
        rec = self.get(steam_id)
        return rec["nick"] if rec else None

    def find_by_nick(self, nick: str) -> Optional[str]:
        """SteamID whose *current* nickname matches (case-insensitive); None if absent or ambiguous."""
        key = (nick or "").strip().casefold()
        if not key:
            return None
        with self._lock:
            hits = [sid for sid, rec in self._players.items() if rec["nick"].casefold() == key]
        return hits[0] if len(hits) == 1 else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._players)
