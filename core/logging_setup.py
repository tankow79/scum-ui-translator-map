"""Application-wide logging configuration (rotating file + console)."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from core.paths import get_logs_dir

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> str:
    """Configure the root logger once. Returns the log file path."""
    global _CONFIGURED
    log_path = os.path.join(get_logs_dir(), "app.log")
    if _CONFIGURED:
        return log_path

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)

    try:
        file_handler = RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass

    # Windowed (PyInstaller) builds have no stderr; only attach a console handler when present.
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        root.addHandler(console)

    _CONFIGURED = True
    return log_path
