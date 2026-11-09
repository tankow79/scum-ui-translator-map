"""
Модуль перевірки, завантаження та автоматичного оновлення програми SCUM Chat Translator.
Забезпечує:
- Асинхронну перевірку нових версій через GitHub Releases API без зависання UI;
- Відображення прогресу завантаження оновлення;
- Гарантоване збереження всіх персональних налаштувань (config.json) та збережених точок (points.json);
- Безшовне оновлення в 1 клік на Windows із перезапуском програми.
"""

import os
import sys
import json
import time
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal

from core.version import (
    __version__, __app_name__, GITHUB_RELEASES_API,
    GITHUB_ALL_RELEASES_API, GITHUB_REPO_URL, is_version_newer
)


@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    content_type: str


@dataclass
class UpdateInfo:
    version: str
    name: str
    body: str
    published_at: str
    html_url: str
    download_url: Optional[str]
    asset_name: Optional[str]
    asset_size: int
    is_newer: bool
    is_zip: bool


PROTECTED_USER_DATA_FILES = ["config.json", "points.json"]


def get_application_root_dir() -> str:
    """
    Повертає робочу директорію програми (папку з .exe при frozen або корінь репозиторію).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_current_executable_path() -> str:
    """
    Повертає повний шлях до поточного виконуваного файлу чи точки входу.
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(os.path.join(get_application_root_dir(), "main.py"))


class UpdateChecker(QObject):
    """
    Асинхронний перевіряльник наявності свіжих релізів на GitHub.
    """
    check_started = pyqtSignal()
    update_available = pyqtSignal(object)   # UpdateInfo
    no_update_found = pyqtSignal(str)       # current version
    check_error = pyqtSignal(str)           # error text

    def __init__(self, current_version: str = __version__):
        super().__init__()
        self.current_version = current_version
        self._executor = ThreadPoolExecutor(max_workers=1)

    def check_for_updates_async(self):
        """Запуск перевірки у фоновому потоці."""
        self.check_started.emit()
        self._executor.submit(self._worker_check)

    def _worker_check(self):
        try:
            info = self.fetch_latest_release_info()
            if not info:
                self.no_update_found.emit(self.current_version)
            elif info.is_newer:
                self.update_available.emit(info)
            else:
                self.no_update_found.emit(self.current_version)
        except Exception as e:
            self.check_error.emit(str(e))

    def fetch_latest_release_info(self) -> Optional[UpdateInfo]:
        """
        Синхронний запит до GitHub API для отримання інформації про останній реліз.
        """
        headers = {
            "User-Agent": f"SCUM-Chat-Translator-Updater/{self.current_version}",
            "Accept": "application/vnd.github.v3+json"
        }

        # 1. Спроба отримати latest release
        req = urllib.request.Request(GITHUB_RELEASES_API, headers=headers)
        data = None
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Релізів немає або вони ще не опубліковані
                data = None
            else:
                raise
        except Exception:
            raise

        # 2. Якщо latest release повернув 404, перевіряємо список усіх релізів (включаючи пре-релізи)
        if not data:
            req_all = urllib.request.Request(GITHUB_ALL_RELEASES_API, headers=headers)
            try:
                with urllib.request.urlopen(req_all, timeout=10) as response:
                    if response.status == 200:
                        all_releases = json.loads(response.read().decode("utf-8"))
                        if all_releases and isinstance(all_releases, list):
                            data = all_releases[0]
            except Exception:
                pass

        if not data:
            return None

        tag_name = data.get("tag_name", "").strip()
        version = tag_name.lstrip("vV")
        name = data.get("name", "") or f"SCUM Translator {tag_name}"
        body = data.get("body", "") or "Опис оновлення відсутній."
        published_at = data.get("published_at", "")[:10]
        html_url = data.get("html_url", GITHUB_REPO_URL)

        # Пошук найкращого ассету для завантаження:
        # Пріоритет: .zip архів із готовим білдом, потім .exe
        assets = data.get("assets", [])
        best_url = None
        best_name = None
        best_size = 0
        is_zip = False

        for asset in assets:
            a_name = asset.get("name", "")
            a_url = asset.get("browser_download_url", "")
            a_size = asset.get("size", 0)
            if a_name.lower().endswith(".zip"):
                best_url = a_url
                best_name = a_name
                best_size = a_size
                is_zip = True
                break
            elif a_name.lower().endswith(".exe") and not best_url:
                best_url = a_url
                best_name = a_name
                best_size = a_size
                is_zip = False

        # Fallback на zipball репозиторію, якщо окремих бінарників ще не прикріплено
        if not best_url:
            best_url = data.get("zipball_url")
            best_name = f"{tag_name}.zip"
            best_size = 0
            is_zip = True

        newer = is_version_newer(self.current_version, version)

        return UpdateInfo(
            version=version,
            name=name,
            body=body,
            published_at=published_at,
            html_url=html_url,
            download_url=best_url,
            asset_name=best_name,
            asset_size=best_size,
            is_newer=newer,
            is_zip=is_zip
        )


class UpdateDownloader(QObject):
    """
    Завантажувач файлу оновлення з відстеженням прогресу в байтах та відсотках.
    """
    progress = pyqtSignal(int, int, float)  # downloaded, total, percent (0-100)
    finished = pyqtSignal(str)             # downloaded file path
    error = pyqtSignal(str)                # error message

    def __init__(self):
        super().__init__()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._cancel_requested = False

    def download_async(self, url: str, filename: Optional[str] = None):
        self._cancel_requested = False
        self._executor.submit(self._worker_download, url, filename)

    def cancel(self):
        self._cancel_requested = True

    def _worker_download(self, url: str, filename: Optional[str] = None):
        try:
            if not filename:
                filename = url.split("/")[-1].split("?")[0] or "update.bin"

            temp_dir = tempfile.mkdtemp(prefix="scum_updater_")
            dest_path = os.path.join(temp_dir, filename)

            headers = {"User-Agent": f"SCUM-Chat-Translator-Updater/{__version__}"}
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 64 * 1024  # 64 KB

                with open(dest_path, "wb") as f:
                    while True:
                        if self._cancel_requested:
                            raise RuntimeError("Завантаження скасовано користувачем.")
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = (downloaded / total_size * 100.0) if total_size > 0 else 0.0
                        self.progress.emit(downloaded, total_size, percent)

            self.finished.emit(dest_path)
        except Exception as e:
            self.error.emit(str(e))


class UpdateInstaller:
    """
    Менеджер встановлення оновлення з абсолютним захистом користувацьких даних.
    """

    @staticmethod
    def backup_user_data(app_dir: str) -> Dict[str, str]:
        """
        Створює локальні копії .bak та архівний бекап у папці .update_backup/
        для всіх критичних файлів користувача (config.json, points.json).
        """
        backups = {}
        backup_dir = os.path.join(app_dir, ".update_backup", f"backup_{int(time.time())}")
        os.makedirs(backup_dir, exist_ok=True)

        for filename in PROTECTED_USER_DATA_FILES:
            src_path = os.path.join(app_dir, filename)
            if os.path.exists(src_path):
                # 1. Поруч у .bak
                bak_path = os.path.join(app_dir, f"{filename}.bak")
                shutil.copy2(src_path, bak_path)
                # 2. В окрему папку бекапу
                archive_path = os.path.join(backup_dir, filename)
                shutil.copy2(src_path, archive_path)
                backups[filename] = bak_path

        return backups

    @staticmethod
    def safe_extract_zip(zip_path: str, target_dir: str):
        """
        Безпечно розпаковує архів, категорично ігноруючи файли користувача (config.json, points.json),
        якщо вони вже існують у цільовій папці.
        """
        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.infolist():
                # Нормалізація шляху для уникнення path traversal
                filename = os.path.basename(member.filename)
                if filename in PROTECTED_USER_DATA_FILES:
                    dest = os.path.join(target_dir, filename)
                    if os.path.exists(dest):
                        # Пропускаємо, щоб зберегти налаштування користувача!
                        continue
                z.extract(member, target_dir)

    @staticmethod
    def launch_windows_updater(downloaded_file: str, current_pid: Optional[int] = None,
                               app_dir: Optional[str] = None) -> bool:
        """
        Генерує та запускає автономний detached .bat скрипт, який:
        1. Чекає завершення роботи поточного процесу програми;
        2. Бекапить config.json та points.json;
        3. Розпаковує/замінює оновлені файли;
        4. Відновлює config.json та points.json у разі потреби;
        5. Перезапускає оновлений додаток;
        6. Видаляє себе.
        """
        if app_dir is None:
            app_dir = get_application_root_dir()

        if current_pid is None:
            current_pid = os.getpid()

        is_frozen = getattr(sys, "frozen", False)
        exe_path = sys.executable if is_frozen else os.path.join(app_dir, "run.bat")
        if not os.path.exists(exe_path) and not is_frozen:
            exe_path = os.path.join(app_dir, "main.py")

        is_zip = downloaded_file.lower().endswith(".zip")
        script_path = os.path.join(app_dir, "_apply_update.bat")

        # Формуємо надійний Windows CMD скрипт
        bat_lines = [
            "@echo off",
            "chcp 65001 >nul",
            "setlocal enabledelayedexpansion",
            f"echo [SCUM Translator] Очікування завершення попереднього процесу (PID: {current_pid})...",
            "",
            ":wait_loop",
            f'tasklist /FI "PID eq {current_pid}" 2>nul | findstr /I "{current_pid}" >nul',
            "if not errorlevel 1 (",
            "    timeout /t 1 /nobreak >nul",
            "    goto wait_loop",
            ")",
            "timeout /t 1 /nobreak >nul",
            "",
            f'cd /d "{app_dir}"',
            "echo [SCUM Translator] Створення безпечного бекапу налаштувань...",
            'if exist "config.json" copy /y "config.json" "config.json.bak" >nul',
            'if exist "points.json" copy /y "points.json" "points.json.bak" >nul',
            "",
        ]

        if is_zip:
            staging_dir = os.path.join(tempfile.gettempdir(), f"scum_staging_{int(time.time())}")
            bat_lines.extend([
                f'echo [SCUM Translator] Розпакування оновлення...',
                f'if exist "{staging_dir}" rmdir /s /q "{staging_dir}"',
                f'powershell -NoProfile -Command "Expand-Archive -Path \'{downloaded_file}\' -DestinationPath \'{staging_dir}\' -Force"',
                "",
                f'echo [SCUM Translator] Захист персональних даних гравця...',
                f'if exist "{staging_dir}\\config.json" del /f /q "{staging_dir}\\config.json"',
                f'if exist "{staging_dir}\\points.json" del /f /q "{staging_dir}\\points.json"',
                "",
                f'echo [SCUM Translator] Копіювання оновлених файлів програми...',
                f'xcopy /e /y /q "{staging_dir}\\*" "{app_dir}\\" >nul',
                f'rmdir /s /q "{staging_dir}" 2>nul',
            ])
        else:
            # Пряма заміна одиночного exe-файлу
            target_exe = os.path.basename(downloaded_file)
            if is_frozen:
                target_exe = os.path.basename(sys.executable)
            bat_lines.extend([
                f'echo [SCUM Translator] Заміна виконуваного файлу...',
                f'copy /y "{downloaded_file}" "{os.path.join(app_dir, target_exe)}" >nul',
            ])

        bat_lines.extend([
            "",
            "echo [SCUM Translator] Фінальна перевірка збереження конфігурації...",
            'if not exist "config.json" if exist "config.json.bak" copy /y "config.json.bak" "config.json" >nul',
            'if not exist "points.json" if exist "points.json.bak" copy /y "points.json.bak" "points.json" >nul',
            "",
            "echo [SCUM Translator] Перезапуск оновленої програми...",
            f'start "" "{exe_path}"',
            "",
            "timeout /t 1 /nobreak >nul",
            f'del /f /q "{downloaded_file}" 2>nul',
            '(goto) 2>nul & del "%~f0"',
            "exit",
        ])

        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\r\n".join(bat_lines))

        # Запуск bat скрипта у повністю відокремленому процесі без блокування
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(
            ["cmd.exe", "/c", script_path],
            creationflags=flags,
            close_fds=True,
            shell=False
        )
        return True
