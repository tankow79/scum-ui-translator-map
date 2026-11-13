"""Hostile / broken answers and outages of the translation service (talks to a fake HTTP adapter)."""
RAW_HTTP = True   # tests/conftest.py: do not replace the HTTP layer, these tests install their own

import json as _json  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402
from requests.adapters import BaseAdapter  # noqa: E402

from core.translator import GoogleTranslatorEngine  # noqa: E402


class _Adapter(BaseAdapter):
    def __init__(self, handler):
        super().__init__()
        self.handler, self.calls = handler, 0

    def send(self, request, **kwargs):
        self.calls += 1
        out = self.handler(self.calls)
        if isinstance(out, Exception):
            raise out
        r = requests.Response()
        r.status_code, r._content, r.url = out[0], out[1].encode() if isinstance(out[1], str) else out[1], request.url
        return r

    def close(self):
        pass


def _engine(handler):
    eng = GoogleTranslatorEngine(target_lang="uk")
    ad = _Adapter(handler)
    eng.session.mount("https://", ad)
    return eng, ad


@pytest.mark.parametrize("body", [
    '[["", "en"]]', "[[null, null]]", "[[1, 2]]", "[]", "{}", '"text"', "<html>", "", "[[]]",
    _json.dumps([["x" * 100000, "en"]]),
], ids=["empty-text", "nulls", "numbers", "empty-list", "dict", "string", "html", "empty-body", "nested-empty", "huge"])
def test_unusable_translation_replies_fall_back_to_the_original(body):
    eng, ad = _engine(lambda n: (200, body))
    assert eng.translate("hello world") == ("hello world", "unknown")
    assert len(eng._cache) == 0                      # a bad reply is never cached


def test_bad_language_code_is_replaced_by_the_requested_source():
    eng, _ = _engine(lambda n: (200, _json.dumps([["ok", "<script>"]])))
    assert eng.translate("hello") == ("ok", "auto")


def test_connection_errors_never_raise():
    for exc in (requests.exceptions.ConnectTimeout(), requests.exceptions.ReadTimeout(),
                requests.exceptions.ConnectionError("dns"), requests.exceptions.SSLError("cert"),
                requests.exceptions.ChunkedEncodingError("reset"), OSError("boom"), RuntimeError("x")):
        eng, _ = _engine(lambda n, exc=exc: exc)
        assert eng.translate("hello world") == ("hello world", "unknown")


def test_outage_opens_a_circuit_breaker_and_recovers(monkeypatch):
    import core.translator as translator_module

    clock = [1000.0]
    monkeypatch.setattr(translator_module.time, "monotonic", lambda: clock[0])
    down = [True]
    eng, ad = _engine(lambda n: requests.exceptions.ConnectionError("dns") if down[0]
                      else (200, _json.dumps([["Привіт", "en"]])))
    eng.translate("one")
    eng.translate("two")                              # second total failure: the breaker opens
    calls = ad.calls
    for word in ("three", "four", "five"):
        assert eng.translate(word) == (word, "unknown")
    assert ad.calls == calls                          # no network traffic while the breaker is open
    down[0] = False
    clock[0] += 6                                     # cooldown over: next message probes the network again
    assert eng.translate("six") == ("Привіт", "en")
    assert eng._fail_streak == 0


def test_api_key_is_sent_in_a_header_not_in_the_url():
    seen = {}

    class Spy(BaseAdapter):
        def send(self, request, **kwargs):
            seen["url"], seen["headers"] = request.url, dict(request.headers)
            r = requests.Response()
            r.status_code, r._content, r.url = 200, _json.dumps(
                {"data": {"translations": [{"translatedText": "Привіт", "detectedSourceLanguage": "en"}]}}).encode(), request.url
            return r

        def close(self):
            pass

    eng = GoogleTranslatorEngine(target_lang="uk", api_key="SECRET123")
    eng.session.mount("https://", Spy())
    assert eng.translate("hello") == ("Привіт", "en")
    assert "SECRET123" not in seen["url"] and seen["headers"].get("X-Goog-Api-Key") == "SECRET123"


def test_one_message_never_exceeds_its_time_budget(monkeypatch):
    import core.translator as translator_module

    clock = [1000.0]
    monkeypatch.setattr(translator_module.time, "monotonic", lambda: clock[0])
    seen_timeouts = []

    def slow_failure(n):
        clock[0] += 5.0                               # every attempt burns 5 seconds before it fails
        return requests.exceptions.ReadTimeout("slow")

    eng, ad = _engine(slow_failure)
    orig_send = ad.send

    def spy(request, **kwargs):
        seen_timeouts.append(kwargs.get("timeout"))
        return orig_send(request, **kwargs)

    ad.send = spy
    assert eng.translate("hello world") == ("hello world", "unknown")
    assert ad.calls == 2                              # 7 s budget: a third server is not even tried
    assert all(max(t) <= 5.0 for t in seen_timeouts) and seen_timeouts[1][1] <= 2.0 + 1e-9


def test_order_wait_is_longer_than_the_translation_budget():
    from core.controller import AppController

    assert AppController.ORDER_WAIT_SECONDS > GoogleTranslatorEngine.TIME_BUDGET_SECONDS + 1
