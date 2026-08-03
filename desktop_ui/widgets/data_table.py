"""Compact, accessible data table used by operational desktop pages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget


class DataTable(QTableWidget):
    """A 40 px-row table with a stable string identifier per row."""

    selection_changed = Signal(str)

    def __init__(self, headers: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(40)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.itemSelectionChanged.connect(self._emit_selection)

    def set_rows(self, rows: Iterable[tuple[str, Sequence[object]]]) -> None:
        self.setRowCount(0)
        for row_id, values in rows:
            index = self.rowCount()
            self.insertRow(index)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, str(row_id))
                self.setItem(index, column, item)
            self.setRowHeight(index, 40)

    def select_id(self, row_id: str) -> bool:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == row_id:
                self.selectRow(row)
                return True
        return False

    def _emit_selection(self) -> None:
        selected = self.selectedItems()
        if selected:
            self.selection_changed.emit(str(selected[0].data(Qt.UserRole)))
