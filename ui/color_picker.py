from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QDialog, QWidget

from core.i18n import tr

# Global state so the game-check timer knows a dialog is open and does not hide windows
is_color_dialog_active: bool = False


def color_dialog_active() -> bool:
    return is_color_dialog_active


def open_safe_color_dialog(
    parent: Optional[QWidget],
    initial_hex: str = "#38bdf8",
    title: Optional[str] = None
) -> Optional[str]:
    """
    Safe color selection that does not minimize the fullscreen SCUM game.
    Uses DontUseNativeDialog (avoids the system Win32 ChooseColor),
    sets WindowStaysOnTopHint and a dark Midnight Cyan style.
    """
    global is_color_dialog_active
    is_color_dialog_active = True
    try:
        dlg = QColorDialog(QColor(initial_hex), parent)
        dlg.setWindowTitle(title or tr("colors.pick_pin_color"))
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dlg.setStyleSheet("""
            QColorDialog {
                background-color: #0b0f19;
                color: #f8fafc;
                border: 2px solid #38bdf8;
                border-radius: 8px;
            }
            QLabel {
                color: #f1f5f9;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 14px;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #0284c7;
                border-color: #38bdf8;
                color: white;
            }
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #ffffff;
                padding: 4px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
            }
            QSpinBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #ffffff;
                padding: 3px;
            }
        """)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected = dlg.selectedColor()
            if selected.isValid():
                return selected.name()
        return None
    finally:
        is_color_dialog_active = False
