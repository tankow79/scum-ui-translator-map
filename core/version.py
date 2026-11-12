"""
Version and repository configuration info for SCUM Chat Translator.
"""

from typing import Tuple

__version__ = "2.2.0"
__app_name__ = "SCUM Tactical Map & Real-Time Chat Translator"
GITHUB_OWNER = "tankow79"
GITHUB_REPO = "scum-ui-translator-map"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_ALL_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def parse_version(ver_str: str) -> Tuple[int, ...]:
    """
    Parses a version string (e.g. 'v1.2.3', '1.0.0', 'v2.1') into a tuple of ints for comparison.
    """
    cleaned = ver_str.strip().lstrip("vV")
    # Drop possible suffixes like -beta, -rc1
    main_part = cleaned.split("-")[0].split("+")[0]
    parts = []
    for part in main_part.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    # Ensure at least 3 parts (major, minor, patch)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_version_newer(current_ver: str, remote_ver: str) -> bool:
    """
    Returns True if remote_ver is strictly newer than current_ver.
    """
    try:
        return parse_version(remote_ver) > parse_version(current_ver)
    except Exception:
        return False
