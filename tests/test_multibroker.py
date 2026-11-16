"""Sync over several relay brokers at once: every message goes to all, duplicates are dropped, one broker is enough."""
import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from mqtt_fake import FakeBroker  # noqa: E402
from test_sync import app, chat_point, make_node, online, wait_for  # noqa: E402,F401

from core import sync_crypto as sc  # noqa: E402
from core import sync_engine  # noqa: E402
from core.mqtt_lite import MultiClient, parse_broker  # noqa: E402

RAW_HTTP = True


def dead_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def two_brokers():
    a, b = FakeBroker(), FakeBroker()
    yield a, b
    a.close()
    b.close()


def test_a_message_reaches_the_listener_once_even_through_two_brokers(two_brokers):
    a, b = two_brokers
    brokers = [parse_broker(a.url), parse_broker(b.url)]
    got = []
    listener = MultiClient(brokers, "listen", ["t/#"], lambda t, p: got.append((t, p)))
    sender = MultiClient(brokers, "send", ["t/#"], lambda t, p: None)
    listener.start()
    sender.start()
    try:
        assert wait_for(lambda: listener.online_count() == 2 and sender.online_count() == 2)
        sender.publish("t/x", b"hello", False)
        assert wait_for(lambda: len(got) >= 1)
        time.sleep(0.5)
        assert got == [("t/x", b"hello")]                       # both brokers delivered it, the listener saw it once
        sender.publish("t/x", b"again", False)                  # a different message is not a duplicate
        assert wait_for(lambda: len(got) == 2)
    finally:
        listener.stop()
        sender.stop()
        listener.join(5)
        sender.join(5)
    assert not listener.is_alive() and not sender.is_alive()


def test_link_is_online_while_one_broker_works(two_brokers):
    a, b = two_brokers
    states = []
    client = MultiClient([parse_broker(a.url), ("127.0.0.1", dead_port(), False)], "c", ["t/#"], lambda t, p: None,
                         lambda s, d: states.append(s))
    client.start()
    try:
        assert wait_for(lambda: "online" in states)
        assert client.connected and client.online_count() == 1
        time.sleep(1.2)
        assert states[-1] == "online"                           # the dead broker never makes the link "offline"
    finally:
        client.stop()
        client.join(5)


def test_two_engines_stay_connected_when_a_broker_dies(tmp_path, monkeypatch, two_brokers):
    a, b = two_brokers
    monkeypatch.setattr(sync_engine, "DEFAULT_BROKERS", [parse_broker(a.url), parse_broker(b.url)])
    code = sc.new_code()
    made = [make_node(tmp_path, n, code, type("B", (), {"url": ""})()) for n in ("alice", "bob")]
    engines = []
    for cfg, mgr, eng in made:
        cfg.set("sync_broker", "")                              # no own relay: both public ones (here: the two fakes)
        engines.append((mgr, eng))
        eng.start()
    (mgr_a, eng_a), (mgr_b, eng_b) = engines
    try:
        assert online(eng_a) and online(eng_b)
        assert mgr_a.add_point(chat_point("One", -600000.0, -500000.0, 1))
        assert wait_for(lambda: len(mgr_b.get_points()) == 1)
        a.close()                                               # one relay dies: nothing must stop working
        time.sleep(0.5)
        assert eng_a.state == "online" and eng_b.state == "online"
        assert mgr_a.add_point(chat_point("Two", -600100.0, -500100.0, 2))
        assert wait_for(lambda: len(mgr_b.get_points()) == 2)
    finally:
        eng_a.stop(quiet=True)
        eng_b.stop(quiet=True)


def test_a_player_on_both_relays_meets_players_who_reach_only_one(tmp_path, monkeypatch, two_brokers):
    a, b = two_brokers
    code = sc.new_code()
    nodes = []
    for name, brokers in (("alice", [a]), ("bob", [a, b]), ("carol", [b])):
        monkeypatch.setattr(sync_engine, "DEFAULT_BROKERS", [parse_broker(x.url) for x in brokers])
        cfg, mgr, eng = make_node(tmp_path, name, code, a)
        cfg.set("sync_broker", "")
        eng.start()
        nodes.append((mgr, eng))
    (mgr_a, eng_a), (mgr_b, eng_b), (mgr_c, eng_c) = nodes
    try:
        assert online(eng_a) and online(eng_b) and online(eng_c)
        assert mgr_a.add_point(chat_point("Only A", -600000.0, -500000.0, 1))
        assert mgr_c.add_point(chat_point("Only B", -600100.0, -500100.0, 2))
        # bob sits on both relays, so he meets both players (a player who reaches only one relay is still heard there)
        assert wait_for(lambda: len(mgr_b.get_points()) == 2)
    finally:
        for _mgr, eng in nodes:
            eng.stop(quiet=True)


def test_own_relay_is_used_alone(tmp_path, monkeypatch):
    own = FakeBroker()
    try:
        monkeypatch.setattr(sync_engine, "DEFAULT_BROKERS", [("203.0.113.9", 8883, True)])
        cfg, mgr, eng = make_node(tmp_path, "alice", sc.new_code(), own)
        eng.start()
        assert len(eng.client.clients) == 1 and eng.client.clients[0].brokers[0][1] == own.port
        eng.stop(quiet=True)
    finally:
        own.close()
