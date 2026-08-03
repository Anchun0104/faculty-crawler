"""Low-noise empty state shared by data-heavy pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    def __init__(self, title: str, detail: str, action: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 40, 24, 40)
        layout.setSpacing(8)
        layout.addStretch(1)
        self.title = QLabel(title, self)
        self.title.setObjectName("emptyStateTitle")
        self.title.setAlignment(Qt.AlignHCenter)
        layout.addWidget(self.title)
        self.detail = QLabel(detail, self)
        self.detail.setObjectName("emptyStateDetail")
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignHCenter)
        layout.addWidget(self.detail)
        self.action_button = QPushButton(action, self)
        self.action_button.setObjectName("primaryButton")
        self.action_button.setVisible(bool(action))
        layout.addWidget(self.action_button, 0, Qt.AlignHCenter)
        layout.addStretch(1)
