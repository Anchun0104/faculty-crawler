"""Site-isolated session metadata view with deliberate destructive actions."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.info_bar import InfoBar


class SessionsPage(QWidget):
    clear_requested = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.facade = facade; self._selected = ""
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Site sessions", self); title.setObjectName("pageHeading"); layout.addWidget(title)
        layout.addWidget(InfoBar("Sessions are encrypted and isolated to their exact host. Clearing a session removes local sign-in state only.", self))
        self.table = DataTable(("Hostname", "Saved", "Expires"), self); self.table.selection_changed.connect(self._select)
        self.empty_state = EmptyState("No saved site sessions", "A session is saved only after a manual, visible verification completes.", parent=self)
        layout.addWidget(self.table, 1); layout.addWidget(self.empty_state, 1)
        actions = QHBoxLayout(); actions.addStretch(1); self.clear_button = QPushButton("Clear selected session", self); self.clear_button.setObjectName("dangerButton"); self.clear_button.setEnabled(False); self.clear_button.clicked.connect(self._confirm_clear)
        actions.addWidget(self.clear_button); layout.addLayout(actions); self.refresh()

    def refresh(self) -> None:
        rows = self.facade.session_rows() if hasattr(self.facade, "session_rows") else ()
        self.table.set_rows((str(row["hostname"]), (row["hostname"], row["saved_at"], row["expires_at"])) for row in rows)
        self.table.setVisible(bool(rows)); self.empty_state.setVisible(not rows)

    def _select(self, hostname: str) -> None:
        self._selected = hostname; self.clear_button.setEnabled(True)

    def _confirm_clear(self) -> None:
        if not self._selected:
            return
        if QMessageBox.question(self, "Clear site session", f"Clear local session data for {self._selected}?") == QMessageBox.Yes:
            self.request_clear(self._selected)

    def request_clear(self, hostname: str) -> None:
        """Express a typed intent; workers/controllers perform the destructive command."""
        self.clear_requested.emit(hostname)
