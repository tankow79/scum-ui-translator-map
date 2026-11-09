import pytest
from core.log_parser import ScumLogParser

def test_parser_player_message():
    captured = []
    def on_msg(time_str, sender, msg, msg_type):
        captured.append((time_str, sender, msg, msg_type))

    parser = ScumLogParser("dummy.log", on_msg)

    line = "[2026.11.03-17.10.32:145][ 74]LogSCUM: Message: Player1: im b2 bro"
    parser._process_line(line)

    assert len(captured) == 1
    t, sender, msg, m_type = captured[0]
    assert t == "17:10:32"
    assert sender == "Player1"
    assert msg == "im b2 bro"
    assert m_type == "player"

def test_parser_special_killfeed_message():
    captured = []
    parser = ScumLogParser("dummy.log", lambda *args: captured.append(args))

    line = "[2026.11.03-16.50.53:815][162]LogSCUM: Message: I ain´t DeAd: ★ [NORGE] Aron ➡ [Death Eaters] Player2 ∴ AK47 - Distance: 30m - Sector: B2"
    parser._process_line(line)

    assert len(captured) == 1
    t, sender, msg, m_type = captured[0]
    assert t == "16:50:53"
    assert sender == "I ain´t DeAd"
    assert "★ [NORGE] Aron ➡ [Death Eaters] Player2" in msg
    assert m_type == "player"

def test_parser_server_announcement():
    captured = []
    parser = ScumLogParser("dummy.log", lambda *args: captured.append(args))

    line = '[2026.11.03-20.51.28:623][382]LogSCUM: Sender player state null for message Message Of The Day: "Наш канал в діскорд https://discord.gg/GRrreuFPRq"!'
    parser._process_line(line)

    assert len(captured) == 1
    t, sender, msg, m_type = captured[0]
    assert t == "20:51:28"
    assert sender == "Message Of The Day"
    assert "https://discord.gg/GRrreuFPRq" in msg
    assert m_type == "server"

def test_parser_format_time():
    parser = ScumLogParser("dummy.log", lambda *a: None)
    assert parser._format_time("2026.11.03-20.51.28") == "20:51:28"
    assert parser._format_time("invalid_format") == "invalid_format"
