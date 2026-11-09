"""
Діалогове вікно оновлення програми SCUM Chat Translator.
Відображає інформацію про новий реліз, список змін, гарантію збереження
персональних налаштувань та виконує завантаження та безшовне оновлення в 1 клік.
"""

import os
import webbrowser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QProgressBar, QFrame, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon

from core.version import __version__, GITHUB_REPO_URL
from core.updater import UpdateInfo, UpdateDownloader, UpdateInstaller


class UpdateDialog(QDialog):
    """
    Сучасне вікно сповіщення про доступне оновлення у стилі Midnight Cyan.
    """
    def __init__(self, update_info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.downloader = UpdateDownloader()

        self.setWindowTitle("🚀 Оновлення програми")
        self.resize(520, 480)
        self.setMinimumSize(460, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #0b0f19;
                color: #e2e8f0;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel {
                color: #e2e8f0;
            }
            QTextEdit {
                background-color: #0f172a;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                line-height: 1.4;
            }
            QProgressBar {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 6px;
                text-align: center;
                color: #38bdf8;
                font-weight: bold;
                height: 22px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0284c7, stop:1 #38bdf8);
                border-radius: 5px;
            }
        """)

        self.setup_ui()
        self.setup_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 1. Заголовок і версії
        header_box = QHBoxLayout()
        header_box.setSpacing(12)

        icon_lbl = QLabel("🚀")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 28))
        header_box.addWidget(icon_lbl)

        v_title = QVBoxLayout()
        v_title.setSpacing(2)
        lbl_title = QLabel("Доступна нова версія!")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
        v_title.addWidget(lbl_title)

        lbl_versions = QLabel(
            f"Ваша версія: <span style='color: #94a3b8;'>v{__version__}</span> ➔ "
            f"Нова версія: <span style='color: #22c55e; font-weight: bold;'>v{self.update_info.version}</span>"
        )
        lbl_versions.setStyleSheet("font-size: 13px;")
        v_title.addWidget(lbl_versions)
        header_box.addLayout(v_title)
        header_box.addStretch()

        layout.addLayout(header_box)

        # 2. Банер гарантії збереження налаштувань
        shield_frame = QFrame()
        shield_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(34, 197, 94, 0.12);
                border: 1px solid rgba(34, 197, 94, 0.35);
                border-radius: 8px;
                padding: 6px 10px;
            }
        """)
        h_shield = QHBoxLayout(shield_frame)
        h_shield.setContentsMargins(8, 6, 8, 6)
        h_shield.setSpacing(8)

        lbl_shield_icon = QLabel("🛡️")
        lbl_shield_icon.setFont(QFont("Segoe UI Emoji", 16))
        h_shield.addWidget(lbl_shield_icon)

        lbl_shield_text = QLabel(
            "<b>100% безпечне оновлення:</b> Усі ваші налаштування (<b>config.json</b>) "
            "та збережені координати (<b>points.json</b>) залишаться без змін!"
        )
        lbl_shield_text.setStyleSheet("color: #86efac; font-size: 12px;")
        lbl_shield_text.setWordWrap(True)
        h_shield.addWidget(lbl_shield_text, 1)

        layout.addWidget(shield_frame)

        # 3. Список змін (Release Notes)
        lbl_notes = QLabel("Список змін та покращень:")
        lbl_notes.setStyleSheet("font-size: 13px; font-weight: bold; color: #94a3b8;")
        layout.addWidget(lbl_notes)

        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        notes_text = self.update_info.body.strip() if self.update_info.body else "Покращення стабільності та виправлення помилок."
        self.txt_notes.setText(notes_text)
        layout.addWidget(self.txt_notes, 1)

        # 4. Прогрес-бар та статусний текст (приховані до старту завантаження)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #94a3b8;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        # 5. Кнопки управління
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_github = QPushButton("🌐 Сторінка релізу")
        self.btn_github.setFixedHeight(36)
        self.btn_github.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #e2e8f0;
            }
        """)
        self.btn_github.clicked.connect(self.open_github_release)
        btn_layout.addWidget(self.btn_github)

        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Пізніше")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: white;
            }
        """)
        self.btn_cancel.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_update = QPushButton("⚡ Оновити в 1 клік")
        self.btn_update.setFixedHeight(36)
        self.btn_update.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: white;
                border: 1px solid #0ea5e9;
                border-radius: 6px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748b;
                border-color: #475569;
            }
        """)
        self.btn_update.clicked.connect(self.start_update)
        btn_layout.addWidget(self.btn_update)

        layout.addLayout(btn_layout)

    def setup_signals(self):
        self.downloader.progress.connect(self.on_download_progress)
        self.downloader.finished.connect(self.on_download_finished)
        self.downloader.error.connect(self.on_download_error)

    def open_github_release(self):
        url = self.update_info.html_url or GITHUB_REPO_URL
        webbrowser.open(url)

    def start_update(self):
        if not self.update_info.download_url:
            self.lbl_status.setText("⚠️ Посилання для прямого завантаження відсутнє. Відкриваємо GitHub...")
            self.lbl_status.setStyleSheet("color: #f59e0b; font-size: 12px;")
            self.lbl_status.setVisible(True)
            self.open_github_release()
            return

        self.btn_update.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_github.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.lbl_status.setVisible(True)
        self.lbl_status.setText("Запуск завантаження оновлення...")
        self.lbl_status.setStyleSheet("color: #38bdf8; font-size: 12px;")

        self.downloader.download_async(
            self.update_info.download_url,
            self.update_info.asset_name
        )

    def on_download_progress(self, downloaded: int, total: int, percent: float):
        self.progress_bar.setValue(int(percent))
        dl_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024) if total > 0 else 0
        if total > 0:
            self.lbl_status.setText(f"Завантаження: {dl_mb:.1f} МБ / {total_mb:.1f} МБ ({percent:.1f}%)")
        else:
            self.lbl_status.setText(f"Завантаження: {dl_mb:.1f} МБ...")

    def on_download_finished(self, file_path: str):
        self.progress_bar.setValue(100)
        self.lbl_status.setText("✅ Завантаження завершено! Застосування оновлення...")
        self.lbl_status.setStyleSheet("color: #22c55e; font-size: 12px; font-weight: bold;")

        # Запуск фонового скрипта оновлення Windows
        success = UpdateInstaller.launch_windows_updater(file_path)
        if success:
            self.lbl_status.setText("🚀 Перезапуск програми...")
            # Закриваємо поточний додаток для того, щоб скрипт замінив виконувані файли
            QApplication.instance().quit()
        else:
            self.lbl_status.setText("❌ Помилка запуску оновлювача Windows.")
            self.lbl_status.setStyleSheet("color: #ef4444; font-size: 12px;")
            self.btn_cancel.setEnabled(True)

    def on_download_error(self, err_msg: str):
        self.lbl_status.setText(f"❌ Помилка завантаження: {err_msg}")
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 12px;")
        self.btn_update.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.btn_github.setEnabled(True)
