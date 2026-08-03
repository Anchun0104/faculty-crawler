"""Task queue with compact filters and a contextual 360px inspector."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.inspector import Inspector
from desktop_ui.widgets.page_header import PageHeader


class TasksPage(QWidget):
    task_selected = Signal(str)
    export_requested = Signal(str)
    new_crawl_requested = Signal()

    _STATUS_LABELS = (
        ("全部", ""),
        ("待确认口径", "needs_policy_confirmation"),
        ("准备运行", "ready"),
        ("运行中", "running"),
        ("已完成", "completed"),
        ("失败", "failed"),
        ("预算暂停", "paused_budget"),
        ("等待人工验证", "needs_verification"),
    )

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._rows: dict[str, dict[str, object]] = {}
        self._selected = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.page_header = PageHeader("任务", "管理采集队列、状态与输出。", "新建采集", self)
        self.page_header.primary_clicked.connect(self.new_crawl_requested)
        layout.addWidget(self.page_header)

        tools = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索任务或站点")
        self.search.setAccessibleName("搜索任务或站点")
        self.search.textChanged.connect(self._render)
        tools.addWidget(self.search, 1)
        self.status_filter = QComboBox(self)
        self.status_filter.setAccessibleName("筛选任务状态")
        for label, value in self._STATUS_LABELS:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self._render)
        tools.addWidget(self.status_filter)
        self.filter_button = QPushButton("筛选", self)
        tools.addWidget(self.filter_button)
        self.more_button = QPushButton("更多", self)
        tools.addWidget(self.more_button)
        layout.addLayout(tools)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.table = DataTable(("任务", "学科", "状态", "更新时间"), self)
        self.table.setAccessibleName("任务列表")
        self.table.selection_changed.connect(self.select_task)
        self.empty_state = EmptyState("没有匹配的任务", "调整筛选条件，或创建一次新的采集。", "新建采集", self)
        self.empty_state.action_button.clicked.connect(self.new_crawl_requested)
        queue = QWidget(self)
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.addWidget(self.table, 1)
        queue_layout.addWidget(self.empty_state, 1)
        body.addWidget(queue, 1)

        self.inspector = Inspector("所选任务", self)
        body.addWidget(self.inspector)
        layout.addLayout(body, 1)

        self.export_button = QPushButton("导出结果", self)
        self.export_button.setObjectName("secondaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(lambda: self.export_requested.emit(self._selected))
        layout.addWidget(self.export_button, 0)
        self.refresh()

    def refresh(self) -> None:
        rows = self.facade.task_rows() if hasattr(self.facade, "task_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}
        if self._selected not in self._rows:
            self._selected = ""
            self.inspector.hide()
            self.export_button.setEnabled(False)
        self._render()

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
                    row.get("name", row.get("run_name", row["id"])),
                    row.get("discipline", ""),
                    self._status_text(row.get("status", "")),
                    row.get("updated_at", ""),
                ),
            )
            for row in rows
        )
        self.table.setVisible(bool(rows))
        self.empty_state.setVisible(not rows)

    def select_task(self, task_id: str) -> None:
        self._selected = task_id
        details = self.facade.task_detail(task_id) if hasattr(self.facade, "task_detail") else self._rows.get(task_id, {})
        translated = self._translated_details(details)
        self.inspector.show_details(translated)
        self.export_button.setEnabled(str(details.get("status", "")) == "completed")
        self.task_selected.emit(task_id)

    @staticmethod
    def _translated_details(details: dict[str, object]) -> dict[str, object]:
        keys = (
            ("discipline", "学科"),
            ("status", "状态"),
            ("schools", "学校数"),
            ("records", "记录数"),
            ("output_dir", "输出位置"),
            ("created_at", "创建时间"),
            ("updated_at", "更新时间"),
            ("budget_usd", "预算"),
        )
        return {label: TasksPage._status_text(details.get(key, "")) if key == "status" else details.get(key, "") for key, label in keys if key in details}

    @staticmethod
    def _status_text(status: object) -> str:
        return {
            "queued": "排队中",
            "ready": "准备运行",
            "running": "运行中",
            "completed": "已完成",
            "needs_policy_confirmation": "待确认口径",
            "needs_verification": "等待人工验证",
            "review": "建议复核",
            "failed": "失败",
            "paused_budget": "预算暂停",
        }.get(str(status), str(status))
