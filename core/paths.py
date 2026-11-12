"""Filesystem locations used by the application (per-user data, logs, updates)."""

import os

APP_DIR_NAME = "SCUM_Chat_Translator"


def _ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def get_user_data_dir() -> str:
    """Per-user writable directory: %LOCALAPPDATA%\\SCUM_Chat_Translator."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return _ensure_dir(os.path.join(base, APP_DIR_NAME))


def get_logs_dir() -> str:
    return _ensure_dir(os.path.join(get_user_data_dir(), "logs"))


def get_updates_dir() -> str:
    """Folder where downloaded updates are stored before installation."""
    return _ensure_dir(os.path.join(get_user_data_dir(), "updates"))
