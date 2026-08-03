"""Translation and external-AI settings with encrypted-key-safe UI state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QSignalBlocker, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_ui.dialogs.api_key import ApiKeyDialog
from desktop_ui.models import AiSettingsView, AiUsageView, SaveAiSettings
from desktop_ui.widgets.info_bar import InfoBar


def _format_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(value)


class _ConnectionTestThread(QThread):
    """Run a potentially slow provider request outside Qt's GUI thread."""

    completed = Signal(bool)

    def __init__(self, facade: object, parent: QWidget) -> None:
        super().__init__(parent)
        self._facade = facade

    def run(self) -> None:  # noqa: N802 - Qt override name
        try:
            self._facade.test_ai_connection()
        except Exception:  # The UI intentionally avoids displaying provider exception text.
            self.completed.emit(False)
        else:
            self.completed.emit(True)


class _UsageCard(QFrame):
    def __init__(self, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        label = QLabel(title, self)
        label.setObjectName("metricLabel")
        layout.addWidget(label)
        self.value = QLabel("—", self)
        self.value.setObjectName("metricValue")
        layout.addWidget(self.value)
        self.note = QLabel(self)
        self.note.setObjectName("metricNote")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)


class AiSettingsPage(QWidget):
    """Settings UI that only receives masked key metadata from the facade."""

    budget_changed = Signal(float)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._connection_thread: _ConnectionTestThread | None = None
        self.setAccessibleName("Translation and AI settings")
        # The containing settings scroll area keeps this full page reachable at
        # the approved 1180 x 720 minimum instead of compressing its controls.
        self.setMinimumHeight(760)
        self._build()
        self.key_dialog = ApiKeyDialog(self)
        self.key_dialog.key_submitted.connect(self._replace_key)
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.info_bar = InfoBar(
            "外部 AI 默认关闭，只会处理已获取的页面；不会发现或替换 URL、猜测邮箱、"
            "或绕过访问控制。",
            self,
        )
        layout.addWidget(self.info_bar)

        service_group = QFrame(self)
        service_group.setObjectName("settingsGroup")
        service_layout = QVBoxLayout(service_group)
        service_layout.setContentsMargins(16, 16, 16, 16)
        service_layout.setSpacing(12)
        heading = QLabel("AI 服务", service_group)
        heading.setObjectName("sectionHeading")
        service_layout.addWidget(heading)

        form = QFormLayout()
        form.setSpacing(10)
        self.enabled_checkbox = QCheckBox("启用外部 AI 辅助", service_group)
        self.enabled_checkbox.setAccessibleName("Enable external AI assistance")
        self.enabled_checkbox.toggled.connect(self._update_field_enabled_state)
        form.addRow("使用外部 AI", self.enabled_checkbox)
        self.provider_combo = QComboBox(service_group)
        self.provider_combo.addItem("DeepSeek", "deepseek")
        self.provider_combo.addItem("OpenAI 兼容接口", "compatible")
        self.provider_combo.setAccessibleName("AI provider")
        self.provider_combo.currentIndexChanged.connect(self._apply_provider_defaults)
        form.addRow("服务商", self.provider_combo)
        self.base_url_edit = QLineEdit(service_group)
        self.base_url_edit.setAccessibleName("AI base URL")
        self.base_url_edit.setPlaceholderText("https://api.example.com")
        form.addRow("Base URL", self.base_url_edit)
        self.model_edit = QLineEdit(service_group)
        self.model_edit.setAccessibleName("AI model")
        self.model_edit.setPlaceholderText("deepseek-v4-flash")
        form.addRow("模型", self.model_edit)
        service_layout.addLayout(form)

        key_row = QHBoxLayout()
        key_copy = QVBoxLayout()
        key_title = QLabel("API Key", service_group)
        key_title.setObjectName("settingRowTitle")
        key_copy.addWidget(key_title)
        key_hint = QLabel("使用 Windows DPAPI 加密；保存后不会再次显示明文。", service_group)
        key_hint.setObjectName("settingRowHint")
        key_hint.setWordWrap(True)
        key_copy.addWidget(key_hint)
        key_row.addLayout(key_copy, 1)
        self.key_status = QLabel("未配置", service_group)
        self.key_status.setObjectName("keyStatus")
        self.key_status.setAccessibleName("API key status")
        key_row.addWidget(self.key_status)
        self.replace_key_button = QPushButton("替换", service_group)
        self.replace_key_button.clicked.connect(self.open_replace_key_dialog)
        key_row.addWidget(self.replace_key_button)
        self.delete_key_button = QPushButton("删除", service_group)
        self.delete_key_button.setObjectName("dangerButton")
        self.delete_key_button.clicked.connect(self.request_delete_key)
        key_row.addWidget(self.delete_key_button)
        service_layout.addLayout(key_row)

        connection_row = QHBoxLayout()
        connection_copy = QVBoxLayout()
        connection_title = QLabel("连接状态", service_group)
        connection_title.setObjectName("settingRowTitle")
        connection_copy.addWidget(connection_title)
        self.connection_endpoint = QLabel(service_group)
        self.connection_endpoint.setObjectName("settingRowHint")
        connection_copy.addWidget(self.connection_endpoint)
        connection_row.addLayout(connection_copy, 1)
        self.connection_status = QLabel("尚未测试", service_group)
        self.connection_status.setAccessibleName("AI connection status")
        connection_row.addWidget(self.connection_status)
        self.test_connection_button = QPushButton("测试连接", service_group)
        self.test_connection_button.clicked.connect(self.test_connection)
        connection_row.addWidget(self.test_connection_button)
        service_layout.addLayout(connection_row)

        self.save_button = QPushButton("保存 AI 设置", service_group)
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save_settings)
        service_layout.addWidget(self.save_button, 0)
        layout.addWidget(service_group)

        usage_layout = QHBoxLayout()
        usage_layout.setSpacing(12)
        self._calls_card = _UsageCard("本月调用", self)
        self.calls_value = self._calls_card.value
        self.calls_note = self._calls_card.note
        usage_layout.addWidget(self._calls_card)
        self._tokens_card = _UsageCard("Token 用量", self)
        self.tokens_value = self._tokens_card.value
        self.tokens_note = self._tokens_card.note
        usage_layout.addWidget(self._tokens_card)
        self._cost_card = _UsageCard("预计费用", self)
        self.cost_value = self._cost_card.value
        self.cost_note = self._cost_card.note
        usage_layout.addWidget(self._cost_card)
        layout.addLayout(usage_layout)

        budget_group = QFrame(self)
        budget_group.setObjectName("settingsGroup")
        budget_layout = QVBoxLayout(budget_group)
        budget_layout.setContentsMargins(16, 16, 16, 16)
        budget_layout.setSpacing(12)
        budget_title = QLabel("预算与数据", budget_group)
        budget_title.setObjectName("sectionHeading")
        budget_layout.addWidget(budget_title)
        budget_row = QHBoxLayout()
        budget_copy = QVBoxLayout()
        default_budget_title = QLabel("默认任务预算", budget_group)
        default_budget_title.setObjectName("settingRowTitle")
        budget_copy.addWidget(default_budget_title)
        budget_hint = QLabel("达到 80% 时提示；达到上限后停止新的模型调用。", budget_group)
        budget_hint.setObjectName("settingRowHint")
        budget_copy.addWidget(budget_hint)
        budget_row.addLayout(budget_copy, 1)
        self.budget_input = QDoubleSpinBox(budget_group)
        self.budget_input.setRange(0.01, 10_000.0)
        self.budget_input.setDecimals(2)
        self.budget_input.setPrefix("$")
        self.budget_input.setSuffix(" USD")
        self.budget_input.setValue(20.0)
        self.budget_input.setAccessibleName("Default task budget in US dollars")
        self.budget_input.valueChanged.connect(self.budget_changed)
        budget_row.addWidget(self.budget_input)
        budget_layout.addLayout(budget_row)
        layout.addWidget(budget_group)

        detail_title = QLabel("用量明细", self)
        detail_title.setObjectName("sectionHeading")
        layout.addWidget(detail_title)
        self.usage_table = QTableWidget(0, 7, self)
        self.usage_table.setAccessibleName("AI usage details")
        self.usage_table.setHorizontalHeaderLabels(
            ("时间", "任务", "操作", "模型", "输入", "输出", "预计费用")
        )
        self.usage_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.usage_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.usage_table.setAlternatingRowColors(False)
        self.usage_table.verticalHeader().setVisible(False)
        self.usage_table.setMinimumHeight(180)
        layout.addWidget(self.usage_table, 1)

    def refresh(self) -> None:
        """Reload only non-secret settings metadata and recorded usage."""
        settings = self.facade.ai_settings()
        usage = self.facade.ai_usage()
        self._render_settings(settings)
        self._render_usage(usage)
        details = self.facade.ai_usage_details() if hasattr(self.facade, "ai_usage_details") else ()
        self._render_usage_details(details)

    def _render_settings(self, settings: AiSettingsView) -> None:
        with QSignalBlocker(self.enabled_checkbox):
            self.enabled_checkbox.setChecked(settings.enabled)
        with QSignalBlocker(self.provider_combo):
            index = self.provider_combo.findData(settings.provider)
            self.provider_combo.setCurrentIndex(index if index >= 0 else 0)
        self.base_url_edit.setText(settings.base_url)
        self.model_edit.setText(settings.model)
        configured = settings.key_configured
        self.key_status.setText("已配置" if configured else "未配置")
        self.key_status.setToolTip("仅显示配置状态；不会读取或显示 API Key。")
        self.delete_key_button.setEnabled(configured)
        self._update_field_enabled_state(settings.enabled)
        endpoint = settings.base_url.rstrip("/")
        self.connection_endpoint.setText(
            f"{endpoint}/chat/completions" if endpoint and not endpoint.endswith("/chat/completions") else endpoint
        )

    def _render_usage(self, usage: AiUsageView) -> None:
        self.calls_value.setText(str(usage.calls))
        self.calls_note.setText(f"成功 {usage.succeeded} · 失败 {usage.failed}")
        total_tokens = usage.input_tokens + usage.output_tokens
        self.tokens_value.setText(_format_tokens(total_tokens))
        self.tokens_note.setText(
            f"输入 {_format_tokens(usage.input_tokens)} · 输出 {_format_tokens(usage.output_tokens)}"
        )
        self.cost_value.setText(f"${usage.estimated_cost_usd:.2f}")
        self.cost_note.setText("以服务商账单为准")

    def _render_usage_details(self, details: Sequence[Mapping[str, object]]) -> None:
        self.usage_table.setRowCount(len(details))
        for row_index, row in enumerate(details):
            values = (
                str(row.get("created_at", "")),
                str(row.get("task_id", "")),
                str(row.get("operation", "")),
                str(row.get("model", "")),
                _format_tokens(int(row.get("input_tokens", 0))),
                _format_tokens(int(row.get("output_tokens", 0))),
                f"${float(row.get('estimated_cost_usd', 0.0)):.2f}",
            )
            for column, value in enumerate(values):
                self.usage_table.setItem(row_index, column, QTableWidgetItem(value))
        self.usage_table.resizeColumnsToContents()

    def _update_field_enabled_state(self, enabled: bool) -> None:
        for field in (self.provider_combo, self.base_url_edit, self.model_edit):
            field.setEnabled(enabled)
        self.replace_key_button.setEnabled(enabled)
        # A retained encrypted key may be deliberately kept while AI is
        # disabled.  It must remain explicitly deletable in that state.
        self.delete_key_button.setEnabled(self.key_status.text() == "已配置")

    def _apply_provider_defaults(self) -> None:
        if self.provider_combo.currentData() == "deepseek" and not self.base_url_edit.text().strip():
            self.base_url_edit.setText("https://api.deepseek.com")
        if self.provider_combo.currentData() == "deepseek" and not self.model_edit.text().strip():
            self.model_edit.setText("deepseek-v4-flash")

    def _settings_command(self, *, api_key: str | None = None) -> SaveAiSettings:
        enabled = self.enabled_checkbox.isChecked()
        return SaveAiSettings(
            enabled=enabled,
            provider=str(self.provider_combo.currentData()) if enabled else "local",
            base_url=self.base_url_edit.text().strip() if enabled else "",
            model=self.model_edit.text().strip() if enabled else "",
            api_key=api_key,
        )

    def save_settings(self) -> bool:
        """Save metadata only: None explicitly preserves the encrypted key."""
        try:
            self.facade.save_ai_settings(self._settings_command(api_key=None))
        except ValueError as error:
            self.info_bar.set_message(f"无法保存 AI 设置：{error}")
            return False
        self.info_bar.set_message("AI 设置已保存。API Key 状态保持不变。")
        self.refresh()
        return True

    def open_replace_key_dialog(self) -> None:
        self.key_dialog.open_for_replacement()

    def _replace_key(self, api_key: str) -> None:
        try:
            self.facade.save_ai_settings(self._settings_command(api_key=api_key))
        except ValueError as error:
            self.info_bar.set_message(f"无法保存 API Key：{error}")
            return
        self.info_bar.set_message("API Key 已加密保存，之后不会显示明文。")
        self.refresh()

    def request_delete_key(self) -> None:
        answer = QMessageBox.question(
            self,
            "删除 API Key",
            "删除后，使用外部 AI 的新调用将无法进行。确定删除吗？",
            QMessageBox.Cancel | QMessageBox.Delete,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Delete:
            self.delete_key()

    def delete_key(self) -> None:
        self.facade.delete_ai_key()
        self.info_bar.set_message("API Key 已删除。")
        self.refresh()

    def test_connection(self) -> None:
        if self._connection_thread is not None:
            return
        if not self.enabled_checkbox.isChecked():
            self.info_bar.set_message("请先启用外部 AI，再测试连接。")
            return
        if self.key_status.text() != "已配置":
            self.info_bar.set_message("请先配置 API Key，再测试连接。")
            return
        if not self.save_settings():
            return
        self.connection_status.setText("正在测试…")
        self.test_connection_button.setEnabled(False)
        thread = _ConnectionTestThread(self.facade, self)
        self._connection_thread = thread
        thread.completed.connect(self._finish_connection_test)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _finish_connection_test(self, succeeded: bool) -> None:
        self._connection_thread = None
        self.test_connection_button.setEnabled(True)
        if succeeded:
            self.connection_status.setText("测试成功")
            self.info_bar.set_message("连接测试成功。外部 AI 仍只会处理已获取的页面。")
        else:
            self.connection_status.setText("测试失败")
            self.info_bar.set_message("连接测试失败。请检查服务商、Base URL、模型和 API Key。")
