"""站点会话页面：精确主机、到期状态和可确认的清理操作。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.info_bar import InfoBar
from desktop_ui.widgets.page_header import PageHeader


class SessionsPage(QWidget):
    clear_requested = Signal(str)
    clear_expired_requested = Signal()

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._rows: dict[str, dict[str, object]] = {}
        self._selected = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.page_header = PageHeader(
            "站点会话",
            "会话仅用于完成过人工验证的精确主机，并受 Windows DPAPI 保护。",
            parent=self,
        )
        header.addWidget(self.page_header, 1)
        self.clear_expired_button = QPushButton("清理过期会话", self)
        self.clear_expired_button.setObjectName("dangerButton")
        self.clear_expired_button.setAccessibleName("清理过期会话")
        self.clear_expired_button.clicked.connect(self._request_expired_clear)
        header.addWidget(self.clear_expired_button, 0)
        layout.addLayout(header)

        self.info_bar = InfoBar(
            "已保存会话按精确主机隔离并加密保存。清理后，相应站点可能再次要求人工验证。",
            self,
        )
        layout.addWidget(self.info_bar)

        tools = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索站点")
        self.search.setAccessibleName("搜索站点")
        self.search.textChanged.connect(self._render)
        tools.addWidget(self.search, 1)
        self.expiry_filter = QComboBox(self)
        self.expiry_filter.setAccessibleName("筛选会话到期状态")
        self.expiry_filter.addItem("全部会话", "")
        self.expiry_filter.addItem("临近到期", "warning")
        self.expiry_filter.addItem("已到期", "expired")
        self.expiry_filter.currentIndexChanged.connect(self._render)
        tools.addWidget(self.expiry_filter)
        layout.addLayout(tools)

        self.table = DataTable(("站点", "保存时间", "最近使用", "计划清理", "操作"), self)
        self.table.setAccessibleName("站点会话列表")
        self.table.selection_changed.connect(self._select)
        layout.addWidget(self.table, 1)
        self.empty_state = EmptyState(
            "暂无保存的站点会话",
            "只有完成一次人工、可见的站点验证后才会保存会话。",
            parent=self,
        )
        layout.addWidget(self.empty_state, 1)

        actions = QHBoxLayout()
        self.selection_hint = QLabel("选择一行后可清除该站点的本地会话。", self)
        self.selection_hint.setObjectName("settingRowHint")
        actions.addWidget(self.selection_hint, 1)
        self.clear_button = QPushButton("清除所选会话", self)
        self.clear_button.setObjectName("dangerButton")
        self.clear_button.setAccessibleName("清除所选会话")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self._confirm_clear)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        rows = self.facade.session_rows() if hasattr(self.facade, "session_rows") else ()
        self._rows = {str(row["hostname"]): dict(row) for row in rows}
        if self._selected not in self._rows:
            self._selected = ""
            self.clear_button.setEnabled(False)
        self._render()
        self.clear_expired_button.setEnabled(any(self._expiry_state(row) == "expired" for row in self._rows.values()))

    def _render(self) -> None:
        query = self.search.text().strip().casefold()
        state = str(self.expiry_filter.currentData() or "")
        rows = [
            row
            for row in self._rows.values()
            if (not query or query in " ".join(map(str, row.values())).casefold())
            and (not state or self._expiry_state(row) == state)
        ]
        self.table.set_rows(
            (
                str(row["hostname"]),
                (
                    row["hostname"],
                    row.get("saved_at", ""),
                    row.get("last_used_at", row.get("saved_at", "")),
                    self._expiry_label(row),
                    "清除",
                ),
            )
            for row in rows
        )
        self.table.setVisible(bool(rows))
        self.empty_state.setVisible(not rows)
        if self._selected and self._selected not in {str(row["hostname"]) for row in rows}:
            self._selected = ""
            self.clear_button.setEnabled(False)

    def _select(self, hostname: str) -> None:
        self._selected = str(hostname)
        self.clear_button.setEnabled(self._selected in self._rows)

    def _confirm_clear(self) -> None:
        if not self._selected:
            return
        if (
            QMessageBox.question(
                self,
                "清除站点会话",
                f"确定清除 {self._selected} 的本地会话数据吗？清理后可能需要再次人工验证。",
            )
            == QMessageBox.Yes
        ):
            self.request_clear(self._selected)

    def _request_expired_clear(self) -> None:
        if self.clear_expired_button.isEnabled():
            self.clear_expired_requested.emit()

    def request_clear(self, hostname: str) -> None:
        """Express a typed intent; workers/controllers perform the destructive command."""
        self.clear_requested.emit(hostname)

    @classmethod
    def _expiry_state(cls, row: dict[str, object]) -> str:
        if bool(row.get("expired", False)):
            return "expired"
        days = row.get("days_remaining")
        try:
            days_value = int(days) if days is not None else None
        except (TypeError, ValueError):
            days_value = None
        if days_value is not None:
            return "expired" if days_value <= 0 else "warning" if days_value <= 7 else "ok"
        return "ok"

    @classmethod
    def _expiry_label(cls, row: dict[str, object]) -> str:
        state = cls._expiry_state(row)
        if state == "expired":
            return "已到期"
        days = row.get("days_remaining")
        if days is not None:
            try:
                days_value = int(days)
            except (TypeError, ValueError):
                days_value = None
            if days_value is not None:
                return "临近到期" if days_value <= 7 else f"{days_value} 天后"
        return str(row.get("expires_at", ""))
