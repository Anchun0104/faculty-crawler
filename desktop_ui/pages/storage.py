"""存储与诊断页面：容量、保留策略和分级清理操作。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_ui.widgets.info_bar import InfoBar


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(max(0, value))
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return "0 B"


class StoragePage(QWidget):
    clear_temporary_requested = Signal()
    clear_internal_requested = Signal()
    diagnostics_export_requested = Signal()

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.section_title = QLabel("存储与诊断", self)
        self.section_title.setObjectName("sectionHeading")
        layout.addWidget(self.section_title)
        self.section_description = QLabel(
            "查看本地占用、清理缓存并导出隐私安全的诊断包。",
            self,
        )
        self.section_description.setObjectName("pageDescription")
        layout.addWidget(self.section_description)
        self.info_bar = InfoBar(
            "诊断包包含版本、脱敏日志和运行摘要；不包含 Cookie、Token、会话凭据或网页正文。",
            self,
        )
        layout.addWidget(self.info_bar)

        top = QHBoxLayout()
        top.setSpacing(12)
        usage = QFrame(self)
        usage.setObjectName("storageUsageCard")
        usage_layout = QVBoxLayout(usage)
        usage_layout.setContentsMargins(16, 14, 16, 14)
        usage_layout.setSpacing(6)
        usage_title = QLabel("本地存储", usage)
        usage_title.setObjectName("settingRowTitle")
        usage_layout.addWidget(usage_title)
        usage_line = QHBoxLayout()
        self.usage_label = QLabel("0 B", usage)
        self.usage_label.setObjectName("metricValue")
        usage_line.addWidget(self.usage_label)
        used_copy = QLabel("已使用", usage)
        used_copy.setObjectName("settingRowHint")
        usage_line.addWidget(used_copy)
        usage_line.addStretch(1)
        self.file_count_label = QLabel("0 个文件", usage)
        self.file_count_label.setObjectName("settingRowHint")
        usage_line.addWidget(self.file_count_label)
        usage_layout.addLayout(usage_line)
        self.storage_usage_bar = QProgressBar(usage)
        self.storage_usage_bar.setObjectName("storageUsageBar")
        self.storage_usage_bar.setRange(0, 100)
        self.storage_usage_bar.setValue(0)
        self.storage_usage_bar.setTextVisible(False)
        self.storage_usage_bar.setAccessibleName("本地存储使用比例")
        usage_layout.addWidget(self.storage_usage_bar)
        legend = QHBoxLayout()
        self.snapshot_label = QLabel("页面快照 0 B", usage)
        self.cache_label = QLabel("翻译缓存 0 B", usage)
        self.logs_label = QLabel("日志 0 B", usage)
        for item in (self.snapshot_label, self.cache_label, self.logs_label):
            item.setObjectName("settingRowHint")
            legend.addWidget(item)
        legend.addStretch(1)
        usage_layout.addLayout(legend)
        top.addWidget(usage, 11)

        retention = QFrame(self)
        retention.setObjectName("storageRetentionCard")
        retention_layout = QVBoxLayout(retention)
        retention_layout.setContentsMargins(16, 14, 16, 14)
        retention_layout.setSpacing(6)
        retention_title = QLabel("保留策略", retention)
        retention_title.setObjectName("settingRowTitle")
        retention_layout.addWidget(retention_title)
        self.retention_status = QLabel("自动清理已启用", retention)
        self.retention_status.setObjectName("sectionHeading")
        retention_layout.addWidget(self.retention_status)
        retention_hint = QLabel(
            "临时页面与日志将在 30 天后清理；正式 Excel 结果不受影响。",
            retention,
        )
        retention_hint.setWordWrap(True)
        retention_hint.setObjectName("settingRowHint")
        retention_layout.addWidget(retention_hint)
        self.retention_button = QPushButton("更改保留策略", retention)
        self.retention_button.setAccessibleName("更改保留策略")
        retention_layout.addWidget(self.retention_button, 0)
        top.addWidget(retention, 9)
        layout.addLayout(top)

        cleanup_group = QFrame(self)
        cleanup_group.setObjectName("settingsGroup")
        cleanup_layout = QVBoxLayout(cleanup_group)
        cleanup_layout.setContentsMargins(16, 14, 16, 14)
        cleanup_layout.setSpacing(0)
        cleanup_title = QLabel("清理", cleanup_group)
        cleanup_title.setObjectName("sectionHeading")
        cleanup_layout.addWidget(cleanup_title)
        cleanup_layout.addWidget(
            self._action_row(
                "临时页面与快照",
                "可安全重新生成；不会删除已导出的 Excel。",
                "清理临时数据",
                "temporary",
                cleanup_group,
            )
        )
        cleanup_layout.addWidget(
            self._action_row(
                "离线翻译缓存",
                "下次使用时会重新建立。",
                "清理翻译缓存",
                "temporary",
                cleanup_group,
            )
        )
        internal_row = self._action_row(
            "内部任务与会话数据",
            "删除后无法恢复；不会删除已导出的 Excel。",
            "清除内部数据",
            "internal",
            cleanup_group,
        )
        cleanup_layout.addWidget(internal_row)
        layout.addWidget(cleanup_group)

        diagnostics_group = QFrame(self)
        diagnostics_group.setObjectName("settingsGroup")
        diagnostics_layout = QVBoxLayout(diagnostics_group)
        diagnostics_layout.setContentsMargins(16, 14, 16, 14)
        diagnostics_layout.setSpacing(8)
        diagnostics_title = QLabel("诊断", diagnostics_group)
        diagnostics_title.setObjectName("sectionHeading")
        diagnostics_layout.addWidget(diagnostics_title)
        diagnostics_row = QHBoxLayout()
        diagnostics_copy = QVBoxLayout()
        diagnostics_copy_title = QLabel("导出问题报告", diagnostics_group)
        diagnostics_copy_title.setObjectName("settingRowTitle")
        diagnostics_copy.addWidget(diagnostics_copy_title)
        diagnostics_hint = QLabel(
            "包含版本、脱敏日志和运行摘要；不包含 Cookie、Token 或网页正文。",
            diagnostics_group,
        )
        diagnostics_hint.setObjectName("settingRowHint")
        diagnostics_hint.setWordWrap(True)
        diagnostics_copy.addWidget(diagnostics_hint)
        diagnostics_row.addLayout(diagnostics_copy, 1)
        self.export_button = QPushButton("导出诊断包", diagnostics_group)
        self.export_button.setObjectName("primaryButton")
        self.export_button.setAccessibleName("导出诊断包")
        self.export_button.clicked.connect(self.diagnostics_export_requested)
        diagnostics_row.addWidget(self.export_button)
        diagnostics_layout.addLayout(diagnostics_row)
        layout.addWidget(diagnostics_group)
        layout.addStretch(1)
        self.refresh()

    def _action_row(
        self,
        title: str,
        hint: str,
        button_text: str,
        kind: str,
        parent: QWidget,
    ) -> QFrame:
        row = QFrame(parent)
        row.setObjectName("settingsRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 12, 0, 12)
        copy = QVBoxLayout()
        title_label = QLabel(title, row)
        title_label.setObjectName("settingRowTitle")
        copy.addWidget(title_label)
        hint_label = QLabel(hint, row)
        hint_label.setObjectName("settingRowHint")
        hint_label.setWordWrap(True)
        copy.addWidget(hint_label)
        row_layout.addLayout(copy, 1)
        button = QPushButton(button_text, row)
        button.setAccessibleName(button_text)
        if kind == "internal":
            button.setObjectName("dangerButton")
            self.clear_internal_button = button
            self.clear_internal_button.setToolTip(
                "清除会话、运行产物和日志；保留诊断 ZIP、任务历史、工作流数据库及已导出的 Excel 文件。"
            )
            button.clicked.connect(self._confirm_internal_clear)
        else:
            if not hasattr(self, "clear_temp_button"):
                self.clear_temp_button = button
                button.clicked.connect(self._confirm_temporary_clear)
            else:
                button.clicked.connect(self._confirm_temporary_clear)
        row_layout.addWidget(button)
        return row

    def refresh(self) -> None:
        summary = self.facade.storage_summary() if hasattr(self.facade, "storage_summary") else {"bytes": 0, "files": 0}
        total = int(summary.get("bytes", 0))
        self.usage_label.setText(_format_bytes(total))
        self.file_count_label.setText(f"{int(summary.get('files', 0))} 个文件")
        snapshot = int(summary.get("snapshot_bytes", 0))
        cache = int(summary.get("translation_cache_bytes", 0))
        logs = int(summary.get("log_bytes", 0))
        self.snapshot_label.setText(f"页面快照 {_format_bytes(snapshot)}")
        self.cache_label.setText(f"翻译缓存 {_format_bytes(cache)}")
        self.logs_label.setText(f"日志 {_format_bytes(logs)}")
        used_categories = snapshot + cache + logs
        self.storage_usage_bar.setValue(min(100, round(used_categories / total * 100)) if total else 0)

    def _confirm_internal_clear(self) -> None:
        if (
            QMessageBox.question(
                self,
                "清除内部数据",
                "此操作会清除本地会话、运行产物和日志。诊断 ZIP、任务历史、工作流数据库及已导出的 Excel 文件会保留。确定继续吗？",
            )
            == QMessageBox.Yes
        ):
            self.clear_internal_requested.emit()

    def _confirm_temporary_clear(self) -> None:
        if (
            QMessageBox.question(
                self,
                "清理临时数据",
                "此操作会移除临时文件和页面截图。确定继续吗？",
            )
            == QMessageBox.Yes
        ):
            self.clear_temporary_requested.emit()
