"""Compact, Steam-style update window: prompt -> download with progress -> install -> restart."""

import logging
import os
import subprocess
import threading
import time
import webbrowser
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.updater import (
    UpdateDownloader,
    UpdateError,
    UpdateInfo,
    UpdateInstaller,
    localize_error,
    safe_release_page,
)
from core.version import __version__

log = logging.getLogger("scum.update_dialog")

STYLE = """
QFrame#card { background-color: #0f1623; border: 1px solid #25324a; border-radius: 10px; }
QLabel { color: #cbd5e1; font-family: 'Segoe UI', Arial, sans-serif; background: transparent; }
QLabel#title { color: #f1f5f9; font-size: 15px; font-weight: 600; }
QLabel#sub { color: #8fa3bf; font-size: 12px; }
QLabel#info { color: #8fa3bf; font-size: 11px; }
QLabel#error { color: #f87171; font-size: 12px; }
QTextEdit { background-color: #0b111c; color: #b6c4d8; border: 1px solid #1c2840; border-radius: 6px;
            padding: 6px; font-size: 12px; font-family: 'Segoe UI', Arial, sans-serif; }
QPushButton { background-color: #1a2438; color: #cbd5e1; border: 1px solid #2a3957; border-radius: 6px;
              padding: 6px 16px; font-size: 12px; font-family: 'Segoe UI', Arial, sans-serif; }
QPushButton:hover { background-color: #243350; color: #ffffff; }
QPushButton#primary { background-color: #1a8fe3; border: 1px solid #3aa6f5; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background-color: #2b9df0; }
QPushButton#close { background: transparent; border: none; color: #6b7d99; font-size: 14px; padding: 0 4px; }
QPushButton#close:hover { color: #ffffff; }
QPushButton#link { background: transparent; border: none; color: #4aa8ff; padding: 0; text-align: left; font-size: 11px; }
QPushButton#link:hover { color: #8ccaff; }
"""


class SteamProgressBar(QWidget):
    """Slim progress bar with a moving shimmer; supports an indeterminate mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._value = 0.0           # 0..1
        self._indeterminate = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def set_value(self, fraction: float):
        self._indeterminate = False
        self._value = max(0.0, min(1.0, fraction))
        self.update()

    def set_indeterminate(self, on: bool = True):
        self._indeterminate = on
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        if self.isVisible():
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b111c"))
        p.drawRoundedRect(rect, radius, radius)

        if self._indeterminate:
            width = rect.width() * 0.3
            x = (rect.width() + width) * self._phase - width
            bar = QRectF(max(0.0, x), 0, min(width, rect.width() - max(0.0, x), x + width), rect.height())
        else:
            bar = QRectF(0, 0, rect.width() * self._value, rect.height())
        if bar.width() <= 0:
            return

        grad = QLinearGradient(QPointF(bar.left(), 0), QPointF(bar.right(), 0))
        grad.setColorAt(0.0, QColor("#1a8fe3"))
        grad.setColorAt(1.0, QColor("#5cc0ff"))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(bar, radius, radius)

        # shimmer highlight sweeping across the filled part
        if not self._indeterminate:
            sx = bar.width() * self._phase
            shine = QLinearGradient(QPointF(sx - 40, 0), QPointF(sx + 40, 0))
            shine.setColorAt(0.0, QColor(255, 255, 255, 0))
            shine.setColorAt(0.5, QColor(255, 255, 255, 70))
            shine.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setClipRect(bar)
            p.setBrush(QBrush(shine))
            p.drawRoundedRect(bar, radius, radius)
        p.setPen(QPen(Qt.PenStyle.NoPen))


class UpdateDialog(QDialog):
    """States: prompt -> downloading -> installing -> restarting (or error)."""

    _install_done = pyqtSignal(str)
    _install_failed = pyqtSignal(str)

    def __init__(self, update_info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.downloader = UpdateDownloader()
        self._downloaded_path: Optional[str] = None
        self._drag_pos = None
        self._started_at = 0.0
        self._speed = 0.0
        self._last_sample = (0.0, 0)
        self._busy = False

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(STYLE)
        self.setFixedWidth(420)

        self._build_ui()
        self.downloader.progress.connect(self._on_progress)
        self.downloader.finished.connect(self._on_downloaded)
        self.downloader.error.connect(self._on_download_error)
        self._install_done.connect(self._on_installed)
        self._install_failed.connect(self._on_error)
        self._show_prompt()

    # ── UI construction ──────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("title")
        top.addWidget(self.lbl_title, 1)
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("close")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self._close_requested)
        top.addWidget(self.btn_close)
        lay.addLayout(top)

        self.lbl_sub = QLabel()
        self.lbl_sub.setObjectName("sub")
        lay.addWidget(self.lbl_sub)

        self.bar = SteamProgressBar()
        lay.addWidget(self.bar)

        self.lbl_info = QLabel()
        self.lbl_info.setObjectName("info")
        self.lbl_info.setWordWrap(True)
        lay.addWidget(self.lbl_info)

        self.lbl_error = QLabel()
        self.lbl_error.setObjectName("error")
        self.lbl_error.setWordWrap(True)
        lay.addWidget(self.lbl_error)

        self.btn_details = QPushButton()
        self.btn_details.setObjectName("link")
        self.btn_details.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_details.clicked.connect(self._toggle_notes)
        lay.addWidget(self.btn_details, 0, Qt.AlignmentFlag.AlignLeft)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setFixedHeight(130)
        self.notes.setPlainText(self.update_info.body.strip() or tr("update.no_notes"))
        self.notes.setVisible(False)
        lay.addWidget(self.notes)

        self.btn_file = QPushButton(tr("update.btn_show_file"))
        self.btn_file.setObjectName("link")
        self.btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_file.clicked.connect(self._show_file)
        lay.addWidget(self.btn_file, 0, Qt.AlignmentFlag.AlignLeft)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        self.btn_secondary = QPushButton()
        self.btn_secondary.clicked.connect(self._on_secondary)
        row.addWidget(self.btn_secondary)
        self.btn_primary = QPushButton()
        self.btn_primary.setObjectName("primary")
        self.btn_primary.clicked.connect(self._on_primary)
        row.addWidget(self.btn_primary)
        lay.addLayout(row)

    # ── states ───────────────────────────────────────────────────────
    def _set_state(self, state: str):
        self._state = state
        self.bar.setVisible(state in ("downloading", "installing", "restarting"))
        self.btn_details.setVisible(state in ("prompt", "error"))
        self.notes.setVisible(self.notes.isVisible() and state in ("prompt", "error"))
        self.btn_file.setVisible(state == "error" and bool(self._downloaded_path))
        self.lbl_error.setVisible(state == "error")
        self.lbl_info.setVisible(state != "error")
        self.btn_primary.setVisible(state in ("prompt", "error"))
        self.btn_secondary.setVisible(state in ("prompt", "downloading", "error"))
        self.btn_close.setVisible(state != "restarting")
        self.adjustSize()

    def _show_prompt(self):
        self.lbl_title.setText(tr("update.title_available"))
        self.lbl_sub.setText(tr("update.versions", current=__version__, new=self.update_info.version))
        self.lbl_info.setText(tr("update.safe_note"))
        self.btn_details.setText(tr("update.whats_new"))
        self.btn_primary.setText(tr("update.btn_update"))
        self.btn_secondary.setText(tr("update.btn_later"))
        self._set_state("prompt")

    def _show_downloading(self):
        self.lbl_title.setText(tr("update.downloading"))
        self.lbl_info.setText("")
        self.btn_secondary.setText(tr("update.btn_cancel"))
        self.bar.set_value(0.0)
        self._set_state("downloading")

    def _show_installing(self):
        self.lbl_title.setText(tr("update.installing"))
        self.lbl_info.setText(tr("update.verifying"))
        self.bar.set_indeterminate(True)
        self._set_state("installing")

    def _show_error(self, message: str):
        self.lbl_title.setText(tr("update.error_title"))
        self.lbl_error.setText(localize_error(message))
        self.btn_primary.setText(tr("update.btn_retry"))
        self.btn_secondary.setText(tr("update.btn_release_page"))
        self.btn_details.setText(tr("update.whats_new"))
        self._set_state("error")

    # ── actions ──────────────────────────────────────────────────────
    def _on_primary(self):
        if self._state == "prompt" or self._state == "error":
            self._start_download()

    def _on_secondary(self):
        if self._state == "downloading":
            self.downloader.cancel()
            self._show_prompt()
        elif self._state == "error":
            self._open_release_page()
        else:
            self.reject()

    def _close_requested(self):
        if self._state in ("installing", "restarting"):
            return
        if self._state == "downloading":
            self.downloader.cancel()
        self.reject()

    def _toggle_notes(self):
        self.notes.setVisible(not self.notes.isVisible())
        self.btn_details.setText(tr("update.hide_details") if self.notes.isVisible() else tr("update.whats_new"))
        self.adjustSize()

    def _open_release_page(self):
        webbrowser.open(safe_release_page(self.update_info.html_url))

    def _show_file(self):
        if self._downloaded_path and os.path.exists(self._downloaded_path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self._downloaded_path)])

    def _start_download(self):
        info = self.update_info
        if not info.download_url:
            self._open_release_page()
            self._show_error(tr("update.no_direct_link"))
            return
        if not info.sha256:
            # Without a published checksum the file cannot be verified: never install it automatically
            self._open_release_page()
            self._show_error(tr("update_errors.no_checksum"))
            return
        self._show_downloading()
        self._started_at = time.monotonic()
        self._last_sample = (self._started_at, 0)
        self._speed = 0.0
        self.downloader.download_async(info.download_url, info.asset_name, info.sha256)

    def _on_progress(self, downloaded: int, total: int, percent: float):
        if self._state != "downloading":
            return
        now = time.monotonic()
        t0, b0 = self._last_sample
        if now - t0 >= 0.5:
            inst = (downloaded - b0) / (now - t0)
            self._speed = inst if self._speed == 0 else self._speed * 0.7 + inst * 0.3
            self._last_sample = (now, downloaded)

        mb = 1024 * 1024
        speed_txt = f"{self._speed / mb:.1f}"
        if total > 0:
            self.bar.set_value(downloaded / total)
            text = tr("update.progress", done=f"{downloaded / mb:.1f}", total=f"{total / mb:.1f}", speed=speed_txt)
            if self._speed > 0:
                text += "  ·  " + tr("update.eta", seconds=int((total - downloaded) / self._speed))
        else:
            self.bar.set_indeterminate(True)
            text = tr("update.progress_unknown", done=f"{downloaded / mb:.1f}", speed=speed_txt)
        self.lbl_info.setText(text)

    def _on_downloaded(self, path: str):
        self._downloaded_path = path
        self._busy = True
        self._show_installing()
        threading.Thread(target=self._install_worker, args=(path,), name="update-install", daemon=True).start()

    def _install_worker(self, path: str):
        try:
            new_exe = UpdateInstaller.apply_update(path)
            self._install_done.emit(new_exe)
        except UpdateError as exc:
            self._install_failed.emit(str(exc))
        except Exception as exc:  # unexpected: still surface it instead of hanging the dialog
            log.exception("Update installation crashed")
            self._install_failed.emit(str(exc))

    def _on_installed(self, exe_path: str):
        self.lbl_title.setText(tr("update.restarting"))
        self.lbl_info.setText("")
        self._set_state("restarting")
        try:
            UpdateInstaller.restart_application(exe_path)
        except OSError as exc:
            self._on_error(tr("update.restart_failed", error=str(exc)))
            return
        app = QApplication.instance()
        if app:
            app.quit()
        # Safety net: background threads must not keep the old process alive. A plain thread timer is used
        # because the Qt event loop has already been asked to quit and would never run a QTimer.
        killer = threading.Timer(4.0, os._exit, args=(0,))
        killer.daemon = True
        killer.start()

    def _on_download_error(self, message: str):
        # A cancelled download must not flip the dialog into an error state
        if self._state == "downloading":
            self._on_error(message)

    def reject(self):
        # Closing mid-install would leave a half-replaced application: ignore Esc and the close button
        if self._state in ("installing", "restarting"):
            return
        super().reject()

    def _on_error(self, message: str):
        self._busy = False
        self.bar.set_indeterminate(False)
        self._show_error(message)

    # ── frameless window dragging ────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._state not in ("installing", "restarting"):
            self._close_requested()
            return
        super().keyPressEvent(event)
