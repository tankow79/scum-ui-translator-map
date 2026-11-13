"""Regression tests for bugs found in the hard-debugging pass (one test per defect class)."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

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
