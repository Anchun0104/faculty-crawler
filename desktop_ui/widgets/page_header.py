"""Shared page title, description and single primary action."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PageHeader(QWidget):
    """A stable page header with at most one primary action."""

    primary_clicked = Signal()

    def __init__(self, title: str, description: str = "", primary_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)
        self.title = QLabel(title, self)
        self.title.setObjectName("pageHeading")
        self.title.setAccessibleName(title)
        copy.addWidget(self.title)
        self.description = QLabel(description, self)
        self.description.setObjectName("pageDescription")
        self.description.setWordWrap(True)
        self.description.setVisible(bool(description))
        copy.addWidget(self.description)
        layout.addLayout(copy, 1)
        self.primary_button = QPushButton(primary_text, self)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setVisible(bool(primary_text))
        self.primary_button.clicked.connect(self.primary_clicked)
        layout.addWidget(self.primary_button, 0)
