"""Accessible background-operation status indicator."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class BackgroundStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_VERIFICATION = "waiting_for_verification"


_PRESENTATION = {
    BackgroundStatus.IDLE: ("Idle", "#667085"),
    BackgroundStatus.RUNNING: ("Running", "#1769AA"),
    BackgroundStatus.WAITING_FOR_VERIFICATION: ("Waiting for verification", "#B56A08"),
}


class StatusBadge(QWidget):
    """A status dot plus text, so operational state is never colour-only."""

    def __init__(self, status: BackgroundStatus = BackgroundStatus.IDLE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Background status")
        self._dot = QLabel(self)
        self._dot.setFixedSize(8, 8)
        self._dot.setAccessibleName("Status indicator")
        self._label = QLabel(self)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        layout.addWidget(self._dot)
        layout.addWidget(self._label)
        self.set_status(status)

    def set_status(self, status: BackgroundStatus) -> None:
        if not isinstance(status, BackgroundStatus):
            raise TypeError("status must be a BackgroundStatus")
        text, color = _PRESENTATION[status]
        self._status = status
        self._label.setText(text)
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self.setToolTip(text)

    @property
    def status(self) -> BackgroundStatus:
        return self._status

    def status_text(self) -> str:
        return self._label.text()
