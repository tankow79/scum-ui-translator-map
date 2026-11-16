"""Settings section for the squad: create / join with a code, who is online, my own names for teammates."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.i18n import tr
from core.sync_crypto import new_code, parse_code
from ui.dialogs import ask, notify
from ui.flow_layout import button_row
from ui.settings_widgets import Section, WrapCheck, make_button, muted_label

COL_NAME, COL_ALIAS, COL_STATE = 0, 1, 2


class SyncSection(Section):
    def __init__(self, engine=None, parent=None):
        super().__init__(tr("sync.title"), parent)
        self.engine = engine
        self.add_widget(muted_label(tr("sync.intro")))
        self.chk_enable = self.add_check(WrapCheck(tr("sync.enable")))

        self.btn_create = make_button(tr("sync.btn_create"), "primary")
        self.btn_join = make_button(tr("sync.btn_join"))
        self.btn_create.clicked.connect(self._create_squad)
        self.btn_join.clicked.connect(self._join_from_clipboard)
        self.add_layout(button_row(self.btn_create, self.btn_join))

        self.txt_code = QLineEdit()
        self.txt_code.setPlaceholderText(tr("sync.code_placeholder"))
        self.txt_code.setMinimumWidth(160)
        self.add_field(tr("sync.code_label"), self.txt_code)
        self.btn_copy = make_button(tr("sync.btn_copy"))
        self.btn_copy.clicked.connect(self._copy_code)
        self.add_layout(button_row(self.btn_copy))

        self.txt_name = QLineEdit()
        self.txt_name.setMaxLength(24)
        self.txt_name.setPlaceholderText(tr("sync.name_placeholder"))
        self.add_field(tr("sync.name_label"), self.txt_name)

        self.add_widget(muted_label(tr("sync.members_title")))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("sync.col_name"), tr("sync.col_alias"), tr("sync.col_state")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setMinimumHeight(130)
        self.table.setMaximumHeight(220)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_ALIAS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._alias_edited)
        self.add_widget(self.table)
        self.btn_forget = make_button(tr("sync.btn_forget"))
        self.btn_forget.clicked.connect(self._forget_selected)
        self.add_layout(button_row(self.btn_forget))

        # rarely needed options live behind one button, so the page stays simple
        self.btn_more = make_button(tr("sync.advanced_show"))
        self.btn_more.clicked.connect(self._toggle_advanced)
        self.add_layout(button_row(self.btn_more))
        self.advanced = QWidget()
        adv = QVBoxLayout(self.advanced)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(10)
        adv.addWidget(muted_label(tr("sync.server_hint")))
        self.chk_points = WrapCheck(tr("sync.points_check"), tr("sync.points_hint"))
        self.chk_position = WrapCheck(tr("sync.position_check"), tr("sync.position_hint"))
        self.chk_auto = WrapCheck(tr("sync.auto_check"))
        adv.addWidget(self.chk_points)
        adv.addWidget(self.chk_position)
        adv.addWidget(self.chk_auto)
        self.spin_auto = QSpinBox()
        self.spin_auto.setRange(3, 60)
        self.spin_auto.setMaximumWidth(110)
        adv.addWidget(QLabel(tr("sync.auto_seconds")))
        adv.addWidget(self.spin_auto)
        adv.addWidget(muted_label(tr("sync.auto_warning")))
        self.txt_broker = QLineEdit()
        self.txt_broker.setPlaceholderText(tr("sync.broker_placeholder"))
        adv.addWidget(QLabel(tr("sync.broker_label")))
        adv.addWidget(self.txt_broker)
        adv.addWidget(muted_label(tr("sync.broker_hint")))
        self.advanced.setVisible(False)
        self.add_widget(self.advanced)

        self.lbl_status = muted_label("")
        self.add_widget(self.lbl_status)
        self.txt_code.textChanged.connect(self._refresh_status)
        self._links = []
        if engine is not None:
            for signal, slot in ((engine.status_changed, self._refresh_status), (engine.friends_changed, self._refresh_status),
                                 (engine.friends_changed, self._refresh_members)):
                signal.connect(slot)
                self._links.append((signal, slot))

    def disconnect_external(self):
        """Before this page is thrown away (language switch): the engine must stop calling it."""
        for signal, slot in self._links:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._links = []

    def _toggle_advanced(self):
        show = not self.advanced.isVisible()
        self.advanced.setVisible(show)
        self.btn_more.setText(tr("sync.advanced_hide" if show else "sync.advanced_show"))

    # ── squad: create / join ─────────────────────────────────────────
    def _create_squad(self):
        if self.code_is_valid() and not ask(self, tr("sync.title"), tr("sync.create_replace"), danger=True):
            return
        self.txt_code.setText(new_code())
        self.chk_enable.setChecked(True)
        if not self.txt_name.text().strip():
            self.txt_name.setText(self._default_name())
        QApplication.clipboard().setText(self.txt_code.text())          # ready to paste to the friends
        notify(self, tr("sync.title"), tr("sync.created"))

    def _join_from_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if parse_code(text) is None:
            notify(self, tr("sync.title"), tr("sync.join_no_code"), "warning")
            return
        self.txt_code.setText(text)
        self.chk_enable.setChecked(True)
        if not self.txt_name.text().strip():
            self.txt_name.setText(self._default_name())
        notify(self, tr("sync.title"), tr("sync.joined"))

    def _default_name(self) -> str:
        return str(getattr(self, "_own_nick", "") or "")

    def set_own_nickname(self, nick: str):
        self._own_nick = nick

    def _copy_code(self):
        QApplication.clipboard().setText(self.txt_code.text().strip())

    # ── members and my own names for them ────────────────────────────
    def _refresh_members(self, *_):
        if self.engine is None:
            return
        editing = self.table.state() == QAbstractItemView.State.EditingState
        if editing:
            return                                           # do not pull the cell away while it is being typed
        rows = self.engine.members()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            name = QTableWidgetItem(row["name"])
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            name.setData(Qt.ItemDataRole.UserRole, row["member"])
            alias = self.engine._aliases().get(row["member"], "")
            alias_item = QTableWidgetItem(alias if isinstance(alias, str) else "")
            alias_item.setData(Qt.ItemDataRole.UserRole, row["member"])
            alias_item.setToolTip(tr("sync.alias_tip"))
            state = QTableWidgetItem(tr("sync.state_online") if row["online"] else tr("sync.state_offline"))
            state.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(i, COL_NAME, name)
            self.table.setItem(i, COL_ALIAS, alias_item)
            self.table.setItem(i, COL_STATE, state)
        self.table.blockSignals(False)

    def _alias_edited(self, item: QTableWidgetItem):
        if item.column() != COL_ALIAS or self.engine is None:
            return
        member = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(member, str):
            self.engine.set_alias(member, item.text())
            QTimer.singleShot(0, self._refresh_members)      # show the cleaned name

    def _forget_selected(self):
        rows = self.table.selectionModel().selectedRows() if self.engine is not None else []
        if not rows:
            return
        member = self.table.item(rows[0].row(), COL_NAME).data(Qt.ItemDataRole.UserRole)
        if isinstance(member, str) and ask(self, tr("sync.title"), tr("sync.forget_confirm"), danger=True):
            self.engine.forget_member(member)
            self._refresh_members()

    # ── load / save ──────────────────────────────────────────────────
    def load(self, cfg: ConfigManager):
        self.chk_enable.setChecked(bool(cfg.get("sync_enabled", False)))
        self.txt_code.setText(str(cfg.get("sync_code", "")))
        self._own_nick = str(cfg.get("own_nickname", ""))
        self.txt_name.setText(str(cfg.get("sync_name", "")) or self._own_nick)
        self.chk_points.setChecked(bool(cfg.get("sync_points", True)))
        self.chk_position.setChecked(bool(cfg.get("sync_position", True)))
        self.chk_auto.setChecked(bool(cfg.get("sync_auto_copy", False)))
        try:
            self.spin_auto.setValue(int(cfg.get("sync_auto_copy_seconds", 5)))
        except (TypeError, ValueError):
            self.spin_auto.setValue(5)
        self.txt_broker.setText(str(cfg.get("sync_broker", "")))
        self._refresh_status()
        self._refresh_members()

    def code_is_valid(self) -> bool:
        return parse_code(self.txt_code.text()) is not None

    def save(self, cfg: ConfigManager):
        code = self.txt_code.text().strip()
        valid = parse_code(code) is not None
        cfg.set("sync_enabled", self.chk_enable.isChecked() and valid)
        cfg.set("sync_code", code)
        cfg.set("sync_name", self.txt_name.text().strip())
        cfg.set("sync_points", self.chk_points.isChecked())
        cfg.set("sync_position", self.chk_position.isChecked())
        cfg.set("sync_auto_copy", self.chk_auto.isChecked())
        cfg.set("sync_auto_copy_seconds", self.spin_auto.value())
        cfg.set("sync_broker", self.txt_broker.text().strip())

    def _refresh_status(self, *_):
        text = self.txt_code.text().strip()
        if text and not self.code_is_valid():
            self.lbl_status.setText(tr("sync.status_invalid_code"))
            return
        state = getattr(self.engine, "state", "off") if self.engine is not None else "off"
        if state == "online":
            self.lbl_status.setText(tr("sync.status_online", members=self.engine.members_online()))
        else:
            self.lbl_status.setText(tr(f"sync.status_{state}"))
