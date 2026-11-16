"""Clan sync: crypto, the MQTT client pieces, and engines talking through a fake broker."""
import os
import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(__file__))
from mqtt_fake import FakeBroker  # noqa: E402

from core import sync_crypto as sc  # noqa: E402
from core.config_manager import ConfigManager  # noqa: E402
from core.coordinate_parser import MapPoint  # noqa: E402
from core.mqtt_lite import PacketReader, packet, parse_broker, topic_matches  # noqa: E402
from core.points_manager import PointsManager  # noqa: E402
from core.position_source import Position, parse_position  # noqa: E402
from core.sync_engine import SyncEngine, point_sid  # noqa: E402

RAW_HTTP = True   # these tests talk to a local socket only
app = QApplication.instance() or QApplication([])


def pump(seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(condition, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


# ── crypto ───────────────────────────────────────────────────────────
def test_clan_code_roundtrip_and_typos():
    code = sc.new_code()
    assert code.startswith("SCUM1-") and sc.parse_code(code) is not None
    assert sc.parse_code(code.lower().replace("-", " ")) == sc.parse_code(code)     # case / separators do not matter
    assert sc.parse_code(code[:-1]) is None and sc.parse_code("") is None and sc.parse_code(None) is None
    assert sc.parse_code("SCUM1-" + "A" * 26) is not None and sc.parse_code("SCUM1-" + "1" * 26) is None
    assert sc.new_code() != code


def test_encryption_is_authenticated():
    keys = sc.keys_from_code(sc.new_code())
    other = sc.keys_from_code(sc.new_code())
    blob = sc.seal(keys, {"hello": "світ", "n": [1, 2]})
    assert sc.open_sealed(keys, blob) == {"hello": "світ", "n": [1, 2]}
    assert sc.open_sealed(other, blob) is None                       # another clan
    assert b"hello" not in blob
    for i in range(len(blob)):                                        # every single flipped byte is rejected
        broken = bytearray(blob)
        broken[i] ^= 0x01
        assert sc.open_sealed(keys, bytes(broken)) is None
    assert sc.open_sealed(keys, blob[:-1]) is None and sc.open_sealed(keys, b"") is None
    assert sc.open_sealed(keys, None) is None and sc.open_sealed(keys, "text") is None
    assert sc.seal(keys, {"a": 1}) != sc.seal(keys, {"a": 1})        # fresh nonce every time
    with pytest.raises(ValueError):
        sc.seal(keys, {"big": "x" * 40000})


def test_room_id_does_not_reveal_the_secret():
    code = sc.new_code()
    keys = sc.keys_from_code(code)
    secret = sc.parse_code(code).hex()
    assert secret not in keys.room and len(keys.room) == 24 and keys.enc != keys.mac


# ── MQTT pieces ──────────────────────────────────────────────────────
def test_parse_broker_forms():
    assert parse_broker("") is None and parse_broker("  ") is None
    assert parse_broker("example.org") == ("example.org", 8883, True)
    assert parse_broker("mqtt://example.org") == ("example.org", 1883, False)
    assert parse_broker("mqtts://example.org:9000/") == ("example.org", 9000, True)
    assert parse_broker("example.org:x") is None and parse_broker("http://x") is None and parse_broker("a b") is None
    assert parse_broker("example.org:70000") is None


def test_topic_matching_and_reader_resilience():
    assert topic_matches("a/+/c", "a/b/c") and topic_matches("a/#", "a/b/c/d") and not topic_matches("a/+", "a/b/c")
    reader = PacketReader()
    raw = packet(3, 0, b"\x00\x01tHELLO") * 3
    out = []
    for i in range(0, len(raw), 3):                                    # byte-trickled stream
        out += list(reader.feed(raw[i:i + 3]))
    assert len(out) == 3 and out[0][0] == 3
    with pytest.raises(ValueError):
        list(PacketReader().feed(bytes([0x30, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F])))
    with pytest.raises(ValueError):
        list(PacketReader().feed(bytes([0x30, 0xFF, 0xFF, 0x7F])))     # larger than the limit


# ── positions ────────────────────────────────────────────────────────
def test_position_parsing():
    ok = "{X=-618089.438 Y=-556227.438 Z=2421.429|P=342.1 Y=24.5 R=0.000000}"
    pos = parse_position(ok)
    assert pos and pos.x == -618089.438 and pos.yaw == 24.5
    assert parse_position("{X=-618089.438 Y=-556227.438 Z=2421.429}") is None      # a chat coordinate, not a position
    assert parse_position("{X=9999999 Y=1 Z=1|P=1 Y=1 R=1}") is None              # outside the island
    assert parse_position("hello") is None and parse_position(None) is None and parse_position("x" * 1000) is None
    assert parse_position("{X=1 Y=1 Z=1|P=1 Y=-90 R=1}").yaw == 270.0


# ── engines through a broker ─────────────────────────────────────────
def make_node(tmp_path, name, code, broker, **extra):
    folder = tmp_path / name
    folder.mkdir()
    cfg = ConfigManager(str(folder / "config.json"))
    cfg.update({"sync_enabled": True, "sync_code": code, "sync_name": name, "sync_broker": broker.url, **extra})
    mgr = PointsManager(str(folder / "points.json"))
    engine = SyncEngine(cfg, mgr, str(folder / "points.sync.json"))
    return cfg, mgr, engine


def chat_point(name, x, y, stamp):
    return MapPoint.from_dict({"id": f"id{stamp}", "name": name, "date_time": f"2026.11.15-12.00.{stamp:02d}",
                               "raw_coord": f"{{X={x} Y={y} Z=10}}", "x": x, "y": y, "z": 10.0})


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


def online(engine):
    return wait_for(lambda: engine.state == "online")


def count_topics(broker, kind):
    return len([m for m in broker.published if m[0].split("/")[3] == kind])


def test_points_travel_both_ways_and_edits_and_deletes_follow(nodes):
    _, mgr_a, a = nodes("alice")
    _, mgr_b, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    p = chat_point("Склад", -600000.0, -500000.0, 1)
    assert mgr_a.add_point(p)
    assert wait_for(lambda: len(mgr_b.get_points()) == 1)
    got = mgr_b.get_points()[0]
    assert got.name == "Склад" and got.x == -600000.0 and got.sector == p.sector
    mgr_b.update_point_name(got.id, "База клану")                               # edit on the other side
    assert wait_for(lambda: mgr_a.get_points()[0].name == "База клану")
    mgr_b.update_point_category(got.id, "base")
    assert wait_for(lambda: mgr_a.get_points()[0].category == "base")
    mgr_a.delete_point(mgr_a.get_points()[0].id)
    assert wait_for(lambda: len(mgr_b.get_points()) == 0)
    pump(0.5)                                                                   # nothing bounces back
    assert len(mgr_a.get_points()) == 0 and len(mgr_b.get_points()) == 0


def test_no_echo_loop(nodes):
    _, mgr_a, a = nodes("alice")
    _, mgr_b, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    mgr_a.add_point(chat_point("One", -600000.0, -500000.0, 1))
    assert wait_for(lambda: len(mgr_b.get_points()) == 1)
    pump(0.6)
    count = count_topics(nodes.broker, "p")
    pump(0.8)
    assert count_topics(nodes.broker, "p") == count == 1


def test_late_joiner_receives_everything_and_same_chat_line_is_one_point(nodes):
    _, mgr_a, a = nodes("alice")
    a.start()
    assert online(a)
    for i in range(1, 6):
        mgr_a.add_point(chat_point(f"P{i}", -600000.0 + i * 1000, -500000.0, i))
    pump(0.4)
    _, mgr_b, b = nodes("bob")
    twin = chat_point("P3", -600000.0 + 3000, -500000.0, 3)                       # bob saw the same chat line
    twin.id = "bobsown"
    mgr_b.add_point(twin)
    b.start()
    assert online(b)
    assert wait_for(lambda: len(mgr_b.get_points()) == 5)
    pump(0.4)
    assert len(mgr_b.get_points()) == 5 and len(mgr_a.get_points()) == 5


def test_offline_changes_are_published_when_connection_returns(nodes):
    _, mgr_a, a = nodes("alice")
    _, mgr_b, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    mgr_a.add_point(chat_point("Before", -600000.0, -500000.0, 1))
    assert wait_for(lambda: len(mgr_b.get_points()) == 1)
    a.stop(quiet=True)
    mgr_a.add_point(chat_point("While away", -601000.0, -500000.0, 2))             # alice is offline
    mgr_a.delete_point(mgr_a.get_points()[-1].id)                                  # ... and removes the old one
    a.start()
    assert online(a)
    assert wait_for(lambda: sorted(p.name for p in mgr_b.get_points()) == ["While away"], 12)


def test_wrong_code_sees_nothing_and_garbage_is_ignored(nodes, tmp_path):
    _, mgr_a, a = nodes("alice")
    a.start()
    assert online(a)
    other = make_node(tmp_path, "mallory", sc.new_code(), nodes.broker)
    other[2].start()
    assert online(other[2])
    mgr_a.add_point(chat_point("Secret", -600000.0, -500000.0, 1))
    pump(0.8)
    assert other[1].get_points() == []
    topic = f"scumsync/v1/{a.keys.room}/p/{'ab' * 8}"          # forged / damaged messages on the right topic
    for blob in (b"junk", sc.seal(sc.keys_from_code(sc.new_code()), {"k": "pt"}), b"\x01" + b"\x00" * 40):
        a._on_message(a._session, topic, blob)
    a._on_message(a._session, "scumsync/v1/other/p/x", b"x")
    a._on_message(a._session, topic, b"")
    assert len(mgr_a.get_points()) == 1
    other[2].stop(quiet=True)


def test_malicious_documents_do_not_crash_or_corrupt(nodes):
    _, mgr_a, a = nodes("alice")
    a.start()
    assert online(a)
    keys, sid = a.keys, "cd" * 8
    topic = f"scumsync/v1/{keys.room}/p/{sid}"
    base = {"k": "pt", "s": sid, "v": 5, "by": "deadbeef", "d": 0}
    bad = [
        {**base, "p": {"x": "nan", "y": 1}}, {**base, "p": {"x": 1e30, "y": 1e30}},
        {**base, "p": "text"}, {**base, "p": None}, {**base, "v": -1}, {**base, "v": 2 ** 60}, {**base, "v": True},
        {**base, "by": "x"}, {**base, "s": "ef" * 8}, {**base, "p": {"y": 3}}, [1, 2], "str", 5, None,
    ]
    for doc in bad:
        a._on_message(a._session, topic, sc.seal(keys, doc))
    assert mgr_a.get_points() == []
    good = {**base, "p": {"x": -600000.0, "y": -500000.0, "name": "<b>ok</b>", "category": "nonsense", "color": "red"}}
    a._on_message(a._session, topic, sc.seal(keys, good))
    point = mgr_a.get_points()[0]
    assert point.name == "<b>ok</b>" and point.category == "default"
    assert point.color.startswith("#") and len(point.color) == 7


def test_newest_version_wins(nodes):
    _, mgr_a, a = nodes("alice")
    a.start()
    assert online(a)
    keys, sid = a.keys, "ab" * 8
    topic = f"scumsync/v1/{keys.room}/p/{sid}"

    def send(version, name, deleted=0):
        doc = {"k": "pt", "s": sid, "v": version, "by": "deadbeef", "d": deleted}
        if not deleted:
            doc["p"] = {"x": -600000.0, "y": -500000.0, "name": name}
        a._on_message(a._session, topic, sc.seal(keys, doc))

    send(10, "v10")
    send(5, "old")
    assert mgr_a.get_points()[0].name == "v10"
    send(11, "v11")
    assert mgr_a.get_points()[0].name == "v11"
    send(12, "", deleted=1)
    assert mgr_a.get_points() == []
    send(11, "late")                                   # an older edit never resurrects a deleted waypoint
    assert mgr_a.get_points() == []
    send(13, "reborn")
    assert [p.name for p in mgr_a.get_points()] == ["reborn"]


def test_clear_all_propagates_and_sharing_can_be_switched_off(nodes):
    _, mgr_a, a = nodes("alice")
    _, mgr_b, b = nodes("bob")
    _, mgr_c, c = nodes("carol", sync_points=False)
    for engine in (a, b, c):
        engine.start()
    assert online(a) and online(b) and online(c)
    for i in range(1, 4):
        mgr_a.add_point(chat_point(f"P{i}", -600000.0 + i * 1000, -500000.0, i))
    assert wait_for(lambda: len(mgr_b.get_points()) == 3)
    pump(0.3)
    assert mgr_c.get_points() == []                                    # carol does not take waypoints
    mgr_c.add_point(chat_point("Private", -590000.0, -500000.0, 9))
    pump(0.5)
    assert all(p.name != "Private" for p in mgr_a.get_points())       # ... and does not give them
    mgr_a.clear_all()
    assert wait_for(lambda: len(mgr_b.get_points()) == 0)


def test_positions_are_shared_and_fade(nodes):
    _, _, a = nodes("alice")
    _, _, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    a.set_my_position(Position(-618089.0, -556227.0, 2421.0, 24.5, time.time()))
    assert wait_for(lambda: any(m["name"] == "alice" for m in b.markers()))
    marker = [m for m in b.markers() if m["name"] == "alice"][0]
    assert marker["x"] == -618089.0 and marker["yaw"] == 24.5 and not marker["me"]
    assert any(m["me"] for m in a.markers())
    assert b.members_online() == 1
    a.stop()                                                            # alice leaves: her marker disappears at once
    assert wait_for(lambda: not any(m["name"] == "alice" for m in b.markers()))


def test_position_sharing_off_sends_no_positions(nodes):
    _, _, a = nodes("alice", sync_position=False)
    _, _, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    a.set_my_position(Position(-618089.0, -556227.0, 2421.0, 24.5, time.time()))
    pump(3.0)
    assert not any(m["name"] == "alice" for m in b.markers())
    assert not [m for m in nodes.broker.published if m[0].split("/")[3] == "m" and len(m[1]) > 120]


def test_reconnects_after_the_broker_drops_everyone(nodes):
    _, mgr_a, a = nodes("alice")
    _, mgr_b, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    nodes.broker.drop_clients()
    pump(0.5)
    mgr_a.add_point(chat_point("After the cut", -600000.0, -500000.0, 7))
    assert wait_for(lambda: len(mgr_b.get_points()) == 1, 25)


def test_sync_off_or_missing_code_never_connects(tmp_path, broker):
    cfg = ConfigManager(str(tmp_path / "c.json"))
    mgr = PointsManager(str(tmp_path / "p.json"))
    engine = SyncEngine(cfg, mgr, str(tmp_path / "p.sync.json"))
    engine.start()
    assert engine.state == "off" and engine.client is None
    cfg.update({"sync_enabled": True, "sync_code": "garbage", "sync_broker": broker.url})
    engine.start()
    assert engine.state == "need_code" and engine.client is None
    assert point_sid(chat_point("a", -600000.0, -500000.0, 1)) == point_sid(chat_point("b", -600000.0, -500000.0, 1))


def test_pvp_mode_hides_waypoints_and_keeps_players(tmp_path):
    from PyQt6.QtCore import QPoint

    from ui.map_window import MapWindow

    cfg = ConfigManager(str(tmp_path / "c.json"))
    mgr = PointsManager(str(tmp_path / "p.json"))
    mgr.add_point(chat_point("A", -600000.0, -500000.0, 1))
    win = MapWindow(cfg, mgr)
    win.resize(900, 700)
    win.show()
    app.processEvents()
    canvas = win.canvas
    canvas.set_friend_markers([{"name": "Bob", "x": -300000.0, "y": -300000.0, "yaw": 10.0, "age": 1.0, "me": False}])
    seen = []
    win.pvp_mode_changed.connect(seen.append)
    with_pins = canvas.grab().toImage()
    win.btn_pvp.click()
    app.processEvents()
    assert canvas.pvp_mode and cfg.get("map_pvp_mode") is True and seen == [True]
    assert canvas._find_marker_at(QPoint(canvas.width() // 2, canvas.height() // 2)) is None
    assert canvas.grab().toImage() != with_pins                    # the pins are gone, the player marker stays
    assert len(canvas.friend_markers) == 1
    win.btn_pvp.click()
    assert not canvas.pvp_mode and cfg.get("map_pvp_mode") is False and seen == [True, False]
    win.close()


# -- squad: my own names, map buttons, drawer ---------------------------
def test_every_player_names_teammates_for_themselves(nodes):
    cfg_a, _, a = nodes("alice")
    cfg_b, _, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    a.set_my_position(Position(-618089.0, -556227.0, 2421.0, 24.5, time.time()))
    b.set_my_position(Position(-600000.0, -500000.0, 100.0, 90.0, time.time()))
    assert wait_for(lambda: any(m["name"] == "alice" for m in b.markers()) and any(m["name"] == "bob" for m in a.markers()))
    alice_id, bob_id = a.member, b.member
    a.set_alias(bob_id, "Андрій")                                  # alice calls bob "Андрій"
    b.set_alias(alice_id, "Олег")                                  # bob calls alice "Олег"
    assert any(m["name"] == "Андрій" and not m["me"] for m in a.markers())
    assert any(m["name"] == "Олег" and not m["me"] for m in b.markers())
    assert not any(m["name"] in ("Олег", "Андрій") for m in (a.markers() + b.markers()) if m["me"])
    assert [r["display"] for r in a.members()] == ["Андрій"] and a.members()[0]["name"] == "bob"
    assert cfg_a.get("sync_aliases") == {bob_id: "Андрій"} and cfg_b.get("sync_aliases") == {alice_id: "Олег"}
    a.set_alias(bob_id, "   ")                                     # empty name = back to the name bob uses
    assert a.members()[0]["display"] == "bob"
    a.set_alias("zz", "x")                                         # junk ids are ignored
    a.set_alias(bob_id, "Андрій")
    a.forget_member(bob_id)
    assert a.members() == [] and cfg_a.get("sync_aliases") == {} and bob_id not in cfg_a.get("sync_members")


def test_members_are_remembered_between_sessions(nodes):
    _, _, a = nodes("alice")
    _, _, b = nodes("bob")
    a.start()
    b.start()
    assert online(a) and online(b)
    assert wait_for(lambda: a.members_online() == 1)
    a.stop(quiet=True)
    rows = a.members()
    assert len(rows) == 1 and rows[0]["name"] == "bob" and rows[0]["online"] is False and rows[0]["position"] is None


def test_map_me_button_keep_zoom_and_squad_list(nodes):
    from core.coordinate_parser import convert_scum_to_norm
    from ui.map_window import MapWindow

    cfg, mgr, engine = nodes("alice")
    _, _, other = nodes("bob")
    engine.start()
    other.start()
    assert online(engine) and online(other)
    win = MapWindow(cfg, mgr)
    win.set_sync(engine)
    win.resize(1000, 800)
    win.show()
    app.processEvents()
    canvas = win.canvas
    canvas.reset_view()
    whole_zoom = canvas.zoom
    win.locate_me()                                                # position unknown yet: nothing moves, a hint is shown
    assert canvas.zoom == whole_zoom and "Ctrl+C" in win.lbl_cursor.toolTip()
    engine.set_my_position(Position(-618089.0, -556227.0, 2421.0, 24.5, time.time()))
    win.locate_me()
    assert canvas.zoom >= 3.0
    nx, ny = convert_scum_to_norm(-618089.0, -556227.0)
    img = canvas.map_images[canvas.current_variant]
    assert abs(canvas.pan_x + nx * img.width() * canvas.zoom - canvas.width() / 2) < 1.5
    assert abs(canvas.pan_y + ny * img.height() * canvas.zoom - canvas.height() / 2) < 1.5

    # keep zoom: the zoom I leave is the zoom the map opens with; off = the whole island again
    win.btn_keep.click()
    canvas.zoom = 5.0
    win.hide()
    assert cfg.get("map_keep_zoom_on_me") is True and cfg.get("map_me_zoom") == 5.0
    win.show()
    win._apply_open_view_now()
    assert canvas.zoom == 5.0
    win.btn_keep.click()
    win._apply_open_view_now()
    assert cfg.get("map_keep_zoom_on_me") is False and abs(canvas.zoom - whole_zoom) < 1e-6

    # squad list: only members that are on the map now, shown with my own names
    assert win.squad_entries() == []
    other.set_my_position(Position(-600000.0, -500000.0, 10.0, 0.0, time.time()))
    assert wait_for(lambda: len(win.squad_entries()) == 1)
    engine.set_alias(other.member, "Андрій")
    label, x, y = win.squad_entries()[0]
    assert label == "Андрій" and (x, y) == (-600000.0, -500000.0)
    win.focus_member(x, y)
    nx, ny = convert_scum_to_norm(x, y)
    assert abs(canvas.pan_x + nx * img.width() * canvas.zoom - canvas.width() / 2) < 1.5
    win.close()


def test_points_drawer_slides_and_remembers(tmp_path):
    from ui.points_drawer import PointsDrawer

    cfg = ConfigManager(str(tmp_path / "c.json"))
    mgr = PointsManager(str(tmp_path / "p.json"))
    drawer = PointsDrawer(cfg, mgr)
    drawer.resize(800, 400)
    drawer.show()
    app.processEvents()
    assert not drawer.open and drawer.points.maximumHeight() == 0 and not drawer.points.isVisible()
    assert "(0)" in drawer.handle.text()
    mgr.add_point(chat_point("A", -600000.0, -500000.0, 1))
    assert "(1)" in drawer.handle.text()
    drawer.handle.click()
    assert drawer.open and cfg.get("points_drawer_open") is True
    assert wait_for(lambda: drawer.points.maximumHeight() == drawer.target_height(), 3)
    assert drawer.points.isVisible()
    drawer.handle.click()
    assert wait_for(lambda: drawer.points.maximumHeight() == 0 and not drawer.points.isVisible(), 3)
    assert cfg.get("points_drawer_open") is False
    cfg.set("points_drawer_open", True)
    again = PointsDrawer(cfg, mgr)
    again.restore_state()
    assert again.open and again.points.maximumHeight() == again.target_height()
    drawer.close()
    again.close()


def test_settings_create_join_and_member_names(nodes, monkeypatch):
    from PyQt6.QtWidgets import QApplication as QApp

    from ui.settings_window import SettingsDialog

    cfg, _, engine = nodes("alice")
    cfg.update({"sync_enabled": False, "sync_code": "", "sync_name": "", "own_nickname": "Nick"})
    monkeypatch.setattr("ui.sync_page.notify", lambda *a, **k: None)
    dialog = SettingsDialog(cfg, sync=engine)
    section = dialog.tab_sync
    section.load(cfg)
    section.btn_create.click()
    assert section.code_is_valid() and section.chk_enable.isChecked() and section.txt_name.text() == "Nick"
    assert QApp.clipboard().text() == section.txt_code.text()
    created = section.txt_code.text()
    QApp.clipboard().setText("nonsense")
    section.txt_code.setText("")
    section.chk_enable.setChecked(False)
    section.btn_join.click()                                       # not a code: nothing is accepted
    assert section.txt_code.text() == "" and not section.chk_enable.isChecked()
    QApp.clipboard().setText(created)
    section.btn_join.click()
    assert section.txt_code.text() == created and section.chk_enable.isChecked()
    section.save(cfg)
    assert cfg.get("sync_enabled") is True and cfg.get("sync_code") == created
    cfg.set("sync_members", {"aabbccdd": "bob"})                   # typing my own name for a teammate stores it
    section._refresh_members()
    assert section.table.rowCount() == 1 and section.table.item(0, 0).text() == "bob"
    section.table.item(0, 1).setText("Андрій")
    assert cfg.get("sync_aliases") == {"aabbccdd": "Андрій"}
    dialog.close()
