"""Layout that wraps its items onto new lines when the width is not enough (good for button rows)."""

from PyQt6 import sip
from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def _live_items(self):
        """The items whose widget still exists: a row whose widgets were deleted must never be measured (it crashes Qt)."""
        alive = []
        for item in self._items:
            if sip.isdeleted(item):
                continue
            widget = item.widget()
            if widget is not None and sip.isdeleted(widget):
                continue
            alive.append(item)
        return alive

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._live_items():
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._live_items():
            hint = item.sizeHint()
            if hint.width() > area.width() > 0:
                hint = QSize(area.width(), hint.height())  # too wide for one line: let the item shrink
            next_x = x + hint.width()
            if next_x > area.right() + 1 and line_height > 0:
                x = area.x()
                y += line_height + self._spacing
                next_x = x + hint.width()
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


def button_row(*widgets, spacing: int = 8) -> FlowLayout:
    """A row of widgets that wraps to extra lines instead of stretching the window."""
    layout = FlowLayout(spacing=spacing)
    for w in widgets:
        layout.addWidget(w)
    return layout


__all__ = ["FlowLayout", "button_row"]
