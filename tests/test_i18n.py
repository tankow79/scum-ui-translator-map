import json

from core.i18n import FALLBACK_LOCALE, LocalizationManager


def _keys(d, prefix=""):
    out = []
    for k, v in d.items():
        if k.startswith("_"):
            continue
        cur = f"{prefix}.{k}" if prefix else k
        out.extend(_keys(v, cur) if isinstance(v, dict) else [cur])
    return out


def make_locales(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"_meta": {"name": "English"}, "a": {"b": "Hello {name}"}, "only_en": "EN"}), encoding="utf-8")
    (tmp_path / "de.json").write_text(json.dumps({"_meta": {"name": "Deutsch"}, "a": {"b": "Hallo {name}"}}), encoding="utf-8")
    (tmp_path / "_template.json").write_text("{}", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{nope", encoding="utf-8")
    return str(tmp_path)


def test_locales_are_discovered_from_folder(tmp_path):
    mgr = LocalizationManager(locales_dir=make_locales(tmp_path))
    assert mgr.available_locales() == [("en", "English"), ("de", "Deutsch")]  # English first, junk ignored


def test_switching_language_and_fallback_to_english(tmp_path):
    mgr = LocalizationManager(locales_dir=make_locales(tmp_path))
    assert mgr.set_locale("de")
    assert mgr.tr("a.b", name="X") == "Hallo X"
    assert mgr.tr("only_en") == "EN"               # missing in de -> English
    assert mgr.tr("missing.key") == "missing.key"  # unknown -> key
    assert mgr.tr("missing.key", default="Fallback") == "Fallback"
    assert not mgr.set_locale("xx") and mgr.current_locale == "de"


def test_bad_placeholder_does_not_crash(tmp_path):
    mgr = LocalizationManager(locales_dir=make_locales(tmp_path))
    assert mgr.tr("a.b", other=1) == "Hello {name}"


def test_unknown_initial_locale_falls_back_to_english(tmp_path):
    mgr = LocalizationManager("zz", locales_dir=make_locales(tmp_path))
    assert mgr.current_locale == FALLBACK_LOCALE


def test_shipped_locales_are_complete_and_placeholders_match():
    import re

    def flat(d, prefix=""):
        for k, v in d.items():
            if k.startswith("_"):
                continue
            cur = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from flat(v, cur)
            else:
                yield cur, v

    mgr = LocalizationManager()
    en = dict(flat(mgr.translations["en"]))
    assert mgr.translations["en"]["_meta"]["name"] == "English" and len(en) > 150
    assert "uk" in mgr.translations and mgr.translations["uk"]["_meta"]["name"] == "Українська"

    def placeholders(text):
        return set(re.findall(r"\{(\w+)\}", text))

    for code, data in mgr.translations.items():
        if code in ("en", "ru"):   # ru is not a shipped locale
            continue
        loc = dict(flat(data))
        assert set(loc) == set(en), f"{code}: missing {set(en) - set(loc)} extra {set(loc) - set(en)}"
        for key, text in loc.items():
            assert placeholders(text) == placeholders(en[key]), f"{code}:{key} placeholders differ"
