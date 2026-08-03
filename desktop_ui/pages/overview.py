"""Quiet operational overview; it intentionally avoids decorative analytics."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState


class OverviewPage(QWidget):
    new_crawl_requested = Signal()

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        heading = QLabel("Overview", self); heading.setObjectName("pageHeading")
        header.addWidget(heading); header.addStretch(1)
        self.new_crawl_button = QPushButton("New crawl", self); self.new_crawl_button.setObjectName("primaryButton")
        self.new_crawl_button.clicked.connect(self.new_crawl_requested)
        header.addWidget(self.new_crawl_button); layout.addLayout(header)
        cards = QHBoxLayout()
        self.task_count = self._card("Tasks", cards)
        self.action_count = self._card("Needs attention", cards)
        layout.addLayout(cards)
        self.table = DataTable(("Task", "Discipline", "Status", "Updated"), self)
        self.table.setAccessibleName("Recent tasks")
        self.empty_state = EmptyState("No tasks yet", "Create a crawl from verified directory URLs or an XLSX source.", parent=self)
        layout.addWidget(self.table, 1); layout.addWidget(self.empty_state, 1)
        self.refresh()

    def _card(self, title: str, layout: QHBoxLayout) -> QLabel:
        card = QFrame(self); card.setObjectName("metricCard"); card_layout = QVBoxLayout(card)
        card_layout.addWidget(QLabel(title, card)); value = QLabel("0", card); value.setObjectName("metricValue")
        card_layout.addWidget(value); layout.addWidget(card)
        return value

    def refresh(self) -> None:
        rows = tuple(self.facade.task_rows()) if hasattr(self.facade, "task_rows") else ()
        self.task_count.setText(str(len(rows)))
        self.action_count.setText(str(sum(row.get("status") in {"failed", "paused_budget", "needs_verification"} for row in rows)))
        self.table.set_rows((str(row["id"]), (row["id"], row["discipline"], row["status"], row["updated_at"])) for row in rows)
        self.table.setVisible(bool(rows)); self.empty_state.setVisible(not rows)
