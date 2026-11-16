"""Clan sync under abuse: random concurrent edits, flaky broker, bulk import, hostile payloads, hostile servers."""
import json
import os
import random
import socket
import sys
import threading
import time
import tracemalloc

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from mqtt_fake import FakeBroker  # noqa: E402
from test_sync import app, make_node, online, pump, wait_for  # noqa: E402,F401  (app = the QApplication)

from core import sync_crypto as sc  # noqa: E402
from core.coordinate_parser import MapPoint  # noqa: E402
from core.mqtt_lite import MqttClient  # noqa: E402
from core.sync_engine import MAX_V, point_sid  # noqa: E402

RAW_HTTP = True   # local sockets only


# ── helpers ──────────────────────────────────────────────────────────
def make_point(i, name=None):
    x, y = -600000.0 + i * 10, -500000.0 + (i % 50) * 10
    stamp = f"2026.11.15-{(i // 3600) % 24:02d}.{(i // 60) % 60:02d}.{i % 60:02d}"
    return MapPoint.from_dict({"id": f"id{i}", "name": name or f"p{i}", "date_time": stamp,
                               "raw_coord": f"{{X={x} Y={y} Z=10}}", "x": x, "y": y, "z": 10.0})


def names(mgr):
    return sorted(p.name for p in mgr.get_points())


def sids(mgr):
    return sorted(point_sid(p) for p in mgr.get_points())


def threads_named(name="mqtt-sync"):
    return [t for t in threading.enumerate() if t.name == name and t.is_alive()]


@pytest.fixture
def broker():
    b = FakeBroker()
    yield b
    b.close()


@pytest.fixture
def nodes(tmp_path, broker):
    code = sc.new_code()
    made = []

    def factory(name, **extra):
        node = make_node(tmp_path, name, code, broker, **extra)
        made.append(node)
        return node
    factory.code, factory.broker = code, broker
    yield factory
    for _cfg, _mgr, engine in made:
        engine.stop(quiet=True)


def start_all(engines):
    for e in engines:
        e.start()
    for e in engines:
        assert online(e)


# ── (1) five peers, random concurrent edits ──────────────────────────
def test_five_peers_random_edits_converge(nodes):
    rng = random.Random(1234)
    peers = [nodes(f"n{i}") for i in range(5)]
    start_all([p[2] for p in peers])
    pump(0.5)
    counter = 0
    end = time.time() + 3.0
    while time.time() < end:
        _cfg, mgr, _eng = rng.choice(peers)
        op = rng.choice(["add", "add", "rename", "delete"])
        pts = mgr.get_points()
        if op == "add" or not pts:
            counter += 1
            mgr.add_point(make_point(counter))
        elif op == "rename":
            counter += 1
            mgr.update_point_name(rng.choice(pts).id, f"r{counter}")
        else:
            mgr.delete_point(rng.choice(pts).id)
        pump(0.01)

    def converged():
        first = sids(peers[0][1])
        return all(sids(p[1]) == first for p in peers) and \
            all(names(p[1]) == names(peers[0][1]) for p in peers)

    assert wait_for(converged, 15.0), [len(p[1].get_points()) for p in peers]
    assert counter > 20


# ── (2) broker cut during a burst ────────────────────────────────────
def test_connection_cuts_during_burst_eventually_consistent(nodes):
    a, b = nodes("a"), nodes("b")
    start_all([a[2], b[2]])
    pump(0.3)
    for i in range(100):
        a[1].add_point(make_point(i))
        if i % 20 == 10:
            nodes.broker.drop_clients()
        pump(0.01)
    assert wait_for(lambda: len(b[1].get_points()) == 100 and names(a[1]) == names(b[1]), 25.0), \
        (len(a[1].get_points()), len(b[1].get_points()))


# ── (3) bulk import then clear ───────────────────────────────────────
def test_bulk_import_replace_then_clear_all(nodes, tmp_path):
    a, b, c = nodes("a"), nodes("b"), nodes("c")
    start_all([a[2], b[2], c[2]])
    pump(0.3)
    path = tmp_path / "bulk.json"
    path.write_text(json.dumps({"format": "x", "points": [make_point(i).to_dict() for i in range(300)]}),
                    encoding="utf-8")
    t0 = time.time()
    res = a[1].import_from_file(str(path), replace=True)
    print("import", time.time() - t0)
    assert res.added == 300
    assert wait_for(lambda: len(b[1].get_points()) == 300 and len(c[1].get_points()) == 300, 15.0), \
        (len(b[1].get_points()), len(c[1].get_points()))
    print("synced", time.time() - t0)
    assert names(b[1]) == names(a[1])
    a[1].clear_all()
    assert wait_for(lambda: not b[1].get_points() and not c[1].get_points(), 40.0), \
        (len(b[1].get_points()), len(c[1].get_points()))


# ── (4) hostile flood into _on_message ───────────────────────────────
def test_hostile_flood_creates_nothing(nodes):
    cfg, mgr, engine = nodes("victim")
    engine.start()
    rng = random.Random(99)
    keys, other = engine.keys, sc.keys_from_code(sc.new_code())
    base = f"scumsync/v1/{keys.room}"
    good = {"k": "pt", "s": "", "v": 1000, "by": "abcdef01", "d": 0,
            "p": {"name": "x", "x": -600000.0, "y": -500000.0, "z": 1.0}}

    def doc_with(**over):
        d = json.loads(json.dumps(good))
        for k, v in over.items():
            if k == "p":
                d["p"] = v
            else:
                d[k] = v
        return d

    bad_docs = [
        lambda s: doc_with(s=s, k="zz"), lambda s: doc_with(s="0" * 16),
        lambda s: doc_with(s=s, v=True), lambda s: doc_with(s=s, v=1.5), lambda s: doc_with(s=s, v="9"),
        lambda s: doc_with(s=s, v=-1), lambda s: doc_with(s=s, v=MAX_V), lambda s: doc_with(s=s, v=10 ** 30),
        lambda s: doc_with(s=s, by="nope"), lambda s: doc_with(s=s, by=5), lambda s: doc_with(s=s, p=None),
        lambda s: doc_with(s=s, p=[1, 2]), lambda s: doc_with(s=s, p={"name": 5, "x": 1, "y": 1}),
        lambda s: doc_with(s=s, p={"name": "n"}), lambda s: doc_with(s=s, p={"name": "n", "x": "a", "y": 1}),
        lambda s: doc_with(s=s, p={"name": "n", "x": 9e9, "y": 1}),
        lambda s: doc_with(s=s, p={"name": "n", "x": -600000, "y": -500000, "z": 1e300}),
        lambda s: doc_with(s=s, p={"name": "n", "x": -600000, "y": -500000, "color": ["x"]}),
        lambda s: doc_with(s=s, p={"name": "n", "x": -600000, "y": -500000, "players": {"a": 1}}),
        lambda s: {"k": "pt"}, lambda s: {}, lambda s: {"v": [1, 2, 3]},
    ]
    sid = lambda: "".join(rng.choice("0123456789abcdef") for _ in range(16))  # noqa: E731
    tracemalloc.start()
    base_mem = tracemalloc.get_traced_memory()[0]
    for i in range(2000):
        kind = i % 8
        s = sid()
        topic = f"{base}/p/{s}"
        if kind == 0:
            payload = os.urandom(rng.randint(0, 600))
        elif kind == 1:
            payload = sc.seal(keys, {"a": 1})                                  # genuine envelope, garbled below
            payload = bytes(b ^ rng.randint(0, 255) if rng.random() < 0.1 else b for b in payload)
        elif kind == 2:
            payload = sc.seal(other, good)                                     # another clan's key
        elif kind == 3:
            payload = os.urandom(1_000_000) if i % 200 == 3 else os.urandom(60000)   # oversized
        elif kind == 4:
            payload = rng.choice([b"", b"\x00", b"null", b"{}", b"[1,2]", b"\xff" * 5000])
        elif kind == 5:
            topic = rng.choice([f"{base}/p", f"{base}/p/{s}/x", f"other/v1/x/p/{s}", f"{base}/q/{s}",
                                f"{base}/p/ZZZ", f"{base}/p/{s.upper()}", "", "/" * 50, "\udcff/x"])
            payload = sc.seal(keys, doc_with(s=s))
        else:
            payload = sc.seal(keys, rng.choice(bad_docs)(s))
        engine._on_message(engine._session, topic, payload)                                    # must never raise
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert mgr.get_points() == [] and engine._meta == {} and engine._known == {}
    assert engine.applied_count == 0
    assert len(engine._seen_v) <= 2000          # (header-valid but insane docs still leave a _seen_v entry)
    assert current - base_mem < 20_000_000 and peak < 200_000_000


# ── (5) poisoned version number ──────────────────────────────────────
def test_near_max_version_does_not_lock_waypoint(nodes):
    a, b = nodes("a"), nodes("b")
    start_all([a[2], b[2]])
    pump(0.3)
    a[1].add_point(make_point(1, "orig"))
    assert wait_for(lambda: names(b[1]) == ["orig"], 8.0)
    sid = point_sid(a[1].get_points()[0])
    poison = sc.seal(a[2].keys, {"k": "pt", "s": sid, "v": 2 ** 53 - 1, "by": "deadbeef", "d": 0,
                                 "p": {"name": "poison", "x": -600010.0, "y": -500000.0, "z": 10.0,
                                       "raw_coord": a[1].get_points()[0].raw_coord,
                                       "date_time": a[1].get_points()[0].date_time}})
    topic = f"scumsync/v1/{a[2].keys.room}/p/{sid}"
    for eng in (a[2], b[2]):
        eng._on_message(eng._session, topic, poison)
    assert names(a[1]) == ["orig"] and names(b[1]) == ["orig"]              # a version from the far future is refused
    a[1].update_point_name(a[1].get_points()[0].id, "legit")
    pump(0.5)
    assert wait_for(lambda: names(a[1]) == ["legit"] and names(b[1]) == ["legit"], 4.0), (names(a[1]), names(b[1]))
    a[1].delete_point(a[1].get_points()[0].id)
    assert wait_for(lambda: not b[1].get_points(), 4.0)


# ── (6) MqttClient against hostile servers ───────────────────────────
class RawServer:
    """Accepts connections and misbehaves according to ``mode``."""

    def __init__(self, mode):
        self.mode, self.times, self.closed = mode, [], False
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.held = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.closed:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.times.append(time.monotonic())
            try:
                if self.mode == "garbage":
                    conn.sendall(b"\xff\xff\xff\xff\xff\x7f" + os.urandom(64))
                    self.held.append(conn)
                elif self.mode == "close":
                    conn.close()
                else:
                    self.held.append(conn)          # silent: never answers
            except OSError:
                pass

    def close(self):
        self.closed = True
        for c in self.held:
            try:
                c.close()
            except OSError:
                pass
        self.sock.close()


@pytest.mark.parametrize("mode", ["garbage", "close"])
def test_client_backs_off_and_stops_fast(mode):
    server = RawServer(mode)
    states = []
    client = MqttClient([("127.0.0.1", server.port, False)], "scum-test", ["t/#"], lambda t, p: None,
                        lambda s, d: states.append(s))
    client.start()
    try:
        end = time.time() + 12
        while len(server.times) < 3 and time.time() < end:
            time.sleep(0.05)
        assert len(server.times) >= 3, server.times
        gaps = [b - a for a, b in zip(server.times, server.times[1:], strict=False)]
        assert gaps[0] >= 0.9 and gaps[1] >= 1.9, gaps                    # back-off grows, no hot reconnect loop
        assert "online" not in states
    finally:
        t0 = time.monotonic()
        client.stop()
        client.join(3)
        took = time.monotonic() - t0
        server.close()
    assert not client.is_alive() and took < 2.0, took


def test_client_stops_fast_when_connack_never_comes():
    server = RawServer("silent")
    client = MqttClient([("127.0.0.1", server.port, False)], "scum-test", ["t/#"], lambda t, p: None)
    client.start()
    try:
        assert wait_for(lambda: len(server.times) == 1, 3.0)
        time.sleep(0.5)
        t0 = time.monotonic()
        client.stop()
        client.join(3)
        assert not client.is_alive() and time.monotonic() - t0 < 2.0
        assert not client.connected
    finally:
        server.close()


# ── (7) start/stop loops leak no threads ─────────────────────────────
def test_start_stop_loop_leaves_no_threads(nodes):
    _cfg, _mgr, engine = nodes("loop")
    before = len(threads_named())
    for _ in range(20):
        engine.start()
        pump(0.02)
        engine.stop(quiet=True)
    engine.stop(quiet=True)
    assert wait_for(lambda: len(threads_named()) <= before, 4.0), [t.name for t in threads_named()]
    engine.start()
    assert online(engine)
    assert len(threads_named()) == before + 1
    engine.stop(quiet=True)
    assert wait_for(lambda: len(threads_named()) <= before, 4.0)
