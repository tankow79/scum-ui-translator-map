from core.languages import ALL_LANGUAGES, get_language_name


def test_languages_list_validity():
    assert len(ALL_LANGUAGES) >= 100, "At least 100 languages expected"

    codes = [code for _, code in ALL_LANGUAGES]
    # Check code uniqueness
    assert len(codes) == len(set(codes)), "Duplicate language codes found"

    # Check key languages are present
    assert "uk" in codes
    assert "en" in codes
    assert "pl" in codes
    assert "de" in codes
    assert "fr" in codes
    assert "es" in codes

def test_get_language_name():
    assert "Українська" in get_language_name("uk")
    assert "English" in get_language_name("en")
    # Unknown code returns itself
    assert get_language_name("unknown_xyz") == "unknown_xyz"
