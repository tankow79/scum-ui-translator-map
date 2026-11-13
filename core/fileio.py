"""Crash-safe JSON file helpers shared by every module that stores user data."""

import json
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("scum.fileio")

_WRITE_LOCK = threading.Lock()  # one writer at a time: they all share "<file>.tmp"


def _replace_with_retry(src: str, dst: str, attempts: int = 8) -> None:
    """os.replace that survives the short sharing violations Windows reports while an antivirus scanner or
    the search indexer briefly holds the destination file."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def atomic_write_json(path: str, data: Any, indent: int = 2) -> None:
    """Write JSON to ``path`` via a temp file + fsync + os.replace, so a crash never leaves a half-written file.

    Raises OSError on failure (callers log it).
    """
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with _WRITE_LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            _replace_with_retry(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise


def quarantine_corrupt(path: str) -> str:
    """Move an unreadable user file aside (``name.corrupt-<time>``) so the next save cannot destroy it.

    Returns the new path, or "" when it could not be moved.
    """
    target = f"{path}.corrupt-{int(time.time())}"
    try:
        os.replace(path, target)
        log.warning("Unreadable file %s was kept as %s", path, target)
        return target
    except OSError as exc:
        log.error("Could not preserve corrupt file %s: %s", path, exc)
        return ""
