from core.coordinate_parser import (
    MapPoint,
    convert_norm_to_scum,
    convert_scum_to_norm,
    get_sector_info,
    parse_chat_coordinate,
)

SAMPLE_COORD = "{X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}"


def test_parse_name_before():
    text = f"машина{SAMPLE_COORD}"
    pt = parse_chat_coordinate(text, "12:34:56")
    assert pt is not None
    assert pt.name == "машина"
    assert pt.x == 174468.797
    assert pt.y == 345933.000
    assert pt.z == 34103.105
    assert pt.raw_coord == SAMPLE_COORD
    assert pt.sector == "D3"


def test_parse_name_after():
    text = f"{SAMPLE_COORD} машина"
    pt = parse_chat_coordinate(text, "12:34:56")
    assert pt is not None
    assert pt.name == "машина"


def test_parse_parentheses():
    text = f"(машина{SAMPLE_COORD})"
    pt = parse_chat_coordinate(text)
    assert pt is not None
    assert pt.name == "машина"


def test_parse_no_name():
    text = SAMPLE_COORD
    pt = parse_chat_coordinate(text)
    assert pt is not None
    assert pt.name == "None"


def test_norm_conversion_roundtrip():
    x, y = 174468.797, 345933.0
    nx, ny = convert_scum_to_norm(x, y)
    rx, ry = convert_norm_to_scum(nx, ny)
    assert abs(rx - x) < 0.001
    assert abs(ry - y) < 0.001


def test_sector_calculation():
    # Test known bounds
    # (0, 0) should be D4
    sec_tl, k_tl = get_sector_info(0.01, 0.01)
    assert sec_tl == "D4"
    assert k_tl == "k7"

    # (1.0, 1.0) should be Z0
    sec_br, k_br = get_sector_info(0.99, 0.99)
    assert sec_br == "Z0"
    assert k_br == "k3"


def test_serialization():
    pt = parse_chat_coordinate(f"Склад {SAMPLE_COORD}")
    d = pt.to_dict()
    pt2 = MapPoint.from_dict(d)
    assert pt2.name == "Склад"
    assert pt2.sector == pt.sector
    assert pt2.raw_coord == pt.raw_coord


def test_category_auto_detection():
    # Car
    pt_car = parse_chat_coordinate(f"машина{SAMPLE_COORD}")
    assert pt_car.category == "car"
    assert pt_car.color == "#f59e0b"

    # Base
    pt_base = parse_chat_coordinate(f"{SAMPLE_COORD} база")
    assert pt_base.category == "base"
    assert pt_base.color == "#a855f7"

    # Plane
    pt_plane = parse_chat_coordinate(f"(літак {SAMPLE_COORD})")
    assert pt_plane.category == "plane"
    assert pt_plane.color == "#0ea5e9"

    # Moto
    pt_moto = parse_chat_coordinate(f"мотоцик{SAMPLE_COORD}")
    assert pt_moto.category == "moto"
    assert pt_moto.color == "#f97316"

    # Boat
    pt_boat = parse_chat_coordinate(f"лодка{SAMPLE_COORD}")
    assert pt_boat.category == "boat"
    assert pt_boat.color == "#06b6d4"

    # Cache (stash / loot chest)
    pt_cache = parse_chat_coordinate(f"схрон(сундук с лутом){SAMPLE_COORD}")
    assert pt_cache.category == "cache"
    assert pt_cache.color == "#10b981"

    # Default / Generic
    pt_def = parse_chat_coordinate(SAMPLE_COORD)
    assert pt_def.category == "default"
    assert pt_def.color == "#38bdf8"


def test_base_players_serialization():
    pt = parse_chat_coordinate(f"База Альянсу {SAMPLE_COORD}")
    assert pt.category == "base"
    pt.players = "PlayerA, PlayerB, Sniper99"
    d = pt.to_dict()
    pt2 = MapPoint.from_dict(d)
    assert pt2.category == "base"
    assert pt2.players == "PlayerA, PlayerB, Sniper99"
