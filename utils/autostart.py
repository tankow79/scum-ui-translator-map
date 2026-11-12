import logging
import sys
import winreg
from typing import Optional

log = logging.getLogger("scum.autostart")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "SCUM_Chat_Translator"

def set_autostart(enable: bool, exe_path: Optional[str] = None) -> bool:
    """
    Adds or removes app autostart in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    Safe, needs no administrator rights (UAC) and is supported on Windows 10/11.
    """
    if exe_path is None:
        exe_path = sys.executable

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                # Quote the path to avoid problems with spaces
                cmd = f'"{exe_path}"'
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        log.error("Failed to configure autostart: %s", e)
        return False

def is_autostart_enabled() -> bool:
    """Checks whether autostart is active in the Windows registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
            val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False
