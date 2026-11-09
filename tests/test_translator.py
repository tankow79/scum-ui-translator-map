import pytest
from core.translator import GoogleTranslatorEngine

def test_translator_empty_and_special_text():
    tr = GoogleTranslatorEngine(target_lang="uk")

    # Пустий текст
    res, lang = tr.translate("")
    assert res == ""
    assert lang == "unknown"

    # Посилання пропускаються без запиту до мережі
    url = "https://discord.gg/GRrreuFPRq"
    res, lang = tr.translate(url)
    assert res == url
    assert lang == "auto"

    # Числа пропускаються без змін
    res, lang = tr.translate("123456")
    assert res == "123456"

def test_translator_caching():
    tr = GoogleTranslatorEngine(target_lang="uk")
    cache_key = "auto->uk:Hello SCUM survivor"
    tr._cache[cache_key] = ("Привіт тому, хто вижив у SCUM", "en")

    # Має миттєво повернути з кешу
    res, lang = tr.translate("Hello SCUM survivor")
    assert res == "Привіт тому, хто вижив у SCUM"
    assert lang == "en"

def test_translator_real_incoming():
    tr = GoogleTranslatorEngine(target_lang="uk")
    res, lang = tr.translate("Airdrop incoming at sector B2")
    assert len(res) > 0
    assert lang == "en"
    # Перевірка наявності ключових слів
    assert any(w in res.lower() for w in ["ейрдроп", "вантаж", "сектор", "b2", "б2", "скидання"])

def test_translator_real_outgoing():
    tr = GoogleTranslatorEngine(target_lang="uk")
    res, _ = tr.translate_custom("Де знайти паливо для авто?", target="en", source="uk")
    assert len(res) > 0
    # Переклад англійською містить fuel/gasoline/car
    assert any(w in res.lower() for w in ["fuel", "gas", "gasoline", "car", "vehicle", "where", "find"])
