from core.chat_color import log_time_to_local
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
    assert t == log_time_to_local("2026.11.03-17.10.32").split(" - ")[1]
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
    assert t == log_time_to_local("2026.11.03-16.50.53").split(" - ")[1]
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
    assert t == log_time_to_local("2026.11.03-20.51.28").split(" - ")[1]
    assert sender == "Message Of The Day"
    assert "https://discord.gg/GRrreuFPRq" in msg
    assert m_type == "server"

def test_parser_format_time():
    parser = ScumLogParser("dummy.log", lambda *a: None)
    assert parser._format_time("2026.11.03-20.51.28") == log_time_to_local("2026.11.03-20.51.28").split(" - ")[1]
    assert parser._format_time("invalid_format") == "invalid_format"

def test_parser_squad_message():
    captured = []
    parser = ScumLogParser("dummy.log", lambda *args: captured.append(args))

    # 1. English prefix (Squad)
    line1 = "[2026.11.03-18.00.00:100][ 88]LogSCUM: Message: (Squad) Teammate1: enemy at bunker"
    parser._process_line(line1)
    assert len(captured) == 1
    assert captured[0][1] == "(Squad) Teammate1"
    assert captured[0][2] == "enemy at bunker"
    assert captured[0][3] == "squad"

    # 2. [Squad] prefix in text
    line2 = "[2026.11.03-18.00.05:100][ 88]LogSCUM: Message: Teammate2: [Squad] take ammo"
    parser._process_line(line2)
    assert len(captured) == 2
    assert captured[1][3] == "squad"

    # 3. Cyrillic (Сквад)
    line3 = "[2026.11.03-18.00.10:100][ 88]LogSCUM: Message: (Сквад) Friend: тут лут"
    parser._process_line(line3)
    assert len(captured) == 3
    assert captured[2][3] == "squad"


def test_parser_thread_start_reads_file_and_stops(tmp_path):
    """start()/stop() and the tail loop were never exercised; a missing attribute crashed the app on launch."""
    import time

    log_file = tmp_path / "SCUM.log"
    log_file.write_text(
        "[2026.11.13-01.54.49:390][201]LogSCUM: Message from user: AndraX (76561198995660378) (hash: 0985AB)\n"
        "[2026.11.13-01.54.49:390][201]LogSCUM: Message: AndraX: Hello\n",
        encoding="utf-8",
    )
    messages, players = [], []
    parser = ScumLogParser(str(log_file), lambda *a: messages.append(a), lambda *a: players.append(a))
    parser.start()
    try:
        parser.start()  # second start() is a no-op
        deadline = time.time() + 5
        while (not messages or not players) and time.time() < deadline:
            time.sleep(0.05)
        assert parser._thread is not None and parser._thread.is_alive()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("[2026.11.13-01.56.27:866][217]LogSCUM: Message: AndraX: second\n")
        deadline = time.time() + 5
        while len(messages) < 2 and time.time() < deadline:
            time.sleep(0.05)
    finally:
        parser.stop()
    assert [m[2] for m in messages] == ["Hello", "second"]
    assert players and players[0][:2] == ("76561198995660378", "AndraX")
    assert not parser._thread.is_alive()
