import os
import re
import time
import threading
from typing import Callable, Optional
from datetime import datetime

class ScumLogParser:
    """
    Моніторить SCUM.log у реальному часі та парсить повідомлення чату.
    """
    def __init__(self, log_path: str, on_message: Callable[[str, str, str, str], None]):
        """
        :param log_path: Повний шлях до SCUM.log
        :param on_message: Callback(timestamp_str, sender, message, msg_type)
        """
        self.log_path = log_path
        self.on_message = on_message
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Регулярні вирази для повідомлень чату SCUM
        # 1. Звичайні повідомлення від гравців
        self._pattern_player = re.compile(
            r'\[(?P<time>\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}):\d+\]\[\s*\d+\]LogSCUM:\s*Message:\s*(?P<sender>[^:]+):\s*(?P<msg>.*)',
            re.DOTALL
        )
        # 2. Серверні повідомлення (MOTD, Welcome, Оголошення, Статистика)
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
        last_inode = None

        while self._running:
            try:
                if not os.path.exists(self.log_path):
                    time.sleep(1.0)
                    continue

                if file is None:
                    try:
                        file = open(self.log_path, "r", encoding="utf-8", errors="ignore")
                        # На старті завантажуємо останні ~4 КБ, щоб одразу показати останні повідомлення чату
                        file.seek(0, os.SEEK_END)
                        end_pos = file.tell()
                        start_pos = max(0, end_pos - 8192)
                        file.seek(start_pos, os.SEEK_SET)
                        if start_pos > 0:
                            file.readline()  # пропускаємо можливий обрізок рядка
                    except Exception as e:
                        time.sleep(1.0)
                        continue

                line = file.readline()
                if not line:
                    # Перевіряємо, чи файл не зменшився (перезапуск гри/ротація логу)
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

            except Exception as e:
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

            # Очищуємо лапки, якщо є ("текст" -> текст)
            if msg.startswith('"') and msg.endswith('"') and len(msg) >= 2:
                msg = msg[1:-1].strip()

            # Визначення повідомлення загону / скваду (Squad chat)
            # В SCUM логах чат скваду маркується префіксами у відправнику або повідомленні:
            # Наприклад: "Message: (Squad) Nickname: hello", "(Team) Nick", "Nickname (Squad): hello", "[Squad] msg"
            lower_sender = sender.lower()
            lower_msg = msg.lower()
            if (
                "(squad)" in lower_sender or "[squad]" in lower_sender or
                "(team)" in lower_sender or "[team]" in lower_sender or
                lower_sender.startswith("squad ") or lower_sender.startswith("team ") or
                lower_msg.startswith("(squad)") or lower_msg.startswith("[squad]") or
                lower_msg.startswith("(team)") or lower_msg.startswith("[team]")
            ):
                msg_type = "squad"

            if msg:
                self.on_message(time_str, sender, msg, msg_type)
