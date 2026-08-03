"""A fixed-width contextual inspector, not a second application page."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QFormLayout, QLabel, QVBoxLayout, QWidget

from desktop_ui.tokens import LIGHT_TOKENS


class Inspector(QFrame):
    """Shows selected-row details at the approved 360 px desktop width."""

    def __init__(self, title: str = "Details", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskInspector")
        self.setFixedWidth(LIGHT_TOKENS.inspector_width)
        self.setAccessibleName(f"{title} inspector")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.title = QLabel(title, self)
        self.title.setObjectName("sectionHeading")
        layout.addWidget(self.title)
        self.form = QFormLayout()
        self.form.setSpacing(10)
        layout.addLayout(self.form)
        layout.addStretch(1)
        self.hide()

    def show_details(self, values: Mapping[str, object]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        for label, value in values.items():
            rendered = QLabel(str(value), self)
            rendered.setWordWrap(True)
            rendered.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.form.addRow(str(label), rendered)
        self.show()
