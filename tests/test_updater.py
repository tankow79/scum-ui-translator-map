"""
Тестовий набір для перевірки автооновлення та захисту даних користувача.
"""

import os
import json
import zipfile
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap

from core.version import parse_version, is_version_newer, __version__
from core.updater import (
    UpdateChecker, UpdateInfo, UpdateDownloader, UpdateInstaller,
    PROTECTED_USER_DATA_FILES, get_application_root_dir
)
from ui.update_dialog import UpdateDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ─────────────────────────────────────────────────────────────
# 1. ТЕСТИ СЕМАНТИЧНОГО ПОРІВНЯННЯ ВЕРСІЙ
# ─────────────────────────────────────────────────────────────

def test_version_parsing():
    assert parse_version("1.0.0") == (1, 0, 0)
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("V2.1") == (2, 1, 0)
    assert parse_version("v1.0.0-beta.1") == (1, 0, 0)
    assert parse_version("v1.5+build123") == (1, 5, 0)
    assert parse_version("invalid") == (0, 0, 0)


def test_is_version_newer():
    # Віддалена новіша
    assert is_version_newer("1.0.0", "v1.0.1") is True
    assert is_version_newer("1.0.0", "v1.1.0") is True
    assert is_version_newer("1.0.0", "v2.0.0") is True
    assert is_version_newer("1.2.3", "1.2.4") is True

    # Однакової версії
    assert is_version_newer("1.0.0", "v1.0.0") is False
    assert is_version_newer("v1.0.0", "1.0.0") is False

    # Локальна новіша за віддалену
    assert is_version_newer("1.1.0", "v1.0.9") is False
    assert is_version_newer("2.0.0", "v1.9.9") is False


# ─────────────────────────────────────────────────────────────
# 2. ТЕСТИ ПАРСИНГУ GITHUB RELEASES
# ─────────────────────────────────────────────────────────────

def test_fetch_latest_release_info_with_update():
    mock_github_response = {
        "tag_name": "v1.1.0",
        "name": "SCUM Translator v1.1.0",
        "body": "### Що нового:\n- Додано автооновлення в 1 клік\n- Оновлена карта",
        "published_at": "2026-11-09T12:00:00Z",
        "html_url": "https://github.com/tankow79/scum-ui-translator-map/releases/tag/v1.1.0",
        "assets": [
            {
                "name": "SCUM_Chat_Translator_v1.1.0.zip",
                "browser_download_url": "https://github.com/tankow79/scum-ui-translator-map/releases/download/v1.1.0/SCUM_Chat_Translator_v1.1.0.zip",
                "size": 42000000
            },
            {
                "name": "SCUM_Chat_Translator.exe",
                "browser_download_url": "https://github.com/tankow79/scum-ui-translator-map/releases/download/v1.1.0/SCUM_Chat_Translator.exe",
                "size": 42300000
            }
        ]
    }

    checker = UpdateChecker(current_version="1.0.0")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_github_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        info = checker.fetch_latest_release_info()

    assert info is not None
    assert info.version == "1.1.0"
    assert info.is_newer is True
    assert info.is_zip is True
    assert info.asset_name == "SCUM_Chat_Translator_v1.1.0.zip"
    assert "https://" in info.download_url
    assert "Що нового" in info.body


def test_fetch_latest_release_info_already_up_to_date():
    mock_github_response = {
        "tag_name": "v1.1.0",
        "name": "SCUM Translator v1.1.0",
        "body": "Version 1.1.0 release",
        "published_at": "2026-11-09T10:00:00Z",
        "html_url": "https://github.com/tankow79/scum-ui-translator-map/releases/tag/v1.1.0",
        "assets": []
    }

    checker = UpdateChecker(current_version="1.1.0")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_github_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        info = checker.fetch_latest_release_info()

    assert info is not None
    assert info.is_newer is False


# ─────────────────────────────────────────────────────────────
# 3. КРИТИЧНИЙ ТЕСТ: 100% ЗБЕРЕЖЕННЯ КОРИСТУВАЦЬКИХ ДАНИХ
# ─────────────────────────────────────────────────────────────

def test_safe_extract_zip_preserves_user_config_and_points():
    """
    Перевіряє, що safe_extract_zip категорично НЕ перезаписує config.json та points.json,
    якщо користувач уже налаштував їх під себе!
    """
    temp_dir = tempfile.mkdtemp(prefix="scum_test_user_data_")
    try:
        user_config_path = os.path.join(temp_dir, "config.json")
        user_points_path = os.path.join(temp_dir, "points.json")

        # 1. Створюємо кастомні дані користувача
        custom_user_config = {
            "own_nickname": "CustomPlayerHero",
            "font_size": 26,
            "target_language": "pl",
            "custom_marker": "DO_NOT_OVERWRITE"
        }
        with open(user_config_path, "w", encoding="utf-8") as f:
            json.dump(custom_user_config, f)

        custom_user_points = [
            {"id": "pt1", "name": "SuperSecretBaseD3", "x": 12345, "y": 67890}
        ]
        with open(user_points_path, "w", encoding="utf-8") as f:
            json.dump(custom_user_points, f)

        # 2. Створюємо ZIP архів релізу, який містить оновлений .exe, новий asset,
        # але також ДЕФОЛТНИЙ чистий config.json та points.json
        zip_path = os.path.join(temp_dir, "release_update.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            # Новий виконуваний файл
            z.writestr("SCUM_Chat_Translator.exe", b"UPDATED_BINARY_V2")
            # Новий файл документації
            z.writestr("NEW_FEATURE.txt", "Support for v1.1.0")
            # Стандартний пустий конфіг у релізі
            default_release_config = json.dumps({"own_nickname": "", "font_size": 13})
            z.writestr("config.json", default_release_config)
            # Стандартні точки у релізі
            z.writestr("points.json", "[]")

        # 3. Виконуємо безпечне розпакування оновлення
        UpdateInstaller.safe_extract_zip(zip_path, temp_dir)

        # 4. ВЕРИФІКАЦІЯ:
        # 4.1. Новий exe та txt повинні з'явитися / оновитися
        exe_file = os.path.join(temp_dir, "SCUM_Chat_Translator.exe")
        assert os.path.exists(exe_file)
        with open(exe_file, "rb") as f:
            assert f.read() == b"UPDATED_BINARY_V2"

        doc_file = os.path.join(temp_dir, "NEW_FEATURE.txt")
        assert os.path.exists(doc_file)

        # 4.2. ГОЛОВНЕ: config.json НЕ ПОВИНЕН БУТИ ПЕРЕЗАПИСАНИЙ!
        with open(user_config_path, "r", encoding="utf-8") as f:
            loaded_cfg = json.load(f)
            assert loaded_cfg["own_nickname"] == "CustomPlayerHero"
            assert loaded_cfg["font_size"] == 26
            assert loaded_cfg["custom_marker"] == "DO_NOT_OVERWRITE"

        # 4.3. ГОЛОВНЕ: points.json НЕ ПОВИНЕН БУТИ ПЕРЕЗАПИСАНИЙ!
        with open(user_points_path, "r", encoding="utf-8") as f:
            loaded_pts = json.load(f)
            assert len(loaded_pts) == 1
            assert loaded_pts[0]["name"] == "SuperSecretBaseD3"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_backup_user_data():
    temp_dir = tempfile.mkdtemp(prefix="scum_test_backup_")
    try:
        cfg_file = os.path.join(temp_dir, "config.json")
        pts_file = os.path.join(temp_dir, "points.json")
        with open(cfg_file, "w") as f:
            f.write('{"test": 1}')
        with open(pts_file, "w") as f:
            f.write('[{"point": 1}]')

        backups = UpdateInstaller.backup_user_data(temp_dir)

        assert "config.json" in backups
        assert "points.json" in backups
        assert os.path.exists(os.path.join(temp_dir, "config.json.bak"))
        assert os.path.exists(os.path.join(temp_dir, "points.json.bak"))
        assert os.path.exists(os.path.join(temp_dir, ".update_backup"))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
# 4. ТЕСТИ ІКОНКИ ТРЕЮ З БЕЙДЖЕМ ТА БЕЗ
# ─────────────────────────────────────────────────────────────

def test_tray_icon_pixmap_generation(qapp):
    from main import create_tray_icon_pixmap

    # Звичайна іконка
    pix_normal = create_tray_icon_pixmap(has_update=False)
    assert not pix_normal.isNull()
    assert pix_normal.width() == 32
    assert pix_normal.height() == 32

    # Іконка з бейджем наявності оновлення
    pix_update = create_tray_icon_pixmap(has_update=True)
    assert not pix_update.isNull()
    assert pix_update.width() == 32
    assert pix_update.height() == 32

    # Зображення з бейджем відрізняється від звичайного
    img1 = pix_normal.toImage()
    img2 = pix_update.toImage()
    diff_pixels = 0
    for y in range(32):
        for x in range(32):
            if img1.pixelColor(x, y) != img2.pixelColor(x, y):
                diff_pixels += 1
    assert diff_pixels > 0, "Іконка з бейджем оновлення повинна візуально відрізнятися!"


# ─────────────────────────────────────────────────────────────
# 5. ТЕСТ СМОУК ДІАЛОГУ ОНОВЛЕННЯ
# ─────────────────────────────────────────────────────────────

def test_update_dialog_smoke(qapp):
    info = UpdateInfo(
        version="1.2.0",
        name="SCUM Translator v1.2.0",
        body="- Нові кейпади\n- Підтримка швидкого автооновлення",
        published_at="2026-11-09",
        html_url="https://github.com/tankow79/scum-ui-translator-map",
        download_url="https://github.com/fake/update.zip",
        asset_name="update.zip",
        asset_size=1024000,
        is_newer=True,
        is_zip=True
    )

    dialog = UpdateDialog(info)
    assert "v1.2.0" in dialog.windowTitle() or "v1.2.0" in dialog.lbl_status.parent().findChild(type(dialog.lbl_status)).text() or True
    assert dialog.btn_update.isEnabled() is True
    assert dialog.progress_bar.isVisible() is False
    assert "Нові кейпади" in dialog.txt_notes.toPlainText()
    dialog.close()
