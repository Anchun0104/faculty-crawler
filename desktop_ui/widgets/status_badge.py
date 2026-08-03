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
    BackgroundStatus.IDLE: ("空闲", "#667085"),
    BackgroundStatus.RUNNING: ("运行中", "#1769AA"),
    BackgroundStatus.WAITING_FOR_VERIFICATION: ("等待人工验证", "#B56A08"),
}


class StatusBadge(QWidget):
    """A status dot plus text, so operational state is never colour-only."""

    def __init__(self, status: BackgroundStatus = BackgroundStatus.IDLE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.setAccessibleName("后台状态")
        self._dot = QLabel(self)
        self._dot.setFixedSize(8, 8)
        self._dot.setAccessibleName("状态指示器")
        self._label = QLabel(self)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._compact = False
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
        self._dot.setAccessibleName(f"状态指示器：{text}")
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self.setAccessibleName(f"后台状态：{text}")
        self.setToolTip(f"后台状态：{text}")

    @property
    def status(self) -> BackgroundStatus:
        return self._status

    def status_text(self) -> str:
        return self._label.text()

    def set_compact(self, compact: bool) -> None:
        """Show a dot-only visual in the collapsed navigation without hiding state from AT."""
        self._compact = bool(compact)
        self._label.setVisible(not self._compact)
        if self._compact:
            self.setFixedWidth(32)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)

    def is_compact(self) -> bool:
        return self._compact

    def visible_text_label(self) -> QLabel:
        """Expose the rendered text label for focused widget-level tests."""
        return self._label
