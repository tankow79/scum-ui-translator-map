"""Languages supported by the translation service.

Each entry is ``(code, English name, native name)``. The UI shows ``"English name — native name"`` so users can
always find their language, whatever the interface language is. Popular languages are listed first.
"""

from typing import List, Tuple

_POPULAR = [
    ("uk", "Ukrainian", "Українська"), ("en", "English", "English"), ("pl", "Polish", "Polski"),
    ("de", "German", "Deutsch"), ("fr", "French", "Français"), ("es", "Spanish", "Español"),
    ("it", "Italian", "Italiano"), ("tr", "Turkish", "Türkçe"), ("cs", "Czech", "Čeština"),
    ("sk", "Slovak", "Slovenčina"), ("ro", "Romanian", "Română"), ("hu", "Hungarian", "Magyar"),
    ("bg", "Bulgarian", "Български"), ("hr", "Croatian", "Hrvatski"), ("sr", "Serbian", "Srpski"),
    ("sl", "Slovenian", "Slovenščina"), ("nl", "Dutch", "Nederlands"), ("sv", "Swedish", "Svenska"),
    ("no", "Norwegian", "Norsk"), ("fi", "Finnish", "Suomi"), ("da", "Danish", "Dansk"),
    ("el", "Greek", "Ελληνικά"), ("lt", "Lithuanian", "Lietuvių"), ("lv", "Latvian", "Latviešu"),
    ("et", "Estonian", "Eesti"), ("ru", "Russian", "Русский"), ("ja", "Japanese", "日本語"),
    ("ko", "Korean", "한국어"), ("zh-CN", "Chinese (Simplified)", "中文"),
    ("zh-TW", "Chinese (Traditional)", "繁體中文"), ("ar", "Arabic", "العربية"), ("he", "Hebrew", "עברית"),
    ("hi", "Hindi", "हिन्दी"), ("id", "Indonesian", "Bahasa Indonesia"), ("vi", "Vietnamese", "Tiếng Việt"),
    ("th", "Thai", "ไทย"), ("ka", "Georgian", "ქართული"), ("hy", "Armenian", "Հայերեն"),
    ("az", "Azerbaijani", "Azərbaycan"), ("kk", "Kazakh", "Қазақ"), ("uz", "Uzbek", "O'zbek"),
]

_OTHER = [
    ("af", "Afrikaans", "Afrikaans"), ("sq", "Albanian", "Shqip"), ("am", "Amharic", "አማርኛ"),
    ("eu", "Basque", "Euskara"), ("be", "Belarusian", "Беларуская"), ("bn", "Bengali", "বাংলা"),
    ("bs", "Bosnian", "Bosanski"), ("ca", "Catalan", "Català"), ("ceb", "Cebuano", "Cebuano"),
    ("co", "Corsican", "Corsu"), ("eo", "Esperanto", "Esperanto"), ("fil", "Filipino", "Filipino"),
    ("fy", "Frisian", "Frysk"), ("gl", "Galician", "Galego"), ("gu", "Gujarati", "ગુજરાતી"),
    ("ht", "Haitian Creole", "Kreyòl Ayisyen"), ("ha", "Hausa", "Hausa"), ("haw", "Hawaiian", "ʻŌlelo Hawaiʻi"),
    ("hmn", "Hmong", "Hmong"), ("is", "Icelandic", "Íslenska"), ("ig", "Igbo", "Igbo"),
    ("ga", "Irish", "Gaeilge"), ("jv", "Javanese", "Basa Jawa"), ("kn", "Kannada", "ಕನ್ನಡ"),
    ("km", "Khmer", "ភាសាខ្មែរ"), ("rw", "Kinyarwanda", "Kinyarwanda"), ("ku", "Kurdish", "Kurdî"),
    ("ky", "Kyrgyz", "Кыргызча"), ("lo", "Lao", "ລາວ"), ("la", "Latin", "Latina"),
    ("lb", "Luxembourgish", "Lëtzebuergesch"), ("mk", "Macedonian", "Македонски"),
    ("mg", "Malagasy", "Malagasy"), ("ms", "Malay", "Bahasa Melayu"), ("ml", "Malayalam", "മലയാളം"),
    ("mt", "Maltese", "Malti"), ("mi", "Maori", "Māori"), ("mr", "Marathi", "मराठी"),
    ("mn", "Mongolian", "Монгол"), ("my", "Burmese", "မြန်မာ"), ("ne", "Nepali", "नेपाली"),
    ("or", "Odia", "ଓଡ଼ିଆ"), ("ps", "Pashto", "پښتو"), ("fa", "Persian", "فارسی"),
    ("pt", "Portuguese", "Português"), ("pa", "Punjabi", "ਪੰਜਾਬੀ"), ("gd", "Scottish Gaelic", "Gàidhlig"),
    ("st", "Sesotho", "Sesotho"), ("sn", "Shona", "Shona"), ("sd", "Sindhi", "سنڌي"),
    ("si", "Sinhala", "සිංහල"), ("so", "Somali", "Soomaali"), ("su", "Sundanese", "Basa Sunda"),
    ("sw", "Swahili", "Kiswahili"), ("tg", "Tajik", "Тоҷикӣ"), ("ta", "Tamil", "தமிழ்"),
    ("tt", "Tatar", "Татарча"), ("te", "Telugu", "తెలుగు"), ("tk", "Turkmen", "Türkmen"),
    ("ug", "Uyghur", "ئۇيغۇرچە"), ("ur", "Urdu", "اردو"), ("cy", "Welsh", "Cymraeg"),
    ("xh", "Xhosa", "isiXhosa"), ("yi", "Yiddish", "ייִדיש"), ("yo", "Yoruba", "Yorùbá"),
    ("zu", "Zulu", "isiZulu"),
]


def _label(english: str, native: str) -> str:
    return english if english == native else f"{english} — {native}"


# List of tuples: (UI display name, language code). Popular first, the rest alphabetical by English name.
ALL_LANGUAGES: List[Tuple[str, str]] = (
    [(_label(en, native), code) for code, en, native in _POPULAR]
    + [(_label(en, native), code) for code, en, native in sorted(_OTHER, key=lambda item: item[1].lower())]
)

LANGUAGE_DICT = {code: name for name, code in ALL_LANGUAGES}


def get_language_name(code: str) -> str:
    return LANGUAGE_DICT.get(code, code)
