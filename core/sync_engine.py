"""Clan sync: waypoints and live positions shared between friends through an encrypted mailbox (MQTT broker).

* Everything is encrypted with a key made from the clan code (see sync_crypto); the broker only sees noise.
* Waypoints: one retained message per waypoint (topic ``p/<id>``) holds its newest version, so a member who joins
  later receives the whole set at once. Conflicts: the newest version wins (a per-waypoint counter that never goes
  backwards), deletions travel as small "tombstones".
* Positions: not stored on the broker (``m/<member>``, not retained); a marker fades when it stops updating.
"""
import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.coordinate_parser import MapPoint
from core.fileio import atomic_write_json
from core.mqtt_lite import DEFAULT_BROKERS, MultiClient, parse_broker
from core.position_source import Position, in_world
from core.sync_crypto import Keys, keys_from_code, open_sealed, seal

log = logging.getLogger("scum.sync")

TOPIC_ROOT = "scumsync/v1"
_SID = re.compile(r"^[0-9a-f]{16}$")
_MEMBER = re.compile(r"^[0-9a-f]{8}$")
POSITION_INTERVAL = 2.0          # seconds between position messages
HELLO_INTERVAL = 20.0
MEMBER_TTL = 70.0                # a member not heard from for this long is "away"
MARKER_TTL = 150.0               # a position older than this is dropped from the map
MAX_V = 2 ** 53
MAX_AHEAD_MS = 24 * 3600 * 1000      # a version more than a day ahead is refused (it would lock the waypoint)
MAX_POINTS = 5000                # waypoints one clan can hold
MAX_FRIENDS = 64
POSITION_SKEW_MS = 10 * 60 * 1000
SETTLE_QUIET_MS = 1500           # publish ours once the stored waypoints stopped arriving for this long
SETTLE_CAP_MS = 10000
POINT_FIELDS = ("name", "date_time", "raw_coord", "x", "y", "z", "category", "color", "players")


@dataclass
class Friend:
    member: str
    name: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    has_position: bool = False
    seen: float = 0.0            # monotonic time of the last message of any kind
    moved: float = 0.0           # monotonic time of the last position


def point_sid(point: MapPoint) -> str:
    """The same chat message gives the same id on every PC, so a waypoint two friends both captured is one waypoint."""
    if point.raw_coord and point.date_time:
        key = f"chat|{point.raw_coord}|{point.date_time}"
    else:
        key = f"xy|{round(point.x, 1)}|{round(point.y, 1)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def clean_name(value: Any, fallback: str = "Player") -> str:
    text = "".join(ch for ch in str(value or "") if ch.isprintable()).strip()[:24]
    return text or fallback


_TEXT_LIMITS = {"name": 80, "date_time": 40, "raw_coord": 120, "category": 24, "color": 7, "players": 200}


def _sane_point_data(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fields of a waypoint that came over the network, checked and trimmed; None when it cannot be a real waypoint."""
    out: Dict[str, Any] = {}
    for key, limit in _TEXT_LIMITS.items():
        value = data.get(key, "")
        if not isinstance(value, str):
            return None
        out[key] = value[:limit]
    try:
        x, y, z = float(data["x"]), float(data["y"]), float(data.get("z", 0.0))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not (x == x and y == y and z == z) or not in_world(x, y) or abs(z) > 1e8:
        return None
    out.update(x=x, y=y, z=z)
    return out


def _doc_fields(point: MapPoint) -> Dict[str, Any]:
    return {name: getattr(point, name) for name in POINT_FIELDS}


class SyncEngine(QObject):
    status_changed = pyqtSignal(str, str)        # state, detail  (off / need_code / connecting / online / offline / error)
    friends_changed = pyqtSignal()
    _got_message = pyqtSignal(int, str, bytes)
    _got_state = pyqtSignal(int, str, str)

    def __init__(self, cfg, points_mgr, meta_path: str, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.points = points_mgr
        self.meta_path = meta_path
        self.keys: Optional[Keys] = None
        self.client: Optional[MultiClient] = None
        self.state = "off"
        self.detail = ""
        self.member = ""
        self.name = "Player"
        self.friends: Dict[str, Friend] = {}
        self.me: Optional[Position] = None
        self._pending_position = False
        self._sent_position_at = 0.0
        self._meta: Dict[str, List[Any]] = {}        # sid -> [version, author, deleted 0/1]
        self._seen_v: Dict[str, int] = {}            # versions the broker is known to hold
        self._known: Dict[str, str] = {}             # sid -> local point id
        self._by_local: Dict[str, str] = {}          # local point id -> sid
        self._applying = False
        self._synced_once = False
        self.applied_count = 0
        self._session = 0                            # events of an older client are ignored
        self._published: Dict[str, str] = {}         # sid -> hash of the content we last sent
        self._last_pos_t: Dict[str, int] = {}        # member -> newest position stamp (replay guard)
        self._settle_started = 0.0
        self._load_meta()

        self._got_message.connect(self._on_message)
        self._got_state.connect(self._on_state)
        self.points.point_added.connect(self._local_changed)
        self.points.point_updated.connect(self._local_changed)
        self.points.point_deleted.connect(self._local_deleted)
        self.points.points_cleared.connect(self._local_cleared)
        self.points.points_reloaded.connect(self._local_reloaded)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self._save_meta)
        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._on_tick)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_QUIET_MS)
        self._settle.timeout.connect(self._publish_missing)
        self._last_hello = 0.0

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self):
        """(Re)read the settings and connect; with sync switched off or no code this just stops."""
        self.stop(quiet=True)
        if not self.cfg.get("sync_enabled", False):
            self._set_state("off", "")
            return
        self.keys = keys_from_code(self.cfg.get("sync_code", ""))
        if self.keys is None:
            self._set_state("need_code", "")
            return
        self.member = self._member_id()
        self.name = clean_name(self.cfg.get("sync_name", ""))
        custom = parse_broker(self.cfg.get("sync_broker", ""))
        # all public relays at once (a message goes through every one); an own relay is used alone
        brokers = [custom] if custom else list(DEFAULT_BROKERS)
        base = f"{TOPIC_ROOT}/{self.keys.room}"
        self._reindex()
        self._synced_once = False
        self._session += 1
        session = self._session
        self.client = MultiClient(brokers, "scum-" + uuid.uuid4().hex[:12], [base + "/p/+", base + "/m/+"],
                                 lambda topic, payload: self._got_message.emit(session, topic, payload),
                                 lambda state, detail: self._got_state.emit(session, state, detail))
        self.client.start()
        self._tick.start()
        self._set_state("connecting", "")

    def stop(self, quiet: bool = False):
        self._tick.stop()
        self._settle.stop()
        client, self.client = self.client, None
        if client is not None:
            if self.cfg.get("sync_position", True) and client.connected and self.keys:
                self._send_to(client, "m", self.member, {"k": "bye", "m": self.member})
            client.stop()
            client.join(0.8)                        # the thread sends what is queued (the "bye") before it leaves
        self.friends.clear()
        self._last_pos_t.clear()
        self._published.clear()
        self._session += 1
        self._save_meta()
        self.points.flush()
        self.cfg.save()
        if not quiet:
            self._set_state("off", "")
            self.friends_changed.emit()

    def _member_id(self) -> str:
        member = self.cfg.get("sync_member_id", "")
        if not isinstance(member, str) or not _MEMBER.match(member):
            member = uuid.uuid4().hex[:8]
            self.cfg.set("sync_member_id", member)
        return member

    def _set_state(self, state: str, detail: str):
        self.state, self.detail = state, detail
        self.status_changed.emit(state, detail)

    # ── sending ──────────────────────────────────────────────────────
    def _base(self) -> str:
        return f"{TOPIC_ROOT}/{self.keys.room}"

    def _send_to(self, client: MultiClient, kind: str, ident: str, message: Dict[str, Any], retain: bool = False):
        if not self.keys:
            return
        try:
            client.publish(f"{self._base()}/{kind}/{ident}", seal(self.keys, message), retain)
        except ValueError:
            log.warning("sync message too large; skipped")

    def _send(self, kind: str, ident: str, message: Dict[str, Any], retain: bool = False):
        if self.client is not None:
            self._send_to(self.client, kind, ident, message, retain)

    @property
    def sharing_points(self) -> bool:
        return bool(self.cfg.get("sync_points", True))

    def _bump(self, sid: str) -> int:
        old = self._meta.get(sid)
        now = int(time.time() * 1000)
        version = max(now, (int(old[0]) + 1) if old else 0, self._seen_v.get(sid, 0) + 1)
        return min(version, now + MAX_AHEAD_MS)

    def _publish_point(self, point: MapPoint, force: bool = False):
        if not self.sharing_points or self.client is None:
            return
        sid = point_sid(point)
        digest = hashlib.sha1(json.dumps(_doc_fields(point), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if not force and self._published.get(sid) == digest and sid in self._meta and not self._meta[sid][2]:
            self._known[sid] = point.id
            self._by_local[point.id] = sid
            return
        self._published[sid] = digest
        version = self._bump(sid)
        self._meta[sid] = [version, self.member, 0]
        self._known[sid] = point.id
        self._by_local[point.id] = sid
        self._send("p", sid, {"k": "pt", "s": sid, "v": version, "by": self.member, "d": 0, "p": _doc_fields(point)}, True)
        self._save_timer.start()

    def _publish_tombstone(self, sid: str):
        if not self.sharing_points or self.client is None:
            return
        self._published.pop(sid, None)
        version = self._bump(sid)
        self._meta[sid] = [version, self.member, 1]
        self._send("p", sid, {"k": "pt", "s": sid, "v": version, "by": self.member, "d": 1}, True)
        self._save_timer.start()

    # ── local changes ────────────────────────────────────────────────
    def _local_changed(self, point):
        if self._applying or not isinstance(point, MapPoint):
            return
        old = self._by_local.get(point.id)
        if old and old != point_sid(point):
            self._known.pop(old, None)
            self._publish_tombstone(old)           # the waypoint moved: its old identity must not stay behind
        self._publish_point(point)

    def _local_deleted(self, point_id: str):
        if self._applying:
            return
        sid = self._by_local.pop(point_id, None)
        if sid:
            self._known.pop(sid, None)
            self._publish_tombstone(sid)

    def _local_cleared(self):
        if self._applying:
            return
        for sid in list(self._known):
            self._publish_tombstone(sid)
        self._known.clear()
        self._by_local.clear()

    def _local_reloaded(self):
        if self._applying:
            return
        current = {point_sid(p): p for p in self.points.get_points()}
        for sid in list(self._known):
            if sid not in current:
                self._publish_tombstone(sid)
        self._reindex()
        for point in current.values():
            self._publish_point(point)

    def _reindex(self):
        self._known, self._by_local = {}, {}
        for point in self.points.get_points():
            sid = point_sid(point)
            self._known[sid] = point.id
            self._by_local[point.id] = sid

    # ── receiving ────────────────────────────────────────────────────
    def _on_state(self, session: int, state: str, detail: str):
        if self.client is None or session != self._session:
            return
        if state == "online":
            self._synced_once = False
            self._seen_v.clear()                    # the relay may be another one now: what it holds is unknown
            self._settle_started = time.monotonic()
            self._settle.start()
            self._last_hello = 0.0
        self._set_state(state, detail)

    def _on_message(self, session: int, topic: str, payload: bytes):
        if self.keys is None or self.client is None or session != self._session:
            return
        parts = topic.split("/")
        if len(parts) != 5 or "/".join(parts[:2]) != TOPIC_ROOT or parts[2] != self.keys.room:
            return
        kind, ident = parts[3], parts[4]
        if not payload:
            return                                  # an erased retained message
        doc = open_sealed(self.keys, payload)
        if not isinstance(doc, dict):
            return
        if kind == "p" and _SID.match(ident):
            self._remote_point(ident, doc)
        elif kind == "m" and _MEMBER.match(ident) and ident != self.member:
            self._remote_member(ident, doc)

    def _remote_point(self, sid: str, doc: Dict[str, Any]):
        version = doc.get("v")
        author = doc.get("by")
        if (doc.get("k") != "pt" or doc.get("s") != sid or not isinstance(version, int) or isinstance(version, bool)
                or not 0 <= version < MAX_V or not isinstance(author, str) or not _MEMBER.match(author)):
            return
        if version > int(time.time() * 1000) + MAX_AHEAD_MS:
            return                                  # from the far future: would lock the waypoint
        deleted = bool(doc.get("d"))
        clean = None
        if not deleted:
            data = doc.get("p")
            clean = _sane_point_data(data) if isinstance(data, dict) else None
            if clean is None:
                return
        self._seen_v[sid] = max(self._seen_v.get(sid, 0), version)
        if self._settle.isActive() and time.monotonic() - self._settle_started < SETTLE_CAP_MS / 1000:
            self._settle.start()                    # more stored waypoints are still arriving
        if not self.sharing_points:
            return
        mine = self._meta.get(sid)
        if mine and (int(mine[0]), str(mine[1])) >= (version, author):
            return                                  # we already hold this version or a newer one
        self._applying = True
        try:
            local_id = self._known.get(sid)
            if deleted:
                if local_id:
                    self.points.delete_point(local_id)
                    self._known.pop(sid, None)
                    self._by_local.pop(local_id, None)
                self._meta[sid] = [version, author, 1]
            else:
                if not local_id and len(self._known) >= MAX_POINTS:
                    return
                point = self.points.apply_remote(clean, local_id or sid[:10])
                if point is None:
                    return
                self._known[sid] = point.id
                self._by_local[point.id] = sid
                self._meta[sid] = [version, author, 0]
            self.applied_count += 1
        finally:
            self._applying = False
        self._save_timer.start()

    def _remote_member(self, member: str, doc: Dict[str, Any]):
        kind = doc.get("k")
        now = time.monotonic()
        if kind == "bye":
            if self.friends.pop(member, None) is not None:
                self.friends_changed.emit()
            self._last_pos_t.pop(member, None)
            return
        if kind not in ("pos", "hi") or doc.get("m") != member:
            return
        stamp = doc.get("t")
        if kind == "pos":
            if not isinstance(stamp, int) or isinstance(stamp, bool):
                return
            if abs(stamp - int(time.time() * 1000)) > POSITION_SKEW_MS or stamp <= self._last_pos_t.get(member, 0):
                return                              # an old message played again
            self._last_pos_t[member] = stamp
        friend = self.friends.get(member)
        if friend is None:
            if len(self.friends) >= MAX_FRIENDS:
                return
            friend = self.friends[member] = Friend(member, clean_name(doc.get("n")))
        friend.name = clean_name(doc.get("n"), friend.name)
        friend.seen = now
        self._remember_member(member, friend.name)
        if kind == "pos" and self.cfg.get("sync_position", True):
            try:
                x, y, z, yaw = (float(doc[k]) for k in ("x", "y", "z", "w"))
            except (KeyError, TypeError, ValueError, OverflowError):
                return
            if in_world(x, y) and all(abs(v) < 1e8 for v in (z, yaw)) and x == x and y == y:
                friend.x, friend.y, friend.z, friend.yaw = x, y, z, yaw % 360.0
                friend.has_position, friend.moved = True, now
        self.friends_changed.emit()

    # ── anti-entropy: after connecting, publish what the broker lacks ─
    def _publish_missing(self):
        if self.client is None or not self.sharing_points:
            return
        self._synced_once = True
        self._reindex()
        sent = 0
        for point in self.points.get_points():
            sid = point_sid(point)
            meta = self._meta.get(sid)
            seen = self._seen_v.get(sid)
            if meta is None:
                if seen is not None:
                    continue                        # the broker has a version of it that we already applied or ignored
                self._publish_point(point)
                sent += 1
            elif seen is None or int(meta[0]) > seen:
                if meta[2]:
                    continue
                self._publish_point(point)
                sent += 1
        for sid, meta in list(self._meta.items()):
            if sid in self._known:
                continue
            seen = self._seen_v.get(sid)
            if not meta[2] or seen is None or int(meta[0]) > seen:
                self._publish_tombstone(sid)        # deleted while we were away (or the relay lost the tombstone)
        log.info("Clan sync: published %d waypoint(s) the relay did not have", sent)

    # ── positions ────────────────────────────────────────────────────
    def set_my_position(self, pos: Position):
        self.me = pos
        self._pending_position = True
        self.friends_changed.emit()

    def _on_tick(self):
        now = time.monotonic()
        changed = False
        for member, friend in list(self.friends.items()):
            if now - friend.seen > MEMBER_TTL * 2:
                del self.friends[member]
                changed = True
            elif friend.has_position and now - friend.moved > MARKER_TTL:
                friend.has_position = False
                changed = True
        if changed:
            self.friends_changed.emit()
        client = self.client
        if client is None or not client.connected:
            return
        if (self._pending_position and self.me and self.cfg.get("sync_position", True)
                and now - self._sent_position_at >= POSITION_INTERVAL):
            self._pending_position = False
            self._sent_position_at = now
            p = self.me
            self._send("m", self.member, {"k": "pos", "m": self.member, "n": self.name,
                                          "x": round(p.x, 1), "y": round(p.y, 1), "z": round(p.z, 1),
                                          "w": round(p.yaw, 1), "t": int(time.time() * 1000)})
            self._last_hello = now
        elif now - self._last_hello >= HELLO_INTERVAL:
            self._last_hello = now
            self._send("m", self.member, {"k": "hi", "m": self.member, "n": self.name})

    # ── for the UI ───────────────────────────────────────────────────
    def markers(self) -> List[Dict[str, Any]]:
        """What the map draws: friends with a live position (and "me" when sharing)."""
        now = time.monotonic()
        out = [{"member": f.member, "name": self.display_name(f.member, f.name), "x": f.x, "y": f.y, "yaw": f.yaw, "age": now - f.moved, "me": False}
               for f in self.friends.values() if f.has_position]
        if self.me is not None and self.state != "off":
            out.append({"member": self.member, "name": self.name, "x": self.me.x, "y": self.me.y, "yaw": self.me.yaw,
                        "age": max(0.0, time.time() - self.me.stamp), "me": True})
        return out

    # ── squad members, with my own names for them ────────────────────
    def _aliases(self) -> Dict[str, str]:
        value = self.cfg.get("sync_aliases", {})
        return value if isinstance(value, dict) else {}

    def display_name(self, member: str, fallback: str = "") -> str:
        """The name I gave this teammate; otherwise the name the teammate uses."""
        alias = self._aliases().get(member)
        return clean_name(alias, fallback or "Player") if isinstance(alias, str) and alias.strip() else (fallback or "Player")

    def set_alias(self, member: str, alias: str):
        if not _MEMBER.match(member or ""):
            return
        aliases = dict(self._aliases())
        text = clean_name(alias, "")
        if text and (member in aliases or len(aliases) < 200):
            aliases[member] = text
        else:
            aliases.pop(member, None)
        self.cfg.set("sync_aliases", aliases)
        self.friends_changed.emit()

    def _remember_member(self, member: str, name: str):
        known = self.cfg.get("sync_members", {})
        known = dict(known) if isinstance(known, dict) else {}
        if known.get(member) == name:
            return
        if member not in known and len(known) >= 200:
            known.pop(next(iter(known)))                 # the oldest one makes room
        known[member] = name
        self.cfg.set("sync_members", known, save=False)       # written with the next save, not on every message

    def forget_member(self, member: str):
        known = self.cfg.get("sync_members", {})
        if isinstance(known, dict) and member in known:
            known = dict(known)
            del known[member]
            self.cfg.set("sync_members", known)
        aliases = dict(self._aliases())
        if aliases.pop(member, None) is not None:
            self.cfg.set("sync_aliases", aliases)
        self.friends.pop(member, None)
        self.friends_changed.emit()

    def members(self) -> List[Dict[str, Any]]:
        """Everyone of the squad I have met: [{member, name, display, online, position (x, y, yaw, age) or None}]."""
        now = time.monotonic()
        known = self.cfg.get("sync_members", {})
        rows: Dict[str, Dict[str, Any]] = {}
        for member, name in (known.items() if isinstance(known, dict) else []):
            if isinstance(member, str) and _MEMBER.match(member) and member != self.member:
                rows[member] = {"member": member, "name": clean_name(name), "online": False, "position": None}
        for friend in self.friends.values():
            row = rows.setdefault(friend.member, {"member": friend.member, "name": friend.name})
            row["name"] = friend.name
            row["online"] = now - friend.seen <= MEMBER_TTL
            row["position"] = ((friend.x, friend.y, friend.yaw, now - friend.moved) if friend.has_position else None)
        for row in rows.values():
            row["display"] = self.display_name(row["member"], row["name"])
        return sorted(rows.values(), key=lambda r: (not r["online"], r["display"].lower()))

    def members_online(self) -> int:
        now = time.monotonic()
        return sum(1 for f in self.friends.values() if now - f.seen <= MEMBER_TTL)

    # ── persistence of the version table ─────────────────────────────
    def _load_meta(self):
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            for sid, row in data.items():
                if (_SID.match(sid) and isinstance(row, list) and len(row) == 3 and isinstance(row[0], int)
                        and isinstance(row[1], str) and _MEMBER.match(row[1])):
                    if 0 <= row[0] <= int(time.time() * 1000) + MAX_AHEAD_MS:
                        self._meta[sid] = [row[0], row[1], 1 if row[2] else 0]
        if len(self._meta) > 20000:
            self._meta = dict(list(self._meta.items())[-20000:])

    def _save_meta(self):
        try:
            atomic_write_json(self.meta_path, self._meta, indent=0)
        except OSError as exc:
            log.warning("Could not save the sync table: %s", exc)


def default_meta_path(points_file: str) -> str:
    return os.path.splitext(points_file)[0] + ".sync.json"
