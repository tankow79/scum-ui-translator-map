"""Update checking, downloading and in-place installation.

Flow
----
1. ``UpdateChecker`` asks the GitHub Releases API for the latest release and picks the best asset
   (an ``.exe`` or a ``.zip`` containing one, matching the normal/portable variant of the running app).
2. ``UpdateDownloader`` saves it to ``%LOCALAPPDATA%\\SCUM_Chat_Translator\\updates`` (``*.part`` while
   in progress), verifying SHA-256 when GitHub provides a digest.
3. ``UpdateInstaller.apply_update`` swaps the running executable in place:
   running .exe -> ``.old`` (Windows allows renaming a loaded image), new .exe -> original path,
   with automatic rollback on failure. No batch scripts, no waiting for the process to exit.
4. ``UpdateInstaller.restart_application`` starts the new executable; the old process then quits.
   ``cleanup_leftovers`` removes ``.old`` files on the next start.

``config.json`` / ``points.json`` / ``profiles.json`` are never touched.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.paths import get_updates_dir
from core.version import (
    GITHUB_ALL_RELEASES_API,
    GITHUB_RELEASES_API,
    GITHUB_REPO_URL,
    __version__,
    is_version_newer,
)

log = logging.getLogger("scum.updater")

PROTECTED_USER_DATA_FILES = ["config.json", "points.json", "profiles.json"]
MIN_EXE_SIZE = 1_000_000  # a real build is tens of MB; anything smaller is an error page / truncated file


class UpdateError(Exception):
    """Raised with a user-presentable message when an update cannot be completed."""


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
    sha256: Optional[str] = None


# ───────────────────────── paths ─────────────────────────

def get_application_root_dir() -> str:
    """Folder containing the running .exe (frozen) or the repository root (source run)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_current_executable_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(os.path.join(get_application_root_dir(), "main.py"))


def is_portable_build(exe_name: Optional[str] = None) -> bool:
    name = (exe_name or os.path.basename(sys.executable)).lower()
    return "portable" in name


# ───────────────────────── release parsing ─────────────────────────

def select_asset(assets: List[Dict[str, Any]], portable: bool = False) -> Optional[Dict[str, Any]]:
    """Choose the release asset matching this build variant. Prefers .exe, then .zip; never source archives."""
    candidates = []
    for a in assets:
        name = str(a.get("name", "")).lower()
        if not a.get("browser_download_url"):
            continue
        if name.endswith(".exe"):
            kind = 0
        elif name.endswith(".zip"):
            kind = 1
        else:
            continue
        if "cert" in name or "source" in name:
            continue
        variant_match = (("portable" in name) == portable)
        candidates.append((0 if variant_match else 1, kind, a))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def _parse_digest(asset: Dict[str, Any]) -> Optional[str]:
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        value = digest.split(":", 1)[1].strip().lower()
        if len(value) == 64:
            return value
    return None


def parse_release(data: Dict[str, Any], current_version: str = __version__,
                  portable: Optional[bool] = None) -> UpdateInfo:
    tag_name = str(data.get("tag_name", "")).strip()
    version = tag_name.lstrip("vV")
    portable = is_portable_build() if portable is None else portable
    asset = select_asset(data.get("assets", []) or [], portable)

    return UpdateInfo(
        version=version,
        name=data.get("name") or f"SCUM Translator {tag_name}",
        body=data.get("body") or "",
        published_at=str(data.get("published_at") or "")[:10],
        html_url=data.get("html_url") or GITHUB_REPO_URL,
        download_url=asset.get("browser_download_url") if asset else None,
        asset_name=asset.get("name") if asset else None,
        asset_size=int(asset.get("size", 0)) if asset else 0,
        is_newer=is_version_newer(current_version, version),
        is_zip=bool(asset and str(asset.get("name", "")).lower().endswith(".zip")),
        sha256=_parse_digest(asset) if asset else None,
    )


class UpdateChecker(QObject):
    """Checks GitHub for a newer release on a background thread."""
    check_started = pyqtSignal()
    update_available = pyqtSignal(object)   # UpdateInfo
    no_update_found = pyqtSignal(str)       # current version
    check_error = pyqtSignal(str)           # error text

    def __init__(self, current_version: str = __version__):
        super().__init__()
        self.current_version = current_version

    def check_for_updates_async(self):
        self.check_started.emit()
        threading.Thread(target=self._worker_check, name="update-check", daemon=True).start()

    def _worker_check(self):
        try:
            info = self.fetch_latest_release_info()
            if info and info.is_newer:
                self.update_available.emit(info)
            else:
                self.no_update_found.emit(self.current_version)
        except Exception as exc:
            log.warning("Update check failed: %s", exc)
            self.check_error.emit(self._friendly_error(exc))

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code == 403:
                return "GitHub rate limit reached. Try again in a few minutes."
            return f"GitHub responded with HTTP {exc.code}."
        if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
            return "No connection to GitHub. Check your internet connection."
        return str(exc)

    def _get_json(self, url: str) -> Any:
        headers = {
            "User-Agent": f"SCUM-Chat-Translator-Updater/{self.current_version}",
            "Accept": "application/vnd.github+json",
        }
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_latest_release_info(self) -> Optional[UpdateInfo]:
        data = None
        try:
            data = self._get_json(GITHUB_RELEASES_API)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

        if not data:  # no "latest" release: fall back to the newest published one
            try:
                releases = self._get_json(GITHUB_ALL_RELEASES_API)
                data = next((r for r in releases if not r.get("draft")), None) if isinstance(releases, list) else None
            except Exception:
                data = None

        if not data:
            return None
        return parse_release(data, self.current_version)


# ───────────────────────── download ─────────────────────────

class UpdateDownloader(QObject):
    """Downloads the update with progress, integrity checking and cancel support."""
    progress = pyqtSignal(int, int, float)  # downloaded, total, percent (0-100)
    finished = pyqtSignal(str)              # final file path
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._cancel_requested = False

    def download_async(self, url: str, filename: Optional[str] = None, expected_sha256: Optional[str] = None):
        self._cancel_requested = False
        threading.Thread(target=self._worker_download, args=(url, filename, expected_sha256),
                         name="update-download", daemon=True).start()

    def cancel(self):
        self._cancel_requested = True

    def _worker_download(self, url: str, filename: Optional[str], expected_sha256: Optional[str]):
        part_path = ""
        try:
            filename = os.path.basename(filename or url.split("?")[0]) or "update.bin"
            dest_path = os.path.join(get_updates_dir(), filename)
            part_path = dest_path + ".part"

            req = urllib.request.Request(url, headers={"User-Agent": f"SCUM-Chat-Translator-Updater/{__version__}"})
            sha = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=30) as response:
                total = int(response.headers.get("Content-Length", 0) or 0)
                downloaded = 0
                with open(part_path, "wb") as f:
                    while True:
                        if self._cancel_requested:
                            raise UpdateError("Download cancelled.")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        sha.update(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total, (downloaded / total * 100.0) if total > 0 else 0.0)

            if total and downloaded != total:
                raise UpdateError("Download was incomplete. Please try again.")
            if expected_sha256 and sha.hexdigest().lower() != expected_sha256.lower():
                raise UpdateError("Downloaded file failed the integrity check (SHA-256 mismatch).")

            os.replace(part_path, dest_path)
            log.info("Update downloaded to %s", dest_path)
            self.finished.emit(dest_path)
        except Exception as exc:
            log.warning("Update download failed: %s", exc)
            if part_path and os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            self.error.emit(str(exc) if isinstance(exc, UpdateError) else self._friendly(exc))

    @staticmethod
    def _friendly(exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            return "Cannot write the update file (permission denied)."
        if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
            return "Download failed. Check your internet connection and try again."
        return str(exc)


# ───────────────────────── install ─────────────────────────

class UpdateInstaller:
    """Installs a downloaded update by swapping the executable in place."""

    @staticmethod
    def backup_user_data(app_dir: str) -> Dict[str, str]:
        """Copy user data files into ``.update_backup/backup_<ts>/`` and next to the originals as ``.bak``."""
        backups: Dict[str, str] = {}
        backup_dir = os.path.join(app_dir, ".update_backup", f"backup_{int(time.time())}")
        for filename in PROTECTED_USER_DATA_FILES:
            src = os.path.join(app_dir, filename)
            if not os.path.exists(src):
                continue
            os.makedirs(backup_dir, exist_ok=True)
            bak = os.path.join(app_dir, f"{filename}.bak")
            shutil.copy2(src, bak)
            shutil.copy2(src, os.path.join(backup_dir, filename))
            backups[filename] = bak
        return backups

    @staticmethod
    def safe_extract_zip(zip_path: str, target_dir: str):
        """Extract an archive without overwriting existing user data and without path traversal."""
        target_root = os.path.realpath(target_dir)
        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.infolist():
                dest = os.path.realpath(os.path.join(target_dir, member.filename))
                if dest != target_root and not dest.startswith(target_root + os.sep):
                    raise UpdateError("Update archive contains an unsafe path.")
                if os.path.basename(member.filename) in PROTECTED_USER_DATA_FILES and os.path.exists(dest):
                    continue
                z.extract(member, target_dir)

    @staticmethod
    def extract_executable(archive_path: str, portable: Optional[bool] = None) -> str:
        """Pull the application .exe out of a release .zip. Returns the extracted path."""
        portable = is_portable_build() if portable is None else portable
        with zipfile.ZipFile(archive_path, "r") as z:
            exes = [m for m in z.infolist() if m.filename.lower().endswith(".exe") and not m.is_dir()]
            if not exes:
                raise UpdateError("The update archive does not contain an application (.exe).")
            exes.sort(key=lambda m: (("portable" in m.filename.lower()) != portable, -m.file_size))
            member = exes[0]
            out_dir = os.path.join(get_updates_dir(), "extracted")
            shutil.rmtree(out_dir, ignore_errors=True)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, os.path.basename(member.filename))
            with z.open(member) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return out_path

    @staticmethod
    def validate_executable(path: str):
        if not os.path.isfile(path) or os.path.getsize(path) < MIN_EXE_SIZE:
            raise UpdateError("The downloaded update is not a valid application file.")
        with open(path, "rb") as f:
            if f.read(2) != b"MZ":
                raise UpdateError("The downloaded update is not a Windows executable.")

    @staticmethod
    def _assert_writable(directory: str):
        probe = os.path.join(directory, f".write_test_{os.getpid()}")
        try:
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
        except OSError as exc:
            raise UpdateError(
                "The installation folder is not writable. Move the application to a normal folder "
                "(for example Documents) or run it as administrator once."
            ) from exc

    @staticmethod
    def apply_update(downloaded_file: str, target_exe: Optional[str] = None) -> str:
        """Replace the running executable with the downloaded build. Returns the path of the new executable.

        Raises ``UpdateError`` (with the original file restored) when anything goes wrong.
        """
        if target_exe is None:
            if not getattr(sys, "frozen", False):
                raise UpdateError(
                    "Automatic installation works only in the packaged .exe. "
                    f"The update was saved to:\n{downloaded_file}"
                )
            target_exe = sys.executable
        target_exe = os.path.abspath(target_exe)
        app_dir = os.path.dirname(target_exe)

        new_exe = downloaded_file
        if downloaded_file.lower().endswith(".zip"):
            new_exe = UpdateInstaller.extract_executable(downloaded_file, is_portable_build(os.path.basename(target_exe)))
        UpdateInstaller.validate_executable(new_exe)
        UpdateInstaller._assert_writable(app_dir)

        try:
            UpdateInstaller.backup_user_data(app_dir)
        except OSError as exc:
            log.warning("User data backup failed: %s", exc)

        staged = target_exe + ".new"
        old = target_exe + ".old"
        try:
            shutil.copy2(new_exe, staged)
            if os.path.exists(old):
                try:
                    os.remove(old)
                except OSError:
                    old = f"{target_exe}.{int(time.time())}.old"
            os.replace(target_exe, old)            # a running image can be renamed, not overwritten
            try:
                os.replace(staged, target_exe)
            except OSError:
                os.replace(old, target_exe)         # rollback
                raise
        except OSError as exc:
            if os.path.exists(staged):
                try:
                    os.remove(staged)
                except OSError:
                    pass
            raise UpdateError(f"Could not install the update: {exc}") from exc

        log.info("Update installed: %s (previous build kept as %s)", target_exe, old)
        return target_exe

    @staticmethod
    def restart_application(exe_path: str):
        """Launch the (new) executable detached. The caller must quit the current process afterwards."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # makes a onefile child extract its own runtime
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        subprocess.Popen([exe_path, "--post-update"], env=env, creationflags=flags,
                         close_fds=True, cwd=os.path.dirname(exe_path))

    @staticmethod
    def cleanup_leftovers():
        """Remove ``.old`` / ``.new`` files from a previous update and stale downloads."""
        try:
            app_dir = get_application_root_dir()
            exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else None
            if exe_name:
                for fname in os.listdir(app_dir):
                    if fname.startswith(exe_name) and fname.endswith((".old", ".new")):
                        try:
                            os.remove(os.path.join(app_dir, fname))
                        except OSError:
                            pass
            updates = get_updates_dir()
            for fname in os.listdir(updates):
                path = os.path.join(updates, fname)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    elif time.time() - os.path.getmtime(path) > 24 * 3600:
                        os.remove(path)
                except OSError:
                    pass
        except OSError as exc:
            log.debug("Cleanup skipped: %s", exc)
