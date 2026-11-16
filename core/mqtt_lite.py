"""A small MQTT 3.1.1 client (QoS 0, retained messages) used as the relay for clan sync.

Runs in its own daemon thread: connects (TLS by default), reconnects with back-off across several brokers,
subscribes, delivers incoming messages to ``on_message(topic, payload)`` and sends queued publishes.
"""
import hashlib
import logging
import random
import socket
import ssl
import struct
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

log = logging.getLogger("scum.mqtt")

MAX_PACKET = 256 * 1024
KEEPALIVE = 30
QUEUE_LIMIT = 4000

DEFAULT_BROKERS: List[Tuple[str, int, bool]] = [("broker.hivemq.com", 8883, True), ("broker.emqx.io", 8883, True)]


def parse_broker(text: str) -> Optional[Tuple[str, int, bool]]:
    """"host", "host:port", "mqtt://host:1883" (plain) or "mqtts://host:8883" (TLS). Empty/invalid -> None."""
    text = (text or "").strip()
    if not text:
        return None
    tls = True
    if "://" in text:
        scheme, text = text.split("://", 1)
        if scheme.lower() == "mqtt":
            tls = False
        elif scheme.lower() not in ("mqtts", "ssl", "tls"):
            return None
    host, _, port_text = text.strip("/").partition(":")
    if not host or any(c.isspace() for c in host):
        return None
    try:
        port = int(port_text) if port_text else (8883 if tls else 1883)
    except ValueError:
        return None
    return (host, port, tls) if 0 < port < 65536 else None


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        digit, n = n % 128, n // 128
        out.append(digit | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _utf8(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def packet(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | flags]) + _varint(len(body)) + body


def _send(sock, data: bytes):
    """Writes with a generous timeout: the short read timeout must not cut a packet in half."""
    sock.settimeout(10)
    try:
        sock.sendall(data)
    finally:
        sock.settimeout(0.25)


def topic_matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


class PacketReader:
    """Splits the incoming byte stream into MQTT packets; raises ValueError on garbage."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes):
        self.buffer += data
        while True:
            if len(self.buffer) < 2:
                return
            length, shift, pos = 0, 0, 1
            while True:
                if pos >= len(self.buffer):
                    return  # the length is not complete yet
                byte = self.buffer[pos]
                length |= (byte & 0x7F) << shift
                pos += 1
                if not byte & 0x80:
                    break
                shift += 7
                if shift > 21:
                    raise ValueError("bad remaining length")
            if length > MAX_PACKET:
                raise ValueError("packet too large")
            if len(self.buffer) < pos + length:
                return
            first = self.buffer[0]
            body = bytes(self.buffer[pos:pos + length])
            del self.buffer[:pos + length]
            yield first >> 4, first & 0x0F, body


def parse_publish(flags: int, body: bytes) -> Tuple[str, bytes, int]:
    """(topic, payload, packet_id) of a PUBLISH body; packet_id is 0 for QoS 0."""
    if len(body) < 2:
        raise ValueError("short publish")
    tlen = struct.unpack(">H", body[:2])[0]
    if len(body) < 2 + tlen:
        raise ValueError("short publish")
    topic = body[2:2 + tlen].decode("utf-8", "replace")
    pos, packet_id = 2 + tlen, 0
    if (flags >> 1) & 0x03:
        if len(body) < pos + 2:
            raise ValueError("short publish")
        packet_id = struct.unpack(">H", body[pos:pos + 2])[0]
        pos += 2
    return topic, body[pos:], packet_id


class MqttClient(threading.Thread):
    def __init__(self, brokers: List[Tuple[str, int, bool]], client_id: str, subscriptions: List[str],
                 on_message: Callable[[str, bytes], None], on_state: Optional[Callable[[str, str], None]] = None):
        super().__init__(daemon=True, name="mqtt-sync")
        self.brokers = list(brokers) or list(DEFAULT_BROKERS)
        self.client_id = client_id
        self.subscriptions = list(subscriptions)
        self.on_message = on_message
        self.on_state = on_state or (lambda state, detail: None)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._outbox: Deque[Tuple[str, bytes, bool]] = deque()
        self._wake = threading.Event()
        self.connected = False
        self.connected_once = False
        self.broker_label = ""

    # ── public ───────────────────────────────────────────────────────
    def publish(self, topic: str, payload: bytes, retain: bool = False):
        with self._lock:
            if len(self._outbox) >= QUEUE_LIMIT:
                for i, item in enumerate(self._outbox):     # drop the oldest message that is not retained state
                    if not item[2]:
                        del self._outbox[i]
                        break
                else:
                    self._outbox.popleft()
            self._outbox.append((topic, payload, retain))
        self._wake.set()

    def stop(self):
        self._stop_event.set()
        self._wake.set()

    # ── thread ───────────────────────────────────────────────────────
    def run(self):
        delay, index = 1.0, 0
        while not self._stop_event.is_set():
            host, port, tls = self.brokers[index % len(self.brokers)]
            self.broker_label = f"{host}:{port}"
            self._state("connecting", self.broker_label)
            try:
                self._session(host, port, tls)
                delay = 1.0
            except (OSError, ValueError, ssl.SSLError) as exc:
                log.info("MQTT %s:%s: %s", host, port, exc)
                self._state("error", f"{type(exc).__name__}")
            except Exception:
                log.exception("MQTT session failed")
                self._state("error", "unexpected")
            self.connected = False
            if self._stop_event.is_set():
                break
            if self.connected_once:
                delay = 1.0                                       # a good session: reconnect quickly
            index = 0 if self.connected_once else index + 1       # prefer the first broker again after a good session
            self._state("offline", "")
            if self._stop_event.wait(delay + random.random()):
                break
            delay = min(delay * 2, 30.0)
        self._state("stopped", "")

    def _state(self, state: str, detail: str):
        try:
            self.on_state(state, detail)
        except Exception:
            log.exception("on_state failed")

    def _session(self, host: str, port: int, tls: bool):
        self.connected_once = False
        if self._stop_event.is_set():
            return
        sock = socket.create_connection((host, port), timeout=10)
        try:
            if tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            sock.settimeout(0.25)
            body = (_utf8("MQTT") + bytes([4, 0x02]) + struct.pack(">H", KEEPALIVE) + _utf8(self.client_id))
            _send(sock, packet(1, 0, body))
            reader = PacketReader()
            deadline = time.monotonic() + 10
            acked = False
            last_sent = last_received = time.monotonic()
            while not self._stop_event.is_set():
                try:
                    data = sock.recv(8192)
                    if not data:
                        raise OSError("connection closed by the broker")
                    last_received = time.monotonic()
                    for kind, flags, pbody in reader.feed(data):
                        if kind == 2:       # CONNACK
                            if len(pbody) < 2 or pbody[1] != 0:
                                raise OSError(f"broker refused the connection ({pbody[1] if len(pbody) > 1 else '?'})")
                            acked = True
                            sub = struct.pack(">H", 1) + b"".join(_utf8(s) + b"\x00" for s in self.subscriptions)
                            _send(sock, packet(8, 2, sub))
                            self.connected = True
                            self.connected_once = True
                            self._state("online", self.broker_label)
                        elif kind == 9:     # SUBACK: a refused subscription is as good as no connection
                            if len(pbody) < 3 or any(code == 0x80 for code in pbody[2:]):
                                raise OSError("the broker refused the subscription")
                        elif kind == 3:     # PUBLISH
                            topic, payload, packet_id = parse_publish(flags, pbody)
                            if packet_id and (flags >> 1) & 0x03 == 1:
                                _send(sock, packet(4, 0, struct.pack(">H", packet_id)))
                            try:
                                self.on_message(topic, payload)
                            except Exception:
                                log.exception("on_message failed")
                except (TimeoutError, ssl.SSLWantReadError):
                    pass
                now = time.monotonic()
                if not acked:
                    if now > deadline:
                        raise OSError("no CONNACK from the broker")
                    continue
                if now - last_received > KEEPALIVE * 2:
                    raise OSError("broker went silent")
                self._wake.clear()
                while True:
                    with self._lock:
                        item = self._outbox.popleft() if self._outbox else None
                    if item is None:
                        break
                    topic, payload, retain = item
                    try:
                        _send(sock, packet(3, 1 if retain else 0, _utf8(topic) + payload))
                    except OSError:
                        with self._lock:
                            self._outbox.appendleft(item)
                        raise
                    last_sent = time.monotonic()
                if time.monotonic() - last_sent > KEEPALIVE / 2:
                    _send(sock, packet(12, 0, b""))
                    last_sent = time.monotonic()
            try:
                if acked:
                    for _ in range(50):             # last words (the "bye" of a member who switches sync off)
                        with self._lock:
                            item = self._outbox.popleft() if self._outbox else None
                        if item is None:
                            break
                        _send(sock, packet(3, 1 if item[2] else 0, _utf8(item[0]) + item[1]))
                _send(sock, packet(14, 0, b""))
            except OSError:
                pass
        finally:
            try:
                sock.close()
            except OSError:
                pass


class MultiClient:
    """Several relay brokers used at the same time: every message goes to all of them, messages from all of them are
    listened to (a copy that arrives twice is dropped), and the link counts as online while at least one broker works."""

    DEDUPE_SECONDS = 45.0
    DEDUPE_LIMIT = 4096

    def __init__(self, brokers: List[Tuple[str, int, bool]], client_id: str, subscriptions: List[str],
                 on_message: Callable[[str, bytes], None], on_state: Optional[Callable[[str, str], None]] = None):
        brokers = list(brokers) or list(DEFAULT_BROKERS)
        self.on_message = on_message
        self.on_state = on_state or (lambda state, detail: None)
        self._lock = threading.Lock()
        self._seen: Dict[bytes, float] = {}
        self._states: List[str] = ["connecting"] * len(brokers)
        self._labels: List[str] = [f"{b[0]}:{b[1]}" for b in brokers]
        self.clients = [
            MqttClient([broker], f"{client_id}-{i}", subscriptions, self._message,
                       lambda state, detail, i=i: self._child_state(i, state, detail))
            for i, broker in enumerate(brokers)
        ]

    # ── same surface as MqttClient ───────────────────────────────────
    @property
    def connected(self) -> bool:
        return any(c.connected for c in self.clients)

    @property
    def connected_once(self) -> bool:
        return any(c.connected_once for c in self.clients)

    def online_count(self) -> int:
        return sum(1 for c in self.clients if c.connected)

    def start(self):
        for c in self.clients:
            c.start()

    def stop(self):
        for c in self.clients:
            c.stop()

    def join(self, timeout: Optional[float] = None):
        deadline = None if timeout is None else time.monotonic() + timeout
        for c in self.clients:
            c.join(None if deadline is None else max(0.0, deadline - time.monotonic()))

    def is_alive(self) -> bool:
        return any(c.is_alive() for c in self.clients)

    def publish(self, topic: str, payload: bytes, retain: bool = False):
        for c in self.clients:
            c.publish(topic, payload, retain)

    # ── merging what the brokers say ─────────────────────────────────
    def _message(self, topic: str, payload: bytes):
        key = hashlib.sha1(topic.encode("utf-8", "replace") + b"\0" + payload).digest()
        now = time.monotonic()
        with self._lock:
            if len(self._seen) > self.DEDUPE_LIMIT:
                self._seen = {k: t for k, t in self._seen.items() if now - t < self.DEDUPE_SECONDS}
                if len(self._seen) > self.DEDUPE_LIMIT:
                    self._seen.clear()
            stamp = self._seen.get(key)
            if stamp is not None and now - stamp < self.DEDUPE_SECONDS:
                return                                   # the same message already came through another broker
            self._seen[key] = now
        self.on_message(topic, payload)

    def _child_state(self, index: int, state: str, detail: str):
        if state == "stopped":
            return
        with self._lock:
            self._states[index] = state
            others_online = any(s == "online" for i, s in enumerate(self._states) if i != index)
            online_labels = [self._labels[i] for i, s in enumerate(self._states) if s == "online"]
            connecting = any(s == "connecting" for s in self._states)
        if state == "online":
            self.on_state("online", ", ".join(online_labels))
        elif others_online:
            return                                       # one broker is down, the link as a whole still works
        elif connecting and state != "connecting":
            self.on_state("connecting", "")
        else:
            self.on_state(state, detail)
