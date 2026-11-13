"""Settings -> Players: the nickname <-> SteamID base collected automatically from the game logs."""

import html
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.players import PlayerRegistry, steam_profile_url
from ui.dialogs import ask
from ui.flow_layout import button_row
from ui.settings_widgets import Section, make_button, muted_label

ROLE_SID = Qt.ItemDataRole.UserRole
ROLE_OLD_INDEX = Qt.ItemDataRole.UserRole + 1
ROLE_OLD_AT = Qt.ItemDataRole.UserRole + 2


def _format_date(ts: float) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


class PlayersPage(QWidget):
    """Tree of players: the current nickname with a clickable SteamID; players who renamed expand
    into a list of old nicknames with the date of each change."""

    def __init__(self, registry: Optional[PlayerRegistry], parent=None):
        super().__init__(parent)
        self.registry = registry
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        section = Section(tr("players.title"))
        section.add_widget(muted_label(tr("players.hint")))

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("players.search_placeholder"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        section.add_widget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("players.col_nick"), tr("players.col_steam")])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setMinimumHeight(240)
        self.tree.setStyleSheet(
            "QTreeWidget { background-color: #0f172a; border: 1px solid #26344d; border-radius: 6px; }"
            "QTreeWidget::item { padding: 3px 2px; }"
            "QTreeWidget::item:selected { background-color: #0c4a6e; color: #ffffff; }"
            "QHeaderView::section { background-color: #111a2b; color: #94a3b8; border: none; padding: 4px 6px; }"
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 180)   # wide enough for a 17-digit SteamID link (the cell widget is not measured)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        section.add_widget(self.tree)

        self.btn_del_old = make_button(tr("players.delete_old"), "danger")
        self.btn_del_player = make_button(tr("players.delete_player"), "danger")
        self.btn_clear = make_button(tr("players.clear_all"), "danger")
        self.btn_del_old.clicked.connect(self._delete_old_nick)
        self.btn_del_player.clicked.connect(self._delete_player)
        self.btn_clear.clicked.connect(self._clear_all)
        section.add_layout(button_row(self.btn_del_old, self.btn_del_player, self.btn_clear))

        self.lbl_status = QLabel("")
        self.lbl_status.setProperty("role", "muted")
        self.lbl_status.setWordWrap(True)
        section.add_widget(self.lbl_status)
        root.addWidget(section)

        self._dirty = False
        if registry is not None:
            registry.data_changed.connect(self.refresh)
        self._rebuild()

    # ── view ─────────────────────────────────────────────────────────
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self._rebuild()

    def refresh(self, *_):
        """Registry changed (or the search text did): rebuild now if visible, otherwise on the next show."""
        if self.isVisible():
            self._rebuild()
        else:
            self._dirty = True

    def _rebuild(self):
        self._dirty = False
        if self.registry is None:
            return
        expanded = {self.tree.topLevelItem(i).data(0, ROLE_SID)
                    for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).isExpanded()}
        selected = self._selected()
        query = self.search.text().strip().casefold()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        shown = 0
        players = self.registry.all_players()
        for sid, rec in players:
            names = [rec["nick"]] + [h["nick"] for h in rec["previous_nicks"]]
            if query and query not in sid and not any(query in n.casefold() for n in names):
                continue
            shown += 1
            top = QTreeWidgetItem([rec["nick"], ""])
            top.setData(0, ROLE_SID, sid)
            self.tree.addTopLevelItem(top)
            link = QLabel(f'<a style="color:#38bdf8" href="{steam_profile_url(sid)}">{html.escape(sid)}</a>')
            link.setTextFormat(Qt.TextFormat.RichText)
            link.setToolTip(tr("players.open_profile"))
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.linkActivated.connect(self._open_link)
            self.tree.setItemWidget(top, 1, link)
            for index, old in enumerate(rec["previous_nicks"]):
                child = QTreeWidgetItem([old["nick"], tr("players.changed_on", date=_format_date(old["changed_at"]))])
                child.setData(0, ROLE_SID, sid)
                child.setData(0, ROLE_OLD_INDEX, index)
                child.setData(0, ROLE_OLD_AT, old["changed_at"])
                child.setForeground(0, Qt.GlobalColor.gray)
                child.setForeground(1, Qt.GlobalColor.gray)
                top.addChild(child)
            top.setExpanded(sid in expanded)
            if selected and selected[0] == sid and selected[1] is None:
                top.setSelected(True)
        self.tree.setUpdatesEnabled(True)
        self.lbl_status.setText(tr("players.count", shown=shown, total=len(players)))
        self._update_buttons()

    @staticmethod
    def _open_link(url: str):
        # Only the Steam profile links built by this app are ever opened
        if url.startswith("https://steamcommunity.com/profiles/"):
            QDesktopServices.openUrl(QUrl(url))

    def _selected(self):
        """(steam_id, old_nick_index or None) of the selected row, else None."""
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, ROLE_SID), items[0].data(0, ROLE_OLD_INDEX)

    def _update_buttons(self):
        sel = self._selected()
        self.btn_del_old.setEnabled(bool(sel) and sel[1] is not None)
        self.btn_del_player.setEnabled(bool(sel))
        self.btn_clear.setEnabled(self.registry is not None and len(self.registry) > 0)

    # ── actions (always confirmed) ───────────────────────────────────
    def _confirm(self, text: str) -> bool:
        return ask(self, tr("players.title"), text, danger=True)

    def _delete_old_nick(self):
        sel = self._selected()
        if not self.registry or not sel or sel[1] is None:
            return
        item = self.tree.selectedItems()[0]
        nick, changed_at = item.text(0), item.data(0, ROLE_OLD_AT)
        if self._confirm(tr("players.confirm_delete_old", nick=nick)):
            self.registry.remove_old_nick_entry(sel[0], nick, changed_at)

    def _delete_player(self):
        sel = self._selected()
        if not self.registry or not sel:
            return
        rec = self.registry.get(sel[0])
        if rec and self._confirm(tr("players.confirm_delete_player", nick=rec["nick"], steam_id=sel[0])):
            self.registry.remove_player(sel[0])

    def _clear_all(self):
        if not self.registry or len(self.registry) == 0:
            return
        if self._confirm(tr("players.confirm_clear", count=len(self.registry))):
            self.registry.clear()
