"""Lightweight offline language detection used to skip needless translation calls.

Only scripts that can be recognised reliably are handled; Latin-script text returns
``None`` (unknown) so the translation backend decides.
"""

import re
from typing import Iterable, Optional

_URL_RE = re.compile(r"https?://\S+")
_COORD_RE = re.compile(r"\{X=.*?\}", re.DOTALL)
_UK_ONLY = set("іїєґІЇЄҐ")
_RU_ONLY = set("ыэъёЫЭЪЁ")


def base_lang(code: str) -> str:
    """'zh-CN' -> 'zh', 'UK' -> 'uk'."""
    return (code or "").strip().lower().replace("_", "-").split("-")[0]


def _letters(text: str) -> str:
    cleaned = _COORD_RE.sub(" ", _URL_RE.sub(" ", text))
    return "".join(ch for ch in cleaned if ch.isalpha())


def quick_detect(text: str, min_letters: int = 3) -> Optional[str]:
    """Return a base language code when the script makes it obvious, otherwise ``None``."""
    letters = _letters(text)
    if len(letters) < max(1, min_letters):
        return None

    counts = {"cyr": 0, "han": 0, "kana": 0, "hangul": 0, "arabic": 0, "greek": 0, "hebrew": 0, "thai": 0, "other": 0}
    for ch in letters:
        o = ord(ch)
        if 0x0400 <= o <= 0x052F:
            counts["cyr"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["han"] += 1
        elif 0x3040 <= o <= 0x30FF:
            counts["kana"] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            counts["hangul"] += 1
        elif 0x0600 <= o <= 0x06FF:
            counts["arabic"] += 1
        elif 0x0370 <= o <= 0x03FF:
            counts["greek"] += 1
        elif 0x0590 <= o <= 0x05FF:
            counts["hebrew"] += 1
        elif 0x0E00 <= o <= 0x0E7F:
            counts["thai"] += 1
        else:
            counts["other"] += 1

    total = len(letters)
    script, top = max(counts.items(), key=lambda kv: kv[1])
    if script == "other" or top / total < 0.7:
        # Japanese mixes kana and han; treat any kana presence as Japanese.
        if counts["kana"] and (counts["kana"] + counts["han"]) / total >= 0.7:
            return "ja"
        return None

    if script == "cyr":
        chars = set(letters)
        if chars & _UK_ONLY:
            return "uk"
        if chars & _RU_ONLY:
            return "ru"
        return None  # ru/uk/bg/sr are ambiguous without special letters
    if script == "han":
        return "zh"
    if script == "kana":
        return "ja"
    return {"hangul": "ko", "arabic": "ar", "greek": "el", "hebrew": "he", "thai": "th"}[script]


def is_same_language(detected: Optional[str], targets: Iterable[str]) -> bool:
    if not detected:
        return False
    d = base_lang(detected)
    return any(d == base_lang(t) for t in targets if t)
