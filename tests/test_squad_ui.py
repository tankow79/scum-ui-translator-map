"""Squad / drawer / map UI edge cases (headless Qt, local fake broker only)."""
import json
import math
import os
import re
import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

sys.path.insert(0, os.path.dirname(__file__))
from mqtt_fake import FakeBroker  # noqa: E402

from core.config_manager import ConfigManager  # noqa: E402
from core.coordinate_parser import MapPoint  # noqa: E402
from core.points_manager import PointsManager  # noqa: E402
from core.sync_engine import SyncEngine, clean_name  # noqa: E402

RAW_HTTP = True   # these tests talk to a local socket only
app = QApplication.instance() or QApplication([])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pump(seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(condition, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def make_point(i):
    return MapPoint.from_dict({"id": f"id{i}", "name": f"P{i}", "date_time": f"2026.11.15-12.00.{i}",
                               "raw_coord": f"{{X={-600000 + i} Y={-500000 + i} Z=10}}",
                               "x": -600000.0 + i, "y": -500000.0 + i, "z": 10.0})


@pytest.fixture
def env(tmp_path):
    cfg = ConfigManager(str(tmp_path / "c.json"))
    mgr = PointsManager(str(tmp_path / "p.json"))
    return cfg, mgr


@pytest.fixture
def engine(tmp_path):
    broker = FakeBroker()
    cfg = ConfigManager(str(tmp_path / "ec.json"))
    cfg.update({"sync_enabled": False, "sync_broker": broker.url})
    mgr = PointsManager(str(tmp_path / "ep.json"))
    eng = SyncEngine(cfg, mgr, str(tmp_path / "points.sync.json"))
    yield cfg, mgr, eng
    eng.stop(quiet=True)
    broker.close()


def assert_drawer_consistent(drawer):
    assert wait_for(lambda: drawer.points.maximumHeight() == (drawer.target_height() if drawer.open else 0)
                    and (not drawer.isVisible() or drawer.points.isVisible() == drawer.open))
    assert drawer.cfg.get("points_drawer_open") is drawer.open


# ── (1) drawer toggled rapidly ───────────────────────────────────────
@pytest.mark.parametrize("shown", [True, False])
def test_drawer_rapid_toggle(env, shown):
    from ui.points_drawer import PointsDrawer

    cfg, mgr = env
    drawer = PointsDrawer(cfg, mgr)
    drawer.resize(800, 400)
    if shown:
        drawer.show()
    app.processEvents()
    for _ in range(20):                       # no event-loop spin in between
        drawer.toggle()
    assert drawer.open is False               # even count of toggles
    assert_drawer_consistent(drawer)
    for _ in range(21):
        drawer.handle.click()
    assert drawer.open is True
    assert_drawer_consistent(drawer)
    drawer.hide()                              # hidden while a slide is running
    drawer.toggle()
    drawer.show()
    for _ in range(5):
        drawer.toggle()
        app.processEvents()
    assert_drawer_consistent(drawer)
    drawer.close()


# ── (2) many points ──────────────────────────────────────────────────
def test_drawer_with_600_points(env):
    from ui.points_drawer import PointsDrawer

    cfg, mgr = env
    for i in range(600):
        assert mgr.add_point(make_point(i))
    start = time.time()
    drawer = PointsDrawer(cfg, mgr)
    drawer.resize(800, 500)
    drawer.show()
    drawer.set_open(True)
    assert_drawer_consistent(drawer)
    drawer.set_open(False)
    assert_drawer_consistent(drawer)
    assert time.time() - start < 3.0
    assert "(600)" in drawer.handle.text()
    # rows are built in batches between event-loop turns; let them finish before the drawer is destroyed
    assert wait_for(lambda: len(drawer.points._row_widgets) == 600, 5)
    drawer.close()


def test_drawer_destroyed_while_rows_still_building(tmp_path):
    import subprocess
    lines = [
        f"import sys; sys.path.insert(0, {os.path.join(ROOT, 'tests')!r}); sys.path.insert(0, {ROOT!r})",
        "import test_squad_ui as t",
        "from core.config_manager import ConfigManager",
        "from core.points_manager import PointsManager",
        "from ui.points_drawer import PointsDrawer",
        f"cfg = ConfigManager({str(tmp_path / 'c.json')!r}); mgr = PointsManager({str(tmp_path / 'p.json')!r})",
        "[mgr.add_point(t.make_point(i)) for i in range(600)]",
        "d = PointsDrawer(cfg, mgr); d.show(); d.set_open(True); d.close(); del d; import gc; gc.collect()",
        "t.pump(0.5)",
    ]
    code = chr(10).join(lines)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
    assert res.returncode == 0 and "RuntimeError" not in res.stderr, res.stderr[-300:]


# ── (3) map window sizes ─────────────────────────────────────────────
def _finite_view(canvas):
    for name in ("zoom", "pan_x", "pan_y", "offset_x", "offset_y"):
        value = getattr(canvas, name, None)
        if isinstance(value, (int, float)):
            assert math.isfinite(value), name


@pytest.mark.parametrize("size", [(300, 250), (4000, 2500)])
def test_map_window_extreme_sizes(env, engine, size):
    from core.position_source import Position
    from ui.map_window import MapWindow

    cfg, mgr = env
    _, _, eng = engine
    win = MapWindow(cfg, mgr)
    win.set_sync(eng)
    win.resize(*size)
    win.show()
    app.processEvents()
    win.locate_me()                             # no position known yet
    eng.me = Position(-600000.0, -500000.0, 10.0, 45.0, time.time())
    eng.state = "online"
    win.locate_me()
    win.apply_open_view()
    pump(0.1)
    win.focus_member(-300000.0, -300000.0)
    win.focus_member(1e9, -1e9)                 # outside the island
    win.canvas.reset_view()
    _finite_view(win.canvas)
    win.close()


# ── (4) never shown ──────────────────────────────────────────────────
def test_apply_open_view_never_shown(env):
    from ui.map_window import MapWindow

    cfg, mgr = env
    win = MapWindow(cfg, mgr)
    assert win.canvas.width() >= 0
    win.apply_open_view()
    win.locate_me()
    win.focus_member(-300000.0, -300000.0)
    pump(0.1)
    _finite_view(win.canvas)
    win.deleteLater()


# ── (5) PvP mode ─────────────────────────────────────────────────────
def test_pvp_mode_at_construction(env):
    from ui.map_window import MapWindow

    cfg, mgr = env
    cfg.set("map_pvp_mode", True)
    win = MapWindow(cfg, mgr)
    win.resize(900, 700)
    win.show()
    app.processEvents()
    assert win.canvas.pvp_mode and not win.drawer.isVisible() and win.btn_pvp.isChecked()
    win.btn_pvp.click()
    app.processEvents()
    assert not win.canvas.pvp_mode and win.drawer.isVisible()
    assert cfg.get("map_pvp_mode") is False
    win.btn_pvp.click()
    app.processEvents()
    assert win.canvas.pvp_mode and not win.drawer.isVisible()
    win.close()


# ── (6) aliases ──────────────────────────────────────────────────────
MEMBER = "aabbccdd"


@pytest.mark.parametrize("alias,expected", [
    ("", None),
    ("   \t ", None),
    ("x" * 40, "x" * 24),
    ("<b>x</b>", "<b>x</b>"),
    ("a\x00b\x07c\x1bd", "abcd"),
    ("a\nb", "ab"),
    ("\U0001F600 hi", "\U0001F600 hi"),
])
def test_set_alias_cleaning(engine, alias, expected):
    cfg, _, eng = engine
    eng.set_alias(MEMBER, alias)
    stored = cfg.get("sync_aliases")
    assert isinstance(stored, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in stored.items())
    if expected is None:
        assert MEMBER not in stored
    else:
        assert stored[MEMBER] == expected and len(stored[MEMBER]) <= 24
    assert eng.display_name(MEMBER, "fb")


def test_alias_invalid_member_and_non_dict(engine):
    cfg, _, eng = engine
    eng.set_alias("", "x")
    eng.set_alias("not a member!", "x")
    assert not cfg.get("sync_aliases")
    cfg.set("sync_aliases", ["junk"])
    eng.set_alias(MEMBER, "ok")                 # a corrupted value must not break it
    assert cfg.get("sync_aliases") == {MEMBER: "ok"}
    cfg.set("sync_aliases", {MEMBER: 5})
    assert eng.display_name(MEMBER, "fb") == "fb"


def test_1000_aliases_and_forget(engine):
    cfg, _, eng = engine
    start = time.time()
    for i in range(1000):
        eng.set_alias(f"{i:08x}", f"name{i}" + "z" * 30)
    stored = cfg.get("sync_aliases")
    assert isinstance(stored, dict)
    assert all(isinstance(v, str) and len(v) <= 24 for v in stored.values())
    assert time.time() - start < 30
    cfg.set("sync_members", {"00000001": "bob"})
    eng.forget_member("00000001")
    assert "00000001" not in cfg.get("sync_aliases") and "00000001" not in cfg.get("sync_members")
    eng.forget_member("ffffffff")               # unknown: no error
    assert clean_name("x" * 100) == "x" * 24


# ── (7) settings sync section ────────────────────────────────────────
def test_settings_alias_html_stays_plain(engine, monkeypatch):
    from ui.settings_window import SettingsDialog

    cfg, _, eng = engine
    monkeypatch.setattr("ui.sync_page.notify", lambda *a, **k: None)
    cfg.set("sync_members", {MEMBER: "bob"})
    dialog = SettingsDialog(cfg, sync=eng)
    section = dialog.tab_sync
    section._refresh_members()
    section.table.item(0, 1).setText("<b>x</b>")
    assert cfg.get("sync_aliases") == {MEMBER: "<b>x</b>"}
    assert section.table.item(0, 1).text() == "<b>x</b>"
    section.table.item(0, 1).setText("")
    assert MEMBER not in cfg.get("sync_aliases")
    dialog.close()


@pytest.mark.parametrize("answer", [False, True])
def test_create_squad_with_existing_code_asks(engine, monkeypatch, answer):
    from core import sync_crypto as sc
    from ui.settings_window import SettingsDialog

    cfg, _, eng = engine
    monkeypatch.setattr("ui.sync_page.notify", lambda *a, **k: None)
    asked = []
    monkeypatch.setattr("ui.sync_page.ask", lambda *a, **k: asked.append(1) or answer)
    existing = sc.new_code()
    cfg.update({"sync_code": existing, "sync_enabled": False})
    dialog = SettingsDialog(cfg, sync=eng)
    section = dialog.tab_sync
    section.load(cfg)
    assert section.code_is_valid()
    section.btn_create.click()
    assert len(asked) == 1
    if answer:
        assert section.txt_code.text() != existing and section.code_is_valid()
    else:
        assert section.txt_code.text() == existing
    dialog.close()


# ── (8) localisation ─────────────────────────────────────────────────
def _flat(data, prefix=""):
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _flat(value, path + ".")
        else:
            yield path


def _new_keys():
    keys = {}
    for lang in ("en", "uk"):
        with open(os.path.join(ROOT, "assets", "locales", f"{lang}.json"), encoding="utf-8") as f:
            keys[lang] = set(_flat(json.load(f)))
    wanted = {k for k in keys["en"] | keys["uk"]
              if k.startswith(("sync.", "map_window.")) or k.startswith("points.drawer_")}
    return keys, wanted


def test_new_keys_exist_in_both_locales():
    keys, wanted = _new_keys()
    assert wanted
    for lang in ("en", "uk"):
        assert not (wanted - keys[lang]), f"missing in {lang}: {sorted(wanted - keys[lang])}"


def test_keys_used_in_source_exist():
    keys, _ = _new_keys()
    used = set()
    for path in ("ui/sync_page.py", "ui/map_window.py", "ui/points_drawer.py", "ui/settings_window.py"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            used |= set(re.findall(r'\btr\(\s*"((?:sync|map_window|points)\.[a-z0-9_.]+)"', f.read()))
    assert used
    for lang in ("en", "uk"):
        assert not (used - keys[lang]), f"used but missing in {lang}: {sorted(used - keys[lang])}"


def test_no_raw_keys_after_language_switch(env, engine, monkeypatch):
    from core.i18n import LocalizationManager
    from ui.map_window import MapWindow
    from ui.settings_window import SettingsDialog

    monkeypatch.setattr("ui.sync_page.notify", lambda *a, **k: None)
    manager = LocalizationManager.get_instance()
    original = manager.current_locale
    pattern = re.compile(r"\b(sync|map_window|points)\.[a-z0-9_]+")
    cfg, mgr = env
    _, _, eng = engine
    try:
        for locale in ("uk", "en"):
            assert manager.set_locale(locale)
            widgets = [SettingsDialog(cfg, sync=eng), MapWindow(cfg, mgr)]
            for top in widgets:
                top.show()
                app.processEvents()
                for w in top.findChildren(QWidget):
                    texts = [w.toolTip()]
                    if isinstance(w, (QLabel, QPushButton)):
                        texts.append(w.text())
                    for text in texts:
                        assert not pattern.fullmatch(text.strip()), f"raw key {text!r} in {locale}"
                top.close()
    finally:
        manager.set_locale(original)
