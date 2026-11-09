import ctypes
from ctypes import wintypes
import os
import sys

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

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

# Визначаємо типи для 64-бітних покажчиків
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

# Збережений дескриптор вікна гри SCUM для миттєвого повернення фокусу
_last_game_hwnd: int = 0
_app_mutex_handle = None


def check_single_instance(mutex_name: str = "SCUM_Chat_Translator_Mutex_Unique") -> bool:
    """
    Захист від випадкового повторного запуску програми.
    Повертає True, якщо це єдиний екземпляр, або False, якщо програма вже працює.
    """
    global _app_mutex_handle
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _app_mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    return True


def set_last_game_hwnd(hwnd: int):
    """Зберегти дескриптор вікна гри SCUM."""
    global _last_game_hwnd
    if hwnd and user32.IsWindow(hwnd):
        _last_game_hwnd = hwnd


def get_last_game_hwnd() -> int:
    """Отримати останній активний дескриптор вікна SCUM або знайти його."""
    global _last_game_hwnd
    if _last_game_hwnd and user32.IsWindow(_last_game_hwnd):
        return _last_game_hwnd

    # Спроба знайти вікно Unreal Engine / SCUM напряму
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
    Якщо enable=True: вікно стає прозорим для кліків мишкою (кліки летять безпосередньо в гру SCUM).
    Якщо enable=False: вікно можна хапати мишкою, пересувати та змінювати розмір.
    """
    try:
        current_style = GetWindowLongPtr(hwnd, GWL_EXSTYLE)
        if enable:
            new_style = current_style | WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            new_style = (current_style & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED
        SetWindowLongPtr(hwnd, GWL_EXSTYLE, new_style)
    except Exception as e:
        print(f"[WinAPI] Помилка встановлення click-through: {e}")


def keep_on_top(hwnd: int):
    """
    Забезпечує перебування вікна оверлея поверх гри (fullscreen borderless).
    """
    try:
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
    except Exception as e:
        print(f"[WinAPI] Помилка keep_on_top: {e}")


def force_foreground_window(hwnd: int):
    """
    Надійно активує вікно та передає йому клавіатурний фокус введення,
    навіть коли активна повноекранна гра SCUM.
    Використовує try...finally для запобігання витоку потоків AttachThreadInput.
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
        print(f"[WinAPI] Помилка force_foreground_window: {e}")


def restore_game_focus(game_hwnd: int = 0):
    """
    Миттєво повертає фокус та мишу назад у вікно гри SCUM (аналог поведінки NVIDIA / Steam overlay).
    Гравець може одразу рухати мишкою та грати без додаткового кліку на екран гри.
    """
    if not game_hwnd or not user32.IsWindow(game_hwnd):
        game_hwnd = get_last_game_hwnd()

    if not game_hwnd or not user32.IsWindow(game_hwnd):
        return

    try:
        # Знімаємо обмеження зміни фокусу Windows (імітація завершення системної комбінації)
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
        print(f"[WinAPI] Помилка restore_game_focus: {e}")


def is_scum_running(target_name: str = "scum") -> bool:
    """
    Перевіряє, чи запущений процес гри SCUM (SCUM.exe / SCUM-Win64-Shipping.exe тощо).
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
                    if target in name:
                        kernel32.CloseHandle(h_proc)
                        return True
                kernel32.CloseHandle(h_proc)
        return False
    except Exception as e:
        print(f"[WinAPI] Помилка is_scum_running: {e}")
        return False


def is_game_foreground(target_name: str = "scum", allow_own_process: bool = True) -> bool:
    """
    Перевіряє, чи активне на передньому плані вікно гри SCUM (і не згорнуте в трей/панель),
    або наше власне вікно вводу/налаштувань.
    Зберігає актуальний дескриптор вікна SCUM для наступного повернення фокусу.
    """
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False

        # Якщо активне наше власне вікно
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
                    # Зберігаємо актуальний дескриптор вікна гри SCUM
                    set_last_game_hwnd(hwnd)
                    return True
            return False
        finally:
            kernel32.CloseHandle(h_proc)
    except Exception as e:
        print(f"[WinAPI] Помилка is_game_foreground: {e}")
        return False
