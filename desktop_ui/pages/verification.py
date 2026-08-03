"""Manual-only verification queue. No CAPTCHA bypassing is offered or implied."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.info_bar import InfoBar


class VerificationPage(QWidget):
    start_requested = Signal(str); defer_requested = Signal(str); complete_requested = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.facade = facade; self._selected = ""
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Manual verification", self); title.setObjectName("pageHeading"); layout.addWidget(title)
        self.info_bar = InfoBar("人工验证使用可见浏览器；不会自动破解 CAPTCHA、绕过访问控制或跨站点复用会话。", self)
        layout.addWidget(self.info_bar)
        self.table = DataTable(("School", "Reason", "URL"), self); self.table.selection_changed.connect(self._select)
        self.empty_state = EmptyState("No manual verification needed", "Blocked or login-required sites will appear here.", parent=self)
        layout.addWidget(self.table, 1); layout.addWidget(self.empty_state, 1)
        actions = QHBoxLayout(); self.selection_label = QLabel("Select a site to continue", self); actions.addWidget(self.selection_label, 1)
        self.start_button = QPushButton("Start visible browser", self); self.start_button.setObjectName("primaryButton"); self.start_button.clicked.connect(lambda: self.start_requested.emit(self._selected))
        self.defer_button = QPushButton("Defer", self); self.defer_button.clicked.connect(lambda: self.defer_requested.emit(self._selected))
        self.complete_button = QPushButton("Complete", self); self.complete_button.clicked.connect(lambda: self.complete_requested.emit(self._selected))
        for button in (self.start_button, self.defer_button, self.complete_button): button.setEnabled(False); actions.addWidget(button)
        layout.addLayout(actions); self.refresh()

    def refresh(self) -> None:
        rows = self.facade.verification_rows() if hasattr(self.facade, "verification_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}
        self.table.set_rows((str(row["id"]), (row["school"], row["reason"], row["url"])) for row in rows)
        self.table.setVisible(bool(rows)); self.empty_state.setVisible(not rows)

    def _select(self, review_id: str) -> None:
        self._selected = review_id; row = self._rows[review_id]; self.selection_label.setText(str(row["url"]))
        for button in (self.start_button, self.defer_button, self.complete_button): button.setEnabled(True)
