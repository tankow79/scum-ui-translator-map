"""Chat history viewer with search, filters and export (TXT / CSV / JSON)."""

import logging
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.chat_history import ChatHistory, HistoryEntry
from core.i18n import tr

log = logging.getLogger("scum.history_window")

MAX_ROWS = 2000

STYLE = """
QWidget#history { background-color: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; }
QLabel { color: #94a3b8; font-size: 12px; }
QLineEdit, QComboBox { background-color: #0b111c; border: 1px solid #334155; border-radius: 5px;
                       color: #f8fafc; padding: 4px 8px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #38bdf8; }
QComboBox QAbstractItemView { background-color: #0b111c; color: #f8fafc; selection-background-color: #0284c7; }
QCheckBox { color: #cbd5e1; spacing: 6px; }
QTableWidget { background-color: #0b111c; alternate-background-color: #0f172a; color: #e2e8f0;
               gridline-color: #1e293b; border: 1px solid #334155; border-radius: 6px; }
QTableWidget::item:selected { background-color: #0369a1; }
QHeaderView::section { background-color: #1e293b; color: #94a3b8; border: none; padding: 5px; font-weight: 600; }
QPushButton { background-color: #1e293b; color: #cbd5e1; border: 1px solid #334155; border-radius: 6px; padding: 5px 14px; }
QPushButton:hover { background-color: #334155; color: #ffffff; }
QPushButton#primary { background-color: #0284c7; border-color: #0ea5e9; color: white; font-weight: 600; }
QPushButton#danger:hover { background-color: #7f1d1d; border-color: #ef4444; }
"""

TYPE_COLORS = {"squad": "#4ade80", "server": "#fbbf24"}


class HistoryWindow(QWidget):
    def __init__(self, history: ChatHistory, parent=None):
        super().__init__(parent)
        self.setObjectName("history")
        self.history = history
        self._shown_revision = -1
        self._rows: List[HistoryEntry] = []
        self.setWindowTitle(tr("history.title"))
        self.resize(900, 520)
        self.setStyleSheet(STYLE)
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_if_changed)
        self._timer.start(700)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        filters = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(tr("history.search"))
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._reload)
        filters.addWidget(self.txt_search, 3)

        self.combo_sender = QComboBox()
        self.combo_sender.currentIndexChanged.connect(self._reload)
        filters.addWidget(self.combo_sender, 2)

        self.combo_type = QComboBox()
        self.combo_type.addItem(tr("history.type_all"), "")
        self.combo_type.addItem(tr("history.type_player"), "player")
        self.combo_type.addItem(tr("history.type_squad"), "squad")
        self.combo_type.addItem(tr("history.type_server"), "server")
        self.combo_type.currentIndexChanged.connect(self._reload)
        filters.addWidget(self.combo_type, 1)

        self.chk_translated = QCheckBox(tr("history.translated_only"))
        self.chk_translated.toggled.connect(self._reload)
        filters.addWidget(self.chk_translated)
        root.addLayout(filters)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr("history.col_time"), tr("history.col_type"), tr("history.col_sender"),
            tr("history.col_original"), tr("history.col_translation"),
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.lbl_count = QLabel()
        bottom.addWidget(self.lbl_count, 1)
        self.chk_autoscroll = QCheckBox(tr("history.autoscroll"))
        self.chk_autoscroll.setChecked(True)
        bottom.addWidget(self.chk_autoscroll)

        btn_export = QPushButton(tr("history.export"))
        btn_export.setObjectName("primary")
        btn_export.clicked.connect(self._export)
        bottom.addWidget(btn_export)
        btn_clear = QPushButton(tr("history.clear"))
        btn_clear.setObjectName("danger")
        btn_clear.clicked.connect(self._clear)
        bottom.addWidget(btn_clear)
        root.addLayout(bottom)

    # ── data ─────────────────────────────────────────────────────────
    def _refresh_senders(self):
        current = self.combo_sender.currentData()
        self.combo_sender.blockSignals(True)
        self.combo_sender.clear()
        self.combo_sender.addItem(tr("history.all_senders"), "")
        for name in self.history.senders():
            self.combo_sender.addItem(name, name)
        idx = self.combo_sender.findData(current)
        self.combo_sender.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_sender.blockSignals(False)

    def _refresh_if_changed(self):
        if self.isVisible() and self.history.revision != self._shown_revision:
            self._reload()

    def _reload(self, *_):
        self._shown_revision = self.history.revision
        if self.combo_sender.count() == 0 or len(self.history.senders()) != self.combo_sender.count() - 1:
            self._refresh_senders()
        self._rows = self.history.query(
            text=self.txt_search.text(),
            sender=self.combo_sender.currentData() or "",
            msg_type=self.combo_type.currentData() or "",
            translated_only=self.chk_translated.isChecked(),
        )
        visible = self._rows[-MAX_ROWS:]
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(visible))
        for r, e in enumerate(visible):
            cells = [e.time_str, e.msg_type, e.sender, e.original, e.translated if e.was_translated else ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                color = TYPE_COLORS.get(e.msg_type)
                if color and c in (1, 2):
                    item.setForeground(Qt.GlobalColor.green if color == "#4ade80" else Qt.GlobalColor.yellow)
                self.table.setItem(r, c, item)
        self.table.resizeRowsToContents()
        self.table.setUpdatesEnabled(True)
        self.lbl_count.setText(tr("history.count", shown=len(visible), total=len(self.history)))
        if self.chk_autoscroll.isChecked():
            self.table.scrollToBottom()

    def showEvent(self, event):
        self._reload()
        super().showEvent(event)

    # ── actions ──────────────────────────────────────────────────────
    def _export(self):
        path, selected = QFileDialog.getSaveFileName(
            self, tr("history.export"), "scum_chat_history.txt",
            "Text (*.txt);;CSV (*.csv);;JSON (*.json)",
        )
        if not path:
            return
        fmt = "csv" if "csv" in selected.lower() else "json" if "json" in selected.lower() else "txt"
        if "." not in path.rsplit("\\", 1)[-1]:
            path += f".{fmt}"
        try:
            count = self.history.export(path, self._rows)
            QMessageBox.information(self, tr("history.title"), tr("history.export_done", count=count, path=path))
        except (OSError, ValueError) as exc:
            log.warning("History export failed: %s", exc)
            QMessageBox.warning(self, tr("history.title"), tr("history.export_failed", error=str(exc)))

    def _clear(self):
        answer = QMessageBox.question(self, tr("history.title"), tr("history.clear_confirm"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self._reload()
