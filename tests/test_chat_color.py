from core.chat_color import DEFAULT_COLOR, SQUAD_COLOR, extract_text_color, parse_nick_list, pick_color


def test_squad_green_others_blue():
    squad = parse_nick_list("Ghost, reaper ;Alex")
    assert squad == ["Ghost", "reaper", "Alex"]
    assert pick_color("REAPER", squad) == SQUAD_COLOR
    assert pick_color("Stranger", squad) == DEFAULT_COLOR


def test_explicit_color_wins():
    text, color = extract_text_color("<color=#FF8800>raid at B2</color>")
    assert (text, color) == ("raid at B2", "#ff8800")
    assert pick_color("Ghost", ["Ghost"], color) == "#ff8800"
    text, color = extract_text_color('[color=00ff00]hi[/color] <font color="#112233">x</font>')
    assert text == "hi x" and color == "#00ff00"
    assert extract_text_color("plain <3 text") == ("plain <3 text", None)


def test_server_yellow_and_game_timestamp():
    from datetime import datetime

    from core.chat_color import SERVER_COLOR, game_timestamp, log_time_to_local

    assert pick_color("Server", [], server=True) == SERVER_COLOR
    assert pick_color("Ghost", ["Ghost"], server=True) == SQUAD_COLOR
    now = datetime(2026, 11, 13, 3, 0, 0)
    assert game_timestamp("02:56:27", now) == "13/11/2026 - 02:56:27"
    assert game_timestamp("23:59:00", now) == "12/11/2026 - 23:59:00"
    assert game_timestamp("13/11/2026 - 02:56:27", now) == "13/11/2026 - 02:56:27"
    local = datetime.strptime(log_time_to_local("2026.11.13-01.54.49"), "%d/%m/%Y - %H:%M:%S")
    utc = datetime(2026, 11, 13, 1, 54, 49).replace(tzinfo=__import__("datetime").timezone.utc)
    assert local == utc.astimezone().replace(tzinfo=None)
