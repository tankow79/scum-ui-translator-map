import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

# Regex for finding SCUM coordinates in text
# Example: {X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}
# Or short form: {X=174468.797 Y=345933.000 Z=34103.105}
SCUM_COORD_REGEX = re.compile(
    r'\{X=(?P<x>[-0-9\.]+)\s+Y=(?P<y>[-0-9\.]+)\s+Z=(?P<z>[-0-9\.]+)(?:\|P=(?P<p>[-0-9\.]+)\s+Y=(?P<py>[-0-9\.]+)\s+R=(?P<r>[-0-9\.]+))?\}',
    re.IGNORECASE
)

# SCUM world bounds (matching scum-map.com math)
RL = 619200.0
FL = 1524000.0
YL = 619199.9375
AL = 1523999.9375
NL = 320.0


def convert_scum_to_norm(x: float, y: float) -> Tuple[float, float]:
    """
    Converts SCUM game coordinates (X, Y in cm) to normalized map coordinates (0.0 .. 1.0).
    (0.0, 0.0) is the top-left corner (Sector D4).
    (1.0, 1.0) is the bottom-right corner (Sector Z0).
    """
    norm_x = (RL - x) / FL
    norm_y = (YL - y) / AL
    # Clamp to 0.0 .. 1.0 (in case the player is outside the map)
    norm_x = max(0.0, min(1.0, norm_x))
    norm_y = max(0.0, min(1.0, norm_y))
    return norm_x, norm_y


def convert_norm_to_scum(norm_x: float, norm_y: float) -> Tuple[float, float]:
    """
    Reverse conversion from normalized map coordinates (0.0 .. 1.0) to SCUM game coordinates.
    """
    x = RL - norm_x * FL
    y = YL - norm_y * AL
    return x, y


def get_sector_info(norm_x: float, norm_y: float) -> Tuple[str, str]:
    """
    Determines the game sector (D0-D4, C0-C4, B0-B4, A0-A4, Z0-Z4)
    and keypad (k1..k9) from normalized map coordinates (0.0..1.0).
    Returns: (sector, keypad), e.g. ("D3", "k2")
    """
    # 1. Row: D, C, B, A, Z (vertically, north to south)
    row_idx = int(norm_y * 5.0)
    row_idx = max(0, min(4, row_idx))
    rows = ["D", "C", "B", "A", "Z"]
    sector_letter = rows[row_idx]

    # 2. Column: 4, 3, 2, 1, 0 (horizontally, west to east in SCUM coordinates)
    col_idx = int(norm_x * 5.0)
    col_idx = max(0, min(4, col_idx))
    cols = ["4", "3", "2", "1", "0"]
    sector_number = cols[col_idx]

    sector = f"{sector_letter}{sector_number}"

    # 3. Keypad (1..9 inside each 3x3 sector)
    # n_in_sec (0..2), m_in_sec (0..2)
    sub_col = int((norm_x * 15.0) % 3.0)
    sub_row = int((norm_y * 15.0) % 3.0)
    sub_col = max(0, min(2, sub_col))
    sub_row = max(0, min(2, sub_row))

    # Standard SCUM numpad:
    # 7 8 9 (top row: sub_row=0)
    # 4 5 6 (middle row: sub_row=1)
    # 1 2 3 (bottom row: sub_row=2)
    keypad_matrix = [
        ["k7", "k8", "k9"],
        ["k4", "k5", "k6"],
        ["k1", "k2", "k3"]
    ]
    keypad = keypad_matrix[sub_row][sub_col]

    return sector, keypad


# ─────────────────────────────────────────────────────────────
# Point categories (marker type, emoji, default color and keywords)
# ─────────────────────────────────────────────────────────────
POINT_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "default": {
        "id": "default",
        "name": "Просто мітка",
        "emoji": "📍",
        "default_color": "#38bdf8",
        "keywords": ["метка", "точка", "мітка", "point", "marker"]
    },
    "base": {
        "id": "base",
        "name": "База",
        "emoji": "🏠",
        "default_color": "#a855f7",
        "keywords": ["база", "баз", "base", "хата", "хат", "дім", "дом", "кемп", "camp"]
    },
    "car": {
        "id": "car",
        "name": "Машина",
        "emoji": "🚗",
        "default_color": "#f59e0b",
        "keywords": ["машина", "машин", "авто", "тачка", "тачк", "car", "suv", "truck", "пікап", "пикап"]
    },
    "plane": {
        "id": "plane",
        "name": "Літак",
        "emoji": "✈️",
        "default_color": "#0ea5e9",
        "keywords": ["літак", "самолет", "самольот", "plane", "airplane", "кукурузник", "авіа"]
    },
    "moto": {
        "id": "moto",
        "name": "Мотоцикл",
        "emoji": "🏍️",
        "default_color": "#f97316",
        "keywords": ["мотоцик", "мотоцикл", "мото", "байк", "bike", "motorcycle"]
    },
    "boat": {
        "id": "boat",
        "name": "Лодка",
        "emoji": "🚤",
        "default_color": "#06b6d4",
        "keywords": ["лодка", "лодк", "човен", "чов", "катер", "boat", "яхта", "яхт"]
    },
    "cache": {
        "id": "cache",
        "name": "Схрон",
        "emoji": "📦",
        "default_color": "#10b981",
        "keywords": ["схрон", "сундук", "лут", "ящик", "заначка", "заначк", "cache", "loot", "chest"]
    }
}


def detect_category_from_name(name: str) -> str:
    """
    Automatically detects the point category from its name (chat message or point name).
    If nothing matches, returns 'default' (plain marker).
    """
    if not name or name.strip().lower() in ("none", ""):
        return "default"
    low = name.strip().lower()
    for cat_id, data in POINT_CATEGORIES.items():
        if cat_id == "default":
            continue
        for kw in data["keywords"]:
            if kw in low:
                return cat_id
    return "default"


def get_category_info(category_id: Optional[str]) -> Dict[str, Any]:
    """Returns category metadata (name, emoji, color)."""
    if not category_id or category_id not in POINT_CATEGORIES:
        return POINT_CATEGORIES["default"]
    return POINT_CATEGORIES[category_id]


@dataclass
class MapPoint:
    id: str
    name: str
    date_time: str
    raw_coord: str
    x: float
    y: float
    z: float
    sector: str
    keypad: str
    norm_x: float
    norm_y: float
    created_timestamp: float
    color: str = "#38bdf8"
    category: str = "default"
    players: str = ""

    def full_sector_name(self) -> str:
        return f"{self.sector} ({self.keypad})"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MapPoint":
        name = data.get("name", "None")
        cat = data.get("category")
        if not cat:
            cat = detect_category_from_name(name)
        cat_info = get_category_info(cat)
        color = data.get("color") or cat_info["default_color"]

        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=name,
            date_time=data.get("date_time", ""),
            raw_coord=data.get("raw_coord", ""),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            z=float(data.get("z", 0.0)),
            sector=data.get("sector", "??"),
            keypad=data.get("keypad", "k5"),
            norm_x=float(data.get("norm_x", 0.0)),
            norm_y=float(data.get("norm_y", 0.0)),
            created_timestamp=float(data.get("created_timestamp", time.time())),
            color=color,
            category=cat,
            players=data.get("players", "")
        )


def extract_point_name(text: str, coord_match: re.Match) -> str:
    """
    Extracts the point name from a message.
    Examples:
      'машина{X=...}' -> 'машина'
      '{X=...} машина' -> 'машина'
      '(машина{X=...})' -> 'машина'
      '{X=...}' -> 'None'
    """
    start, end = coord_match.span()
    label = text[:start] + " " + text[end:]
    # Strip quotes, brackets, colons and extra whitespace
    label = label.strip("()[]{} \t\r\n:;,-\"\'")
    return label if label else "None"


def parse_chat_coordinate(text: str, time_str: Optional[str] = None) -> Optional[MapPoint]:
    """
    Searches a message string for SCUM coordinates.
    If found, creates and returns a MapPoint object.
    """
    match = SCUM_COORD_REGEX.search(text)
    if not match:
        return None

    raw_coord = match.group(0)
    x = float(match.group("x"))
    y = float(match.group("y"))
    z = float(match.group("z"))

    name = extract_point_name(text, match)
    category = detect_category_from_name(name)
    cat_info = get_category_info(category)
    default_color = cat_info["default_color"]

    norm_x, norm_y = convert_scum_to_norm(x, y)
    sector, keypad = get_sector_info(norm_x, norm_y)

    from datetime import datetime
    if not time_str:
        dt_str = datetime.now().strftime("%d.%m %H:%M:%S")
    else:
        # If time_str contains only a time like "12:30:45", prepend today's date
        if len(time_str) <= 8 and ":" in time_str:
            dt_str = f"{datetime.now().strftime('%d.%m')} {time_str}"
        else:
            dt_str = time_str

    point_id = uuid.uuid4().hex[:10]

    return MapPoint(
        id=point_id,
        name=name,
        date_time=dt_str,
        raw_coord=raw_coord,
        x=x,
        y=y,
        z=z,
        sector=sector,
        keypad=keypad,
        norm_x=norm_x,
        norm_y=norm_y,
        created_timestamp=time.time(),
        color=default_color,
        category=category,
        players=""
    )
