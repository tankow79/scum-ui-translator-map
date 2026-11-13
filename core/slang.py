"""Chat abbreviations and gaming slang (GG, GGNT, BRB, AFK, KOS ...) and their full meaning.

The abbreviation table holds the English meaning; the translator turns that into any chat language. For the
most common ones there are also ready Ukrainian phrases, so the typical ``gg`` / ``thx`` / ``brb`` messages are
translated instantly and without the network.

Two tiers keep real words safe: STRONG abbreviations are expanded anywhere in a message, WEAK ones (``ty``, ``u``,
``np``, ``dc`` ... which are also ordinary words in Polish, Czech, Russian and so on) only when the whole message
consists of abbreviations, for example ``ty gg``.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MODE_TRANSLATE = "translate"   # the full meaning, translated into the chat language (default)
MODE_EXPAND = "expand"         # the full meaning, left in English
MODE_KEEP = "keep"             # abbreviations are left exactly as typed
MODES = (MODE_TRANSLATE, MODE_EXPAND, MODE_KEEP)


def normalize_mode(value: object) -> str:
    return value if value in MODES else MODE_TRANSLATE


# ── English meanings ─────────────────────────────────────────────────────────────────────────────────────────
STRONG: Dict[str, str] = {
    # good manners in a match
    "gg": "good game", "ggs": "good games", "ggwp": "good game, well played", "ggnt": "good game, nice try",
    "ggez": "good game, easy", "ggwpez": "good game, well played, easy", "gghf": "good game, have fun",
    "wp": "well played", "gj": "good job", "nj": "nice job", "ns": "nice shot", "nt": "nice try",
    "ng": "nice game", "gl": "good luck", "glhf": "good luck, have fun", "hf": "have fun",
    "hfgl": "have fun, good luck", "gla": "good luck all", "ez": "easy", "ezpz": "easy peasy",
    "gz": "congratulations", "grats": "congratulations", "gratz": "congratulations", "congrats": "congratulations",
    "rip": "rest in peace", "wb": "welcome back", "hbd": "happy birthday", "pwned": "owned", "rekt": "wrecked",
    "gud": "good", "mbmb": "my bad, my bad",
    # coming and going
    "gn": "good night", "gnite": "good night", "gnight": "good night", "gtg": "got to go", "g2g": "got to go",
    "brb": "be right back", "bbl": "be back later", "bbs": "be back soon", "bbiab": "be back in a bit",
    "bak": "back at keyboard", "afk": "away from keyboard", "ttyl": "talk to you later", "cya": "see you",
    "cul8r": "see you later", "l8r": "later", "omw": "on my way", "eta": "estimated time of arrival",
    # thanks and politeness
    "thx": "thanks", "thnx": "thanks", "thanx": "thanks", "tnx": "thanks", "tyvm": "thank you very much",
    "tysm": "thank you so much", "pls": "please", "plz": "please", "plox": "please", "pliz": "please",
    "sry": "sorry", "soz": "sorry",
    # everyday chat
    "idk": "I don't know", "idc": "I don't care", "idgaf": "I don't give a f***", "ikr": "I know, right",
    "idek": "I don't even know", "idrk": "I don't really know", "imo": "in my opinion",
    "imho": "in my humble opinion", "tbh": "to be honest", "tbf": "to be fair", "ngl": "not gonna lie",
    "frfr": "for real, for real", "asap": "as soon as possible", "fyi": "for your information",
    "btw": "by the way", "afaik": "as far as I know", "iirc": "if I remember correctly", "irl": "in real life",
    "ofc": "of course", "obv": "obviously", "prob": "probably", "probs": "probably", "tho": "though",
    "thru": "through", "w/o": "without", "b/c": "because", "cuz": "because", "coz": "because",
    "ppl": "people", "abt": "about", "bday": "birthday", "rly": "really", "rlly": "really", "srsly": "seriously",
    "b4": "before", "gr8": "great", "2day": "today", "2moro": "tomorrow", "2nite": "tonight", "tmr": "tomorrow",
    "tmrw": "tomorrow", "4u": "for you", "kk": "okay, okay", "nvm": "never mind", "jk": "just kidding",
    "smh": "shaking my head", "tmi": "too much information", "yolo": "you only live once", "aka": "also known as",
    "ily": "I love you", "luv": "love",
    "wyd": "what are you doing", "wbu": "what about you", "hbu": "how about you", "hru": "how are you",
    "hmu": "hit me up", "sup": "what's up", "wassup": "what's up", "wazzup": "what's up",
    # laughter and swearing (kept as polite as the original allows)
    "lol": "laughing out loud", "lmao": "laughing my a** off", "lmfao": "laughing my f***ing a** off",
    "rofl": "rolling on the floor laughing", "xd": "laughing", "omg": "oh my god", "omfg": "oh my f***ing god",
    "wtf": "what the f***", "wth": "what the heck", "ffs": "for f***'s sake", "stfu": "shut the f*** up",
    "gtfo": "get the f*** out",
    # games and SCUM
    "ign": "in-game name", "ffa": "free for all", "pvp": "player versus player", "pve": "player versus environment",
    "kos": "kill on sight", "kd": "kill/death ratio", "dmg": "damage", "dps": "damage per second",
    "aoe": "area of effect", "xp": "experience points", "lvl": "level", "inv": "inventory", "dced": "disconnected",
    "fps": "frames per second", "rng": "random luck", "gank": "ambush", "hax": "hacks", "sqd": "squad",
    "lfg": "looking for group", "lfm": "looking for members", "wts": "want to sell", "wtb": "want to buy",
    "wtt": "want to trade",
    # the same abbreviations typed on a Cyrillic keyboard layout or in Russian / Ukrainian chat
    "гг": "good game", "ггвп": "good game, well played", "ггизи": "good game, easy", "глхф": "good luck, have fun",
    "афк": "away from keyboard", "брб": "be right back", "спс": "thanks", "пжлст": "please", "пжл": "please",
    "плз": "please", "плиз": "please", "сорян": "sorry", "имхо": "in my humble opinion", "кст": "by the way",
    "хз": "I don't know", "нзч": "you're welcome", "лол": "laughing out loud", "кек": "laughing",
    "рип": "rest in peace", "изи": "easy", "гз": "congratulations",
}

# Ordinary words in other languages (ty = "you" in Polish/Czech, u = "at" in Polish, np = "for example" ...):
# expanded only when the entire message is made of abbreviations.
WEAK: Dict[str, str] = {
    "ty": "thank you", "np": "no problem", "yw": "you're welcome", "u": "you", "ur": "your", "r": "are",
    "y": "why", "k": "okay", "ik": "I know", "fr": "for real", "rn": "right now", "atm": "at the moment",
    "def": "definitely", "bc": "because", "dw": "don't worry", "mb": "my bad", "nm": "not much", "ig": "I guess",
    "gm": "good morning", "cu": "see you", "otw": "on the way", "sec": "one second", "pm": "private message",
    "hp": "health points", "cd": "cooldown", "dc": "disconnected", "op": "overpowered", "tk": "team kill",
    "ff": "friendly fire", "sq": "squad", "tp": "teleport", "lf": "looking for", "gd": "good",
    "вп": "well played", "нт": "nice try", "гл": "good luck", "пж": "please", "мб": "maybe", "сек": "one second",
}

# ── ready Ukrainian phrases (no network needed) ──────────────────────────────────────────────────────────────
UK: Dict[str, str] = {
    "gg": "гарна гра", "ggs": "гарні ігри", "ggwp": "гарна гра, добре зіграно", "ggnt": "гарна гра, непогана спроба",
    "ggez": "гарна гра, легко", "wp": "добре зіграно", "gj": "гарна робота", "nj": "гарна робота",
    "ns": "гарний постріл", "nt": "непогана спроба", "ng": "гарна гра", "gl": "удачі",
    "glhf": "удачі та приємної гри", "hf": "приємної гри", "hfgl": "приємної гри, удачі", "gla": "удачі всім",
    "ez": "легко", "ezpz": "легко-легко", "gz": "вітаю", "grats": "вітаю", "gratz": "вітаю", "congrats": "вітаю",
    "rip": "спочивай з миром", "wb": "з поверненням", "hbd": "з днем народження", "pwned": "розгромлено",
    "rekt": "розгромлено", "gud": "добре", "gn": "на добраніч", "gnite": "на добраніч", "gnight": "на добраніч",
    "gtg": "мені час іти", "g2g": "мені час іти", "brb": "зараз повернусь", "bbl": "повернусь пізніше",
    "bbs": "скоро повернусь", "bbiab": "повернусь за хвилинку", "bak": "повернувся до клавіатури",
    "afk": "відійшов від клавіатури", "ttyl": "поговоримо пізніше", "cya": "бувай", "cul8r": "до зустрічі пізніше",
    "l8r": "пізніше", "omw": "уже в дорозі", "eta": "орієнтовний час прибуття", "thx": "дякую", "thnx": "дякую",
    "thanx": "дякую", "tnx": "дякую", "tyvm": "щиро дякую", "tysm": "дуже дякую", "pls": "будь ласка",
    "plz": "будь ласка", "plox": "будь ласка", "pliz": "будь ласка", "sry": "вибач", "soz": "вибач",
    "idk": "не знаю", "idc": "мені байдуже", "ikr": "знаю, правда ж", "idek": "я навіть не знаю",
    "idrk": "точно не знаю", "imo": "на мою думку", "imho": "на мою скромну думку", "tbh": "чесно кажучи",
    "tbf": "якщо чесно", "ngl": "не буду брехати", "frfr": "справді, справді", "asap": "якнайшвидше",
    "fyi": "до відома", "btw": "до речі", "afaik": "наскільки я знаю", "iirc": "якщо я правильно пам'ятаю",
    "irl": "у реальному житті", "ofc": "звісно", "obv": "очевидно", "prob": "мабуть", "probs": "мабуть",
    "tho": "хоча", "thru": "крізь", "w/o": "без", "b/c": "бо", "cuz": "бо", "coz": "бо", "ppl": "люди",
    "abt": "про", "bday": "день народження", "rly": "справді", "rlly": "справді", "srsly": "серйозно",
    "b4": "раніше", "gr8": "чудово", "2day": "сьогодні", "2moro": "завтра", "2nite": "сьогодні ввечері",
    "tmr": "завтра", "tmrw": "завтра", "4u": "для тебе", "kk": "окей, окей", "nvm": "забудь, не зважай",
    "jk": "жартую", "smh": "хитаю головою", "tmi": "забагато інформації", "yolo": "живемо один раз",
    "aka": "він же", "ily": "я тебе люблю", "luv": "люблю", "wyd": "що робиш", "wbu": "а ти", "hbu": "а ти як",
    "hru": "як справи", "hmu": "напиши мені", "sup": "як справи", "wassup": "як справи", "wazzup": "як справи",
    "lol": "ха-ха", "lmao": "ржу не можу", "lmfao": "ржу не можу", "rofl": "валяюся від сміху", "xd": "ха-ха",
    "omg": "боже мій", "omfg": "боже мій", "wtf": "що за чортівня", "wth": "що це таке", "ffs": "та щоб воно все",
    "stfu": "замовкни", "gtfo": "геть звідси", "ign": "нік у грі", "ffa": "кожен сам за себе",
    "pvp": "гравець проти гравця", "pve": "гравець проти середовища", "kos": "вбивати на місці",
    "kd": "співвідношення вбивств і смертей", "dmg": "шкода", "dps": "шкода за секунду", "aoe": "площа ураження",
    "xp": "досвід", "lvl": "рівень", "inv": "інвентар", "dced": "відключився", "fps": "кадри за секунду",
    "rng": "удача", "gank": "засідка", "hax": "чити", "sqd": "загін", "lfg": "шукаю групу",
    "lfm": "шукаю учасників", "wts": "продам", "wtb": "куплю", "wtt": "обміняю", "idgaf": "мені глибоко байдуже",
    "mbmb": "моя вина, моя вина",
    "гг": "гарна гра", "ггвп": "гарна гра, добре зіграно", "ггизи": "гарна гра, легко", "глхф": "удачі та приємної гри",
    "афк": "відійшов від клавіатури", "брб": "зараз повернусь", "спс": "дякую", "пжлст": "будь ласка",
    "пжл": "будь ласка", "плз": "будь ласка", "плиз": "будь ласка", "сорян": "вибач", "имхо": "на мою скромну думку",
    "кст": "до речі", "хз": "не знаю", "нзч": "будь ласка", "лол": "ха-ха", "кек": "ха-ха", "рип": "спочивай з миром",
    "изи": "легко", "гз": "вітаю",
    # weak ones
    "ty": "дякую", "np": "без проблем", "yw": "будь ласка", "u": "ти", "ur": "твій", "r": "є", "y": "чому",
    "k": "окей", "ik": "я знаю", "fr": "справді", "rn": "зараз", "atm": "наразі", "def": "однозначно",
    "bc": "бо", "dw": "не хвилюйся", "mb": "моя вина", "nm": "нічого особливого", "ig": "мабуть",
    "gm": "доброго ранку", "cu": "бачимось", "otw": "уже в дорозі", "sec": "секунду", "pm": "особисте повідомлення",
    "hp": "здоров'я", "cd": "перезарядка", "dc": "відключився", "op": "занадто сильне", "tk": "вбивство свого",
    "ff": "вогонь по своїх", "sq": "загін", "tp": "телепорт", "lf": "шукаю", "gd": "добре",
    "вп": "добре зіграно", "нт": "непогана спроба", "гл": "удачі", "пж": "будь ласка", "мб": "можливо",
    "сек": "секунду",
}

# ── more abbreviations: texting, informal speech, streaming, SCUM and survival-game terms ────────────────────
STRONG.update({
    "aight": "all right", "cba": "can't be bothered", "eli5": "explain like I'm five", "ftw": "for the win",
    "fwiw": "for what it's worth", "icymi": "in case you missed it", "idts": "I don't think so", "iono": "I don't know",
    "jw": "just wondering", "lmk": "let me know", "nbd": "no big deal", "nvr": "never", "oic": "oh I see",
    "pov": "point of view", "smth": "something", "sum1": "someone", "tba": "to be announced", "tbc": "to be continued",
    "tbd": "to be determined", "ttys": "talk to you soon", "u2": "you too", "w8": "wait", "w84me": "wait for me",
    "wat": "what", "wut": "what", "yea": "yes", "yeh": "yes", "yup": "yes", "nope": "no", "nah": "no",
    "yknow": "you know", "ymmv": "your mileage may vary", "cmon": "come on", "dunno": "don't know", "kinda": "kind of",
    "sorta": "sort of", "gotcha": "got you", "tryna": "trying to", "lemme": "let me", "gimme": "give me",
    "wanna": "want to", "gonna": "going to", "gotta": "got to", "lates": "see you later", "ttfn": "ta-ta for now",
    "hny": "happy new year", "xmas": "Christmas", "gc": "good call", "gp": "good play", "gw": "good work",
    "ragequit": "quit in anger", "pog": "awesome", "poggers": "awesome", "lul": "laughing", "kekw": "laughing",
    "omegalul": "laughing hard", "ult": "ultimate", "ttk": "time to kill", "mre": "meal ready to eat",
    "rpg": "rocket-propelled grenade", "hud": "heads-up display", "fov": "field of view",
    "fpp": "first-person perspective", "tpp": "third-person perspective", "npc": "non-player character",
    "dlc": "downloadable content", "wip": "work in progress", "srv": "server", "hq": "headquarters",
    "poi": "point of interest", "wpn": "weapon", "wpns": "weapons", "coord": "coordinates", "coords": "coordinates",
    "obo": "or best offer", "bbq": "barbecue", "tyvm": "thank you very much", "ggwpnt": "good game, well played, nice try",
    "ggnore": "good game, no report", "gg2": "good game too", "gl2": "good luck too", "hf2": "have fun too",
    "wb2": "welcome back too", "ily2": "I love you too", "gnn": "good night", "gm2": "good morning too",
    "mrc": "my respect", "rspct": "respect", "tyfp": "thank you for playing",
    "tyfh": "thank you for the help", "tyfg": "thank you for the game", "tyfl": "thank you for the loot",
    "ggbg": "good game, bad game", "gs": "good shot", "gks": "good kill",
    # Russian / Ukrainian chat typed in Cyrillic
    "лфг": "looking for group", "лвл": "level", "пвп": "player versus player", "пве": "player versus environment",
    "рофл": "rolling on the floor laughing", "омг": "oh my god", "втф": "what the f***", "пасиб": "thanks",
    "пасибо": "thanks", "спасиб": "thanks", "сенкс": "thanks", "дяк": "thanks", "дякс": "thanks", "прив": "hi",
    "ггвпнт": "good game, well played, nice try", "ггез": "good game, easy", "ггшка": "good game",
})
WEAK.update({
    "nw": "no worries", "sm": "so much", "yh": "yeah", "ge": "good evening", "wr": "win rate", "ks": "kill steal",
    "fp": "fame points", "sv": "server", "rdm": "random deathmatch",
    "pos": "position", "loc": "location", "sth": "something", "bb": "bye bye",
    "хп": "health points", "лс": "private messages", "тп": "teleport", "бб": "bye bye",
})
UK.update({
    "aight": "гаразд", "cba": "не хочеться морочитись", "ftw": "за перемогу", "fwiw": "для чого це варте",
    "lmk": "дай знати", "nbd": "нічого страшного", "nvr": "ніколи", "pov": "точка зору", "smth": "щось",
    "tba": "буде оголошено", "tbc": "далі буде", "tbd": "буде визначено", "ttys": "поговоримо скоро",
    "u2": "і тобі", "w8": "зачекай", "w84me": "зачекай мене", "wat": "що", "wut": "що",
    "yea": "так", "yeh": "так", "yup": "так", "nope": "ні", "nah": "ні", "yknow": "знаєш", "cmon": "давай",
    "dunno": "не знаю", "kinda": "начебто", "sorta": "ніби", "gotcha": "зрозумів", "tryna": "намагаюсь",
    "lemme": "дай мені", "gimme": "дай мені", "wanna": "хочу", "gonna": "збираюсь", "gotta": "треба",
    "lates": "бувай", "hny": "з новим роком", "xmas": "Різдво", "gc": "гарне рішення", "gp": "гарна гра",
    "gw": "гарна робота", "ragequit": "вийшов від злості", "pog": "круто", "poggers": "круто", "lul": "ха-ха",
    "kekw": "ха-ха", "ult": "ультимейт", "ttk": "час на вбивство", "mre": "сухий пайок", "rpg": "гранатомет",
    "hud": "інтерфейс", "fov": "поле зору", "npc": "неігровий персонаж", "dlc": "додатковий контент",
    "wip": "у роботі", "srv": "сервер", "hq": "штаб", "poi": "цікаве місце", "wpn": "зброя", "wpns": "зброя",
    "coord": "координати", "coords": "координати", "obo": "або найкраща пропозиція", "rspct": "повага",
    "gs": "гарний постріл", "gks": "гарне вбивство",
    "лфг": "шукаю групу", "лвл": "рівень", "пвп": "гравець проти гравця", "пве": "гравець проти середовища",
    "рофл": "валяюся від сміху", "омг": "боже мій", "втф": "що за чортівня", "пасиб": "дякую", "пасибо": "дякую",
    "спасиб": "дякую", "сенкс": "дякую", "дяк": "дякую", "дякс": "дякую", "прив": "привіт", "ггез": "гарна гра, легко",
    "ггшка": "гарна гра", "ггвпнт": "гарна гра, добре зіграно, непогана спроба",
    "nw": "без проблем", "sm": "так багато", "yh": "ага", "ge": "добрий вечір", "wr": "відсоток перемог",
    "ks": "крадіжка вбивства", "fp": "очки слави", "sv": "сервер", "rdm": "випадковий дезматч",
    "pos": "позиція", "loc": "локація", "хп": "здоров'я", "лс": "особисті повідомлення", "тп": "телепорт",
    "бб": "бувай",
})

_TOKEN = re.compile(r"(?<!\w)[^\W_]+(?:/[^\W_]+)?(?!\w)", re.UNICODE)
_RUN3 = re.compile(r"(.)\1{2,}")
_RUN2 = re.compile(r"(.)\1+")


def _lookup(token: str) -> Optional[Tuple[str, bool]]:
    """Return (table key, is_weak) for a token, tolerating stretched letters (``ggggg``, ``looool``)."""
    low = token.lower()
    candidates = [low, _RUN3.sub(r"\1\1", low), _RUN2.sub(r"\1", low)]
    for cand in candidates:
        if len(cand) < 2 and cand not in ("u", "r", "y", "k"):
            continue
        if cand in STRONG:
            return cand, False
        if cand in WEAK:
            return cand, True
    # two or three glued abbreviations: "ggwpez" style pairs not in the table ("gjwp", "gghf")
    for cut in range(2, len(low) - 1):
        left, right = low[:cut], low[cut:]
        if left in STRONG and right in STRONG:
            return f"{left} {right}", False
    return None


def _phrase(key: str, table: Dict[str, str]) -> Optional[str]:
    if " " in key:
        parts = [table.get(k) for k in key.split()]
        return ", ".join(parts) if all(parts) else None
    return table.get(key)


def _meaning(key: str) -> str:
    return _phrase(key, STRONG) or WEAK[key]


@dataclass
class SlangResult:
    """What was found in a message.

    ``expanded`` is the message with every recognised abbreviation replaced by its English meaning;
    ``only_slang`` is True when nothing but abbreviations (and punctuation) was written.
    """
    expanded: str
    only_slang: bool
    keys: List[str] = field(default_factory=list)
    ending: str = ""

    def ukrainian(self) -> Optional[str]:
        """Ready Ukrainian text for an abbreviation-only message, or None when a phrase is missing."""
        if not self.only_slang:
            return None
        parts = []
        for key in self.keys:
            part = _phrase(key, UK)
            if not part:
                return None
            parts.append(part)
        text = ", ".join(parts)
        return text[:1].upper() + text[1:] + self.ending


def analyse(text: str) -> Optional[SlangResult]:
    """Find abbreviations in ``text``; None when there is nothing to expand."""
    matches = []
    other_words = 0
    for m in _TOKEN.finditer(text):
        found = _lookup(m.group(0))
        if found:
            matches.append((m, found))
        else:
            other_words += 1
    if not matches:
        return None

    only_slang = other_words == 0
    if not only_slang:
        matches = [(m, f) for m, f in matches if not f[1]]   # weak ones are ordinary words in a real sentence
        if not matches:
            return None

    keys = [f[0] for _, f in matches]
    if only_slang:
        english = ", ".join(_meaning(k) for k in keys)
        ending = text.rstrip()[-1:] if text.rstrip()[-1:] in "!?." else ""
        english = english[:1].upper() + english[1:] + ending
        return SlangResult(expanded=english, only_slang=True, keys=keys, ending=ending)

    out, last = [], 0
    for m, (key, _weak) in matches:
        out.append(text[last:m.start()])
        out.append(_meaning(key))
        last = m.end()
    out.append(text[last:])
    return SlangResult(expanded="".join(out), only_slang=False, keys=keys)
