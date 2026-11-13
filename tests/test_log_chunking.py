"""Property test: however the game happens to write the log (any chunk size, splits inside a UTF-8 character or a
CRLF, a rotation in the middle), every chat message arrives exactly once and in order."""
import os
import random
import time

import pytest

from core.log_parser import ScumLogParser

ALPHABET = "abcdefgh ijkl привіт світ ґєї 你好 😀 ä ö ü ß ★ ➡ ∴ .,!?-"


def _line(i, rnd):
    text = "".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(1, 60))).strip() or "x"
    return f"[2026.11.13-10.{i // 60 % 60:02d}.{i % 60:02d}:123][  1]LogSCUM: Message: Bot{i % 5}: m{i} {text}", f"m{i} {text}"


def _wait(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_every_message_arrives_once_and_in_order(tmp_path, seed):
    rnd = random.Random(seed)
    path = tmp_path / "SCUM.log"
    path.write_bytes(b"")
    got = []
    parser = ScumLogParser(str(path), lambda t, s, m, ty: got.append(m))
    parser.start()
    try:
        expected = []
        rotate_at = rnd.randint(25, 45)
        for i in range(70):
            line, msg = _line(i, rnd)
            expected.append(msg)
            data = (line + rnd.choice(["\n", "\r\n"])).encode("utf-8")
            if i == rotate_at:
                # the game starts a new log: wait until everything so far was read, then rotate (rename + recreate)
                assert _wait(lambda: len(got) == len(expected) - 1, 8), (len(got), len(expected))
                os.replace(path, tmp_path / "SCUM-backup.log")
                path.write_bytes(b"")
                time.sleep(0.5)
            with open(path, "ab") as f:
                pos = 0
                while pos < len(data):
                    step = rnd.randint(1, 9)                 # may cut a multi-byte character or the CRLF in two
                    f.write(data[pos:pos + step])
                    f.flush()
                    pos += step
                    if rnd.random() < 0.3:
                        time.sleep(0.02)
            if rnd.random() < 0.2:
                time.sleep(0.05)
        assert _wait(lambda: len(got) >= len(expected), 15), (len(got), len(expected))
    finally:
        parser.stop()
    assert got == expected
