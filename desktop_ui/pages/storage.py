"""Storage and diagnostics display that exposes no raw local file paths."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.info_bar import InfoBar


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB"); amount = float(max(0, value))
    for unit in units:
        if amount < 1024 or unit == units[-1]: return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return "0 B"


class StoragePage(QWidget):
    clear_temporary_requested = Signal()
    clear_internal_requested = Signal()
    diagnostics_export_requested = Signal()

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.facade = facade; layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Storage and diagnostics", self); title.setObjectName("sectionHeading"); layout.addWidget(title)
        layout.addWidget(InfoBar("Diagnostics include sanitized task failures and application logs. They exclude API keys, browser session data, credentials, and page content.", self))
        usage = QFrame(self); usage.setObjectName("settingsGroup"); usage_layout = QHBoxLayout(usage)
        usage_layout.addWidget(QLabel("Internal storage", usage)); self.usage_label = QLabel("0 B", usage); self.usage_label.setObjectName("metricValue"); usage_layout.addWidget(self.usage_label, 1)
        self.file_count_label = QLabel("0 files", usage); usage_layout.addWidget(self.file_count_label); layout.addWidget(usage)
        actions = QFrame(self); actions.setObjectName("settingsGroup"); rows = QVBoxLayout(actions)
        self.export_button = QPushButton("Export diagnostics", actions); self.export_button.setObjectName("primaryButton"); self.export_button.clicked.connect(self.diagnostics_export_requested); rows.addWidget(self.export_button)
        self.clear_temp_button = QPushButton("Clear temporary data", actions); self.clear_temp_button.clicked.connect(self._confirm_temporary_clear); rows.addWidget(self.clear_temp_button)
        self.clear_internal_button = QPushButton("Clear internal data", actions); self.clear_internal_button.setObjectName("dangerButton"); self.clear_internal_button.clicked.connect(self._confirm_internal_clear); rows.addWidget(self.clear_internal_button)
        self.clear_internal_button.setToolTip("Clears sessions, run artifacts and logs; preserves diagnostic ZIPs, task history, workflow database and exported Excel files.")
        layout.addWidget(actions); layout.addStretch(1); self.refresh()

    def refresh(self) -> None:
        summary = self.facade.storage_summary() if hasattr(self.facade, "storage_summary") else {"bytes": 0, "files": 0}
        self.usage_label.setText(_format_bytes(int(summary.get("bytes", 0)))); self.file_count_label.setText(f"{int(summary.get('files', 0))} files")

    def _confirm_internal_clear(self) -> None:
        if QMessageBox.question(self, "Clear internal data", "This clears local sessions, run artifacts and logs. Diagnostic ZIPs, task history, workflow database and exported Excel files are preserved. Continue?") == QMessageBox.Yes:
            self.clear_internal_requested.emit()

    def _confirm_temporary_clear(self) -> None:
        if QMessageBox.question(
            self,
            "Clear temporary data",
            "This removes temporary files and screenshots. Continue?",
        ) == QMessageBox.Yes:
            self.clear_temporary_requested.emit()
