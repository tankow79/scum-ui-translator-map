"""The player's own position, taken from the clipboard: in SCUM, Ctrl+C copies ``{X= Y= Z=|P= Y= R=}``."""
import math
import time
from dataclasses import dataclass
from typing import Optional

from core.coordinate_parser import AL, FL, RL, SCUM_COORD_REGEX, YL


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float
    yaw: float            # degrees, 0 = towards +X, growing towards +Y (measured in the game)
    stamp: float          # time.time() when it was read


def in_world(x: float, y: float) -> bool:
    return RL - FL <= x <= RL and YL - AL <= y <= YL


def parse_position(text: str, now: Optional[float] = None) -> Optional[Position]:
    """The position block of a Ctrl+C copy, or None. The rotation part (``|P= Y= R=``) is what tells a position copy
    from a plain coordinate that someone wrote in the chat, so it is required."""
    if not isinstance(text, str) or len(text) > 400:
        return None
    match = SCUM_COORD_REGEX.search(text)
    if not match or match.group("py") is None:
        return None
    try:
        x, y, z, yaw = (float(match.group(k)) for k in ("x", "y", "z", "py"))
    except ValueError:
        return None
    if not all(math.isfinite(v) for v in (x, y, z, yaw)) or not in_world(x, y):
        return None
    return Position(x, y, z, yaw % 360.0, time.time() if now is None else now)
