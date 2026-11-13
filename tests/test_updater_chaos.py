"""The update check and download under a flaky or hostile network."""
import http.client
import io
import urllib.error

import pytest

import core.updater as updater


class _Response:
    def __init__(self, body=b"", headers=None, url="https://github.com/x/y/releases/download/v9/SCUM_Chat_Translator.exe",
                 fail_after=None, exc=None):
        self._body, self.headers, self._url = io.BytesIO(body), headers or {}, url
        self._read_bytes, self._fail_after, self._exc = 0, fail_after, exc

    def read(self, n=-1):
        if self._fail_after is not None and self._read_bytes >= self._fail_after:
            raise self._exc
        data = self._body.read(n)
        self._read_bytes += len(data)
        return data

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _checker():
    return updater.UpdateChecker(current_version="2.4.0")


def _errors(checker):
    seen = []
    checker.check_error.connect(seen.append)
    return seen


@pytest.mark.parametrize("failure,expected", [
    (urllib.error.URLError("dns"), "No connection"),
    (TimeoutError("slow"), "No connection"),
    (ConnectionResetError("reset"), "No connection"),
    (http.client.RemoteDisconnected("closed"), "No connection"),
    (http.client.IncompleteRead(b"abc"), "No connection"),
    (urllib.error.HTTPError("u", 403, "rate", {}, None), "rate limit"),
    (urllib.error.HTTPError("u", 429, "slow down", {}, None), "rate limit"),
    (urllib.error.HTTPError("u", 502, "bad gateway", {}, None), "HTTP 502"),
])
def test_check_reports_network_failures_in_plain_words(monkeypatch, failure, expected):
    def boom(*a, **k):
        raise failure
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    c, seen = _checker(), []
    c.check_error.connect(seen.append)
    c._worker_check()
    assert seen and expected in seen[0]


@pytest.mark.parametrize("body", [b"<html>Log in to the Wi-Fi</html>", b"", b"\xff\xfe", b"[]", b'"x"', b"null", b"[1, 2]",
                                  b'{"tag_name": 5, "assets": "x"}', b'{"assets": [null, 3, "a"]}'])
def test_captive_portals_and_garbage_replies_do_not_crash_the_check(monkeypatch, body):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Response(body))
    c, errors, nothing = _checker(), [], []
    c.check_error.connect(errors.append)
    c.no_update_found.connect(nothing.append)
    c.update_available.connect(lambda info: nothing.append("update"))
    c._worker_check()                                   # must finish, whatever came back
    assert errors or nothing
    for message in errors:
        assert "Traceback" not in message and "Expecting value" not in message and "object has no attribute" not in message


def test_oversized_api_reply_is_refused(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda *a, **k: _Response(b"[" + b"1," * updater.MAX_API_BYTES + b"1]"))
    c, errors = _checker(), []
    c.check_error.connect(errors.append)
    c._worker_check()
    assert errors and "unexpected reply" in errors[0]


def test_weird_asset_sizes_do_not_crash():
    info = updater.parse_release({"tag_name": "v9.9.9", "assets": [
        {"name": "SCUM_Chat_Translator.exe", "size": "huge", "browser_download_url":
         "https://github.com/a/b/releases/download/v9.9.9/SCUM_Chat_Translator.exe"}]}, "2.4.0", portable=False)
    assert info.asset_size == 0 and info.is_newer


@pytest.mark.parametrize("exc", [ConnectionResetError("reset"), http.client.IncompleteRead(b"x"), TimeoutError("stalled"),
                                 urllib.error.URLError("gone")])
def test_download_that_dies_midway_leaves_no_file_and_a_plain_message(monkeypatch, tmp_path, exc):
    monkeypatch.setattr(updater, "get_updates_dir", lambda: str(tmp_path))
    body = b"MZ" + b"x" * 200_000
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body, {"Content-Length": str(len(body))}, fail_after=70_000, exc=exc))
    d, errors, done = updater.UpdateDownloader(), [], []
    d.error.connect(errors.append)
    d.finished.connect(done.append)
    d._worker_download("https://github.com/a/b/releases/download/v9/SCUM_Chat_Translator.exe", None, None)
    assert errors and "Download failed" in errors[0] and not done
    assert list(tmp_path.iterdir()) == []               # no half-downloaded .part file is left behind


def test_download_with_a_wrong_content_length_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "get_updates_dir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda *a, **k: _Response(b"MZ123", {"Content-Length": "9999"}))
    d, errors = updater.UpdateDownloader(), []
    d.error.connect(errors.append)
    d._worker_download("https://github.com/a/b/releases/download/v9/SCUM_Chat_Translator.exe", None, None)
    assert errors and "incomplete" in errors[0]
    assert list(tmp_path.iterdir()) == []
