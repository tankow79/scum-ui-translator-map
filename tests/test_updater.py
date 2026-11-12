"""Tests for update checking, downloading, in-place installation and user-data protection."""

import hashlib
import io
import json
import os
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

import core.updater as updater
from core.updater import (
    UpdateChecker,
    UpdateDownloader,
    UpdateError,
    UpdateInfo,
    UpdateInstaller,
    parse_release,
    select_asset,
)
from core.version import is_version_newer, parse_version
from ui.update_dialog import UpdateDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def updates_dir(tmp_path, monkeypatch):
    """Redirect the updates folder to a temp dir."""
    folder = tmp_path / "updates"
    folder.mkdir()
    monkeypatch.setattr(updater, "get_updates_dir", lambda: str(folder))
    return folder


def fake_exe(content: bytes = b"X") -> bytes:
    """Bytes that pass executable validation (MZ header, > 1 MB)."""
    return b"MZ" + content + b"\0" * (updater.MIN_EXE_SIZE + 10)


# ───────────── version comparison ─────────────

def test_version_parsing():
    assert parse_version("1.0.0") == (1, 0, 0)
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("V2.1") == (2, 1, 0)
    assert parse_version("v1.0.0-beta.1") == (1, 0, 0)
    assert parse_version("invalid") == (0, 0, 0)


def test_is_version_newer():
    assert is_version_newer("1.0.0", "v1.0.1")
    assert is_version_newer("1.2.3", "2.0.0")
    assert not is_version_newer("1.0.0", "v1.0.0")
    assert not is_version_newer("2.0.0", "v1.9.9")


# ───────────── release parsing / asset selection ─────────────

ASSETS = [
    {"name": "SCUM_Chat_Translator_v2.1.0.zip", "browser_download_url": "https://x/full.zip", "size": 10},
    {"name": "SCUM_Chat_Translator.exe", "browser_download_url": "https://x/app.exe", "size": 20,
     "digest": "sha256:" + "a" * 64},
    {"name": "SCUM_Chat_Translator_Portable.exe", "browser_download_url": "https://x/portable.exe", "size": 30},
    {"name": "SCUM_Chat_Translator.cer", "browser_download_url": "https://x/cert.cer", "size": 1},
]


def test_select_asset_prefers_exe_for_normal_build():
    assert select_asset(ASSETS, portable=False)["browser_download_url"] == "https://x/app.exe"


def test_select_asset_matches_portable_variant():
    assert select_asset(ASSETS, portable=True)["browser_download_url"] == "https://x/portable.exe"


def test_select_asset_ignores_non_binaries():
    assert select_asset([{"name": "notes.txt", "browser_download_url": "https://x/n"}]) is None
    assert select_asset([]) is None


def test_parse_release_reads_digest_and_never_uses_source_zipball():
    data = {"tag_name": "v2.1.0", "name": "R", "body": "notes", "published_at": "2026-11-12T10:00:00Z",
            "html_url": "https://x/r", "assets": ASSETS, "zipball_url": "https://x/source.zip"}
    info = parse_release(data, "2.0.0", portable=False)
    assert info.is_newer and info.sha256 == "a" * 64 and info.download_url.endswith("app.exe")

    no_assets = parse_release({**data, "assets": []}, "2.0.0", portable=False)
    assert no_assets.download_url is None  # the dialog then opens the release page instead


def test_fetch_latest_release_info_with_update():
    payload = {"tag_name": "v1.1.0", "name": "R", "body": "### What's new", "published_at": "2026-11-09T12:00:00Z",
               "html_url": "https://github.com/x/y/releases/tag/v1.1.0", "assets": ASSETS}
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    with patch("urllib.request.urlopen", return_value=resp):
        info = UpdateChecker(current_version="1.0.0").fetch_latest_release_info()
    assert info and info.version == "1.1.0" and info.is_newer
    assert "What's new" in info.body


def test_fetch_latest_release_info_up_to_date():
    payload = {"tag_name": "v1.1.0", "assets": []}
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    with patch("urllib.request.urlopen", return_value=resp):
        info = UpdateChecker(current_version="1.1.0").fetch_latest_release_info()
    assert info is not None and info.is_newer is False


# ───────────── download ─────────────

def _fake_response(data: bytes):
    resp = MagicMock()
    resp.headers = {"Content-Length": str(len(data))}
    stream = io.BytesIO(data)
    resp.read.side_effect = stream.read
    resp.__enter__.return_value = resp
    return resp


def test_download_saves_file_verifies_sha_and_leaves_no_part_file(qapp, updates_dir):
    data = fake_exe(b"NEW")
    dl = UpdateDownloader()
    done, errors = [], []
    dl.finished.connect(done.append)
    dl.error.connect(errors.append)
    with patch("urllib.request.urlopen", return_value=_fake_response(data)):
        dl._worker_download("https://x/app.exe", "app.exe", hashlib.sha256(data).hexdigest())
    assert not errors and len(done) == 1
    assert os.path.dirname(done[0]) == str(updates_dir)
    assert open(done[0], "rb").read() == data
    assert not list(updates_dir.glob("*.part"))


def test_download_rejects_hash_mismatch(qapp, updates_dir):
    dl = UpdateDownloader()
    errors = []
    dl.error.connect(errors.append)
    with patch("urllib.request.urlopen", return_value=_fake_response(fake_exe())):
        dl._worker_download("https://x/app.exe", "app.exe", "0" * 64)
    assert errors and "integrity" in errors[0].lower()
    assert not list(updates_dir.iterdir())


# ───────────── installation ─────────────

def test_apply_update_swaps_executable_and_keeps_old_copy(tmp_path):
    target = tmp_path / "SCUM_Chat_Translator.exe"
    target.write_bytes(fake_exe(b"OLD"))
    new = tmp_path / "download.exe"
    new.write_bytes(fake_exe(b"NEW"))
    (tmp_path / "config.json").write_text('{"own_nickname": "Hero"}')

    result = UpdateInstaller.apply_update(str(new), target_exe=str(target))

    assert result == str(target)
    assert target.read_bytes().startswith(b"MZNEW")
    assert (tmp_path / "SCUM_Chat_Translator.exe.old").read_bytes().startswith(b"MZOLD")
    assert json.loads((tmp_path / "config.json").read_text())["own_nickname"] == "Hero"
    assert (tmp_path / "config.json.bak").exists()


def test_apply_update_rolls_back_when_swap_fails(tmp_path, monkeypatch):
    target = tmp_path / "app.exe"
    target.write_bytes(fake_exe(b"OLD"))
    new = tmp_path / "new.exe"
    new.write_bytes(fake_exe(b"NEW"))

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # the "staged -> target" step
            raise OSError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky_replace)
    with pytest.raises(UpdateError):
        UpdateInstaller.apply_update(str(new), target_exe=str(target))
    assert target.read_bytes().startswith(b"MZOLD")
    assert not (tmp_path / "app.exe.new").exists()


def test_apply_update_rejects_invalid_download(tmp_path):
    target = tmp_path / "app.exe"
    target.write_bytes(fake_exe(b"OLD"))
    bogus = tmp_path / "page.exe"
    bogus.write_text("<html>404</html>")
    with pytest.raises(UpdateError):
        UpdateInstaller.apply_update(str(bogus), target_exe=str(target))
    assert target.read_bytes().startswith(b"MZOLD")


def test_apply_update_extracts_exe_from_zip(tmp_path, updates_dir):
    target = tmp_path / "SCUM_Chat_Translator.exe"
    target.write_bytes(fake_exe(b"OLD"))
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("SCUM_Chat_Translator/SCUM_Chat_Translator.exe", fake_exe(b"ZIPPED"))
        z.writestr("SCUM_Chat_Translator/INSTRUCTION_EN.txt", "echo")
    UpdateInstaller.apply_update(str(archive), target_exe=str(target))
    assert target.read_bytes().startswith(b"MZZIPPED")


def test_apply_update_refuses_outside_packaged_exe(tmp_path):
    new = tmp_path / "x.exe"
    new.write_bytes(fake_exe())
    with pytest.raises(UpdateError):
        UpdateInstaller.apply_update(str(new))  # running from source: not frozen


def test_safe_extract_zip_preserves_user_data(tmp_path):
    (tmp_path / "config.json").write_text('{"own_nickname": "CustomHero"}')
    (tmp_path / "points.json").write_text('[{"id": "pt1"}]')
    archive = tmp_path / "r.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("app.exe", b"NEW")
        z.writestr("config.json", '{"own_nickname": ""}')
        z.writestr("points.json", "[]")
    UpdateInstaller.safe_extract_zip(str(archive), str(tmp_path))
    assert (tmp_path / "app.exe").read_bytes() == b"NEW"
    assert json.loads((tmp_path / "config.json").read_text())["own_nickname"] == "CustomHero"
    assert json.loads((tmp_path / "points.json").read_text()) == [{"id": "pt1"}]


def test_safe_extract_zip_blocks_path_traversal(tmp_path):
    target = tmp_path / "app"
    target.mkdir()
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(UpdateError):
        UpdateInstaller.safe_extract_zip(str(archive), str(target))
    assert not (tmp_path / "evil.txt").exists()


def test_backup_user_data(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "profiles.json").write_text("{}")
    backups = UpdateInstaller.backup_user_data(str(tmp_path))
    assert set(backups) == {"config.json", "profiles.json"}
    assert (tmp_path / "config.json.bak").exists()
    assert (tmp_path / ".update_backup").is_dir()


# ───────────── UI ─────────────

def test_tray_icon_pixmap_generation(qapp):
    from main import create_tray_icon_pixmap
    normal = create_tray_icon_pixmap(has_update=False).toImage()
    badge = create_tray_icon_pixmap(has_update=True).toImage()
    assert normal.width() == 32 and badge.width() == 32
    assert any(normal.pixelColor(x, y) != badge.pixelColor(x, y) for x in range(32) for y in range(32))


def make_info(**overrides) -> UpdateInfo:
    base = dict(version="1.2.0", name="R", body="- New keypads\n- Faster updates", published_at="2026-11-09",
                html_url="https://github.com/x/y", download_url="https://x/update.exe", asset_name="update.exe",
                asset_size=1024000, is_newer=True, is_zip=False)
    base.update(overrides)
    return UpdateInfo(**base)


def test_update_dialog_prompt_state(qapp):
    dialog = UpdateDialog(make_info())
    assert dialog.btn_primary.isEnabled()
    assert not dialog.bar.isVisibleTo(dialog)  # progress bar appears only while downloading
    assert "New keypads" in dialog.notes.toPlainText()
    dialog.close()


def test_update_dialog_without_direct_link_shows_error_instead_of_downloading(qapp):
    dialog = UpdateDialog(make_info(download_url=None))
    with patch("ui.update_dialog.webbrowser.open") as opened:
        dialog._start_download()
    opened.assert_called_once()
    assert dialog._state == "error"
    dialog.close()
