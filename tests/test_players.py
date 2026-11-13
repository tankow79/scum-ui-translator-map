import json
import sys
import time

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from core.coordinate_parser import MapPoint
from core.log_parser import ScumLogParser
from core.players import PlayerRegistry, is_steam_id, parse_user_line, steam_profile_url
from core.points_manager import PointsManager

SID = "76561199117414081"
SID2 = "76561198995660378"
HASH = "46E01DF23CEE761799406204211C0F7266CF0DB2"

app = QApplication.instance() or QApplication(sys.argv)


def _line(ts, nick, sid=SID, h=HASH):
    return f"[{ts}:621][526]LogSCUM: Message from user: {nick} ({sid}) (hash: {h})"


def _base(name="base"):
    return MapPoint(
        id="b1", name=name, date_time="", raw_coord="", x=0, y=0, z=0, sector="B2", keypad="k5",
        norm_x=0.5, norm_y=0.5, created_timestamp=1.0, category="base",
    )


def _setup(folder):
    folder.mkdir(exist_ok=True)
    reg = PlayerRegistry(str(folder / "players.json"))
    mgr = PointsManager(str(folder / "points.json"), registry=reg)
    mgr.add_point(_base())
    return reg, mgr


def test_steam_helpers():
    assert is_steam_id(SID) and not is_steam_id("scorpio10") and not is_steam_id("123")
    assert steam_profile_url(SID) == f"https://steamcommunity.com/profiles/{SID}"


def test_parse_user_line():
    sid, nick, h, ts = parse_user_line(_line("2026.11.12-18.12.23", "A (b)"))
    assert (sid, nick, h) == (SID, "A (b)", HASH) and ts > 0
    assert parse_user_line("[2026.11.12-18.12.23:621][526]LogSCUM: Message: x: hi") is None


def test_parser_feeds_registry_end_to_end(tmp_path):
    """The parser's callback order must match PlayerRegistry.observe (regression: args were swapped)."""
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    msgs = []
    parser = ScumLogParser("x.log", lambda *a: msgs.append(a), reg.observe)
    parser._process_line(_line("2026.11.12-18.12.23", "scorpio10"))
    parser._process_line("[2026.11.12-18.12.23:621][526]LogSCUM: Message: scorpio10: hi)")
    assert reg.nick_of(SID) == "scorpio10"
    assert len(msgs) == 1 and msgs[0][1] == "scorpio10"


def test_rename_keeps_dated_history(tmp_path):
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    events = []
    reg.player_changed.connect(lambda *a: events.append(a))
    reg.observe(SID, "Old", HASH, 1000.0)
    reg.observe(SID, "Old", HASH, 1100.0)  # no change -> no event
    reg.observe(SID, "New", HASH, 2000.0)
    reg.observe(SID, "Older", HASH, 500.0)  # older information is ignored
    assert events == [(SID, SID, "Old", True), (SID, "Old", "New", False)]
    rec = PlayerRegistry(str(tmp_path / "players.json")).get(SID)
    assert rec["nick"] == "New" and rec["previous_nicks"] == [{"nick": "Old", "changed_at": 2000.0}]


def test_scan_logs_reads_old_logs_once(tmp_path):
    logs = tmp_path / "Logs"
    logs.mkdir()
    (logs / "SCUM-backup-2026.11.01-10.00.00.log").write_text(
        _line("2026.11.01-09.00.00", "First") + "\nnoise\n" + _line("2026.11.01-09.30.00", "Other", SID2) + "\n",
        encoding="utf-8")
    (logs / "SCUM-backup-2026.11.05-10.00.00.log").write_text(
        _line("2026.11.05-09.00.00", "Second") + "\n", encoding="utf-8")
    live = logs / "SCUM.log"
    live.write_text(_line("2026.11.10-09.00.00", "Third") + "\n", encoding="utf-8")

    reg = PlayerRegistry(str(tmp_path / "players.json"))
    done = []
    reg.scan_finished.connect(done.append)
    assert reg.scan_logs(str(live)) == 3 and done == [3]
    rec = reg.get(SID)
    assert rec["nick"] == "Third" and [h["nick"] for h in rec["previous_nicks"]] == ["Second", "First"]
    assert reg.nick_of(SID2) == "Other"

    # Nothing new -> nothing read; deleted data is not re-imported from old logs
    assert reg.scan_logs(str(live)) == 0
    reg.clear()
    assert PlayerRegistry(str(tmp_path / "players.json")).scan_logs(str(live)) == 0
    assert len(reg) == 0

    # New lines appended to the live log are picked up
    with open(live, "a", encoding="utf-8") as f:
        f.write(_line("2026.11.11-09.00.00", "Fourth") + "\n")
    assert PlayerRegistry(str(tmp_path / "players.json")).scan_logs(str(live)) == 1


def test_legacy_v1_file_is_loaded(tmp_path):
    (tmp_path / "players.json").write_text(json.dumps(
        {SID: {"nick": "A", "hash": "", "first_seen": 1, "last_seen": 2, "previous_nicks": ["Old"]}}),
        encoding="utf-8")
    rec = PlayerRegistry(str(tmp_path / "players.json")).get(SID)
    assert rec["previous_nicks"] == [{"nick": "Old", "changed_at": 0.0}]


def test_base_links_by_nickname_and_follows_rename(tmp_path):
    reg, mgr = _setup(tmp_path)
    reg.observe(SID, "Old", HASH, 1000.0)
    mgr.update_point_players("b1", "Ghost, old")
    pt = mgr.get_point_by_id("b1")
    assert pt.player_ids == [SID] and pt.players == "Ghost, Old"

    reg.observe(SID, "NewNick", HASH, 2000.0)
    pt = mgr.get_point_by_id("b1")
    assert pt.players == "Ghost, NewNick" and pt.player_ids == [SID]
    assert mgr.describe_players(pt) == [("NewNick", SID), ("Ghost", None)]

    # an OLD nickname typed later still resolves to the same player
    mgr.update_point_players("b1", "Old")
    assert mgr.get_point_by_id("b1").players == "NewNick"

    again = PointsManager(str(tmp_path / "points.json"), registry=reg)
    assert again.get_point_by_id("b1").player_ids == [SID]


def test_steam_id_typed_by_user_is_not_special(tmp_path):
    reg, mgr = _setup(tmp_path)
    reg.observe(SID, "Scorpio", HASH, 1000.0)
    mgr.update_point_players("b1", SID)
    pt = mgr.get_point_by_id("b1")
    assert pt.player_ids == [] and pt.players == SID


def test_plain_nick_links_when_player_first_seen(tmp_path):
    reg, mgr = _setup(tmp_path)
    mgr.update_point_players("b1", "scorpio10, Stranger")
    reg.observe(SID, "Scorpio10", HASH, 1000.0)
    assert mgr.get_point_by_id("b1").player_ids == [SID]


def test_relink_after_bulk_scan(tmp_path):
    reg, mgr = _setup(tmp_path)
    mgr.update_point_players("b1", "Stranger")
    reg.observe(SID2, "Stranger", HASH, 1.0, silent=True)
    assert mgr.get_point_by_id("b1").player_ids == []
    mgr.relink_players()
    assert mgr.get_point_by_id("b1").player_ids == [SID2]


def test_deleting_players_unlinks_bases(tmp_path):
    reg, mgr = _setup(tmp_path)
    reg.observe(SID, "Scorpio", HASH, 1000.0)
    mgr.update_point_players("b1", "Scorpio")
    assert mgr.get_point_by_id("b1").player_ids == [SID]
    assert reg.remove_player(SID)
    pt = mgr.get_point_by_id("b1")
    assert pt.player_ids == [] and pt.players == "Scorpio"
    reg.observe(SID, "Scorpio", HASH, 2000.0)
    mgr.update_point_players("b1", "Scorpio")
    reg.clear()
    assert mgr.get_point_by_id("b1").player_ids == [] and len(reg) == 0


def test_remove_old_nick(tmp_path):
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    reg.observe(SID, "A", HASH, 1.0)
    reg.observe(SID, "B", HASH, 2.0)
    reg.observe(SID, "C", HASH, 3.0)
    assert reg.remove_old_nick(SID, 0)  # newest old nickname "B"
    assert [h["nick"] for h in reg.get(SID)["previous_nicks"]] == ["A"]
    assert not reg.remove_old_nick(SID, 5)


def test_map_card_link_button_and_old_nick_flyout(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QToolButton

    from ui import map_window
    from ui.map_window import MapCanvasWidget

    reg, mgr = _setup(tmp_path)
    reg.observe(SID, "Old", HASH, 1000.0)
    reg.observe(SID, "Scorpio", HASH, 2000.0)
    reg.observe(SID2, "Solo", HASH, 2000.0)
    mgr.update_point_players("b1", "Scorpio, Solo, Plain")
    canvas = MapCanvasWidget(ConfigManager(str(tmp_path / "cfg.json")), mgr)
    canvas.resize(700, 400)
    canvas.show()
    canvas._show_card(mgr.get_point_by_id("b1"), ["a", "b", "c", "sector", "time", "coords"], QPoint(100, 100))
    card = canvas._card
    assert card.isVisible() and card.geometry().contains(QPoint(100, 100))

    links = [b for b in card.findChildren(QToolButton) if b.objectName() == "steamLink"]
    assert len(links) == 2  # Scorpio and Solo; the plain-text name has no link
    opened = []
    monkeypatch.setattr(map_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    links[0].click()
    assert opened == [steam_profile_url(SID)] or opened == [steam_profile_url(SID2)]

    # only the renamed player has the drop-down; it opens a flyout with the date and the old nick
    drops = [b for b in card.findChildren(QToolButton) if b.objectName() != "steamLink"]
    assert len(drops) == 1 and "Scorpio" in drops[0].text()
    drops[0].click()
    assert card._flyout.isVisible()
    texts = [lbl.text() for lbl in card._flyout.findChildren(map_window.QLabel)]
    assert any("Old" in t and "/" in t for t in texts)
    drops[0].click()
    assert not card._flyout.isVisible()
    canvas.close()


@pytest.fixture
def page(tmp_path):
    from ui.players_page import PlayersPage

    reg = PlayerRegistry(str(tmp_path / "players.json"))
    reg.observe(SID, "Old", HASH, time.time() - 100)
    reg.observe(SID, "New", HASH, time.time())
    reg.observe(SID2, "Solo", HASH, time.time())
    pg = PlayersPage(reg)
    pg.show()
    return reg, pg


def _top(pg, nick):
    return next(pg.tree.topLevelItem(i) for i in range(pg.tree.topLevelItemCount())
                if pg.tree.topLevelItem(i).text(0) == nick)


def test_players_page_lists_and_confirms_deletes(page, monkeypatch):
    reg, pg = page
    assert pg.tree.topLevelItemCount() == 2
    renamed = _top(pg, "New")
    assert renamed.childCount() == 1 and renamed.child(0).text(0) == "Old"
    assert steam_profile_url(SID) in pg.tree.itemWidget(renamed, 1).text()

    asked = []
    monkeypatch.setattr("ui.players_page.ask", lambda *a, **k: asked.append(a[2]) or False)
    renamed.child(0).setSelected(True)
    pg._delete_old_nick()
    pg.tree.clearSelection()
    _top(pg, "New").setSelected(True)
    pg._delete_player()
    pg._clear_all()
    assert len(asked) == 3 and len(reg) == 2 and len(reg.get(SID)["previous_nicks"]) == 1  # "No" deletes nothing

    monkeypatch.setattr("ui.players_page.ask", lambda *a, **k: True)
    pg.tree.clearSelection()
    _top(pg, "New").child(0).setSelected(True)
    pg._delete_old_nick()
    assert reg.get(SID)["previous_nicks"] == []
    pg._clear_all()
    assert len(reg) == 0 and pg.tree.topLevelItemCount() == 0


def test_collection_switch_off_stores_nothing(tmp_path):
    logs = tmp_path / "Logs"
    logs.mkdir()
    live = logs / "SCUM.log"
    live.write_text(_line("2026.11.10-09.00.00", "Third") + "\n", encoding="utf-8")
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    reg.enabled = False
    reg.observe(SID, "Live", HASH, 1000.0)
    assert reg.scan_logs(str(live)) == 0
    assert len(reg) == 0 and not (tmp_path / "players.json").exists()

    # switching on again scans everything (current and old logs), even after a cleared base
    reg.enabled = True
    assert reg.rescan_all(str(live)) == 1 and reg.nick_of(SID) == "Third"
    reg.clear()
    assert reg.scan_logs(str(live)) == 0
    assert reg.rescan_all(str(live)) == 1 and reg.nick_of(SID) == "Third"


def test_settings_collect_switch_roundtrip(tmp_path):
    from ui.settings_window import SettingsDialog

    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    dlg = SettingsDialog(cfg, players=reg)
    assert dlg.chk_collect_ids.isChecked()  # on by default
    dlg.chk_collect_ids.setChecked(False)
    dlg._write_to_cfg()
    assert cfg.get("collect_steam_ids") is False
