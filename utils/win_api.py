import ctypes
import logging
import os
import sys
from ctypes import wintypes

log = logging.getLogger("scum.winapi")

# Private library objects (not ctypes.windll's shared ones) so the declarations below cannot affect other libraries
user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
psapi = ctypes.WinDLL("psapi")

# Explicit signatures: handles are pointer sized, the ctypes default (C int) would truncate them on 64-bit Windows
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = -1
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Define types for 64-bit pointers
if sys.maxsize > 2**32:
    SetWindowLongPtr = user32.SetWindowLongPtrW
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    SetWindowLongPtr.restype = ctypes.c_ssize_t

    GetWindowLongPtr = user32.GetWindowLongPtrW
    GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongPtr.restype = ctypes.c_ssize_t
else:
    SetWindowLongPtr = user32.SetWindowLongW
    GetWindowLongPtr = user32.GetWindowLongW

# Saved SCUM game window handle for instant focus restore
_last_game_hwnd: int = 0
_app_mutex_handle = None


def check_single_instance(mutex_name: str = "SCUM_Chat_Translator_Mutex_Unique",
                          wait_seconds: float = 0.0) -> bool:
    """
    Guard against running two copies of the app.
    Returns True if this is the only instance, False if another one is already running.
    ``wait_seconds`` lets a freshly updated process wait for its predecessor to exit.
    """
    import time

    global _app_mutex_handle
    # GetLastError must be read through a library loaded with use_last_error, otherwise another call in between
    # can overwrite it and a second copy of the program would start
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ERROR_ALREADY_EXISTS = 183
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        ctypes.set_last_error(0)
        handle = k32.CreateMutexW(None, False, mutex_name)
        error = ctypes.get_last_error()
        if handle and error != ERROR_ALREADY_EXISTS:
            _app_mutex_handle = handle
            return True
        if handle:
            k32.CloseHandle(handle)
        elif error != ERROR_ALREADY_EXISTS:
            return True      # the mutex could not be created at all (e.g. access denied): do not block start-up
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def set_last_game_hwnd(hwnd: int):
    """Save the SCUM game window handle."""
    global _last_game_hwnd
    if hwnd and user32.IsWindow(hwnd):
        _last_game_hwnd = hwnd


def get_last_game_hwnd() -> int:
    """Get the last active SCUM window handle or find it."""
    global _last_game_hwnd
    if _last_game_hwnd and user32.IsWindow(_last_game_hwnd):
        return _last_game_hwnd

    # Try to find the Unreal Engine / SCUM window directly
    h = user32.FindWindowW("UnrealWindow", None)
    if h and user32.IsWindow(h):
        _last_game_hwnd = h
        return h

    h = user32.FindWindowW(None, "SCUM")
    if h and user32.IsWindow(h):
        _last_game_hwnd = h
        return h

    h = user32.FindWindowW(None, "SCUM  ")
    if h and user32.IsWindow(h):
        _last_game_hwnd = h
        return h

    return 0


def set_click_through(hwnd: int, enable: bool):
    """
    If enable=True: the window becomes click-through (clicks go straight to the SCUM game).
    If enable=False: the window can be grabbed, moved and resized.
    """
    try:
        current_style = GetWindowLongPtr(hwnd, GWL_EXSTYLE)
        if enable:
            new_style = current_style | WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            new_style = (current_style & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED
        SetWindowLongPtr(hwnd, GWL_EXSTYLE, new_style)
    except Exception as e:
        log.error("Failed to set click-through: %s", e)


def keep_on_top(hwnd: int):
    """
    Keeps the overlay window above the game (fullscreen borderless).
    """
    try:
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
    except Exception as e:
        log.error("keep_on_top failed: %s", e)


def force_foreground_window(hwnd: int):
    """
    Reliably activates a window and gives it keyboard input focus,
    even while the fullscreen SCUM game is active.
    Uses try...finally to prevent AttachThreadInput thread leaks.
    """
    try:
        cur_thread = kernel32.GetCurrentThreadId()
        fg_window = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_window, None) if fg_window else 0
        if fg_thread and fg_thread != cur_thread:
            try:
                user32.AttachThreadInput(cur_thread, fg_thread, True)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
            finally:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
        else:
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
    except Exception as e:
        log.error("force_foreground_window failed: %s", e)


def restore_game_focus(game_hwnd: int = 0):
    """
    Instantly returns focus and mouse to the SCUM game window (like NVIDIA / Steam overlay behavior).
    The player can move the mouse and play right away without an extra click on the game.
    """
    if not game_hwnd or not user32.IsWindow(game_hwnd):
        game_hwnd = get_last_game_hwnd()

    if not game_hwnd or not user32.IsWindow(game_hwnd):
        return

    try:
        # Lift Windows focus-change restrictions (simulates finishing a system key combo)
        user32.keybd_event(0x12, 0, 0x0002, 0)  # VK_MENU (Alt) up

        cur_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(game_hwnd, None)

        if fg_thread and fg_thread != cur_thread:
            try:
                user32.AttachThreadInput(cur_thread, fg_thread, True)
                user32.SetForegroundWindow(game_hwnd)
                user32.SetActiveWindow(game_hwnd)
                user32.SetFocus(game_hwnd)
            finally:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
        else:
            user32.SetForegroundWindow(game_hwnd)
            user32.SetActiveWindow(game_hwnd)
            user32.SetFocus(game_hwnd)
    except Exception as e:
        log.error("restore_game_focus failed: %s", e)


def is_scum_running(target_name: str = "scum") -> bool:
    """
    Checks whether the SCUM game process is running (SCUM.exe / SCUM-Win64-Shipping.exe etc.).
    """
    try:
        target = target_name.lower()
        pids = (wintypes.DWORD * 2048)()
        bytes_returned = wintypes.DWORD()
        if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(bytes_returned)):
            return False
        count = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
        for i in range(count):
            pid = pids[i]
            if pid == 0:
                continue
            h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h_proc:
                buf = ctypes.create_unicode_buffer(512)
                sz = wintypes.DWORD(512)
                if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(sz)):
                    name = os.path.basename(buf.value).lower()
                    # Skip ourselves: "SCUM_Chat_Translator.exe" also contains "scum"
                    if target in name and pid != os.getpid() and "translator" not in name:
                        kernel32.CloseHandle(h_proc)
                        return True
                kernel32.CloseHandle(h_proc)
        return False
    except Exception as e:
        log.error("is_scum_running failed: %s", e)
        return False


def is_game_foreground(target_name: str = "scum", allow_own_process: bool = True) -> bool:
    """
    Checks whether the SCUM game window is in the foreground (and not minimized to tray/taskbar),
    or our own input/settings window is.
    Saves the current SCUM window handle for later focus restore.
    """
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False

        # If our own window is active
        if allow_own_process and pid.value == os.getpid():
            return True

        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_proc:
            return False
        try:
            buf = ctypes.create_unicode_buffer(512)
            sz = wintypes.DWORD(512)
            if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(sz)):
                name = os.path.basename(buf.value).lower()
                if target_name.lower() in name:
                    if user32.IsIconic(hwnd):
                        return False
                    # Save the current SCUM game window handle
                    set_last_game_hwnd(hwnd)
                    return True
            return False
        finally:
            kernel32.CloseHandle(h_proc)
    except Exception as e:
        log.error("is_game_foreground failed: %s", e)
        return False
