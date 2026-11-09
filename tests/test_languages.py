import pytest
from core.languages import ALL_LANGUAGES, LANGUAGE_DICT, get_language_name

def test_languages_list_validity():
    assert len(ALL_LANGUAGES) >= 100, "Кількість мов повинна бути 100+"

    codes = [code for _, code in ALL_LANGUAGES]
    # Перевірка на унікальність кодів
    assert len(codes) == len(set(codes)), "Знайдено дублікати мовних кодів"

    # Перевірка наявності ключових мов
    assert "uk" in codes
    assert "en" in codes
    assert "pl" in codes
    assert "de" in codes
    assert "fr" in codes
    assert "es" in codes

def test_get_language_name():
    assert "Українська" in get_language_name("uk")
    assert "English" in get_language_name("en")
    # Невідомий код повертає сам себе
    assert get_language_name("unknown_xyz") == "unknown_xyz"
