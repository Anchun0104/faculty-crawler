"""Manual-only verification queue. No CAPTCHA bypassing is offered or implied."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.info_bar import InfoBar


class VerificationPage(QWidget):
    """Two-pane workflow: queue on the left, selected manual site on the right."""

    start_requested = Signal(str)
    defer_requested = Signal(str)
    complete_requested = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._selected = ""
        self._rows: dict[str, dict[str, object]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Manual verification", self)
        title.setObjectName("pageHeading")
        layout.addWidget(title)
        self.info_bar = InfoBar(
            "人工验证使用可见浏览器；不会自动破解 CAPTCHA、绕过访问控制或跨站点复用会话。",
            self,
        )
        layout.addWidget(self.info_bar)

        panes = QHBoxLayout()
        self.table = DataTable(("School", "Reason", "URL"), self)
        self.table.setAccessibleName("Manual verification queue")
        self.table.selection_changed.connect(self.select_review)
        self.empty_state = EmptyState(
            "No manual verification needed",
            "Blocked or login-required sites will appear here.",
            parent=self,
        )
        queue = QWidget(self)
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.addWidget(self.table, 1)
        queue_layout.addWidget(self.empty_state, 1)
        panes.addWidget(queue, 1)
        panes.addWidget(self._build_selected_site_pane())
        layout.addLayout(panes, 1)
        self.refresh()

    def _build_selected_site_pane(self) -> QFrame:
        pane = QFrame(self)
        pane.setObjectName("verificationInspector")
        pane.setFixedWidth(360)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 16, 16, 16)
        heading = QLabel("Selected site", pane)
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)
        self.selected_site_label = QLabel("Select a site to continue", pane)
        self.selected_site_label.setWordWrap(True)
        layout.addWidget(self.selected_site_label)
        self.browser_status_label = QLabel("Visible browser: not started", pane)
        self.browser_status_label.setObjectName("settingRowHint")
        self.browser_status_label.setWordWrap(True)
        layout.addWidget(self.browser_status_label)
        self.instructions_label = QLabel(
            "1. Start the visible browser.\n"
            "2. Complete any sign-in or verification yourself.\n"
            "3. Return here and mark the site complete, or defer it.",
            pane,
        )
        self.instructions_label.setWordWrap(True)
        layout.addWidget(self.instructions_label)
        layout.addStretch(1)
        self.start_button = QPushButton("Start visible browser", pane)
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self._selected))
        self.defer_button = QPushButton("Defer", pane)
        self.defer_button.clicked.connect(lambda: self.defer_requested.emit(self._selected))
        self.complete_button = QPushButton("Complete", pane)
        self.complete_button.clicked.connect(lambda: self.complete_requested.emit(self._selected))
        for button in (self.start_button, self.defer_button, self.complete_button):
            button.setEnabled(False)
            layout.addWidget(button)
        return pane

    def refresh(self) -> None:
        rows = self.facade.verification_rows() if hasattr(self.facade, "verification_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}
        if self._selected not in self._rows:
            self._clear_selection()
        self.table.set_rows(
            (str(row["id"]), (row["school"], row["reason"], row["url"]))
            for row in rows
        )
        self.table.setVisible(bool(rows))
        self.empty_state.setVisible(not rows)

    def select_review(self, review_id: str) -> None:
        row = self._rows.get(review_id)
        if row is None:
            self._clear_selection()
            return
        self._selected = review_id
        self.selected_site_label.setText(str(row["url"]))
        self.browser_status_label.setText("Visible browser: ready to start")
        for button in (self.start_button, self.defer_button, self.complete_button):
            button.setEnabled(True)

    def _clear_selection(self) -> None:
        self._selected = ""
        self.selected_site_label.setText("Select a site to continue")
        self.browser_status_label.setText("Visible browser: not started")
        for button in (self.start_button, self.defer_button, self.complete_button):
            button.setEnabled(False)
