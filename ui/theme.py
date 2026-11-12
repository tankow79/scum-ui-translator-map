"""Shared dark theme (Midnight Cyan) for dialogs and reusable styled helpers."""

BG = "#0b111c"
SURFACE = "#111a2b"
SURFACE_ALT = "#16213a"
BORDER = "#26344d"
TEXT = "#e2e8f0"
MUTED = "#8fa3bf"
ACCENT = "#38bdf8"
ACCENT_DARK = "#0284c7"
OK = "#10b981"
DANGER = "#ef4444"

DIALOG_QSS = f"""
* {{ font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; }}
QDialog, QWidget#page {{ background-color: {BG}; color: {TEXT};
    font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; font-size: 12px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 11px; font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; }}
QLabel[role="section"] {{ color: {ACCENT}; font-size: 11px; font-weight: 700; }}
QLabel[role="title"] {{ color: #f8fafc; font-size: 16px; font-weight: 600; }}
QLabel[role="value"] {{ color: {ACCENT}; font-weight: 600; }}
QFrame[role="rule"] {{ background-color: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}

QListWidget#nav {{ background-color: {SURFACE}; border: none; border-right: 1px solid {BORDER}; outline: 0; padding: 8px 6px; }}
QListWidget#nav::item {{ color: {MUTED}; padding: 9px 12px; border-radius: 6px; margin: 1px 0; }}
QListWidget#nav::item:hover {{ background-color: {SURFACE_ALT}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background-color: {SURFACE_ALT}; color: {ACCENT}; font-weight: 600; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 6px; color: #f8fafc; padding: 5px 8px; min-height: 20px; selection-background-color: {ACCENT_DARK}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background-color: {SURFACE}; color: #f8fafc; border: 1px solid {ACCENT};
    selection-background-color: {ACCENT_DARK}; selection-color: #ffffff; padding: 4px; outline: 0; }}
QListWidget {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; outline: 0; }}
QListWidget::item {{ padding: 7px 10px; border-radius: 4px; color: {TEXT}; }}
QListWidget::item:selected {{ background-color: {ACCENT_DARK}; color: #ffffff; }}

QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #475569; background-color: {SURFACE}; }}
QCheckBox::indicator:checked {{ background-color: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ background-color: {BG}; border-color: {BORDER}; }}

QSlider::groove:horizontal {{ height: 6px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_DARK}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: #7dd3fc; }}

QPushButton {{ background-color: {SURFACE_ALT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background-color: #1f2d4a; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #5b6b85; }}
QPushButton[role="primary"] {{ background-color: {ACCENT_DARK}; border-color: {ACCENT}; color: #ffffff; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background-color: #0e90d9; }}
QPushButton[role="danger"]:hover {{ background-color: #7f1d1d; border-color: {DANGER}; }}
QPushButton[role="icon"] {{ padding: 0; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4d6e; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{ background-color: {SURFACE_ALT}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
"""


def mnemonic_safe(text: str) -> str:
    """Escape ``&`` so Qt shows it literally instead of treating it as a keyboard mnemonic (menus, buttons)."""
    return text.replace("&", "&&")


def repolish(widget) -> None:
    """Re-apply the stylesheet after a dynamic property (``role``) was changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)

MENU_QSS = f"""
QMenu {{ background-color: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
    font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; font-size: 12px; }}
QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background-color: {SURFACE_ALT}; color: {ACCENT}; }}
QMenu::item:disabled {{ color: #5b6b85; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
"""

# Application-wide rules for stock dialogs (message boxes, input dialogs), menus and tooltips.
APP_QSS = MENU_QSS + f"""
QMessageBox, QInputDialog {{ background-color: {BG}; color: {TEXT}; font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; }}
QMessageBox QLabel, QInputDialog QLabel {{ color: {TEXT}; background: transparent; font-size: 12px; min-width: 260px; }}
QMessageBox QPushButton, QInputDialog QPushButton {{ background-color: {SURFACE_ALT}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 6px 16px; min-width: 70px; }}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {{ background-color: #1f2d4a; border-color: {ACCENT}; }}
QMessageBox QPushButton:default, QInputDialog QPushButton:default {{ background-color: {ACCENT_DARK}; border-color: {ACCENT}; color: #ffffff; }}
QInputDialog QLineEdit {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; color: #f8fafc; padding: 5px 8px;
    selection-background-color: {ACCENT_DARK}; selection-color: #ffffff; }}
QToolTip {{ background-color: {SURFACE_ALT}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
"""
