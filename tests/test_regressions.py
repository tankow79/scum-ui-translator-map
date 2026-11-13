"""Regression tests for bugs found in the hard-debugging pass (one test per defect class)."""

import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from core.chat_history import ChatHistory
from core.config_manager import ConfigManager
from core.coordinate_parser import MapPoint, parse_chat_coordinate
from core.log_parser import ScumLogParser
from core.players import PlayerRegistry
from core.points_manager import PointsManager
from core.translator import GoogleTranslatorEngine
from core.version import __version__

ROOT = Path(__file__).resolve().parent.parent
app = QApplication.instance() or QApplication(sys.argv)


# ───────────── versions must agree (a tag/exe mismatch makes the updater offer the running version forever) ─────────────

def test_version_files_agree():
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert pyproject == __version__
    for name in ("version_info.txt", "version_info_portable.txt"):
        info = (ROOT / name).read_text(encoding="utf-8")
        tuple_form = tuple(int(x) for x in re.search(r"filevers=\((\d+), (\d+), (\d+), (\d+)\)", info).groups())
        assert tuple_form == tuple(int(x) for x in __version__.split(".")) + (0,), name
        assert f"'FileVersion', '{__version__}.0'" in info and f"'ProductVersion', '{__version__}.0'" in info, name
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(__version__)}\]", changelog, re.M), "CHANGELOG has no entry for this version"
    assert (ROOT / ".github" / "release-notes" / f"v{__version__}.md").exists(), "release notes are missing"


# ───────────── chat content must never crash the app ─────────────

@pytest.mark.parametrize("text", ["{X=. Y=1 Z=2}", "{X=1.2.3 Y=1 Z=2}", "{X=- Y=- Z=-}", "{X=1 Y=2 Z=}"])
def test_malformed_coordinates_are_ignored(text):
    assert parse_chat_coordinate(text) is None


def test_valid_coordinates_still_parse():
    pt = parse_chat_coordinate("base {X=174468.797 Y=345933.000 Z=34103.105|P=1.0 Y=2.0 R=0.0}")
    assert pt is not None and pt.x == pytest.approx(174468.797)
    assert parse_chat_coordinate("{X=-142861 Y=-142348 Z=15000}") is not None


def test_translation_failures_are_not_cached():
    engine = GoogleTranslatorEngine(target_lang="uk")
    results = iter([("hello friend", "unknown"), ("привіт друже", "en")])
    with patch.object(engine, "_translate_with_fallbacks", side_effect=lambda *a: next(results)):
        assert engine.translate("hello friend") == ("hello friend", "unknown")
        assert engine.translate("hello friend") == ("привіт друже", "en")   # retried, not stuck on the failure
        assert engine.translate("hello friend") == ("привіт друже", "en")   # successes are cached (no 3rd call)


def test_translation_cache_is_bounded():
    engine = GoogleTranslatorEngine(target_lang="uk")
    engine.CACHE_LIMIT = 5
    for i in range(20):
        engine._cache_put(f"k{i}", (f"v{i}", "en"))
    assert len(engine._cache) == 5 and "k19" in engine._cache and "k0" not in engine._cache


# ───────────── user data survives crashes and corruption ─────────────

def test_corrupt_config_is_preserved_not_overwritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"own_nickname": "Hero", ', encoding="utf-8")   # truncated JSON
    cfg = ConfigManager(str(path))
    cfg.set("font_size", 20)
    kept = list(tmp_path.glob("config.json.corrupt-*"))
    assert len(kept) == 1 and "Hero" in kept[0].read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["font_size"] == 20


def test_config_batch_writes_once_and_atomically(tmp_path):
    cfg = ConfigManager(str(tmp_path / "config.json"))
    writes = []
    real_save = cfg.save
    cfg.save = lambda: (writes.append(1), real_save())
    with cfg.batch():
        for i in range(10):
            cfg.set(f"k{i}", i)
        assert writes == []
    assert writes == [1]
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["k9"] == 9
    assert not (tmp_path / "config.json.tmp").exists()


def test_corrupt_points_and_players_are_kept(tmp_path):
    (tmp_path / "points.json").write_text("[{broken", encoding="utf-8")
    (tmp_path / "players.json").write_text("{broken", encoding="utf-8")
    PointsManager(str(tmp_path / "points.json"))
    PlayerRegistry(str(tmp_path / "players.json"))
    assert list(tmp_path.glob("points.json.corrupt-*")) and list(tmp_path.glob("players.json.corrupt-*"))


def test_players_file_with_garbage_values_loads(tmp_path):
    sid = "76561199117414081"
    (tmp_path / "players.json").write_text(json.dumps({"version": 2, "players": {
        sid: {"nick": "A", "last_seen": "abc", "first_seen": None,
              "previous_nicks": [{"nick": "Old", "changed_at": "bad"}, None, 5]},
        "76561198995660378": {"nick": "B", "previous_nicks": None},
    }}), encoding="utf-8")
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    assert reg.nick_of(sid) == "A" and reg.get(sid)["previous_nicks"] == [{"nick": "Old", "changed_at": 0.0}]
    reg.observe(sid, "A2", "", 100.0)   # must not raise on the reader thread
    assert reg.nick_of(sid) == "A2" and reg.nick_of("76561198995660378") == "B"


def test_same_waypoint_is_not_added_twice(tmp_path):
    mgr = PointsManager(str(tmp_path / "points.json"))

    def pt(ts):
        return MapPoint(id=str(ts), name="base", date_time="", raw_coord="{X=1 Y=2 Z=3}", x=1, y=2, z=3, sector="B2",
                        keypad="k5", norm_x=.5, norm_y=.5, created_timestamp=ts)
    assert mgr.add_point(pt(1000.0)) is True
    assert mgr.add_point(pt(9999.0)) is False      # the chat backlog replayed on the next start
    assert len(mgr.get_points()) == 1


def test_history_recovers_from_a_half_written_last_line(tmp_path):
    path = tmp_path / "h.jsonl"
    good = {"timestamp": "t", "time_str": "1", "sender": "A", "original": "x", "translated": "x",
            "src_lang": "en", "msg_type": "player"}
    path.write_text(json.dumps(good) + '\n{"timestamp": "t", "sen', encoding="utf-8")   # crash mid-write
    hist = ChatHistory(max_entries=100, path=str(path))
    hist.add("2", "B", "second", "second", "en", "player")
    reloaded = ChatHistory(max_entries=100, path=str(path))
    assert [e.original for e in reloaded.query()] == ["x", "second"]


# ───────────── log tailing ─────────────

def _wait(cond, seconds=5.0):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        time.sleep(0.05)
    return cond()


def test_parser_follows_a_changed_log_path(tmp_path):
    a, b = tmp_path / "a.log", tmp_path / "b.log"
    line = "[2026.11.13-01.54.49:390][201]LogSCUM: Message: Bob: {}\n"
    a.write_text(line.format("from A"), encoding="utf-8")
    b.write_text(line.format("from B"), encoding="utf-8")
    got = []
    parser = ScumLogParser(str(a), lambda *x: got.append(x[2]))
    parser.start()
    try:
        assert _wait(lambda: "from A" in got)
        parser.set_log_path(str(b))
        assert _wait(lambda: "from B" in got)
    finally:
        parser.stop()


def test_parser_waits_for_a_complete_line(tmp_path):
    log_file = tmp_path / "SCUM.log"
    log_file.write_text("", encoding="utf-8")
    got = []
    parser = ScumLogParser(str(log_file), lambda *x: got.append(x[2]))
    parser.start()
    try:
        time.sleep(0.5)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("[2026.11.13-01.54.49:390][201]LogSCUM: Message: Bob: hel")   # game is mid-write
            f.flush()
            time.sleep(0.6)
            assert got == []                                                      # half a message is not delivered
            f.write("lo world\n")
        assert _wait(lambda: got == ["hello world"])
    finally:
        parser.stop()


def test_registry_scan_ignores_an_unfinished_last_line(tmp_path):
    sid = "76561199117414081"
    live = tmp_path / "SCUM.log"
    complete = f"[2026.11.13-01.54.49:390][201]LogSCUM: Message from user: Ann ({sid}) (hash: AB12)\n"
    partial = f"[2026.11.13-01.55.00:390][201]LogSCUM: Message from user: Bea ({sid}) (ha"
    live.write_text(complete + partial, encoding="utf-8")
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    reg.scan_logs(str(live))
    assert reg.nick_of(sid) == "Ann"
    with open(live, "a", encoding="utf-8") as f:
        f.write("sh: CD34)\n")
    reg.scan_logs(str(live))
    assert reg.nick_of(sid) == "Bea"          # the line is read once it is complete, not lost


# ───────────── UI behaviours ─────────────

def test_update_dialog_cannot_be_closed_while_installing(tmp_path):
    from tests.test_updater import make_info
    from ui.update_dialog import UpdateDialog

    dlg = UpdateDialog(make_info())
    dlg.show()
    dlg._set_state("installing")
    dlg.reject()
    assert dlg.isVisible()
    dlg._set_state("prompt")
    dlg.reject()
    assert not dlg.isVisible()


def test_cancelled_download_does_not_show_an_error():
    from tests.test_updater import make_info
    from ui.update_dialog import UpdateDialog

    dlg = UpdateDialog(make_info())
    dlg._set_state("prompt")
    dlg._on_download_error("Download cancelled.")
    assert dlg._state == "prompt"
    dlg._set_state("downloading")
    dlg._on_download_error("Download failed")
    assert dlg._state == "error"


def test_downloader_cancel_token_is_per_download(tmp_path, monkeypatch):
    import core.updater as updater
    dl = updater.UpdateDownloader()
    first = dl._cancel
    dl.cancel()
    assert first.is_set()
    monkeypatch.setattr(updater.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: None})())
    dl.download_async("https://x/a.exe", "a.exe")
    assert dl._cancel is not first and not dl._cancel.is_set()   # a late cancel of the old one cannot hit the new


def test_settings_dialog_discards_cancelled_edits(tmp_path):
    from ui.settings_window import SettingsDialog

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    dlg = SettingsDialog(cfg)
    dlg.show()
    dlg.txt_nickname.setText("Typed but never saved")
    dlg.hide()
    dlg.show()
    assert dlg.txt_nickname.text() == cfg.get("own_nickname", "")
    dlg.close()


def test_map_keeps_view_when_shown_again(tmp_path):
    from ui.map_window import MapWindow

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    win = MapWindow(cfg, PointsManager(str(tmp_path / "p.json")))
    win.show()
    win.canvas.zoom = 3.0
    win.hide()
    win.show()
    assert win.canvas.zoom == 3.0
    win.close()


def test_overlay_does_not_rebuild_identical_chat(tmp_path):
    from ui.overlay import ChatOverlay

    overlay = ChatOverlay(ConfigManager(str(tmp_path / "cfg.json")))
    overlay.add_message("12:00:00", "Bob", "hi", "hi", "en", "player")
    first = overlay._last_rendered_html
    calls = []
    real = overlay.chat_view.setHtml
    overlay.chat_view.setHtml = lambda html: (calls.append(1), real(html))
    overlay._refresh_rendered_chat()   # what the 500 ms fade timer does
    assert overlay._last_rendered_html == first and calls == []


# ───────────── the app survives an exception inside a Qt slot ─────────────

def test_exception_in_a_slot_does_not_kill_the_process(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "from PyQt6.QtCore import QTimer\n"
        "import main\n"
        "main._install_exception_hooks()\n"
        "app = QApplication([])\n"
        "def boom(): raise RuntimeError('slot failure')\n"
        "QTimer.singleShot(50, boom)\n"
        "QTimer.singleShot(400, app.quit)\n"
        "sys.exit(app.exec())\n"
    ) % str(ROOT)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", SCUM_DATA_DIR=str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-1500:]


def test_log_can_be_renamed_while_it_is_being_tailed(tmp_path):
    """The game rotates SCUM.log to SCUM-backup-*.log; our open handle must not block that."""
    log_file = tmp_path / "SCUM.log"
    log_file.write_text("[2026.11.13-01.54.49:390][201]LogSCUM: Message: Bob: hi\n", encoding="utf-8")
    got = []
    parser = ScumLogParser(str(log_file), lambda *x: got.append(x[2]))
    parser.start()
    try:
        assert _wait(lambda: got == ["hi"])
        os.replace(log_file, tmp_path / "SCUM-backup-2026.11.13-02.00.00.log")   # WinError 32 without the fix
        log_file.write_text("[2026.11.13-02.00.01:390][201]LogSCUM: Message: Bob: after rotation\n", encoding="utf-8")
        assert _wait(lambda: "after rotation" in got)
    finally:
        parser.stop()


def test_updater_errors_are_translated():
    from core.i18n import LocalizationManager
    from core.updater import localize_error

    mgr = LocalizationManager.get_instance()
    try:
        mgr.set_locale("uk")
        assert "502" in localize_error("GitHub responded with HTTP 502.")
        assert localize_error("GitHub responded with HTTP 502.") != "GitHub responded with HTTP 502."
        assert localize_error("Something nobody translated") == "Something nobody translated"
        mgr.set_locale("en")
        assert localize_error("Download cancelled.") == "Download cancelled."
    finally:
        mgr.set_locale("en")


def test_chat_messages_are_shown_in_order(tmp_path):
    from core.controller import AppController

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    ctrl = AppController(cfg, GoogleTranslatorEngine(target_lang="uk"))
    shown = []
    ctrl._publish = lambda *a: shown.append(a[2])
    first, second, third = ctrl._take_ticket(), ctrl._take_ticket(), ctrl._take_ticket()
    ctrl._publish_in_order(second, "t", "B", "second", "x", "en", "player")
    ctrl._publish_in_order(third, "t", "C", "third", "x", "en", "player")
    assert shown == []                                   # the first (slow) message is still being translated
    ctrl._publish_in_order(first, "t", "A", "first", "x", "en", "player")
    assert shown == ["first", "second", "third"]


def test_a_hanging_translation_does_not_block_the_chat(tmp_path):
    from core.controller import AppController

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    ctrl = AppController(cfg, GoogleTranslatorEngine(target_lang="uk"))
    ctrl.ORDER_WAIT_SECONDS = 0.3
    shown = []
    ctrl._publish = lambda *a: shown.append(a[2])
    stuck, quick = ctrl._take_ticket(), ctrl._take_ticket()
    ctrl._started_times[stuck] = time.monotonic()         # its translation is running (and hangs)
    ctrl._publish_in_order(quick, "t", "B", "quick", "x", "en", "player")
    assert shown == []
    assert _wait(lambda: shown == ["quick"], 3.0)         # released by the timer after the wait limit
    ctrl._publish_in_order(stuck, "t", "A", "late", "x", "en", "player")
    assert shown == ["quick", "late"]                    # the slow one still appears when it finally finishes


def test_portable_build_is_detected_by_flag_even_when_renamed(tmp_path, monkeypatch):
    import core.updater as updater

    (tmp_path / "portable.flag").write_text("x", encoding="utf-8")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "Translator.exe"))
    assert updater.is_portable_build() is True
    (tmp_path / "portable.flag").unlink()
    assert updater.is_portable_build() is False


def test_damaged_user_file_does_not_replace_a_good_backup(tmp_path):
    import core.updater as updater

    (tmp_path / "config.json").write_text('{"a": 1}', encoding="utf-8")
    updater.UpdateInstaller.backup_user_data(str(tmp_path))
    good_backups = list((tmp_path / ".update_backup").iterdir())
    time.sleep(1.1)                                                        # backup folders are named by second
    (tmp_path / "config.json").write_text('{"a": ', encoding="utf-8")      # corrupted since the last backup
    (tmp_path / "points.json").write_text("[]", encoding="utf-8")
    updater.UpdateInstaller.backup_user_data(str(tmp_path))
    for old in good_backups:
        assert old.exists() and json.loads((old / "config.json").read_text(encoding="utf-8")) == {"a": 1}


# ───────────── updater security ─────────────

def test_only_github_https_addresses_are_trusted():
    from core.updater import is_trusted_url, safe_release_page

    assert is_trusted_url("https://github.com/tankow79/scum-ui-translator-map/releases/download/v1/a.exe")
    assert is_trusted_url("https://objects.githubusercontent.com/x")
    for bad in ("http://github.com/x", "https://evil.com/github.com", "https://github.com.evil.com/x",
                "file:///C:/x.exe", "ms-msdt:/id", r"\\server\share\x.exe", "", None, 5):
        assert not is_trusted_url(bad), bad
    repo = "https://github.com/tankow79/scum-ui-translator-map"
    assert safe_release_page(repo + "/releases/tag/v1") == repo + "/releases/tag/v1"
    assert safe_release_page("file:///C:/Windows/System32/calc.exe") == repo
    assert safe_release_page("https://github.com/someone/else") == repo


def test_release_with_untrusted_or_odd_asset_gets_no_download():
    from core.updater import parse_release

    def info(url, name):
        return parse_release({"tag_name": "v9.9.9", "assets": [{"name": name, "browser_download_url": url, "size": 5}]},
                             "1.0.0", portable=False)
    ok = "https://github.com/tankow79/scum-ui-translator-map/releases/download/v9/SCUM_Chat_Translator.exe"
    assert info(ok, "SCUM_Chat_Translator.exe").download_url == ok
    assert info("http://github.com/x/SCUM_Chat_Translator.exe", "SCUM_Chat_Translator.exe").download_url is None
    assert info("https://evil.example/SCUM_Chat_Translator.exe", "SCUM_Chat_Translator.exe").download_url is None
    assert info(ok, "..\\..\\evil.exe").download_url is None
    assert info(ok, "NUL.exe:stream").download_url is None


def test_download_refuses_redirect_off_github_and_oversized_files(tmp_path, monkeypatch):
    import core.updater as updater
    from tests.test_updater import _fake_response

    monkeypatch.setattr(updater, "get_updates_dir", lambda: str(tmp_path))
    errors = []
    dl = updater.UpdateDownloader()
    dl.error.connect(errors.append)

    evil = _fake_response(b"MZ" + b"0" * 2_000_000)
    evil.geturl.return_value = "https://evil.example/app.exe"
    with patch("urllib.request.urlopen", return_value=evil):
        dl._worker_download("https://github.com/x/app.exe", "app.exe", "0" * 64)
    assert errors and "trusted" in errors[-1]

    huge = _fake_response(b"MZ")
    huge.headers = {"Content-Length": str(updater.MAX_DOWNLOAD_BYTES + 1)}
    with patch("urllib.request.urlopen", return_value=huge):
        dl._worker_download("https://github.com/x/app.exe", "app.exe", "0" * 64)
    assert "unexpectedly large" in errors[-1]

    dl._worker_download("http://github.com/x/app.exe", "app.exe", "0" * 64)
    assert "trusted" in errors[-1]
    dl._worker_download("https://github.com/x/a.exe", "a.exe:stream", "0" * 64)
    assert "not allowed" in errors[-1]
    assert not list(tmp_path.iterdir())


def test_zip_member_larger_than_the_limit_is_refused(tmp_path, monkeypatch):
    import zipfile

    import core.updater as updater

    monkeypatch.setattr(updater, "get_updates_dir", lambda: str(tmp_path / "updates"))
    monkeypatch.setattr(updater, "MAX_DOWNLOAD_BYTES", 1000)
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("app.exe", b"MZ" + b"\0" * 50_000)
    with pytest.raises(updater.UpdateError, match="unexpectedly large"):
        updater.UpdateInstaller.extract_executable(str(archive), portable=False)


def test_old_build_pattern_is_exact(tmp_path, monkeypatch):
    import core.updater as updater

    exe = tmp_path / "SCUM_Chat_Translator.exe"
    exe.write_bytes(b"MZnew")
    (tmp_path / "SCUM_Chat_Translator.exe.old").write_bytes(b"MZold")
    (tmp_path / "SCUM_Chat_Translator.exe.123.old").write_bytes(b"MZolder")
    (tmp_path / "SCUM_Chat_Translator.exe.evil.old").write_bytes(b"MZevil")
    (tmp_path / "SCUM_Chat_Translator_Portable.exe.old").write_bytes(b"MZother")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert updater.UpdateInstaller.remove_previous_versions(str(tmp_path)) == 2
    assert (tmp_path / "SCUM_Chat_Translator.exe.evil.old").exists()
    assert (tmp_path / "SCUM_Chat_Translator_Portable.exe.old").exists()


def test_update_is_tested_and_installed_from_the_same_staged_file(tmp_path, monkeypatch):
    import core.updater as updater

    target = tmp_path / "app.exe"
    target.write_bytes(b"MZ" + b"OLD" * 10)
    new = tmp_path / "download.exe"
    new.write_bytes(b"MZ" + b"NEW" * 10)
    monkeypatch.setattr(updater, "MIN_EXE_SIZE", 0)
    tested = []
    monkeypatch.setattr(updater.UpdateInstaller, "self_test", staticmethod(lambda path, *a, **k: tested.append(path)))
    updater.UpdateInstaller.apply_update(str(new), target_exe=str(target))
    assert tested == [str(target) + ".new"]            # not the original download that could be swapped meanwhile
    assert target.read_bytes().startswith(b"MZNEW")

    # a file changed while the test runs is never installed
    target.write_bytes(b"MZ" + b"OLD" * 10)
    (tmp_path / "app.exe.old").unlink()

    def tamper(path, *a, **k):
        with open(path, "ab") as f:
            f.write(b"EVIL")
    monkeypatch.setattr(updater.UpdateInstaller, "self_test", staticmethod(tamper))
    with pytest.raises(updater.UpdateError, match="changed while"):
        updater.UpdateInstaller.apply_update(str(new), target_exe=str(target))
    assert target.read_bytes().startswith(b"MZOLD") and not (tmp_path / "app.exe.new").exists()


def test_update_without_checksum_is_not_installed_automatically(monkeypatch):
    from tests.test_updater import make_info
    from ui.update_dialog import UpdateDialog

    opened = []
    monkeypatch.setattr("ui.update_dialog.webbrowser.open", lambda url: opened.append(url))
    dlg = UpdateDialog(make_info(sha256=None))
    started = []
    dlg.downloader.download_async = lambda *a, **k: started.append(a)
    dlg._start_download()
    assert started == [] and opened and dlg._state == "error"


# ───────────── fuzz / stress findings ─────────────

def test_keypad_on_the_map_edge_stays_in_the_last_column_and_row():
    from core.coordinate_parser import get_sector_info

    assert get_sector_info(1.0, 0.5)[1] == "k6"          # east edge, middle row (was k4)
    assert get_sector_info(1.0, 1.0)[1] == "k3"          # south-east corner (was k7)
    assert get_sector_info(0.0, 0.0)[1] == "k7"          # north-west corner
    assert get_sector_info(0.999999, 0.5)[1] == "k6"
    assert get_sector_info(0.5, 0.5)[1] in {"k4", "k5", "k6"}


def test_plain_words_are_not_eaten_as_colour_tags():
    from core.chat_color import extract_text_color

    for text in ("[Colorado] see you there", "[Colorblind] lag", "[Colorful] hi"):
        assert extract_text_color(text) == (text, None)
    assert extract_text_color("[color=#00ff00]ok[/color]") == ("ok", "#00ff00")


def test_nicknames_starting_with_team_or_squad_are_not_squad_chat():
    got = []
    parser = ScumLogParser("x.log", lambda *a: got.append(a))
    for nick in ("Team Rocket", "Squad Leader", "Squadron"):
        parser._process_line(f"[2026.11.13-01.54.49:390][201]LogSCUM: Message: {nick}: hi")
    parser._process_line("[2026.11.13-01.54.49:390][201]LogSCUM: Message: (Squad) Bob: hi")
    assert [g[3] for g in got] == ["player", "player", "player", "squad"]


def test_nickname_with_a_colon_is_taken_from_the_user_line():
    got = []
    parser = ScumLogParser("x.log", lambda *a: got.append(a), lambda *a: None)
    parser._process_line("[2026.11.13-01.54.49:390][201]LogSCUM: Message from user: Bob:Dylan (76561199117414081) (hash: AB)")
    parser._process_line("[2026.11.13-01.54.49:390][201]LogSCUM: Message: Bob:Dylan: hi there")
    assert got[0][1] == "Bob:Dylan" and got[0][2] == "hi there"


def test_server_quotes_with_trailing_punctuation_are_removed():
    got = []
    parser = ScumLogParser("x.log", lambda *a: got.append(a))
    parser._process_line('[2026.11.13-01.54.49:390][201]LogSCUM: Sender player state null for message Message Of The Day: "Join Discord!"!')
    assert got[0][2] == "Join Discord!"


def test_category_keywords_match_words_not_substrings():
    from core.coordinate_parser import detect_category_from_name

    assert detect_category_from_name("my car") == "car"
    for name in ("Scarlet", "Database", "Oscar"):
        assert detect_category_from_name(name) == "default", name
    assert detect_category_from_name("base 1") == "base"


def test_nickname_blacklist_does_not_block_other_nicknames():
    from core.message_filter import ChatFilter, split_list

    flt = ChatFilter({"blacklist_nicknames": ["ann", 1337]})
    assert flt.is_nickname_blacklisted("ann") and flt.is_nickname_blacklisted("[CLAN] Ann")
    assert not flt.is_nickname_blacklisted("Joanna")
    assert flt.is_nickname_blacklisted("1337")
    assert split_list([1337, True, 2.5]) == ["1337", "2.5"]


def test_infinite_coordinates_and_bad_point_data_are_rejected(tmp_path):
    assert parse_chat_coordinate("{X=" + "9" * 400 + " Y=0 Z=0}") is None
    pt = MapPoint.from_dict({"name": 5, "x": 1, "y": 2})
    assert pt.name == "5"
    mgr = PointsManager(str(tmp_path / "p.json"))
    (tmp_path / "in.json").write_text(json.dumps([{"x": 10 ** 400, "y": 1, "name": "huge"}, {"name": 5, "x": 1, "y": 2}]),
                                      encoding="utf-8")
    result = mgr.import_from_file(str(tmp_path / "in.json"))
    assert result.invalid == 1 and result.added == 1


def test_profiles_with_wrong_shape_are_kept_not_overwritten(tmp_path):
    from core.profiles import ProfileManager

    class Cfg:
        config = {}

        def get(self, k, d=None):
            return d

    for text in ('{"profiles": [1, 2]}', "[" * 100000):
        path = tmp_path / "profiles.json"
        path.write_text(text, encoding="utf-8")
        ProfileManager(Cfg(), str(path))
        assert list(tmp_path.glob("profiles.json.corrupt-*")), text
        for f in tmp_path.glob("profiles.json*"):
            f.unlink()


def test_concurrent_saves_lose_nothing_and_leave_valid_json(tmp_path):
    import threading

    cfg = ConfigManager(str(tmp_path / "config.json"))

    def worker(n):
        for i in range(60):
            cfg.set(f"k{n}_{i}", i)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert all(saved.get(f"k{n}_59") == 59 for n in range(5))
    assert not (tmp_path / "config.json.tmp").exists()


def test_config_defaults_are_not_shared_between_instances(tmp_path):
    a = ConfigManager(str(tmp_path / "a.json"))
    a.get("blacklist_words").append("leak")
    b = ConfigManager(str(tmp_path / "b.json"))
    assert "leak" not in b.get("blacklist_words")


def test_history_with_undecodable_bytes_still_loads(tmp_path):
    path = tmp_path / "h.jsonl"
    good = {"timestamp": "t", "time_str": "1", "sender": "A", "original": "x", "translated": "x",
            "src_lang": "en", "msg_type": "player"}
    path.write_bytes(json.dumps(good).encode() + b"\n" + b'{"sender": "\xd0' )   # cut in the middle of a character
    assert len(ChatHistory(max_entries=10, path=str(path)).query()) == 1


def test_multibyte_character_split_across_writes_is_not_lost(tmp_path):
    log_file = tmp_path / "SCUM.log"
    log_file.write_bytes(b"")
    got = []
    parser = ScumLogParser(str(log_file), lambda *a: got.append(a[2]))
    parser.start()
    try:
        time.sleep(0.4)
        data = "[2026.11.13-01.54.49:390][201]LogSCUM: Message: Bob: привіт друже\n".encode()
        cut = data.index("п".encode()) + 1                    # split the first Cyrillic letter in two bytes
        with open(log_file, "ab") as f:
            f.write(data[:cut])
            f.flush()
            time.sleep(0.5)
            f.write(data[cut:])
        assert _wait(lambda: got == ["привіт друже"])
    finally:
        parser.stop()


def test_restoring_a_damaged_user_file_keeps_a_copy(tmp_path):
    import core.updater as updater

    (tmp_path / "points.json").write_text("[]", encoding="utf-8")
    updater.UpdateInstaller.backup_user_data(str(tmp_path))
    (tmp_path / "points.json").write_text("[{broken", encoding="utf-8")
    restored = updater.UpdateInstaller.restore_damaged_user_data(str(tmp_path))
    assert "points.json" in restored
    assert (tmp_path / "points.json").read_text(encoding="utf-8") == "[]"
    assert list(tmp_path.glob("points.json.corrupt-*"))


def test_ordered_publishing_survives_a_slow_publisher(tmp_path):
    import threading

    from core.controller import AppController

    ctrl = AppController(ConfigManager(str(tmp_path / "cfg.json")), GoogleTranslatorEngine(target_lang="uk"))
    shown = []
    ctrl._publish = lambda *a: (time.sleep(0.002), shown.append(a[2]))
    tickets = [ctrl._take_ticket() for _ in range(120)]

    def finish(chunk):
        for t in chunk:
            ctrl._publish_in_order(t, "t", "S", str(t), "x", "en", "player")
    threads = [threading.Thread(target=finish, args=(tickets[i::4],)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert shown == [str(t) for t in tickets]
    assert threading.active_count() < 30                      # no timer-thread pile-up


def test_replace_import_without_any_valid_entry_keeps_the_points(tmp_path):
    mgr = PointsManager(str(tmp_path / "p.json"))
    for i in range(3):
        mgr.add_point(MapPoint(id=str(i), name=f"p{i}", date_time="", raw_coord=f"{{X={i} Y=2 Z=3}}", x=i, y=2, z=3,
                               sector="B2", keypad="k5", norm_x=.5, norm_y=.5, created_timestamp=float(i)))
    (tmp_path / "bad.json").write_text(json.dumps(["hello", "world"]), encoding="utf-8")
    with pytest.raises(ValueError):
        mgr.import_from_file(str(tmp_path / "bad.json"), replace=True)
    assert len(mgr.get_points()) == 3


@pytest.mark.parametrize("bad", [
    {"font_size": None}, {"overlay_x": "abc"}, {"squad_nicknames": 5}, {"history_max_entries": "abc"},
    {"font_bold": "yes"}, {"bg_opacity": [1]}, {"font_size": 13.7}, {"target_language": 5},
])
def test_wrong_typed_config_values_fall_back_to_defaults(tmp_path, bad):
    from core.config_manager import DEFAULT_CONFIG

    path = tmp_path / "config.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    cfg = ConfigManager(str(path))
    key = next(iter(bad))
    if key == "font_size":
        assert isinstance(cfg.get(key), int)
    else:
        assert cfg.get(key) == DEFAULT_CONFIG[key]


def test_config_that_is_not_an_object_is_preserved(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    cfg = ConfigManager(str(path))
    assert cfg.get("font_size") == 22 and list(tmp_path.glob("config.json.corrupt-*"))


def test_zip_update_of_the_running_portable_build_picks_the_portable_exe(tmp_path, monkeypatch):
    import zipfile

    import core.updater as updater

    monkeypatch.setattr(updater, "get_updates_dir", lambda: str(tmp_path / "updates"))
    monkeypatch.setattr(updater, "MIN_EXE_SIZE", 0)
    (tmp_path / "portable.flag").write_text("x", encoding="utf-8")
    renamed = tmp_path / "MyRenamed.exe"
    renamed.write_bytes(b"MZ" + b"OLD" * 10)
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(renamed))
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("SCUM_Chat_Translator.exe", b"MZ" + b"NORMAL" * 10)
        z.writestr("SCUM_Chat_Translator_Portable.exe", b"MZ" + b"PORTABLE" * 5)
    updater.UpdateInstaller.apply_update(str(archive), self_test=False)
    assert renamed.read_bytes().startswith(b"MZPORTABLE")


# ───────────── map performance ─────────────

def _canvas_with_points(tmp_path, count=60):
    from ui.map_window import MapCanvasWidget

    mgr = PointsManager(str(tmp_path / "p.json"))
    for i in range(count):
        mgr.add_point(MapPoint(id=str(i), name=f"p{i % 5}", date_time="", raw_coord=f"{{X={i} Y=1 Z=1}}", x=i, y=1, z=1,
                               sector="B2", keypad="k5", norm_x=0.45 + (i % 10) * 0.004, norm_y=0.4 + (i // 10) * 0.004,
                               created_timestamp=float(i), category="base" if i % 2 else "default"))
    canvas = MapCanvasWidget(ConfigManager(str(tmp_path / "cfg.json")), mgr)
    canvas.resize(900, 560)
    canvas.show()
    return canvas


def test_markers_are_rendered_once_and_reused(tmp_path):
    canvas = _canvas_with_points(tmp_path)
    canvas.zoom, canvas.pan_x, canvas.pan_y = 4.0, 450 - 0.45 * 2560 * 4, 280 - 0.4 * 2560 * 4
    canvas.grab()
    first = len(canvas._sprites)
    assert 0 < first <= 10                       # 60 markers share a handful of distinct pin images
    sprites = dict(canvas._sprites)
    canvas.pan_x -= 25
    canvas.grab()
    assert canvas._sprites == sprites            # panning builds nothing new
    canvas.active_point_id = "3"
    canvas.grab()
    assert len(canvas._sprites) > first          # a highlighted pin is a different image
    canvas.close()


def test_panning_and_zooming_use_a_frame_limiter_and_settle(tmp_path):
    canvas = _canvas_with_points(tmp_path, 5)
    updates = []
    canvas.update = lambda *a: updates.append(1)
    for _ in range(50):
        canvas._request_frame()                  # what every wheel/drag event does
    assert canvas._interacting and canvas._frame_timer.isActive() and updates == []   # no repaint per event
    end = time.time() + 3.0
    while canvas._interacting and time.time() < end:
        app.processEvents()                                                               # let the Qt timers run
        time.sleep(0.01)
    assert not canvas._interacting                                                        # high quality returns by itself
    assert updates                                                                    # ...with a final frame
    canvas.close()


@pytest.mark.parametrize("zoom", [0.2, 1.0, 8.0])
def test_map_paints_at_every_zoom_with_only_the_visible_part(tmp_path, zoom):
    canvas = _canvas_with_points(tmp_path, 20)
    canvas.zoom = zoom
    for pan in (-50000.0, 0.0, 50000.0):          # far outside, at the origin, and far past the map
        canvas.pan_x = canvas.pan_y = pan
        canvas.grab()
    canvas.close()


# ───────────── late crashes roll back; big imports stay responsive ─────────────

def test_repeated_crashes_of_a_new_build_trigger_a_rollback(tmp_path, monkeypatch):
    import core.updater as updater

    monkeypatch.setenv("SCUM_DATA_DIR", str(tmp_path))
    U = updater.UpdateInstaller
    assert U.record_run_start("2.4.1", now=1000.0) == 0          # first start after the update
    assert U.record_run_start("2.4.1", now=1100.0) == 1          # it never exited cleanly (died after 0 s)
    assert not U.should_roll_back(1)
    assert U.record_run_start("2.4.1", now=1200.0) == 2          # crashed again
    assert U.should_roll_back(2)


def test_clean_exits_and_long_runs_reset_the_crash_count(tmp_path, monkeypatch):
    import core.updater as updater

    monkeypatch.setenv("SCUM_DATA_DIR", str(tmp_path))
    U = updater.UpdateInstaller
    U.record_run_start("2.4.1", now=1000.0)
    assert U.record_run_start("2.4.1", now=1050.0) == 1
    U.record_clean_exit()                                         # the user closed it normally
    assert U.record_run_start("2.4.1", now=2000.0) == 0

    U.record_heartbeat(now=2000.0 + updater.UpdateInstaller.HEALTHY_AFTER_SECONDS + 5)   # ran for a long time, then died
    assert U.record_run_start("2.4.1", now=9000.0) == 0
    assert U.record_run_start("2.4.2", now=9100.0) == 0          # a different version starts from zero


def test_killed_new_build_is_replaced_by_the_previous_one_after_two_crashes(tmp_path, monkeypatch):
    import core.updater as updater

    exe = tmp_path / "SCUM_Chat_Translator.exe"
    exe.write_bytes(b"MZ" + b"NEWCRASHES")
    (tmp_path / "SCUM_Chat_Translator.exe.old").write_bytes(b"MZ" + b"GOOD")
    monkeypatch.setenv("SCUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    U = updater.UpdateInstaller
    strikes = [U.record_run_start("9.9.9", now=float(t)) for t in (1, 2, 3)]
    assert strikes == [0, 1, 2]
    assert U.should_roll_back(strikes[-1]) and U.rollback_failed_update() == str(exe)
    assert exe.read_bytes().startswith(b"MZGOOD")


def test_points_list_builds_big_imports_in_batches_without_losing_rows(tmp_path):
    from ui.points_window import PointsWindow

    mgr = PointsManager(str(tmp_path / "p.json"))
    win = PointsWindow(ConfigManager(str(tmp_path / "cfg.json")), mgr)
    pts = [MapPoint(id=str(i), name=f"p{i}", date_time="", raw_coord=f"{{X={i} Y=1 Z=1}}", x=i, y=1, z=1, sector="B2",
                    keypad="k5", norm_x=.5, norm_y=.5, created_timestamp=float(i)) for i in range(500)]
    mgr._points = pts
    win.refresh_list()
    assert 0 < len(win._row_widgets) <= win.FIRST_BATCH               # the window is usable immediately
    mgr.delete_point("499")                                            # a point removed while rows are still being built
    end = time.time() + 10
    while win._build_queue and time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    assert len(win._row_widgets) == 499 and "499" not in win._row_widgets
    win.refresh_list()                                                 # a second refresh restarts cleanly
    mgr.clear_all()
    app.processEvents()
    assert win._row_widgets == {} and win._build_queue == []
    win.close()


def test_clear_all_points_needs_explicit_confirmation(tmp_path, monkeypatch):
    from ui.points_window import PointsWindow

    mgr = PointsManager(str(tmp_path / "p.json"))
    mgr.add_point(MapPoint(id="1", name="a", date_time="", raw_coord="{X=1 Y=1 Z=1}", x=1, y=1, z=1, sector="B2",
                           keypad="k5", norm_x=.5, norm_y=.5, created_timestamp=1.0))
    win = PointsWindow(ConfigManager(str(tmp_path / "cfg.json")), mgr)
    monkeypatch.setattr(win, "_ask_clear_all", lambda count: False)
    win._confirm_clear_all()
    assert len(mgr.get_points()) == 1                      # cancelled: nothing is deleted
    monkeypatch.setattr(win, "_ask_clear_all", lambda count: True)
    win._confirm_clear_all()
    assert mgr.get_points() == []
    win.close()


def test_overlay_keeps_the_readers_place_and_offers_a_jump_button(tmp_path):
    from ui.overlay import ChatOverlay

    overlay = ChatOverlay(ConfigManager(str(tmp_path / "cfg.json")))
    overlay.resize(500, 300)
    overlay.show()
    overlay.set_in_chat_mode(True)
    for i in range(40):
        overlay.add_message("12:00:00", "Bob", f"message number {i}", f"message number {i}", "en", "player")
    app.processEvents()
    view = overlay.chat_view
    bar = view.verticalScrollBar()
    assert bar.maximum() > 0 and view.at_bottom() and not view.jump_button.isVisible()

    bar.setValue(20)                                   # the reader scrolls up
    overlay.add_message("12:00:01", "Bob", "brand new", "brand new", "en", "player")
    app.processEvents()
    assert bar.value() == 20                           # no jump
    assert view.jump_button.isVisible()                # but a button appears

    view.jump_button.click()
    assert view.at_bottom() and not view.jump_button.isVisible()

    bar.setValue(20)
    overlay.add_message("12:00:02", "Bob", "another", "another", "en", "player")
    assert view.jump_button.isVisible()
    overlay.set_in_chat_mode(False)                    # closing the chat returns to the newest messages
    assert view.at_bottom() and not view.jump_button.isVisible()
    overlay.close()


def test_concurrent_point_saves_leave_the_latest_state_on_disk(tmp_path):
    import threading

    path = tmp_path / "points.json"
    mgr = PointsManager(str(path))

    def worker(n):
        for i in range(25):
            mgr.add_point(MapPoint(id=f"{n}_{i}", name="p", date_time="", raw_coord=f"{{X={i} Y={n} Z=1}}", x=i, y=n, z=1,
                                   sector="B2", keypad="k5", norm_x=.5, norm_y=.5, created_timestamp=float(n * 100 + i)))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(json.loads(path.read_text(encoding="utf-8"))) == len(mgr.get_points()) == 100


def test_translation_keeps_coordinates_untouched(monkeypatch):
    from core.translator import GoogleTranslatorEngine

    eng = GoogleTranslatorEngine(target_lang="uk")
    original = "Hier ist die Basis {X=-100000.500 Y=-50000.250 Z=1200.000} kommt alle"
    monkeypatch.setattr(eng, "_translate_with_fallbacks",
                        lambda text, target, source: ("Тут база {X=-100000,500 Y=-50000,250 Z=1200,000} приходьте", "de"))
    assert eng.translate(original) == ("Тут база {X=-100000.500 Y=-50000.250 Z=1200.000} приходьте", "de")


def test_point_name_has_no_double_spaces_where_the_coordinates_were():
    from core.coordinate_parser import parse_chat_coordinate

    pt = parse_chat_coordinate("Hier ist die Basis {X=-100000.500 Y=-50000.250 Z=1200.000} kommt alle")
    assert pt is not None and pt.name == "Hier ist die Basis kommt alle"


def test_points_window_is_owned_by_the_map_so_it_stays_above(tmp_path):
    from ui.map_window import MapWindow
    from ui.points_window import PointsWindow

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    mgr = PointsManager(str(tmp_path / "p.json"))
    map_win = MapWindow(cfg, mgr)
    points_win = PointsWindow(cfg, mgr, parent=map_win)
    assert points_win.parent() is map_win and points_win.isWindow()
    map_win.close()


def test_messages_waiting_in_a_long_queue_keep_their_order(tmp_path):
    from core.controller import AppController

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    ctrl = AppController(cfg, GoogleTranslatorEngine(target_lang="uk"))
    ctrl.ORDER_WAIT_SECONDS = 0.2
    shown = []
    ctrl._publish = lambda *a: shown.append(a[2])
    tickets = [ctrl._take_ticket() for _ in range(5)]     # a burst: all queued, none started yet
    time.sleep(0.5)                                        # longer than the wait limit, but only spent in the queue
    for n in (4, 2, 3):                                    # later ones finish first
        ctrl._publish_in_order(tickets[n], "t", "x", f"m{n}", "x", "en", "player")
    assert shown == []                                     # still waiting for the earlier, not yet started ones
    for n in (0, 1):
        ctrl._publish_in_order(tickets[n], "t", "x", f"m{n}", "x", "en", "player")
    assert shown == ["m0", "m1", "m2", "m3", "m4"]


def test_user_line_parsing_is_linear_and_exact():
    from core.players import parse_user_line

    head = "[2026.11.13-10.00.00:123][  1]LogSCUM: Message from user: "
    for hostile in (" " * 20000, "(" * 20000, "x " * 10000, "(hash: " * 3000):
        t0 = time.perf_counter()
        parse_user_line(head + hostile)
        assert time.perf_counter() - t0 < 0.5
    sid = "76561198000000001"
    assert parse_user_line(f"{head}Bob (the great) ({sid}) (hash: ab12)")[:3] == (sid, "Bob (the great)", "AB12")
    assert parse_user_line(f"{head}a:b ({sid}) (hash: AB)")[1] == "a:b"
    assert parse_user_line(f"{head} ({sid}) (hash: AB)") is None                 # no nickname
    assert parse_user_line(f"{head}Bob (1234) (hash: AB)") is None               # not a SteamID
    assert parse_user_line(f"{head}Bob ({sid}) (hash: XYZ)") is None             # not hex


def test_stored_waypoints_with_damaged_numbers_are_repaired_or_rejected():
    from core.coordinate_parser import MapPoint

    pt = MapPoint.from_dict({"id": 7, "name": ["x"], "x": 1000, "y": 2000, "norm_x": float("nan"), "norm_y": 1e300,
                             "color": "red<script>", "category": {"a": 1}, "created_timestamp": float("inf"), "players": 5})
    assert pt.id == "7" and pt.name == "None" and pt.color.startswith("#") and len(pt.color) == 7
    assert -10 <= pt.norm_x <= 10 and -10 <= pt.norm_y <= 10
    assert math.isfinite(pt.created_timestamp) and pt.players == "5"
    for bad in ({"x": float("nan"), "y": 1}, {"x": 1}, {"x": "abc", "y": 1}, "junk", None):
        with pytest.raises(ValueError):
            MapPoint.from_dict(bad)


# ───────── tests added after mutation testing (each one kills a mutant that used to survive) ─────────

def test_nickname_containing_the_hash_marker_is_still_parsed_from_the_right():
    from core.players import parse_user_line

    sid = "76561198000000001"
    line = f"[2026.11.13-10.00.00:123][  1]LogSCUM: Message from user: evil (hash: AA) ({sid}) (hash: BEEF)"
    assert parse_user_line(line)[:3] == (sid, "evil (hash: AA)", "BEEF")


def test_negative_or_odd_asset_sizes_become_zero():
    import core.updater as updater

    for size in (-5, "-7", None, float("nan"), [1]):
        info = updater.parse_release({"tag_name": "v9.9.9", "assets": [
            {"name": "SCUM_Chat_Translator.exe", "size": size,
             "browser_download_url": "https://github.com/a/b/releases/download/v9.9.9/SCUM_Chat_Translator.exe"}]},
            "2.4.0", portable=False)
        assert info.asset_size == 0


def test_a_stale_snapshot_never_overwrites_a_newer_config(tmp_path, monkeypatch):
    import threading

    import core.config_manager as cm

    real_write = cm.atomic_write_json
    first_call = threading.Event()

    def slow_first_write(path, data):
        if not first_call.is_set():
            first_call.set()
            time.sleep(0.4)                       # the first writer is slow, a second save overtakes it
        real_write(path, data)

    monkeypatch.setattr(cm, "atomic_write_json", slow_first_write)
    cfg = ConfigManager(str(tmp_path / "config.json"))
    first_call.clear()
    t1 = threading.Thread(target=lambda: cfg.set("font_size", 21))
    t1.start()
    assert _wait(first_call.is_set, 3)
    cfg.set("font_size", 33)                      # newer value, saved while the older save is still in flight
    t1.join()
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["font_size"] == 33


def test_selected_text_in_the_chat_survives_new_messages(tmp_path):
    from ui.overlay import ChatOverlay

    overlay = ChatOverlay(ConfigManager(str(tmp_path / "cfg.json")))
    overlay.resize(500, 300)
    overlay.show()
    overlay.set_in_chat_mode(True)
    for i in range(40):
        overlay.add_message("12:00:00", "Bob", f"message number {i}", f"message number {i}", "en", "player")
    app.processEvents()
    view = overlay.chat_view
    view.verticalScrollBar().setValue(10)
    cursor = view.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(15, cursor.MoveMode.KeepAnchor)
    view.setTextCursor(cursor)
    assert view.textCursor().hasSelection()
    overlay.add_message("12:00:01", "Bob", "brand new", "brand new", "en", "player")
    app.processEvents()
    assert view.textCursor().hasSelection()       # the document was not rebuilt under the selection
    assert view.jump_button.isVisible()
    overlay.close()


@pytest.mark.parametrize("tick,click_yes,expected", [(True, True, True), (False, True, False), (True, False, False)])
def test_clearing_all_points_needs_the_tick_and_the_yes_button(tmp_path, monkeypatch, tick, click_yes, expected):
    from ui.points_window import ClearAllDialog, PointsWindow

    win = PointsWindow(ConfigManager(str(tmp_path / "cfg.json")), PointsManager(str(tmp_path / "p.json")))

    def fake_exec(dialog):
        dialog.check.setChecked(tick)
        (dialog.btn_yes if click_yes else dialog.btn_cancel).click()      # a disabled button ignores the click
        return dialog.result()

    monkeypatch.setattr(ClearAllDialog, "exec", fake_exec)
    assert win._ask_clear_all(3) is expected
    win.close()


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_clear_dialog_is_laid_out_neatly(lang):
    """Icon on the left, heading and text left-aligned right of it, buttons on the right, nothing clipped."""
    from core.i18n import LocalizationManager
    from ui.points_window import ClearAllDialog

    LocalizationManager.get_instance().set_locale(lang)
    dialog = ClearAllDialog(1234)
    dialog.show()
    app.processEvents()
    assert not dialog.btn_yes.isEnabled() and dialog.btn_cancel.isDefault()
    dialog.check.setChecked(True)
    assert dialog.btn_yes.isEnabled()
    heading, body = dialog.findChild(QLabel, "heading"), dialog.findChild(QLabel, "body")
    icon = dialog.findChild(QLabel, "icon")
    assert "1234" in heading.text()
    for label in (heading, body):
        assert label.alignment() & Qt.AlignmentFlag.AlignLeft or not label.alignment() & Qt.AlignmentFlag.AlignRight
        assert label.x() > icon.x() + icon.width() - 1                 # the text sits to the right of the icon
        assert label.x() + label.width() <= dialog.width()             # ... and inside the window
    assert dialog.btn_yes.x() >= 0 and dialog.btn_yes.x() < dialog.btn_cancel.x()  # buttons not clipped, yes left of cancel
    assert dialog.btn_cancel.geometry().right() <= dialog.width()
    for widget in dialog.findChildren(QPushButton) + [dialog.check]:
        assert widget.geometry().right() <= dialog.width() and widget.geometry().bottom() <= dialog.height()
    LocalizationManager.get_instance().set_locale("en")
    dialog.close()



def test_settings_go_to_the_user_folder_when_the_program_folder_is_read_only(tmp_path, monkeypatch):
    import core.config_manager as cm

    monkeypatch.delenv("SCUM_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(cm, "_WRITABLE_CACHE", {})
    real_open = open

    def deny_probe(path, *a, **k):
        if ".write_test_" in str(path):
            raise PermissionError("read-only")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", deny_probe)
    path = cm.get_portable_config_path("config.json")
    assert str(tmp_path / "local") in path and path.endswith("config.json")
    monkeypatch.undo()
    monkeypatch.delenv("SCUM_DATA_DIR", raising=False)
    monkeypatch.setattr(cm, "_WRITABLE_CACHE", {})
    assert "SCUM_Chat_Translator" not in cm.get_portable_config_path("config.json")   # writable: stays next to the program


def test_deleted_or_renamed_waypoints_do_not_come_back_from_the_replayed_log(tmp_path):
    from core.coordinate_parser import parse_chat_coordinate

    path = str(tmp_path / "points.json")
    mgr = PointsManager(path)
    line = "машина {X=-100000.500 Y=-50000.250 Z=1200.000}"
    assert mgr.add_point(parse_chat_coordinate(line, "12:00:00"))
    original = mgr.get_points()[0]
    mgr.update_point_name(original.id, "my car")
    assert not mgr.add_point(parse_chat_coordinate(line, "12:00:00"))          # replay of a renamed point
    mgr.delete_point(original.id)
    assert not mgr.add_point(parse_chat_coordinate(line, "12:00:00"))          # replay after deleting it
    mgr2 = PointsManager(path)                                                  # ... also after a restart
    assert not mgr2.add_point(parse_chat_coordinate(line, "12:00:00"))
    assert mgr2.add_point(parse_chat_coordinate(line, "12:30:00"))              # a genuinely new post is accepted
    mgr2.clear_all()
    assert not PointsManager(path).add_point(parse_chat_coordinate(line, "12:30:00"))


def test_imported_waypoints_get_their_place_and_sector_from_the_game_position():
    from core.coordinate_parser import MapPoint, convert_norm_to_scum, convert_scum_to_norm, get_sector_info

    pt = MapPoint.from_dict({"x": 100, "y": 200, "name": "a", "norm_x": 0.0, "norm_y": 0.0, "sector": "??"})
    assert (pt.sector, pt.keypad) != ("??", "k5") and (pt.norm_x, pt.norm_y) == convert_scum_to_norm(100, 200)
    # every grid line, converted to game units and back, stays in its own cell
    for i in range(0, 16):
        for j in range(0, 16):
            x, y = convert_norm_to_scum(i / 15, j / 15)
            nx, ny = convert_scum_to_norm(x, y)
            sector, keypad = get_sector_info(nx, ny)
            expected_sector, expected_keypad = get_sector_info(i / 15 + 1e-7, j / 15 + 1e-7)
            if i < 15 and j < 15:
                assert (sector, keypad) == (expected_sector, expected_keypad), (i, j)


def test_a_new_session_log_with_the_same_name_is_read_from_its_start(tmp_path):
    from core.players import PlayerRegistry

    def user_line(sid, nick):
        return f"[2026.11.13-10.00.00:123][  1]LogSCUM: Message from user: {nick} ({sid}) (hash: AB)\n"

    log = tmp_path / "SCUM.log"
    log.write_text("Log file open, 11/12/26 10:00:00\n" + user_line("76561198000000001", "Old") * 3, encoding="utf-8")
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    reg.scan_logs(str(log))
    assert reg.nick_of("76561198000000001") == "Old"
    # the next session: same file name, but it is already BIGGER than what we read before
    log.write_text("Log file open, 11/13/26 09:00:00\n" + user_line("76561198000000002", "Fresh") * 20, encoding="utf-8")
    assert log.stat().st_size > reg._scanned["SCUM.log"]
    reg.scan_logs(str(log))
    assert reg.nick_of("76561198000000002") == "Fresh"
    reg2 = PlayerRegistry(str(tmp_path / "players.json"))      # the fingerprint survives a restart
    assert reg2.nick_of("76561198000000002") == "Fresh" and reg2._heads


def test_csv_export_neutralises_spreadsheet_formulas(tmp_path):
    import csv

    hist = ChatHistory(max_entries=10)
    hist.add("t", "=HYPERLINK(\"http://x\")", "+cmd|'/c calc'!A0", "-1+1", "en", "player")
    hist.add("t", "@SUM(A1)", "\tTAB", "normal text", "en", "player")
    out = tmp_path / "h.csv"
    hist.export(str(out))
    rows = list(csv.reader(out.open(encoding="utf-8-sig", newline="")))
    assert all(cell[:1] not in "=+-@\t\r" for row in rows[1:] for cell in row if cell)
    assert rows[1][2].startswith("'=") and rows[2][4] == "normal text"


def test_history_can_be_switched_to_disk_and_back_at_runtime(tmp_path):
    path = tmp_path / "h.jsonl"
    hist = ChatHistory(max_entries=10, path=str(path))
    hist.add("t", "A", "one", "one", "en", "player")
    hist.set_path(None)                                  # the user turned "keep history" off
    hist.add("t", "A", "two", "two", "en", "player")
    assert path.read_text(encoding="utf-8").count("\n") == 1 and len(hist) == 2
    hist.set_path(str(path))                             # ... and on again
    hist.add("t", "A", "three", "three", "en", "player")
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_profiles_with_bad_values_are_repaired_and_errors_are_coded(tmp_path):
    from core.profiles import ProfileError, ProfileManager

    cfg = ConfigManager(str(tmp_path / "c.json"))
    (tmp_path / "pr.json").write_text(json.dumps({"active": "Default", "profiles": {
        "Default": {"font_size": 20.5, "max_messages": "20", "bg_opacity": "x", "font_bold": 1},
        "Raid": {"font_size": 14}}}), encoding="utf-8")
    mgr = ProfileManager(cfg, str(tmp_path / "pr.json"))
    assert isinstance(mgr.profiles["Default"]["font_size"], int)
    assert isinstance(mgr.profiles["Default"]["max_messages"], int) and isinstance(mgr.profiles["Default"]["font_bold"], bool)
    assert mgr.apply("Raid") and cfg.get("font_size") == 14
    assert mgr.rename("Raid", "Raid") == "Raid"                                   # same name: nothing to do
    for call, code in ((lambda: mgr.create("  "), "empty"), (lambda: mgr.create("Raid"), "exists"),
                       (lambda: mgr.rename("Raid", "Default"), "exists"), (lambda: mgr.delete("Default"), "default_locked")):
        with pytest.raises(ProfileError) as info:
            call()
        assert info.value.code == code


def test_settings_refuse_conflicting_hotkeys(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from ui.settings_window import SettingsDialog

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    dlg = SettingsDialog(cfg)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    dlg.btn_k_map.set_hotkey("F9")                       # the same key as "position setup"
    assert dlg._hotkey_conflict()
    dlg.save_settings()
    assert shown and cfg.get("hotkey_toggle_map") == "Ctrl+M"       # nothing was saved, the dialog stays open
    dlg.btn_k_map.set_hotkey("Enter")
    assert dlg._hotkey_conflict()
    dlg.btn_k_map.set_hotkey("Ctrl+M")
    assert dlg._hotkey_conflict() is None
    dlg.close()


def test_hotkeys_without_a_name_are_stored_and_parsed_as_virtual_keys():
    from core.hotkey_manager import format_hotkey, parse_hotkey_string

    assert parse_hotkey_string("Ctrl+VK_101") == (True, False, False, 101)      # numpad 5
    assert parse_hotkey_string(format_hotkey(False, False, True, 124)) == (False, False, True, 124)   # Shift+F13
    assert parse_hotkey_string("Key_1045") is None and parse_hotkey_string("VK_999") is None


def _pump(cond, timeout):
    """Like _wait, but keeps the Qt event loop running (queued signals from worker threads need it)."""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_enter_never_copies_the_translation_of_older_text(tmp_path):
    from ui.overlay import ChatOverlay

    class SlowTranslator:
        def translate_custom(self, text, target, source="auto"):
            return f"TR<{text}>", "en"

    overlay = ChatOverlay(ConfigManager(str(tmp_path / "cfg.json")))
    overlay.set_translator(SlowTranslator())
    overlay.show()
    overlay.set_in_chat_mode(True)
    copied = []
    overlay.translate_and_copy.connect(lambda orig, trans: copied.append((orig, trans)))
    overlay.input_field.setText("hello")
    overlay._do_live_translate()
    assert _pump(lambda: overlay._current_translation == "TR<hello>", 3)
    overlay.input_field.setText("hello world")          # typed more, Enter pressed before the debounce fired
    assert overlay._current_translation == ""
    overlay._copy_translation()
    assert _pump(lambda: copied, 3)
    assert copied == [("hello world", "TR<hello world>")]
    overlay.close()


@pytest.mark.parametrize("lang", ["en", "uk"])
@pytest.mark.parametrize("font_size", [10, 22, 40])
@pytest.mark.parametrize("size", [(300, 150), (404, 237), (675, 330), (801, 366), (1600, 900)])
@pytest.mark.parametrize("unlocked", [False, True])
def test_overlay_never_clips_its_own_panels(tmp_path, lang, font_size, size, unlocked):
    """The quick-chat bar, the header and the chat view stay completely inside the window at every size, font size,
    language and mode (a window that is too small grows instead of cutting the bar off)."""
    from core.i18n import LocalizationManager
    from ui.overlay import ChatOverlay

    LocalizationManager.get_instance().set_locale(lang)
    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    cfg.set("font_size", font_size)
    overlay = ChatOverlay(cfg)
    overlay.resize(*size)
    overlay.show()
    if unlocked:
        overlay.set_locked(False)
    overlay.set_in_chat_mode(True)
    for i in range(6):
        overlay.add_message("12:00:00", "Bob", f"message {i}", f"message {i}", "en", "player")
    app.processEvents()
    window = overlay.rect()
    panels = [overlay.input_bar, overlay.chat_view] + ([overlay.header_bar] if unlocked else [])
    for panel in panels:
        assert panel.isVisible()
        top_left = panel.mapTo(overlay, panel.rect().topLeft())
        bottom_right = panel.mapTo(overlay, panel.rect().bottomRight())
        assert window.contains(top_left) and window.contains(bottom_right), (panel, top_left, bottom_right, window)
    for button in (overlay.btn_copy,):
        corner = button.mapTo(overlay, button.rect().bottomRight())
        assert window.contains(corner)
    LocalizationManager.get_instance().set_locale("en")
    overlay.close()
