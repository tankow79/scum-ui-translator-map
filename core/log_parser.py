import logging
import os
import re
import threading
import time
from typing import Callable, Optional

from core.chat_color import log_time_to_local
from core.players import parse_user_line
from utils.shared_open import open_shared_binary

log = logging.getLogger("scum.parser")


class ScumLogParser:
    """
    Monitors SCUM.log in real time and parses chat messages.
    """
    def __init__(
        self,
        log_path: str,
        on_message: Callable[[str, str, str, str], None],
        on_player: Optional[Callable[[str, str, str, float], None]] = None,
    ):
        """
        :param log_path: Full path to SCUM.log
        :param on_message: Callback(timestamp_str, sender, message, msg_type)
        :param on_player: Callback(steam_id, nickname, hash, epoch_utc) for ``Message from user:`` lines
        """
        self.log_path = log_path
        self.on_message = on_message
        self.on_player = on_player
        self._running = False
        self._reopen = False
        self._last_nick = ""
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
        if new_path != self.log_path:
            self.log_path = new_path
            self._reopen = True  # the tail loop closes the old file and starts on the new one

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
        # raw_time is UTC ("2026.11.03-20.51.28"); the game chat shows local time -> "21:51:28"
        full = log_time_to_local(raw_time)
        return full.split(" - ")[-1] if " - " in full else raw_time

    def _tail_loop(self):
        file = None
        pending = b""  # a line that is still being written by the game

        while self._running:
            try:
                if self._reopen:
                    self._reopen = False
                    if file is not None:
                        file.close()
                        file = None
                    pending = b""

                if not os.path.exists(self.log_path):
                    time.sleep(1.0)
                    continue

                if file is None:
                    try:
                        file = open_shared_binary(self.log_path)
                        # On start, load the last ~4 KB to immediately show recent chat messages
                        file.seek(0, os.SEEK_END)
                        end_pos = file.tell()
                        start_pos = max(0, end_pos - 8192)
                        file.seek(start_pos, os.SEEK_SET)
                        pending = b""
                        if start_pos > 0:
                            file.readline()  # skip a possibly truncated line
                    except Exception:
                        time.sleep(1.0)
                        continue

                line = file.readline()
                if not line:
                    # Check whether the file shrank (game restart / log rotation)
                    try:
                        path_stat = os.stat(self.log_path)
                        open_stat = os.fstat(file.fileno())
                        rotated = (path_stat.st_ino, path_stat.st_dev) != (open_stat.st_ino, open_stat.st_dev)
                        if rotated or path_stat.st_size < file.tell():
                            file.close()  # the game rotated the log (renamed it / started a new one)
                            file = None
                            pending = b""
                            continue
                    except OSError:
                        pass
                    time.sleep(0.15)
                    continue

                if not line.endswith(b"\n"):
                    pending += line  # incomplete: wait for the rest instead of parsing half a message
                    if len(pending) > 1_000_000:  # a runaway line without a newline must not grow forever
                        pending = b""
                    time.sleep(0.05)
                    continue
                line, pending = pending + line, b""
                self._process_line(line.decode("utf-8", errors="ignore").strip())

            except Exception:
                log.exception("Log parser error (continuing)")
                time.sleep(0.5)

        if file:
            try:
                file.close()
            except Exception:
                pass

    def _process_line(self, line: str):
        if "LogSCUM:" not in line:
            return

        parsed = parse_user_line(line)
        if parsed:
            self._last_nick = parsed[1]
            if self.on_player is not None:
                self.on_player(*parsed)
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

            # A nickname that contains ':' (the pattern stops at the first one): trust the nickname the game
            # announced on the preceding "Message from user" line
            full = f"{sender}:{m.group('msg')}"
            known = self._last_nick
            if known and ":" in known and full.lower().startswith(known.lower() + ":"):
                sender = known
                msg = full[len(known) + 1:].strip()

            # Strip quotes if present ("text" -> text, also "text"!)
            quoted = re.fullmatch(r'"(.*)"[!.?]?', msg, re.DOTALL)
            if quoted and len(msg) >= 2:
                msg = quoted.group(1).strip()

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
                any(lower_msg.startswith(tag) for tag in squad_tags)
            ):
                msg_type = "squad"

            if msg:
                self.on_message(time_str, sender, msg, msg_type)
