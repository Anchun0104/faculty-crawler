"""Aligned setting copy and inline control row."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class SettingsRow(QFrame):
    """A two-column settings row that leaves control signals untouched."""

    def __init__(self, title: str, hint: str = "", control: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(3)
        self.title = QLabel(title, self)
        self.title.setObjectName("settingRowTitle")
        copy.addWidget(self.title)
        self.hint = QLabel(hint, self)
        self.hint.setObjectName("settingRowHint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        copy.addWidget(self.hint)
        layout.addLayout(copy, 1)
        self.control = control
        if control is not None:
            layout.addWidget(control, 0, self._control_alignment(control))

    @staticmethod
    def _control_alignment(control: QWidget):
        del control
        from PySide6.QtCore import Qt

        return Qt.AlignVCenter
