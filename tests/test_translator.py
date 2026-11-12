from core.translator import GoogleTranslatorEngine


def test_translator_empty_and_special_text():
    tr = GoogleTranslatorEngine(target_lang="uk")

    # Empty text
    res, lang = tr.translate("")
    assert res == ""
    assert lang == "unknown"

    # Links are skipped without a network request
    url = "https://discord.gg/GRrreuFPRq"
    res, lang = tr.translate(url)
    assert res == url
    assert lang == "auto"

    # Numbers are passed through unchanged
    res, lang = tr.translate("123456")
    assert res == "123456"

def test_translator_caching():
    tr = GoogleTranslatorEngine(target_lang="uk")
    cache_key = "auto->uk:Hello SCUM survivor"
    tr._cache[cache_key] = ("Привіт тому, хто вижив у SCUM", "en")

    # Should return instantly from cache
    res, lang = tr.translate("Hello SCUM survivor")
    assert res == "Привіт тому, хто вижив у SCUM"
    assert lang == "en"

def test_translator_real_incoming():
    tr = GoogleTranslatorEngine(target_lang="uk")
    res, lang = tr.translate("Airdrop incoming at sector B2")
    assert len(res) > 0
    assert lang == "en"
    # Check for keywords
    assert any(w in res.lower() for w in ["ейрдроп", "вантаж", "сектор", "b2", "б2", "скидання"])

def test_translator_real_outgoing():
    tr = GoogleTranslatorEngine(target_lang="uk")
    res, _ = tr.translate_custom("Де знайти паливо для авто?", target="en", source="uk")
    assert len(res) > 0
    # English translation contains fuel/gasoline/car
    assert any(w in res.lower() for w in ["fuel", "gas", "gasoline", "car", "vehicle", "where", "find"])
