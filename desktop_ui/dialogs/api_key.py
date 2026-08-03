"""Transient API-key entry dialog.

The dialog deliberately has no API-key prefill path.  A saved key remains in
the encrypted settings store and is never requested from a UI view model.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class ApiKeyDialog(QDialog):
    """Collect a replacement key only for the duration of one save action."""

    key_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("替换 API Key")
        self.setAccessibleName("替换 API Key")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        title = QLabel("替换 API Key", self)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        copy = QLabel(
            "密钥将使用 Windows DPAPI 加密，仅当前 Windows 用户可以使用。"
            "保存后不会在应用中再次显示。",
            self,
        )
        copy.setWordWrap(True)
        layout.addWidget(copy)

        self.key_edit = QLineEdit(self)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("粘贴新的 API Key")
        self.key_edit.setAccessibleName("新的 API Key")
        self.key_edit.setClearButtonEnabled(True)
        layout.addWidget(self.key_edit)
        self.error_label = QLabel(self)
        self.error_label.setObjectName("fieldError")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Cancel | QDialogButtonBox.Save,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.Save).setText("保存")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

    def open_for_replacement(self) -> None:
        """Open with an empty editor; no saved value can be copied into it."""
        self.key_edit.clear()
        self.error_label.clear()
        self.open()
        self.key_edit.setFocus()

    def accept(self) -> None:  # noqa: N802 - Qt override name
        value = self.key_edit.text()
        if not value.strip():
            self.error_label.setText("请输入新的 API Key；如需移除密钥，请使用“删除”。")
            self.key_edit.setFocus()
            return
        self.key_submitted.emit(value)
        # Clear immediately after copying the transient value into the signal.
        self.key_edit.clear()
        super().accept()

