"""Run-history view based on stable task records, not monitoring dashboards."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState


class RunsPage(QWidget):
    export_requested = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.facade = facade; self._rows: dict[str, dict[str, object]] = {}; self._selected = ""
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Run history", self); title.setObjectName("pageHeading"); layout.addWidget(title)
        self.table = DataTable(("Batch", "Status", "Created", "Updated"), self); self.table.setAccessibleName("Run history")
        self.table.selection_changed.connect(self._select)
        self.empty_state = EmptyState("No runs yet", "Completed and active crawl batches will be listed here.", parent=self)
        layout.addWidget(self.table, 1); layout.addWidget(self.empty_state, 1)
        self.export_button = QPushButton("Export results", self); self.export_button.setObjectName("primaryButton")
        self.export_button.setEnabled(False); self.export_button.clicked.connect(lambda: self.export_requested.emit(self._selected))
        layout.addWidget(self.export_button); self.refresh()

    def refresh(self) -> None:
        rows = self.facade.task_rows() if hasattr(self.facade, "task_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}
        self.table.set_rows((str(row["id"]), (row["id"], row["status"], row["created_at"], row["updated_at"])) for row in rows)
        self.table.setVisible(bool(rows)); self.empty_state.setVisible(not rows)
        if self._selected not in self._rows:
            self._selected = ""; self.export_button.setEnabled(False)

    def _select(self, task_id: str) -> None:
        self._selected = task_id
        self.export_button.setEnabled(str(self._rows.get(task_id, {}).get("status", "")) == "completed")
