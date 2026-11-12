"""Reusable, language-proof building blocks for the settings dialog.

Design rules that keep every translation readable:
* labels wrap instead of being cut off (no fixed label widths);
* a control sits under its label (or beside it only when both are short);
* checkboxes wrap their text;
* value badges are sized from the widest value they can show.
"""

from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)


def muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setProperty("role", "muted")
    return lbl


class ElideButton(QPushButton):
    """Push button that shrinks below its text width: the caption is elided with "…" and shown fully as tooltip."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._custom_tooltip = ""
        # Preferred (not Minimum) so layouts may squeeze the button down to minimumSizeHint.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def setToolTip(self, tip: str):  # noqa: N802 - Qt API
        self._custom_tooltip = tip
        super().setToolTip(tip)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(80, super().sizeHint().height())

    def paintEvent(self, _event):  # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        available = max(10, self.width() - 28)
        elided = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, available)
        option.text = elided
        if not self._custom_tooltip:
            QPushButton.setToolTip(self, self.text() if elided != self.text() else "")
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


def make_button(text: str, role: Optional[str] = None, tooltip: str = "") -> QPushButton:
    btn = ElideButton(text)
    if role:
        btn.setProperty("role", role)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class WrapCheck(QWidget):
    """Checkbox whose text wraps onto several lines. API mirrors the parts of QCheckBox we use."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, hint: str = "", parent=None):
        super().__init__(parent)
        self._box = QCheckBox()
        self._box.setFixedWidth(18)
        self._box.toggled.connect(self.toggled)
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.mousePressEvent = lambda _e: self._box.toggle() if self._box.isEnabled() else None

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(self._label)
        if hint:
            text_col.addWidget(muted_label(hint))

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._box, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text_col, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def isChecked(self) -> bool:
        return self._box.isChecked()

    def setChecked(self, value: bool):
        self._box.setChecked(bool(value))

    def setEnabled(self, enabled: bool):  # noqa: N802 - Qt naming
        super().setEnabled(enabled)
        self._label.setEnabled(enabled)

    def text(self) -> str:
        return self._label.text()


class Section(QWidget):
    """Titled group: small accent heading, a thin rule and its rows underneath."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(10)
        head = QLabel(title.upper())
        head.setProperty("role", "section")
        head.setWordWrap(True)
        rule = QFrame()
        rule.setProperty("role", "rule")
        rule.setFrameShape(QFrame.Shape.HLine)
        self._lay.addWidget(head)
        self._lay.addWidget(rule)

    def add_widget(self, widget: QWidget):
        self._lay.addWidget(widget)
        return widget

    def add_layout(self, layout):
        self._lay.addLayout(layout)

    def add_field(self, label: str, control: QWidget, hint: str = ""):
        """Label on top (wraps), control below at full width, optional muted hint."""
        box = QVBoxLayout()
        box.setSpacing(4)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        box.addWidget(lbl)
        if isinstance(control, QComboBox):  # never let the longest item dictate the window width
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            control.setMinimumContentsLength(12)
        box.addWidget(control)
        if hint:
            box.addWidget(muted_label(hint))
        self._lay.addLayout(box)
        return control

    def add_check(self, check: WrapCheck):
        self._lay.addWidget(check)
        return check


class SliderRow(QWidget):
    """Label (wraps) with its current value on the right and the slider underneath."""

    def __init__(self, label: str, minimum: int, maximum: int, widest_value_text: str, parent=None):
        super().__init__(parent)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.value_label = QLabel(widest_value_text)
        self.value_label.setProperty("role", "value")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setMinimumWidth(self.value_label.sizeHint().width())

        lbl = QLabel(label)
        lbl.setWordWrap(True)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(lbl, 1)
        top.addWidget(self.value_label, 0)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addLayout(top)
        col.addWidget(self.slider)


class SettingsPage(QScrollArea):
    """Vertically scrolling page that never needs a horizontal scrollbar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(22, 18, 22, 18)
        self.body_layout.setSpacing(22)
        self.setWidget(body)

    def add_section(self, section: QWidget):
        self.body_layout.addWidget(section)
        return section

    def finish(self):
        self.body_layout.addStretch(1)
