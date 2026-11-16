"""A tiny in-process MQTT 3.1.1 broker for the tests (QoS 0, retained messages, + and # wildcards)."""
import socket
import struct
import threading

from core.mqtt_lite import PacketReader, _utf8, packet, parse_publish, topic_matches


class FakeBroker:
    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.retained = {}
        self.clients = []          # (conn, subscriptions list)
        self.published = []        # (topic, payload, retain) in arrival order
        self.lock = threading.Lock()
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"mqtt://127.0.0.1:{self.port}"

    def _accept(self):
        while not self.closed:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def drop_clients(self):
        """Simulate a broker restart / network cut: close every connection."""
        with self.lock:
            clients, self.clients = self.clients, []
        for conn, _ in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
            except OSError:
                pass

    def close(self):
        self.closed = True
        self.drop_clients()
        try:
            self.sock.close()
        except OSError:
            pass

    @staticmethod
    def _deliver(conn, topic, payload, retain_flag=0):
        try:
            conn.sendall(packet(3, retain_flag, _utf8(topic) + payload))
        except OSError:
            pass

    def _serve(self, conn):
        reader, subs = PacketReader(), []
        entry = (conn, subs)
        try:
            while True:
                data = conn.recv(8192)
                if not data:
                    return
                for kind, flags, body in reader.feed(data):
                    if kind == 1:
                        conn.sendall(packet(2, 0, b"\x00\x00"))
                        with self.lock:
                            self.clients.append(entry)
                    elif kind == 8:
                        pid = struct.unpack(">H", body[:2])[0]
                        pos, codes = 2, b""
                        while pos < len(body):
                            tlen = struct.unpack(">H", body[pos:pos + 2])[0]
                            subs.append(body[pos + 2:pos + 2 + tlen].decode())
                            pos += 2 + tlen + 1
                            codes += b"\x00"
                        conn.sendall(packet(9, 0, struct.pack(">H", pid) + codes))
                        with self.lock:
                            stored = list(self.retained.items())
                        for topic, payload in stored:
                            if any(topic_matches(s, topic) for s in subs):
                                self._deliver(conn, topic, payload, 1)
                    elif kind == 3:
                        topic, payload, _ = parse_publish(flags, body)
                        retain = flags & 1
                        with self.lock:
                            self.published.append((topic, payload, bool(retain)))
                            if retain:
                                if payload:
                                    self.retained[topic] = payload
                                else:
                                    self.retained.pop(topic, None)
                            targets = list(self.clients)
                        for other, osubs in targets:
                            if other is not conn and any(topic_matches(s, topic) for s in osubs):
                                self._deliver(other, topic, payload)
                    elif kind == 12:
                        conn.sendall(packet(13, 0, b""))
                    elif kind == 14:
                        return
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                if entry in self.clients:
                    self.clients.remove(entry)
            try:
                conn.close()
            except OSError:
                pass
