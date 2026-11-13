"""Shared test fixtures: the test-suite never talks to Google (tests must not depend on the network)."""
from urllib.parse import urlparse

import pytest
import requests

# Canned answers of the translation endpoint: (source text) -> (translation, detected source language)
_CANNED = {
    "Airdrop incoming at sector B2": ("Скидання вантажу в секторі B2", "en"),
    "Де знайти паливо для авто?": ("Where can I find fuel for the car?", "uk"),
    "Дякую за гру": ("Thanks for the game", "uk"),
}


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def offline_translation(monkeypatch, request):
    if getattr(request.module, "RAW_HTTP", False):
        return                      # the test installs its own HTTP adapter
    real_get = requests.Session.get

    def fake_get(self, url, params=None, **kwargs):
        host = urlparse(str(url)).hostname or ""
        if not host.endswith("google.com") and not host.endswith("googleapis.com"):
            return real_get(self, url, params=params, **kwargs)
        text = (params or {}).get("q", "")
        source = (params or {}).get("sl", "auto")
        target = (params or {}).get("tl", "uk")
        translated, detected = _CANNED.get(text, (f"[{target}] {text}", "en" if source == "auto" else source))
        return _FakeResponse([[translated, detected]])

    monkeypatch.setattr(requests.Session, "get", fake_get)
