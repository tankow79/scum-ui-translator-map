"""Open a file for reading without blocking other processes from renaming or deleting it.

Python's ``open`` on Windows omits FILE_SHARE_DELETE, so while the translator tails SCUM.log the game
could not rotate it to ``SCUM-backup-*.log``. These helpers open the file with all share modes.
"""

import ctypes
import os
import sys
from typing import BinaryIO, TextIO

_GENERIC_READ = 0x80000000
_SHARE_ALL = 0x1 | 0x2 | 0x4          # READ | WRITE | DELETE
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80


def _open_fd(path: str) -> int:
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                     ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.CreateFileW(path, _GENERIC_READ, _SHARE_ALL, None, _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError:
        kernel32.CloseHandle(handle)   # do not leak the handle when it cannot be wrapped
        raise


def open_shared_binary(path: str) -> BinaryIO:
    """Binary reader that allows the file to be renamed/deleted while open (plain ``open`` elsewhere).

    Binary on purpose: the caller decodes only complete lines, so a multi-byte character that the game
    writes in two pieces is never cut in half.
    """
    if sys.platform != "win32":
        return open(path, "rb")
    fd = _open_fd(path)
    try:
        return os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)
        raise


def open_shared_text(path: str, encoding: str = "utf-8", errors: str = "ignore") -> TextIO:
    """Text reader with the same sharing behaviour (plain ``open`` elsewhere)."""
    if sys.platform != "win32":
        return open(path, encoding=encoding, errors=errors)
    fd = _open_fd(path)
    try:
        return os.fdopen(fd, "r", encoding=encoding, errors=errors)
    except OSError:
        os.close(fd)
        raise
