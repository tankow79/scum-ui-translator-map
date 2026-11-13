"""Shared, good-looking message boxes (icon on the left, centred-looking text block, translated buttons)."""
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.i18n import tr

_ICONS = {"question": ("?", "#38bdf8"), "info": ("i", "#38bdf8"), "warning": ("!", "#fbbf24"), "error": ("✕", "#ef4444")}

STYLE = """
    QDialog { background-color: #0b0f19; }
    QLabel#icon { font-size: 22px; font-weight: 800; color: #0b0f19; border-radius: 22px; background: %(color)s; }
    QLabel#title { color: #f8fafc; font-size: 14px; font-weight: 700; }
    QLabel#text { color: #cbd5e1; font-size: 12px; }
    QPushButton { background-color: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px;
                  padding: 7px 22px; font-size: 12px; font-weight: 600; min-width: 70px; }
    QPushButton:hover { border-color: #38bdf8; }
    QPushButton#primary { background-color: #0e7490; border-color: #38bdf8; color: #ffffff; }
    QPushButton#primary:hover { background-color: #0891b2; }
    QPushButton#danger { background-color: #b91c1c; border-color: #ef4444; color: #ffffff; }
    QPushButton#danger:hover { background-color: #dc2626; }
"""


class MessageDialog(QDialog):
    def __init__(self, parent, title: str, text: str, kind: str = "info", yes: Optional[str] = None,
                 no: Optional[str] = None, danger: bool = False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        glyph, color = _ICONS.get(kind, _ICONS["info"])
        self.setStyleSheet(STYLE % {"color": color})

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(20)
        row = QHBoxLayout()
        row.setSpacing(18)
        icon = QLabel(glyph)
        icon.setObjectName("icon")
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(text)
        label.setObjectName("text")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(label, 1)
        root.addLayout(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.btn_yes = self.btn_no = None
        if yes is None:
            ok = QPushButton(tr("common.ok"))
            ok.setObjectName("primary")
            ok.setDefault(True)
            ok.clicked.connect(self.accept)
            buttons.addWidget(ok)
        else:
            self.btn_yes = QPushButton(yes)
            self.btn_yes.setObjectName("danger" if danger else "primary")
            self.btn_no = QPushButton(no or tr("common.no"))
            self.btn_yes.clicked.connect(self.accept)
            self.btn_no.clicked.connect(self.reject)
            buttons.addWidget(self.btn_yes)
            buttons.addWidget(self.btn_no)
        root.addLayout(buttons)
        if self.btn_no is not None:
            self.btn_yes.setAutoDefault(False)
            self.btn_no.setDefault(True)  # the safe answer is the default
            self.btn_no.setFocus()


def ask(parent, title: str, text: str, yes: Optional[str] = None, no: Optional[str] = None,
        danger: bool = False) -> bool:
    """Yes/No question; "No" is the default and Escape means no."""
    dialog = MessageDialog(parent, title, text, "question", yes or tr("common.yes"), no, danger)
    return dialog.exec() == QDialog.DialogCode.Accepted


def notify(parent, title: str, text: str, kind: str = "info") -> None:
    MessageDialog(parent, title, text, kind).exec()
