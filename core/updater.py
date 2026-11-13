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
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.fileio import atomic_write_json, quarantine_corrupt
from core.paths import get_updates_dir
from core.version import (
    GITHUB_ALL_RELEASES_API,
    GITHUB_RELEASES_API,
    GITHUB_REPO_URL,
    __version__,
    is_version_newer,
)

log = logging.getLogger("scum.updater")

# Downloads are accepted only from GitHub over HTTPS (also after redirects), with sane size limits.
TRUSTED_DOWNLOAD_HOSTS = ("github.com", "githubusercontent.com")
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
_SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]*\.(exe|zip)$", re.IGNORECASE)
SELF_TEST_TIMEOUT = 60  # seconds the downloaded build gets to start up and pass its self-test
PROTECTED_USER_DATA_FILES = ["config.json", "points.json", "profiles.json", "players.json"]
MIN_EXE_SIZE = 1_000_000  # a real build is tens of MB; anything smaller is an error page / truncated file


class UpdateError(Exception):
    """Raised with a user-presentable message when an update cannot be completed."""


# English message patterns -> locale keys. Messages stay English in logs and exceptions; the UI shows the
# translated text through ``localize_error`` (unknown messages are shown as they are).
_ERROR_PATTERNS = (
    (r"GitHub rate limit reached", "update_errors.rate_limit"),
    (r"GitHub responded with HTTP (?P<code>\d+)", "update_errors.http"),
    (r"No connection to GitHub", "update_errors.no_connection"),
    (r"Download cancelled", "update_errors.cancelled"),
    (r"The update address is not a trusted GitHub address", "update_errors.untrusted_url"),
    (r"The update is unexpectedly large", "update_errors.too_large"),
    (r"The update file name is not allowed", "update_errors.bad_name"),
    (r"The downloaded version changed while it was being checked", "update_errors.changed"),
    (r"No checksum is published for this update", "update_errors.no_checksum"),
    (r"Download was incomplete", "update_errors.incomplete"),
    (r"Downloaded file failed the integrity check", "update_errors.integrity"),
    (r"Cannot write the update file", "update_errors.write_denied"),
    (r"Download failed", "update_errors.download_failed"),
    (r"Could not back up your settings, so the update was cancelled: (?P<detail>.*)", "update_errors.backup_failed"),
    (r"Update archive contains an unsafe path", "update_errors.unsafe_zip"),
    (r"The update archive does not contain an application", "update_errors.no_exe"),
    (r"The downloaded update is not a valid application file", "update_errors.invalid_file"),
    (r"The downloaded update is not a Windows executable", "update_errors.not_exe"),
    (r"The installation folder is not writable", "update_errors.not_writable"),
    (r"Automatic installation works only in the packaged \.exe\. The update was saved to:\n(?P<path>.*)",
     "update_errors.source_run"),
    (r"Could not install the update: (?P<detail>.*)", "update_errors.install_failed"),
    (r"The downloaded version did not start in time", "update_errors.selftest_timeout"),
    (r"The downloaded version could not be started and was not installed: (?P<detail>.*)",
     "update_errors.selftest_start"),
    (r"The downloaded version failed its start-up check and was not installed\. "
     r"Your current version is unchanged\. \((?P<detail>.*)\)", "update_errors.selftest_failed"),
)


def localize_error(message: str) -> str:
    """Translate a known updater error message into the interface language."""
    from core.i18n import tr

    for pattern, key in _ERROR_PATTERNS:
        m = re.match(pattern, message or "", re.DOTALL)
        if m:
            text = tr(key, **m.groupdict())
            return text if text != key else message
    return message


def is_trusted_url(url: object) -> bool:
    """True for an https:// address on github.com or *.githubusercontent.com."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in TRUSTED_DOWNLOAD_HOSTS)


def safe_release_page(url: Optional[str]) -> str:
    """The release page to open in a browser: only this project's GitHub pages, else the repository."""
    if url and is_trusted_url(url) and urllib.parse.urlparse(url).hostname == "github.com" \
            and url.startswith(GITHUB_REPO_URL):
        return url
    return GITHUB_REPO_URL


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
    """True for the portable edition: the bundled ``portable.flag`` (survives renaming the exe) or the file name."""
    if exe_name is None and getattr(sys, "frozen", False):
        if os.path.exists(os.path.join(getattr(sys, "_MEIPASS", ""), "portable.flag")):
            return True
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


def _is_old_build(filename: str, exe_name: str) -> bool:
    """``app.exe.old`` or ``app.exe.<timestamp>.old`` for exactly this executable."""
    return re.fullmatch(re.escape(exe_name) + r"(\.\d+)?\.old", filename) is not None


def _trusted_download_url(asset: Optional[Dict[str, Any]]) -> Optional[str]:
    """The asset's download address, or None when the address or the file name is not acceptable."""
    if not asset:
        return None
    url, name = asset.get("browser_download_url"), str(asset.get("name") or "")
    if not is_trusted_url(url) or not _SAFE_ASSET_NAME.match(name):
        log.warning("Ignoring update asset with an untrusted address or name: %r %r", url, name)
        return None
    return url


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
        html_url=safe_release_page(data.get("html_url")),
        download_url=_trusted_download_url(asset),
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
        self._cancel = threading.Event()

    def download_async(self, url: str, filename: Optional[str] = None, expected_sha256: Optional[str] = None):
        # Every download gets its own cancel token, so a late cancel of an old one cannot affect a new one
        self._cancel = threading.Event()
        threading.Thread(target=self._worker_download, args=(url, filename, expected_sha256, self._cancel),
                         name="update-download", daemon=True).start()

    def cancel(self):
        self._cancel.set()

    def _worker_download(self, url: str, filename: Optional[str], expected_sha256: Optional[str],
                         cancel: Optional[threading.Event] = None):
        cancel = cancel or self._cancel
        part_path = ""
        try:
            if not is_trusted_url(url):
                raise UpdateError("The update address is not a trusted GitHub address and was not downloaded.")
            filename = os.path.basename(filename or url.split("?")[0]) or "update.bin"
            if not _SAFE_ASSET_NAME.match(filename):
                raise UpdateError("The update file name is not allowed and the update was not downloaded.")
            dest_path = os.path.join(get_updates_dir(), filename)
            part_path = dest_path + ".part"

            req = urllib.request.Request(url, headers={"User-Agent": f"SCUM-Chat-Translator-Updater/{__version__}"})
            sha = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=30) as response:
                if not is_trusted_url(response.geturl()):   # a redirect must stay on GitHub
                    raise UpdateError("The update address is not a trusted GitHub address and was not downloaded.")
                total = int(response.headers.get("Content-Length", 0) or 0)
                if total > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("The update is unexpectedly large and was not downloaded.")
                downloaded = 0
                with open(part_path, "wb") as f:
                    while True:
                        if cancel.is_set():
                            raise UpdateError("Download cancelled.")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        sha.update(chunk)
                        downloaded += len(chunk)
                        if downloaded > MAX_DOWNLOAD_BYTES:
                            raise UpdateError("The update is unexpectedly large and was not downloaded.")
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
            if cancel.is_set():
                return  # the user cancelled: nothing to report, and a stale thread must not touch a new download
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

    BACKUP_DIR_NAME = ".update_backup"

    @staticmethod
    def _sha256_file(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_valid_json(path: str) -> bool:
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def backup_user_data(app_dir: str) -> Dict[str, str]:
        """Copy user data into ``.update_backup/backup_<ts>/`` and verify every copy byte-for-byte.

        Raises ``UpdateError`` (before anything is changed) when a copy cannot be made or does not match.
        Older backup folders are removed so only the newest one exists.
        """
        root = os.path.join(app_dir, UpdateInstaller.BACKUP_DIR_NAME)
        backup_dir = os.path.join(root, f"backup_{int(time.time())}")
        backups: Dict[str, str] = {}
        unreadable: List[str] = []
        try:
            for filename in PROTECTED_USER_DATA_FILES:
                src = os.path.join(app_dir, filename)
                if not os.path.exists(src):
                    continue
                if not UpdateInstaller._is_valid_json(src):
                    unreadable.append(filename)   # do not back up a damaged file over a good older backup
                    continue
                os.makedirs(backup_dir, exist_ok=True)
                dst = os.path.join(backup_dir, filename)
                shutil.copy2(src, dst)
                if UpdateInstaller._sha256_file(src) != UpdateInstaller._sha256_file(dst):
                    raise OSError(f"backup of {filename} does not match the original")
                backups[filename] = dst
        except OSError as exc:
            raise UpdateError(f"Could not back up your settings, so the update was cancelled: {exc}") from exc
        if backups and not unreadable and os.path.isdir(root):  # keep only the newest backup; never drop a good one
            for entry in os.listdir(root):
                full = os.path.join(root, entry)
                if full != backup_dir and os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
        return backups

    @staticmethod
    def _backup_sources(app_dir: str) -> Dict[str, List[str]]:
        """Backup candidates per protected file: newest ``.update_backup`` copy first, legacy ``.bak`` last."""
        result: Dict[str, List[str]] = {name: [] for name in PROTECTED_USER_DATA_FILES}
        root = os.path.join(app_dir, UpdateInstaller.BACKUP_DIR_NAME)
        if os.path.isdir(root):
            for entry in sorted(os.listdir(root), reverse=True):
                for name in PROTECTED_USER_DATA_FILES:
                    candidate = os.path.join(root, entry, name)
                    if os.path.isfile(candidate):
                        result[name].append(candidate)
        for name in PROTECTED_USER_DATA_FILES:
            legacy = os.path.join(app_dir, f"{name}.bak")
            if os.path.isfile(legacy):
                result[name].append(legacy)
        return result

    @staticmethod
    def restore_damaged_user_data(app_dir: Optional[str] = None) -> List[str]:
        """Run at startup BEFORE the settings are loaded: restore a user file that vanished or became unreadable.

        Returns the names of the files that were restored. Healthy files are never touched.
        """
        app_dir = app_dir or get_application_root_dir()
        restored: List[str] = []
        for name, candidates in UpdateInstaller._backup_sources(app_dir).items():
            target = os.path.join(app_dir, name)
            if os.path.exists(target) and UpdateInstaller._is_valid_json(target):
                continue
            for candidate in candidates:
                if UpdateInstaller._is_valid_json(candidate):
                    try:
                        if os.path.exists(target):
                            quarantine_corrupt(target)
                        shutil.copy2(candidate, target)
                        restored.append(name)
                        log.warning("Restored %s from backup %s", name, candidate)
                    except OSError as exc:
                        log.error("Could not restore %s: %s", name, exc)
                    break
        return restored

    @staticmethod
    def remove_backups(app_dir: Optional[str] = None) -> bool:
        """Delete update backups once the app runs fine. Skipped (backups kept) if any user file is missing/invalid."""
        app_dir = app_dir or get_application_root_dir()
        sources = UpdateInstaller._backup_sources(app_dir)
        for name, candidates in sources.items():
            if candidates and not UpdateInstaller._is_valid_json(os.path.join(app_dir, name)):
                log.warning("Keeping update backups: %s is missing or unreadable", name)
                return False
        for candidates in sources.values():
            for candidate in candidates:
                if candidate.endswith(".bak"):
                    try:
                        os.remove(candidate)
                    except OSError as exc:
                        log.debug("Could not delete %s: %s", candidate, exc)
        shutil.rmtree(os.path.join(app_dir, UpdateInstaller.BACKUP_DIR_NAME), ignore_errors=True)
        return True

    @staticmethod
    def safe_extract_zip(zip_path: str, target_dir: str):
        """Extract an archive without overwriting existing user data and without path traversal."""
        target_root = os.path.realpath(target_dir)
        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.infolist():
                dest = os.path.realpath(os.path.join(target_dir, member.filename))
                is_symlink = (member.external_attr >> 16) & 0o170000 == 0o120000
                try:
                    inside = os.path.commonpath([target_root, dest]) == target_root
                except ValueError:  # different drives
                    inside = False
                if not inside or is_symlink or os.path.isabs(member.filename):
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
            if member.file_size > MAX_DOWNLOAD_BYTES:
                raise UpdateError("The update is unexpectedly large and was not downloaded.")
            out_dir = os.path.join(get_updates_dir(), "extracted")
            shutil.rmtree(out_dir, ignore_errors=True)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, os.path.basename(member.filename))
            with z.open(member) as src, open(out_path, "wb") as dst:
                written = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:   # a lying size header (zip bomb)
                        raise UpdateError("The update is unexpectedly large and was not downloaded.")
                    dst.write(chunk)
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
    def apply_update(downloaded_file: str, target_exe: Optional[str] = None, self_test: bool = True) -> str:
        """Replace the running executable with the downloaded build. Returns the path of the new executable.

        Raises ``UpdateError`` (with the original file restored) when anything goes wrong.
        """
        running_build = target_exe is None
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
            new_exe = UpdateInstaller.extract_executable(
                downloaded_file, is_portable_build() if running_build else is_portable_build(os.path.basename(target_exe)))
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
            # Test and install the very same file: nothing can swap it between the check and the install.
            staged_hash = UpdateInstaller._sha256_file(staged)
            if self_test:
                UpdateInstaller.self_test(staged)
                if UpdateInstaller._sha256_file(staged) != staged_hash:
                    raise UpdateError("The downloaded version changed while it was being checked and was not installed.")
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
        except (OSError, UpdateError) as exc:
            if os.path.exists(staged):
                try:
                    os.remove(staged)
                except OSError:
                    pass
            if isinstance(exc, UpdateError):
                raise
            raise UpdateError(f"Could not install the update: {exc}") from exc

        log.info("Update installed: %s (previous build kept as %s)", target_exe, old)
        return target_exe

    @staticmethod
    def _clean_child_env() -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # makes a onefile child extract its own runtime
        return env

    @staticmethod
    def _kill_process_tree(proc):
        """Kill a started build including the child a onefile exe unpacks (it would otherwise be orphaned)."""
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            proc.kill()
        except OSError:
            pass

    @staticmethod
    def self_test(exe_path: str, timeout: float = SELF_TEST_TIMEOUT):
        """Start the downloaded build in ``--smoke-test`` mode (isolated data folder, no single-instance
        lock) and require it to finish cleanly. Raises ``UpdateError`` otherwise, so a broken build is
        never installed over a working one.
        """
        data_dir = tempfile.mkdtemp(prefix="scum_selftest_")
        env = UpdateInstaller._clean_child_env()
        env["SCUM_DATA_DIR"] = data_dir
        report_path = os.path.join(data_dir, "smoke-result.txt")
        try:
            try:
                proc = subprocess.Popen(
                    [exe_path, "--smoke-test"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    returncode = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    UpdateInstaller._kill_process_tree(proc)
                    raise UpdateError("The downloaded version did not start in time and was not installed. "
                                      "Your current version is unchanged.") from exc
            except OSError as exc:
                raise UpdateError(f"The downloaded version could not be started and was not installed: {exc}") from exc
            report = ""
            try:
                with open(report_path, encoding="utf-8") as f:
                    report = f.read().strip()
            except OSError:
                pass
            if returncode != 0 or not report.startswith("OK"):
                detail = (report or f"exit code {returncode}").splitlines()[-1][:200]
                raise UpdateError("The downloaded version failed its start-up check and was not installed. "
                                  f"Your current version is unchanged. ({detail})")
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    @staticmethod
    def rollback_failed_update(target_exe: Optional[str] = None) -> Optional[str]:
        """After a start-up crash of a freshly installed build: put the previous build (``.old``) back.

        Returns the restored executable path, or None when there is nothing to roll back to.
        """
        if target_exe is None:
            if not getattr(sys, "frozen", False):
                return None
            target_exe = sys.executable
        target_exe = os.path.abspath(target_exe)
        app_dir, exe_name = os.path.dirname(target_exe), os.path.basename(target_exe)
        try:
            olds = [os.path.join(app_dir, f) for f in os.listdir(app_dir) if _is_old_build(f, exe_name)]
        except OSError:
            return None
        if not olds:
            return None
        previous = max(olds, key=os.path.getmtime)
        broken = target_exe + ".broken"
        try:
            if os.path.exists(broken):
                os.remove(broken)
            os.replace(target_exe, broken)
            try:
                os.replace(previous, target_exe)
            except OSError:
                os.replace(broken, target_exe)
                raise
        except OSError as exc:
            log.error("Rollback failed: %s", exc)
            return None
        log.warning("The new build failed to start; restored the previous build %s", target_exe)
        return target_exe

    # ── run state: detects a build that keeps crashing after it has started (not only at start-up) ──
    RUN_STATE_FILE = "run_state.json"
    HEALTHY_AFTER_SECONDS = 600      # a run this long proves the build is fine
    CRASH_STRIKES_FOR_ROLLBACK = 2   # consecutive unclean runs that each ended within HEALTHY_AFTER_SECONDS

    @staticmethod
    def _run_state_path() -> str:
        from core.paths import get_user_data_dir
        return os.path.join(get_user_data_dir(), UpdateInstaller.RUN_STATE_FILE)

    @staticmethod
    def _read_run_state() -> Dict[str, Any]:
        try:
            with open(UpdateInstaller._run_state_path(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_run_state(state: Dict[str, Any]) -> None:
        try:
            atomic_write_json(UpdateInstaller._run_state_path(), state)
        except OSError as exc:
            log.debug("Could not write the run state: %s", exc)

    @staticmethod
    def record_run_start(version: str, now: Optional[float] = None) -> int:
        """Note that this run started and return how many consecutive earlier runs of THIS version crashed.

        A crash is a run that never reached a clean exit and died within ``HEALTHY_AFTER_SECONDS``. Closing a
        run cleanly, or one that lived long enough, resets the count.
        """
        now = time.time() if now is None else now
        previous = UpdateInstaller._read_run_state()
        strikes = 0
        try:
            if previous.get("version") == version and not previous.get("clean", True):
                lived = float(previous.get("alive", 0)) - float(previous.get("started", 0))
                if lived < UpdateInstaller.HEALTHY_AFTER_SECONDS:
                    strikes = int(previous.get("strikes", 0)) + 1
        except (TypeError, ValueError):
            strikes = 0
        UpdateInstaller._write_run_state({"version": version, "started": now, "alive": now, "clean": False,
                                          "strikes": strikes})
        return strikes

    @staticmethod
    def record_heartbeat(now: Optional[float] = None) -> float:
        """Called every few seconds while the app runs. Returns how long this run has lasted."""
        now = time.time() if now is None else now
        state = UpdateInstaller._read_run_state()
        if not state:
            return 0.0
        state["alive"] = now
        UpdateInstaller._write_run_state(state)
        try:
            return max(0.0, now - float(state.get("started", now)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def record_clean_exit() -> None:
        state = UpdateInstaller._read_run_state()
        if state:
            state["clean"] = True
            state["strikes"] = 0
            UpdateInstaller._write_run_state(state)

    @staticmethod
    def should_roll_back(strikes: int) -> bool:
        return strikes >= UpdateInstaller.CRASH_STRIKES_FOR_ROLLBACK

    @staticmethod
    def remove_previous_versions(app_dir: Optional[str] = None) -> int:
        """Delete ``.old`` builds once the new version has proven healthy. Returns how many were removed."""
        removed = 0
        try:
            app_dir = app_dir or get_application_root_dir()
            exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else None
            if not exe_name:
                return 0
            for fname in os.listdir(app_dir):
                if _is_old_build(fname, exe_name):
                    try:
                        os.remove(os.path.join(app_dir, fname))
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
        return removed

    @staticmethod
    def restart_application(exe_path: str):
        """Launch the (new) executable detached. The caller must quit the current process afterwards."""
        env = UpdateInstaller._clean_child_env()
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        subprocess.Popen([exe_path, "--post-update"], env=env, creationflags=flags,
                         close_fds=True, cwd=os.path.dirname(exe_path))

    @staticmethod
    def cleanup_leftovers():
        """Remove ``.new`` / ``.broken`` files and stale downloads. ``.old`` builds stay until the new
        version has run healthy (see ``remove_previous_versions``) so a failed start can roll back."""
        try:
            app_dir = get_application_root_dir()
            exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else None
            if exe_name:
                for fname in os.listdir(app_dir):
                    if fname in (exe_name + ".new", exe_name + ".broken"):
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
