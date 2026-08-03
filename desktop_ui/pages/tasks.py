"""Task list with compact filters and a contextual 360 px inspector."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.inspector import Inspector


class TasksPage(QWidget):
    task_selected = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.facade = facade; self._rows: dict[str, dict[str, object]] = {}
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Tasks", self); title.setObjectName("pageHeading"); layout.addWidget(title)
        tools = QHBoxLayout(); self.search = QLineEdit(self); self.search.setPlaceholderText("Search tasks")
        self.search.textChanged.connect(self._render); tools.addWidget(self.search, 1)
        self.status_filter = QComboBox(self); self.status_filter.addItems(("All status", "ready", "running", "completed", "failed", "paused_budget"))
        self.status_filter.currentTextChanged.connect(self._render); tools.addWidget(self.status_filter); layout.addLayout(tools)
        body = QHBoxLayout(); self.table = DataTable(("Task", "Discipline", "Status", "Updated"), self); self.table.selection_changed.connect(self.select_task)
        self.empty_state = EmptyState("No matching tasks", "Adjust the filters or create a new crawl.", parent=self)
        body.addWidget(self.table, 1); body.addWidget(self.empty_state, 1)
        self.inspector = Inspector("Task details", self); body.addWidget(self.inspector); layout.addLayout(body, 1)
        self.refresh()

    def refresh(self) -> None:
        rows = self.facade.task_rows() if hasattr(self.facade, "task_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}; self._render()

    def _render(self) -> None:
        query = self.search.text().strip().casefold(); status = self.status_filter.currentText()
        rows = [row for row in self._rows.values() if (status == "All status" or row["status"] == status) and (not query or query in " ".join(map(str, row.values())).casefold())]
        self.table.set_rows((str(row["id"]), (row["id"], row["discipline"], row["status"], row["updated_at"])) for row in rows)
        self.table.setVisible(bool(rows)); self.empty_state.setVisible(not rows)

    def select_task(self, task_id: str) -> None:
        details = self.facade.task_detail(task_id) if hasattr(self.facade, "task_detail") else self._rows.get(task_id, {})
        self.inspector.show_details(details); self.task_selected.emit(task_id)
