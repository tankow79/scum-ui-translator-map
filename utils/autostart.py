import sys
import winreg
from typing import Optional

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "SCUM_Chat_Translator"

def set_autostart(enable: bool, exe_path: Optional[str] = None) -> bool:
    """
    Встановлює або видаляє автозапуск програми у HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    Це безпечно, не вимагає прав адміністратора (UAC) і підтримується Windows 10/11.
    """
    if exe_path is None:
        exe_path = sys.executable

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                # Додаємо лапки навколо шляху, щоб уникнути помилок із пробілами
                cmd = f'"{exe_path}"'
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"[Autostart] Помилка налаштування автозапуску: {e}")
        return False

def is_autostart_enabled() -> bool:
    """Перевіряє, чи активний автозапуск у реєстрі Windows."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
            val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False
