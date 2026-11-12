import os
import re
import threading
import time
from typing import Callable, Optional


class ScumLogParser:
    """
    Monitors SCUM.log in real time and parses chat messages.
    """
    def __init__(self, log_path: str, on_message: Callable[[str, str, str, str], None]):
        """
        :param log_path: Full path to SCUM.log
        :param on_message: Callback(timestamp_str, sender, message, msg_type)
        """
        self.log_path = log_path
        self.on_message = on_message
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Regexes for SCUM chat messages
        # 1. Regular player messages
        self._pattern_player = re.compile(
            r'\[(?P<time>\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}):\d+\]\[\s*\d+\]LogSCUM:\s*Message:\s*(?P<sender>[^:]+):\s*(?P<msg>.*)',
            re.DOTALL
        )
        # 2. Server messages (MOTD, Welcome, announcements, statistics)
        self._pattern_server = re.compile(
            r'\[(?P<time>\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}):\d+\]\[\s*\d+\]LogSCUM:\s*Sender player state null for message\s*(?P<sender>[^:]+):\s*(?P<msg>.*)',
            re.DOTALL
        )

    def set_log_path(self, new_path: str):
        self.log_path = new_path

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _format_time(self, raw_time: str) -> str:
        # raw_time: "2026.11.03-20.51.28" -> "20:51:28"
        try:
            parts = raw_time.split("-")
            if len(parts) == 2:
                hms = parts[1].replace(".", ":")
                return hms
        except Exception:
            pass
        return raw_time

    def _tail_loop(self):
        file = None

        while self._running:
            try:
                if not os.path.exists(self.log_path):
                    time.sleep(1.0)
                    continue

                if file is None:
                    try:
                        file = open(self.log_path, encoding="utf-8", errors="ignore")
                        # On start, load the last ~4 KB to immediately show recent chat messages
                        file.seek(0, os.SEEK_END)
                        end_pos = file.tell()
                        start_pos = max(0, end_pos - 8192)
                        file.seek(start_pos, os.SEEK_SET)
                        if start_pos > 0:
                            file.readline()  # skip a possibly truncated line
                    except Exception:
                        time.sleep(1.0)
                        continue

                line = file.readline()
                if not line:
                    # Check whether the file shrank (game restart / log rotation)
                    try:
                        cur_size = os.path.getsize(self.log_path)
                        if cur_size < file.tell():
                            file.close()
                            file = None
                            continue
                    except OSError:
                        pass
                    time.sleep(0.15)
                    continue

                self._process_line(line.strip())

            except Exception:
                time.sleep(0.5)

        if file:
            try:
                file.close()
            except Exception:
                pass

    def _process_line(self, line: str):
        if "LogSCUM:" not in line:
            return

        msg_type = "player"
        m = self._pattern_player.match(line)
        if not m:
            m = self._pattern_server.match(line)
            msg_type = "server"

        if m:
            time_str = self._format_time(m.group("time"))
            sender = m.group("sender").strip()
            msg = m.group("msg").strip()

            # Strip quotes if present ("text" -> text)
            if msg.startswith('"') and msg.endswith('"') and len(msg) >= 2:
                msg = msg[1:-1].strip()

            # Detect squad / team chat
            # In SCUM logs squad chat is marked by prefixes/tags in the sender or message:
            # e.g. "Message: (Squad) Nickname: hello", "(Team) Nick", "Nickname (Squad): hello", "[Squad] msg"
            lower_sender = sender.lower()
            lower_msg = msg.lower()
            squad_tags = (
                "(squad)", "[squad]", "(team)", "[team]",
                "(сквад)", "[сквад]", "(отряд)", "[отряд]",
                "(загін)", "[загін]", "(команда)", "[команда]"
            )
            if (
                any(tag in lower_sender for tag in squad_tags) or
                lower_sender.startswith("squad ") or lower_sender.startswith("team ") or
                lower_sender.startswith("сквад ") or lower_sender.startswith("отряд ") or
                any(lower_msg.startswith(tag) for tag in squad_tags)
            ):
                msg_type = "squad"

            if msg:
                self.on_message(time_str, sender, msg, msg_type)
