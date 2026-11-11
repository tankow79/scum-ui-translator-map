"""
Модуль інформації про версію та конфігурацію репозиторію SCUM Chat Translator.
"""

from typing import Tuple

__version__ = "2.0.0"
__app_name__ = "SCUM Tactical Map & Real-Time Chat Translator"
GITHUB_OWNER = "tankow79"
GITHUB_REPO = "scum-ui-translator-map"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_ALL_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def parse_version(ver_str: str) -> Tuple[int, ...]:
    """
    Парсить рядок версії (наприклад 'v1.2.3', '1.0.0', 'v2.1') у кортеж цілих чисел для порівняння.
    """
    cleaned = ver_str.strip().lstrip("vV")
    # Відкидаємо можливі суфікси на кшталт -beta, -rc1
    main_part = cleaned.split("-")[0].split("+")[0]
    parts = []
    for part in main_part.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    # Гарантуємо мінімум 3 частини (major, minor, patch)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_version_newer(current_ver: str, remote_ver: str) -> bool:
    """
    Повертає True, якщо remote_ver строго новіша за current_ver.
    """
    try:
        return parse_version(remote_ver) > parse_version(current_ver)
    except Exception:
        return False
