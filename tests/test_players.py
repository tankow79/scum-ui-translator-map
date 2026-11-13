import json

from core.coordinate_parser import MapPoint
from core.log_parser import ScumLogParser
from core.players import PlayerRegistry, parse_steam_ref, steam_profile_url
from core.points_manager import PointsManager

SID = "76561199117414081"
HASH = "46E01DF23CEE761799406204211C0F7266CF0DB2"


def _base(name="base"):
    return MapPoint(
        id="b1", name=name, date_time="", raw_coord="", x=0, y=0, z=0, sector="B2", keypad="k5",
        norm_x=0.5, norm_y=0.5, created_timestamp=1.0, category="base",
    )


def _setup(tmp_path):
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    mgr = PointsManager(str(tmp_path / "points.json"), registry=reg)
    mgr.add_point(_base())
    return reg, mgr


def test_parse_steam_ref():
    assert parse_steam_ref(SID) == SID
    assert parse_steam_ref(f"https://steamcommunity.com/profiles/{SID}/") == SID
    assert parse_steam_ref("scorpio10") is None
    assert parse_steam_ref("123456") is None
    assert steam_profile_url(SID) == f"https://steamcommunity.com/profiles/{SID}"


def test_parser_emits_player_line():
    seen, msgs = [], []
    parser = ScumLogParser("x.log", lambda *a: msgs.append(a), lambda *a: seen.append(a))
    parser._process_line(
        f"[2026.11.12-18.12.23:621][526]LogSCUM: Message from user: scorpio10 ({SID}) (hash: {HASH})"
    )
    parser._process_line("[2026.11.12-18.12.23:621][526]LogSCUM: Message: scorpio10: hi)")
    assert seen == [("scorpio10", SID, HASH)]
    assert len(msgs) == 1 and msgs[0][1] == "scorpio10"


def test_parser_nick_with_parentheses():
    seen = []
    parser = ScumLogParser("x.log", lambda *a: None, lambda *a: seen.append(a))
    parser._process_line(f"[2026.11.12-18.12.23:621][526]LogSCUM: Message from user: A (b) ({SID}) (hash: {HASH})")
    assert seen[0][0] == "A (b)"


def test_registry_persists_and_tracks_rename(tmp_path):
    reg = PlayerRegistry(str(tmp_path / "players.json"))
    events = []
    reg.player_changed.connect(lambda *a: events.append(a))
    reg.observe(SID, "Old", HASH)
    reg.observe(SID, "Old", HASH)  # no change -> no event
    reg.observe(SID, "New", HASH)
    assert events == [(SID, SID, "Old", True), (SID, "Old", "New", False)]
    data = json.loads((tmp_path / "players.json").read_text(encoding="utf-8"))
    assert data[SID]["nick"] == "New" and data[SID]["previous_nicks"] == ["Old"]
    assert PlayerRegistry(str(tmp_path / "players.json")).nick_of(SID) == "New"


def test_base_links_by_steam_id_and_follows_rename(tmp_path):
    reg, mgr = _setup(tmp_path)
    reg.observe(SID, "Old", HASH)
    mgr.update_point_players("b1", f"Ghost, {SID}")
    pt = mgr.get_point_by_id("b1")
    assert pt.player_ids == [SID] and pt.players == "Ghost, Old"

    reg.observe(SID, "NewNick", HASH)
    pt = mgr.get_point_by_id("b1")
    assert pt.players == "Ghost, NewNick" and pt.player_ids == [SID]
    assert mgr.describe_players(pt) == [("NewNick", SID), ("Ghost", None)]

    # survives a reload
    again = PointsManager(str(tmp_path / "points.json"), registry=reg)
    assert again.get_point_by_id("b1").player_ids == [SID]


def test_unknown_id_resolves_when_player_seen(tmp_path):
    reg, mgr = _setup(tmp_path)
    mgr.update_point_players("b1", f"https://steamcommunity.com/profiles/{SID}")
    assert mgr.get_point_by_id("b1").players == SID
    reg.observe(SID, "Scorpio", HASH)
    assert mgr.get_point_by_id("b1").players == "Scorpio"


def test_plain_nick_links_when_player_first_seen(tmp_path):
    reg, mgr = _setup(tmp_path)
    mgr.update_point_players("b1", "scorpio10")
    assert mgr.get_point_by_id("b1").player_ids == []
    reg.observe(SID, "Scorpio10", HASH)
    assert mgr.get_point_by_id("b1").player_ids == [SID]


def test_without_registry_still_accepts_ids(tmp_path):
    mgr = PointsManager(str(tmp_path / "points.json"))
    mgr.add_point(_base())
    mgr.update_point_players("b1", f"A, {SID}")
    pt = mgr.get_point_by_id("b1")
    assert pt.player_ids == [SID] and pt.players == f"A, {SID}"


def test_map_card_has_clickable_steam_link(tmp_path):
    import sys

    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication

    from core.config_manager import ConfigManager
    from ui.map_window import MapCanvasWidget

    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    reg, mgr = _setup(tmp_path)
    reg.observe(SID, "Scorpio", HASH)
    mgr.update_point_players("b1", SID)
    canvas = MapCanvasWidget(ConfigManager(str(tmp_path / "cfg.json")), mgr)
    canvas.resize(600, 400)
    canvas.show()
    pt = mgr.get_point_by_id("b1")
    canvas._show_card(pt, ["a", "b", "c", "sector", "time", "coords"], QPoint(100, 100))
    assert canvas._card.isVisible()
    text = canvas._card.label.text()
    assert f'href="https://steamcommunity.com/profiles/{SID}"' in text and "Scorpio" in text
    canvas.close()
