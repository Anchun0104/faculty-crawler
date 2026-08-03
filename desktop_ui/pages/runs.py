"""运行历史页面：批次列表、结果指标和阶段时间线。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.page_header import PageHeader


class _MetricCard(QFrame):
    def __init__(self, title: str, object_name: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        self.title = QLabel(title, self)
        self.title.setObjectName("metricLabel")
        layout.addWidget(self.title)
        self.value = QLabel("—", self)
        self.value.setObjectName("metricValue")
        layout.addWidget(self.value)


class RunsPage(QWidget):
    """Stable run-history view; no monitoring or workflow semantics live here."""

    export_requested = Signal(str)
    open_output_requested = Signal(str)
    view_task_requested = Signal(str)

    _STATUS_LABELS = (
        ("全部", ""),
        ("运行中", "running"),
        ("已完成", "completed"),
        ("等待人工验证", "needs_verification"),
        ("失败", "failed"),
    )

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._rows: dict[str, dict[str, object]] = {}
        self._selected = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.page_header = PageHeader(
            "运行历史",
            "查看每次运行的阶段、结果、输出和脱敏诊断。",
            "导出运行报告",
            self,
        )
        self.page_header.primary_clicked.connect(self._export_selected)
        self.export_button = self.page_header.primary_button
        self.export_button.setEnabled(False)
        layout.addWidget(self.page_header)

        tools = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索运行或站点")
        self.search.setAccessibleName("搜索运行或站点")
        self.search.textChanged.connect(self._render)
        tools.addWidget(self.search, 1)
        self.status_filter = QComboBox(self)
        self.status_filter.setAccessibleName("筛选运行状态")
        for label, value in self._STATUS_LABELS:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self._render)
        tools.addWidget(self.status_filter)
        layout.addLayout(tools)

        body = QHBoxLayout()
        body.setSpacing(12)

        queue = QFrame(self)
        queue.setObjectName("runBatchList")
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        self.table = DataTable(("运行批次", "状态", "时间"), queue)
        self.table.setAccessibleName("运行批次列表")
        self.table.selection_changed.connect(self._select)
        self.empty_state = EmptyState(
            "暂无运行记录",
            "完成或正在运行的采集批次会显示在这里。",
            parent=queue,
        )
        queue_layout.addWidget(self.table, 1)
        queue_layout.addWidget(self.empty_state, 1)
        body.addWidget(queue, 2)

        self.detail_panel = QFrame(self)
        self.detail_panel.setObjectName("runDetailPanel")
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(12)

        heading_row = QHBoxLayout()
        heading_copy = QVBoxLayout()
        self.run_name_label = QLabel("选择一个运行批次", self.detail_panel)
        self.run_name_label.setObjectName("sectionHeading")
        heading_copy.addWidget(self.run_name_label)
        self.run_id_label = QLabel("查看该批次的阶段、结果和脱敏诊断。", self.detail_panel)
        self.run_id_label.setObjectName("settingRowHint")
        heading_copy.addWidget(self.run_id_label)
        heading_row.addLayout(heading_copy, 1)
        self.run_status_label = QLabel("", self.detail_panel)
        self.run_status_label.setObjectName("statusBadge")
        heading_row.addWidget(self.run_status_label, 0)
        detail_layout.addLayout(heading_row)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(8)
        self.metrics = [
            _MetricCard("已接受", "acceptedMetric", self.detail_panel),
            _MetricCard("建议复核", "reviewMetric", self.detail_panel),
            _MetricCard("已排除", "excludedMetric", self.detail_panel),
        ]
        for metric in self.metrics:
            metrics_layout.addWidget(metric, 1)
        detail_layout.addLayout(metrics_layout)

        timeline_title = QLabel("阶段时间线", self.detail_panel)
        timeline_title.setObjectName("sectionHeading")
        detail_layout.addWidget(timeline_title)
        self.timeline = QFrame(self.detail_panel)
        self.timeline.setObjectName("runTimeline")
        self.timeline_layout = QVBoxLayout(self.timeline)
        self.timeline_layout.setContentsMargins(4, 0, 4, 0)
        self.timeline_layout.setSpacing(6)
        detail_layout.addWidget(self.timeline, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.output_button = QPushButton("打开输出目录", self.detail_panel)
        self.output_button.clicked.connect(lambda: self.open_output_requested.emit(self._selected))
        self.output_button.setEnabled(False)
        actions.addWidget(self.output_button)
        self.view_task_button = QPushButton("查看任务", self.detail_panel)
        self.view_task_button.clicked.connect(lambda: self.view_task_requested.emit(self._selected))
        self.view_task_button.setEnabled(False)
        actions.addWidget(self.view_task_button)
        detail_layout.addLayout(actions)
        body.addWidget(self.detail_panel, 3)
        layout.addLayout(body, 1)

        self.refresh()

    def refresh(self) -> None:
        rows = self.facade.task_rows() if hasattr(self.facade, "task_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}
        if self._selected not in self._rows:
            self._selected = ""
        self._render()
        # A deterministic first selection keeps the run detail visible in the
        # approved screenshot state while preserving row IDs and signals.
        if not self._selected and self._rows:
            self._select(next(iter(self._rows)))

    def _render(self) -> None:
        query = self.search.text().strip().casefold()
        status = str(self.status_filter.currentData() or "")
        rows = [
            row
            for row in self._rows.values()
            if (not status or row.get("status") == status)
            and (not query or query in " ".join(map(str, row.values())).casefold())
        ]
        self.table.set_rows(
            (
                str(row["id"]),
                (
                    row.get("run_name", row.get("discipline", row["id"])),
                    self._status_text(row.get("status", "")),
                    row.get("updated_at", row.get("created_at", "")),
                ),
            )
            for row in rows
        )
        self.table.setVisible(bool(rows))
        self.empty_state.setVisible(not rows)
        if self._selected and self._selected not in {str(row["id"]) for row in rows}:
            self.detail_panel.setVisible(False)
            self._set_actions_enabled(False)
        elif self._selected:
            self.detail_panel.setVisible(True)

    def _select(self, task_id: str) -> None:
        task_id = str(task_id)
        if task_id not in self._rows:
            return
        self._selected = task_id
        row = self._rows[task_id]
        detail = self._run_detail(task_id, row)
        self.run_name_label.setText(str(detail.get("run_name", row.get("run_name", row.get("discipline", task_id)))))
        run_id = detail.get("run_id", row.get("run_id", task_id))
        source = detail.get("source", row.get("source", "直接 URL"))
        self.run_id_label.setText(f"运行 ID：{run_id} · 来源：{source}")
        self.run_status_label.setText(self._status_text(detail.get("status", row.get("status", ""))))
        self._set_metric(self.metrics[0], detail.get("accepted", detail.get("records", 0)))
        self._set_metric(self.metrics[1], detail.get("review", detail.get("needs_review", 0)))
        self._set_metric(self.metrics[2], detail.get("excluded", 0))
        self._render_timeline(detail.get("timeline", ()))
        self.detail_panel.setVisible(True)
        self._set_actions_enabled(True)
        self.export_button.setEnabled(str(detail.get("status", row.get("status", ""))) == "completed")

    def select_run(self, run_id: str) -> None:
        """Public alias used by the fixture and keyboard-oriented smoke tests."""
        self._select(run_id)

    def _run_detail(self, task_id: str, row: Mapping[str, object]) -> dict[str, object]:
        provider = getattr(self.facade, "run_detail", None)
        if callable(provider):
            detail = provider(task_id)
            if isinstance(detail, Mapping):
                return dict(detail)
        provider = getattr(self.facade, "task_detail", None)
        if callable(provider):
            detail = provider(task_id)
            if isinstance(detail, Mapping):
                return dict(detail)
        return dict(row)

    def _render_timeline(self, events: Sequence[Mapping[str, object]] | object) -> None:
        while self.timeline_layout.count():
            item = self.timeline_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
            events = ()
        if not events:
            events = (
                {"time": "—", "title": "暂无阶段记录", "detail": "运行开始后会在此显示脱敏阶段信息。"},
            )
        for event in events:
            row = QFrame(self.timeline)
            row.setObjectName("timelineEvent")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 3, 0, 3)
            row_layout.setSpacing(8)
            dot = QLabel("●", row)
            dot.setObjectName("timelineDot")
            row_layout.addWidget(dot, 0)
            time = QLabel(str(event.get("time", "")), row)
            time.setObjectName("timelineTime")
            time.setFixedWidth(62)
            row_layout.addWidget(time, 0)
            copy = QVBoxLayout()
            title = QLabel(str(event.get("title", "")), row)
            title.setObjectName("settingRowTitle")
            copy.addWidget(title)
            detail = QLabel(str(event.get("detail", "")), row)
            detail.setObjectName("settingRowHint")
            detail.setWordWrap(True)
            copy.addWidget(detail)
            row_layout.addLayout(copy, 1)
            self.timeline_layout.addWidget(row)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.output_button.setEnabled(enabled)
        self.view_task_button.setEnabled(enabled)

    @staticmethod
    def _set_metric(card: _MetricCard, value: object) -> None:
        card.value.setText(str(value if value is not None else 0))

    def _export_selected(self) -> None:
        if self._selected and self.export_button.isEnabled():
            self.export_requested.emit(self._selected)

    @staticmethod
    def _status_text(status: object) -> str:
        return {
            "queued": "排队中",
            "ready": "准备运行",
            "running": "运行中",
            "completed": "已完成",
            "needs_verification": "等待人工验证",
            "failed": "失败",
            "paused_budget": "预算暂停",
        }.get(str(status), str(status))
