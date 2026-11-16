"""Gap-filling adversarial tests for clan sync: config migration, locale parity, clipboard parsing, settings round trips,
shutdown while connecting, malformed/huge inputs. Local sockets only; no real user files."""
import json
import os
import re
import socket
import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(__file__))

from core import sync_crypto as sc  # noqa: E402
from core.config_manager import DEFAULT_CONFIG, ConfigManager  # noqa: E402
from core.mqtt_lite import PacketReader, parse_broker, topic_matches  # noqa: E402
from core.points_manager import PointsManager  # noqa: E402
from core.position_source import parse_position  # noqa: E402
from core.sync_engine import SyncEngine, clean_name  # noqa: E402

app = QApplication.instance() or QApplication([])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_KEYS = ["map_pvp_mode", "sync_aliases", "sync_members", "map_keep_zoom_on_me", "map_me_zoom",
            "points_drawer_open", "sync_enabled", "sync_code", "sync_name", "sync_member_id", "sync_points",
            "sync_position", "sync_auto_copy", "sync_auto_copy_seconds", "sync_broker"]


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        cur = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flat(v, cur))
        else:
            out[cur] = v
    return out


def _locale(name):
    with open(os.path.join(ROOT, "assets", "locales", name), encoding="utf-8") as f:
        return _flat(json.load(f))


# -- locale parity ----------------------------------------------------
def test_locale_key_parity_en_uk():
    en, uk = _locale("en.json"), _locale("uk.json")
    assert not (set(en) - set(uk)), f"missing in uk: {sorted(set(en) - set(uk))[:10]}"
    assert not (set(uk) - set(en)), f"missing in en: {sorted(set(uk) - set(en))[:10]}"


def test_locale_placeholders_match_and_sync_strings_not_empty():
    en, uk = _locale("en.json"), _locale("uk.json")
    ph = re.compile(r"\{(\w+)\}")
    bad = [k for k in en if k in uk and isinstance(en[k], str) and isinstance(uk[k], str)
           and set(ph.findall(en[k])) != set(ph.findall(uk[k]))]
    assert not bad, f"placeholder mismatch: {bad[:10]}"
    empty = [k for loc in (en, uk) for k, v in loc.items() if k.startswith("sync.") and v == ""]
    assert not empty


# -- config migration -------------------------------------------------
def test_old_config_without_new_keys_gets_defaults_and_keeps_old_values(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"target_language": "de", "font_size": 30}), encoding="utf-8")
    cfg = ConfigManager(str(p))
    for k in NEW_KEYS:
        assert k in cfg.config and cfg.get(k) == DEFAULT_CONFIG[k]
    assert cfg.get("target_language") == "de" and cfg.get("font_size") == 30
    cfg.get("sync_aliases")["x"] = "y"
    assert DEFAULT_CONFIG["sync_aliases"] == {}          # defaults are copied, not shared


@pytest.mark.parametrize("key,bad", [("sync_enabled", "yes"), ("sync_code", 5), ("sync_aliases", [1]),
                                     ("sync_members", "x"), ("map_me_zoom", "big"),
                                     ("sync_auto_copy_seconds", None), ("map_pvp_mode", 1),
                                     ("points_drawer_open", "no"), ("sync_broker", ["a"])])
def test_wrong_typed_new_keys_fall_back_to_default(tmp_path, key, bad):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({key: bad}), encoding="utf-8")
    assert ConfigManager(str(p)).get(key) == DEFAULT_CONFIG[key]


def test_nan_zoom_in_config_falls_back(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"map_me_zoom": NaN}', encoding="utf-8")
    assert ConfigManager(str(p)).get("map_me_zoom") == DEFAULT_CONFIG["map_me_zoom"]


def test_sanitize_values_for_profiles_ignores_unknown_and_fixes_bad_sync_keys():
    out = ConfigManager.sanitize_values({"sync_enabled": "x", "sync_name": "Bob", "unknown_key": 1})
    assert out == {"sync_enabled": False, "sync_name": "Bob"}


def test_config_with_huge_alias_map_loads(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"sync_aliases": {str(i): "n" * 50 for i in range(5000)}}), encoding="utf-8")
    assert len(ConfigManager(str(p)).get("sync_aliases")) == 5000


# -- clipboard position parsing (input of main.py on_clipboard_changed)
GOOD = "{X=-123456.7 Y=234567.8 Z=1234.5|P=0.0 Y=90.0 R=0.0}"


def test_parse_position_good_and_yaw_wrap():
    pos = parse_position(GOOD, now=5.0)
    assert pos is not None and pos.stamp == 5.0 and abs(pos.yaw - 90.0) < 1e-6
    wrapped = parse_position(GOOD.replace("Y=90.0", "Y=-90.0"))
    assert wrapped is not None and abs(wrapped.yaw - 270.0) < 1e-6


@pytest.mark.parametrize("text", [None, 5, b"x", "", "   ", "{X=1 Y=2 Z=3}", "X=Y=Z=",
                                  "{X=nan Y=nan Z=nan|P=0 Y=0 R=0}", "{X=inf Y=1 Z=1|P=0 Y=0 R=0}",
                                  "{X=99999999 Y=99999999 Z=1|P=0 Y=0 R=0}", "x" * 100000,
                                  GOOD + " " * 500, "\x00" * 50])
def test_parse_position_rejects_junk(text):
    assert parse_position(text) is None


def test_parse_position_never_raises_on_random_text():
    import random
    rnd = random.Random(1)
    alphabet = "{}|=XYZPR0123456789.- eE+\n"
    for _ in range(2000):
        parse_position("".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 80))))


# -- broker / names / crypto / framing --------------------------------
@pytest.mark.parametrize("text", ["", "   ", None, "http://x", "mqtt://", "host:0", "host:65536", "host:abc",
                                  "host:-1", "a b:1883", ":1883", "mqtt://:1883"])
def test_parse_broker_rejects_malformed(text):
    assert parse_broker(text) is None


def test_parse_broker_variants():
    assert parse_broker("Host") == ("Host", 8883, True)
    assert parse_broker("mqtt://h") == ("h", 1883, False)
    assert parse_broker("MQTTS://h:1/") == ("h", 1, True)
    assert parse_broker("  mqtt://h:65535  ") == ("h", 65535, False)


def test_parse_broker_extra_colon_is_rejected():
    assert parse_broker("host:1:2") is None


def test_clean_name_hostile_values():
    for bad in (None, 5, [], {}, "", "   ", "\x00\n\t"):
        assert isinstance(clean_name(bad), str) and clean_name(bad)
    assert len(clean_name("я" * 5000)) <= 64
    assert "\n" not in clean_name("a\nb") and "\x00" not in clean_name("a\x00b")


def test_open_sealed_garbage_never_raises():
    keys = sc.keys_from_code(sc.new_code())
    for n in (0, 1, 15, 16, 17, 31, 32, 33, 100, 5000):
        assert sc.open_sealed(keys, os.urandom(n)) is None


def test_packet_reader_garbage_does_not_raise_unexpected():
    for blob in (b"\xff" * 7, b"\x30\x80\x80\x80\x80\x01" + b"x" * 10, b"\x00", b""):
        r = PacketReader()
        try:
            list(r.feed(blob))
        except ValueError:
            pass
    assert topic_matches("a/+/c", "a/b/c") and not topic_matches("a/+", "a/b/c")


# -- engine: lifecycle and hostile inputs -----------------------------
def _engine(tmp_path, **over):
    cfg = ConfigManager(str(tmp_path / "config.json"))
    for k, v in over.items():
        cfg.set(k, v, save=False)
    pm = PointsManager(str(tmp_path / "points.json"))
    return cfg, pm, SyncEngine(cfg, pm, str(tmp_path / "meta.json"))


def _dead_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_start_with_garbage_code_or_disabled_does_not_connect(tmp_path):
    cfg, pm, eng = _engine(tmp_path, sync_enabled=True, sync_code="garbage")
    eng.start()
    assert eng.state == "need_code" and eng.client is None
    cfg.set("sync_enabled", False, save=False)
    eng.start()
    assert eng.state == "off" and eng.client is None
    eng.stop()


def test_stop_while_connecting_is_prompt_and_repeatable(tmp_path):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)                       # accepts TCP but never answers CONNACK: the client hangs "connecting"
    port = srv.getsockname()[1]
    cfg, pm, eng = _engine(tmp_path, sync_enabled=True, sync_code=sc.new_code(),
                           sync_broker=f"mqtt://127.0.0.1:{port}")
    try:
        t0 = time.time()
        eng.start()
        time.sleep(0.3)
        client = eng.client
        eng.stop()
        eng.stop()                      # twice must be harmless
        assert time.time() - t0 < 6.0, "stop() blocked while the broker never answered"
        client.join(8.0)
        assert not client.is_alive(), "mqtt thread leaked after stop()"
        assert eng.client is None and eng.state == "off"
    finally:
        srv.close()


def test_restart_loop_while_unreachable_leaks_no_threads(tmp_path):
    cfg, pm, eng = _engine(tmp_path, sync_enabled=True, sync_code=sc.new_code(),
                           sync_broker=f"mqtt://127.0.0.1:{_dead_port()}")
    clients = []
    for _ in range(5):
        eng.start()
        clients.append(eng.client)
        app.processEvents()
    eng.stop()
    for c in clients:
        c.join(8.0)
        assert not c.is_alive()


def test_events_after_stop_and_hostile_messages_are_ignored(tmp_path):
    cfg, pm, eng = _engine(tmp_path, sync_enabled=True, sync_code=sc.new_code(),
                           sync_broker=f"mqtt://127.0.0.1:{_dead_port()}")
    eng.start()
    keys = eng.keys
    base = f"scum/{keys.room}"
    session = eng._session
    eng.stop()
    for topic, payload in [(base + "/p/abc", b"junk"), (base + "/p/", b""), ("", b""),
                           (base + "/m/x", b"\x00" * 3000), ("weird", b"{}"),
                           (base + "/p/" + "z" * 5000, sc.seal(keys, {"a": 1}))]:
        eng._on_message(session, topic, payload)
        eng._on_message(eng._session, topic, payload)
    eng._on_state(session, "connected", "x")
    assert eng.state == "off"


def test_remote_garbage_documents_do_not_crash(tmp_path):
    cfg, pm, eng = _engine(tmp_path)
    eng.keys = sc.keys_from_code(sc.new_code())
    docs = [{}, {"v": "x"}, {"v": 1, "d": 5}, {"v": 1, "d": {"x": "a", "y": None}}, {"v": 10 ** 30, "d": {}},
            {"v": -1}, {"k": "pos", "m": 5, "x": "q"},
            {"k": "pos", "m": "m1", "x": float("nan"), "y": 1, "z": 1, "w": 1, "t": 1},
            {"k": "pos", "m": "m1", "x": 1e300, "y": 1, "z": 1, "w": 1, "t": 1}]   # non-dict docs are filtered in _on_message
    for i, doc in enumerate(docs):
        for fn in (eng._remote_point, eng._remote_member):
            try:
                fn(f"id{i}", doc)
            except Exception as exc:
                pytest.fail(f"{fn.__name__} raised {type(exc).__name__}: {exc} on {doc!r}")
    for m in eng.markers():
        assert all(abs(m[k]) < 1e7 for k in ("x", "y") if isinstance(m.get(k), (int, float)))


def test_alias_and_forget_edge_cases(tmp_path):
    cfg, pm, eng = _engine(tmp_path)
    eng.set_alias("m1", "x" * 10000)
    assert len(eng.display_name("m1", "Fallback")) <= 64
    eng.set_alias("m1", "")
    assert eng.display_name("m1", "Fallback") == "Fallback"
    eng.set_alias("", "a")
    eng.forget_member("nobody")
    cfg.set("sync_aliases", "corrupt", save=False)
    assert eng.display_name("m1", "F") == "F"
    assert isinstance(eng.members(), list)


def test_meta_file_corrupt_or_wrong_shape(tmp_path):
    for content in ("", "{", "[]", '{"a": 5}', '{"a": [1]}', '{"a": ["x", 1, 0]}', "null"):
        (tmp_path / "meta.json").write_text(content, encoding="utf-8")
        cfg = ConfigManager(str(tmp_path / "config.json"))
        eng = SyncEngine(cfg, PointsManager(str(tmp_path / "points.json")), str(tmp_path / "meta.json"))
        eng._reindex()
        eng.stop()


def test_set_my_position_without_client_is_safe(tmp_path):
    cfg, pm, eng = _engine(tmp_path)
    eng.set_my_position(parse_position(GOOD))
    eng._on_tick()
    assert eng.me is not None


# -- settings dialog round trips --------------------------------------
def _dialog(tmp_path, **over):
    from ui.settings_window import SettingsDialog
    cfg = ConfigManager(str(tmp_path / "config.json"))
    for k, v in over.items():
        cfg.set(k, v, save=False)
    return cfg, SettingsDialog(cfg)


def test_settings_save_roundtrip_keeps_sync_values(tmp_path):
    code = sc.new_code()
    cfg, dlg = _dialog(tmp_path, sync_enabled=True, sync_code=code, sync_name="Bob", sync_auto_copy_seconds=9,
                       sync_broker="mqtt://h:1", sync_points=False)
    dlg.tab_sync.save(cfg)
    assert cfg.get("sync_enabled") is True and cfg.get("sync_code") == code and cfg.get("sync_name") == "Bob"
    assert cfg.get("sync_auto_copy_seconds") == 9 and cfg.get("sync_broker") == "mqtt://h:1"
    assert cfg.get("sync_points") is False


def test_settings_invalid_code_never_enables_and_seconds_clamped(tmp_path):
    cfg, dlg = _dialog(tmp_path, sync_auto_copy_seconds=100000)
    dlg.tab_sync.chk_enable.setChecked(True)
    dlg.tab_sync.txt_code.setText("nonsense")
    dlg.tab_sync.save(cfg)
    assert cfg.get("sync_enabled") is False
    assert 3 <= cfg.get("sync_auto_copy_seconds") <= 60


def test_settings_cancel_does_not_write(tmp_path):
    cfg, dlg = _dialog(tmp_path, sync_name="Keep")
    dlg.tab_sync.txt_name.setText("Changed")
    dlg.tab_sync.chk_enable.setChecked(True)
    dlg.reject()
    assert cfg.get("sync_name") == "Keep" and cfg.get("sync_enabled") is False


def test_sync_page_join_with_hostile_clipboard(tmp_path, monkeypatch):
    import ui.sync_page as sp
    monkeypatch.setattr(sp, "notify", lambda *a, **k: None)
    cfg, dlg = _dialog(tmp_path)
    saved = QApplication.clipboard().text()
    try:
        for text in ("", "SCUM1-", "x" * 100000, "\x00\n"):
            QApplication.clipboard().setText(text)
            dlg.tab_sync._join_from_clipboard()
        assert not dlg.tab_sync.chk_enable.isChecked() and dlg.tab_sync.txt_code.text() == ""
        dlg.tab_sync.set_own_nickname(None)
        assert dlg.tab_sync._default_name() == ""
    finally:
        QApplication.clipboard().setText(saved)
