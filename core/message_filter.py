"""Chat message filtering: nickname blacklist and blocked-word list.

All behaviour is driven by config keys so every user can enable, disable and tune it:

    blacklist_nicknames        list[str] | str   players shown untranslated (original language)
    blacklist_words_enabled    bool              master switch for the word list
    blacklist_words            list[str] | str   blocked words / phrases
    blacklist_words_action     "mask" | "hide" | "no_translate"
    blacklist_words_whole_word bool              match whole words only
    blacklist_words_case_sensitive bool
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Mapping, Optional, Pattern, Tuple


class FilterAction(str, Enum):
    ALLOW = "allow"          # translate normally
    ORIGINAL = "original"    # show as-is, do not translate
    MASK = "mask"            # blocked words replaced by asterisks, then translated
    HIDE = "hide"            # drop the message completely


@dataclass(frozen=True)
class FilterResult:
    action: FilterAction
    message: str
    reason: str = ""


def split_list(raw: Any) -> List[str]:
    """Normalise a config value (list or comma/newline separated string) into a clean list."""
    items: List[str] = []
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, str):
                for part in re.split(r"[,\n;]", item):
                    part = part.strip()
                    if part:
                        items.append(part)
    return items


class ChatFilter:
    def __init__(self, config: Mapping[str, Any]):
        self._cfg = config
        self._pattern_key: Optional[Tuple] = None
        self._pattern: Optional[Pattern[str]] = None

    # ── nickname blacklist ───────────────────────────────────────────
    def is_nickname_blacklisted(self, sender: str) -> bool:
        blacklist = [b.lower() for b in split_list(self._cfg.get("blacklist_nicknames", []))]
        if not blacklist:
            return False
        sender_clean = sender.strip().lower()
        sender_no_tag = re.sub(r"^[\[\(].*?[\]\)]\s*", "", sender_clean).strip()
        sender_words = re.findall(r"\w+", sender_clean)
        for b in blacklist:
            if b in (sender_clean, sender_no_tag) or b in sender_words:
                return True
            if len(b) >= 3 and b in sender_clean:
                return True
        return False

    # ── word blacklist ───────────────────────────────────────────────
    def _word_pattern(self) -> Optional[Pattern[str]]:
        if not self._cfg.get("blacklist_words_enabled", False):
            return None
        words = split_list(self._cfg.get("blacklist_words", []))
        if not words:
            return None
        whole = bool(self._cfg.get("blacklist_words_whole_word", True))
        case = bool(self._cfg.get("blacklist_words_case_sensitive", False))
        key = (tuple(words), whole, case)
        if key != self._pattern_key:
            alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
            body = rf"(?<!\w)(?:{alternatives})(?!\w)" if whole else f"(?:{alternatives})"
            self._pattern = re.compile(body, 0 if case else re.IGNORECASE)
            self._pattern_key = key
        return self._pattern

    def contains_blocked_word(self, message: str) -> bool:
        pattern = self._word_pattern()
        return bool(pattern and pattern.search(message))

    @staticmethod
    def _mask(match: "re.Match[str]") -> str:
        return "*" * len(match.group(0))

    # ── public API ───────────────────────────────────────────────────
    def evaluate(self, sender: str, message: str) -> FilterResult:
        if self.is_nickname_blacklisted(sender):
            return FilterResult(FilterAction.ORIGINAL, message, "nickname")

        pattern = self._word_pattern()
        if pattern and pattern.search(message):
            action = self._cfg.get("blacklist_words_action", "mask")
            if action == "hide":
                return FilterResult(FilterAction.HIDE, message, "word")
            if action == "no_translate":
                return FilterResult(FilterAction.ORIGINAL, message, "word")
            return FilterResult(FilterAction.MASK, pattern.sub(self._mask, message), "word")

        return FilterResult(FilterAction.ALLOW, message)
