"""Non-modal page-level notifications."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class InfoBar(QFrame):
    """A calm, readable notification surface for actionable information."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("infoBar")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAccessibleName("Information")
        self._label = QLabel(text, self)
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self._label)

    def set_message(self, text: str) -> None:
        self._label.setText(text)

    def message(self) -> str:
        return self._label.text()

    def text(self) -> str:
        """Qt-label compatible read accessor used by lightweight page tests."""
        return self.message()
