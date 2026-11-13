"""Chat text style matching the in-game SCUM chat.

Colours were sampled from in-game screenshots: squad chat is lime green, global chat is cyan-blue
(local chat is white, but the log does not say which channel a message came from, so the overlay
cannot tell them apart). Server messages stay yellow.
"""

import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

SQUAD_COLOR = "#c2f800"
DEFAULT_COLOR = "#00e6f3"  # global chat
LOCAL_COLOR = "#fdfdfd"  # local chat (not detectable from the log)
SERVER_COLOR = "#ffca00"

# In-game chat font is a narrow DIN-style sans; Bahnschrift ships with Windows 10/11
GAME_FONT_STACK = "'Bahnschrift SemiBold SemiCondensed','Bahnschrift','Arial Narrow','Segoe UI',sans-serif"
DEFAULT_FONT_SIZE = 22

_HEX = r"#?([0-9a-fA-F]{6})"
# <color=#ff8800>…</color>, [color=#ff8800]…[/color], <font color="#ff8800">…</font>
_COLOR_TAG_RE = re.compile(
    r"""(?:<\s*(?:color\s*=\s*|font\s+color\s*=\s*)["']?""" + _HEX + r"""["']?\s*>)"""
    r"""|(?:\[\s*color\s*=\s*""" + _HEX + r"""\s*\])""",
    re.IGNORECASE,
)
_ANY_TAG_RE = re.compile(r"</?\s*(?:color|font)\b[^<>]{0,60}>|\[\s*color\s*=[^\]]{0,40}\]|\[/color\]", re.IGNORECASE)


def parse_nick_list(value) -> List[str]:
    """Nicknames from a config value: a list or a comma/semicolon separated string."""
    if isinstance(value, str):
        value = re.split(r"[,;]", value)
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def is_squad_member(sender: str, squad_nicks: Iterable[str]) -> bool:
    key = (sender or "").strip().casefold()
    return bool(key) and any(key == n.casefold() for n in squad_nicks)


def extract_text_color(text: str) -> Tuple[str, Optional[str]]:
    """Return (text without colour markup, '#rrggbb' of the first colour tag or None)."""
    m = _COLOR_TAG_RE.search(text or "")
    color = None
    if m:
        color = "#" + (m.group(1) or m.group(2)).lower()
    return _ANY_TAG_RE.sub("", text or ""), color


def pick_color(sender: str, squad_nicks: Iterable[str], explicit: Optional[str] = None, server: bool = False) -> str:
    """Colour for a message: explicit colour in the text, else squad green, else server yellow, else blue."""
    if explicit:
        return explicit
    if is_squad_member(sender, squad_nicks):
        return SQUAD_COLOR
    return SERVER_COLOR if server else DEFAULT_COLOR


def log_time_to_local(raw: str) -> str:
    """'2026.11.13-01.54.49' (UTC, as written in SCUM.log) -> 'dd/mm/YYYY - HH:MM:SS' in local time."""
    try:
        dt = datetime.strptime(raw, "%Y.%m.%d-%H.%M.%S").replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        return raw
    return dt.strftime("%d/%m/%Y - %H:%M:%S")


def game_timestamp(time_str: str, now: Optional[datetime] = None) -> str:
    """Timestamp as the in-game chat prints it: 'dd/mm/YYYY - HH:MM:SS'.

    Accepts a full stamp (returned unchanged) or a bare 'HH:MM:SS', which is dated today, or
    yesterday when that time of day is still in the future.
    """
    if "/" in time_str:
        return time_str
    now = now or datetime.now()
    try:
        t = datetime.strptime(time_str, "%H:%M:%S").time()
    except ValueError:
        return time_str
    day = now.date()
    if t > now.time():
        day = day.fromordinal(day.toordinal() - 1)
    return f"{day.strftime('%d/%m/%Y')} - {time_str}"
