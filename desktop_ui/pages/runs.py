"""Run-history view based on stable task records, not monitoring dashboards."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState


class RunsPage(QWidget):
    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.facade = facade; layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Run history", self); title.setObjectName("pageHeading"); layout.addWidget(title)
        self.table = DataTable(("Batch", "Status", "Created", "Updated"), self); self.table.setAccessibleName("Run history")
        self.empty_state = EmptyState("No runs yet", "Completed and active crawl batches will be listed here.", parent=self)
        layout.addWidget(self.table, 1); layout.addWidget(self.empty_state, 1); self.refresh()

    def refresh(self) -> None:
        rows = self.facade.task_rows() if hasattr(self.facade, "task_rows") else ()
        self.table.set_rows((str(row["id"]), (row["id"], row["status"], row["created_at"], row["updated_at"])) for row in rows)
        self.table.setVisible(bool(rows)); self.empty_state.setVisible(not rows)
