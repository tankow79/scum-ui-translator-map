import pytest
from core.i18n import LocalizationManager, tr

def test_i18n_loading_and_fallback():
    mgr = LocalizationManager.get_instance()
    mgr.set_locale("en")
    assert mgr.tr("overlay.copy_btn") == "📋 Copy"

    mgr.set_locale("uk")
    assert mgr.tr("overlay.copy_btn") == "📋 Скопіювати"

    mgr.set_locale("ru")
    assert mgr.tr("overlay.copy_btn") == "📋 Скопировать"

def test_i18n_formatting():
    mgr = LocalizationManager.get_instance()
    mgr.set_locale("uk")
    msg = tr("tray.open_map", hotkey="Ctrl+M")
    assert "Ctrl+M" in msg
    assert "Відкрити тактичну карту" in msg

def test_i18n_all_locales_have_matching_keys():
    mgr = LocalizationManager.get_instance()
    uk_keys = set(_get_all_keys(mgr.translations.get("uk", {})))
    en_keys = set(_get_all_keys(mgr.translations.get("en", {})))
    ru_keys = set(_get_all_keys(mgr.translations.get("ru", {})))

    assert len(uk_keys) > 0
    assert uk_keys == en_keys, f"Diff uk vs en: {uk_keys ^ en_keys}"
    assert uk_keys == ru_keys, f"Diff uk vs ru: {uk_keys ^ ru_keys}"

def _get_all_keys(d, prefix=""):
    keys = []
    for k, v in d.items():
        curr = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_get_all_keys(v, curr))
        else:
            keys.append(curr)
    return keys
