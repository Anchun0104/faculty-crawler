"""Operational overview with a calm launch surface and actionable summaries."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.page_header import PageHeader


class OverviewPage(QWidget):
    new_crawl_requested = Signal()

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._current_task_id = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.page_header = PageHeader("概览", "查看当前采集状态和需要关注的任务。", "新建采集", self)
        self.page_header.primary_clicked.connect(self.new_crawl_requested)
        self.new_crawl_button = self.page_header.primary_button
        layout.addWidget(self.page_header)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.quick_start_card = self._build_quick_start_card()
        hero.addWidget(self.quick_start_card, 1)
        self.current_run_card = self._build_current_run_card()
        hero.addWidget(self.current_run_card, 1)
        layout.addLayout(hero)

        self.attention_section = QFrame(self)
        self.attention_section.setObjectName("attentionSection")
        attention_layout = QVBoxLayout(self.attention_section)
        attention_layout.setContentsMargins(0, 0, 0, 0)
        attention_title = QLabel("需要关注", self.attention_section)
        attention_title.setObjectName("sectionHeading")
        attention_layout.addWidget(attention_title)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.task_count = self._metric_card("任务", metrics)
        self.action_count = self._metric_card("等待人工验证或建议复核", metrics)
        self.success_rate = self._metric_card("近 7 天成功率", metrics)
        attention_layout.addLayout(metrics)
        layout.addWidget(self.attention_section)

        recent_title = QLabel("最近任务", self)
        recent_title.setObjectName("sectionHeading")
        layout.addWidget(recent_title)
        self.table = DataTable(("任务", "学科", "状态", "更新时间"), self)
        self.table.setAccessibleName("最近任务")
        self.empty_state = EmptyState("暂无任务", "从已验证的目录 URL 或 XLSX 来源创建一次采集。", "新建采集", self)
        self.empty_state.action_button.clicked.connect(self.new_crawl_requested)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_state, 1)
        self.refresh()

    def _build_quick_start_card(self) -> QFrame:
        card = QFrame(self)
        card.setObjectName("quickStartCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        eyebrow = QLabel("快速开始", card)
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("采集教师目录", card)
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        copy = QLabel("输入一个公开教师目录 URL，或导入 XLSX 批量任务。运行前可复核输出位置与访问策略。", card)
        copy.setObjectName("cardDescription")
        copy.setWordWrap(True)
        layout.addWidget(copy)
        actions = QHBoxLayout()
        create = QPushButton("新建采集", card)
        create.setObjectName("primaryButton")
        create.clicked.connect(self.new_crawl_requested)
        actions.addWidget(create)
        import_button = QPushButton("导入 XLSX", card)
        actions.addWidget(import_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return card

    def _build_current_run_card(self) -> QFrame:
        card = QFrame(self)
        card.setObjectName("currentRunCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        eyebrow = QLabel("当前运行", card)
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        self.current_run_title = QLabel("暂无运行中的任务", card)
        self.current_run_title.setObjectName("cardTitle")
        layout.addWidget(self.current_run_title)
        self.current_run_detail = QLabel("后台服务空闲", card)
        self.current_run_detail.setObjectName("cardDescription")
        self.current_run_detail.setWordWrap(True)
        layout.addWidget(self.current_run_detail)
        self.current_run_progress = QLabel("", card)
        self.current_run_progress.setObjectName("progressSummary")
        layout.addWidget(self.current_run_progress)
        layout.addStretch(1)
        self.view_task_button = QPushButton("查看任务", card)
        self.view_task_button.setEnabled(False)
        layout.addWidget(self.view_task_button)
        return card

    @staticmethod
    def _metric_card(title: str, layout: QHBoxLayout) -> QLabel:
        card = QFrame()
        card.setObjectName("metricCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel(title, card)
        label.setObjectName("metricLabel")
        label.setWordWrap(True)
        card_layout.addWidget(label)
        value = QLabel("0", card)
        value.setObjectName("metricValue")
        card_layout.addWidget(value)
        note = QLabel("", card)
        note.setObjectName("metricNote")
        card_layout.addWidget(note)
        value._metric_note = note  # type: ignore[attr-defined]
        layout.addWidget(card, 1)
        return value

    def refresh(self) -> None:
        rows = tuple(self.facade.task_rows()) if hasattr(self.facade, "task_rows") else ()
        attention = sum(row.get("status") in {"failed", "cancelled", "paused_budget", "needs_verification", "review"} for row in rows)
        self.task_count.setText(str(len(rows)))
        self.action_count.setText(str(attention))
        completed = sum(row.get("status") == "completed" for row in rows)
        self.success_rate.setText(f"{round(completed / len(rows) * 100) if rows else 0}%")
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

        current = next((row for row in rows if row.get("status") == "running"), None)
        if current is None:
            current = next((row for row in rows if row.get("status") == "ready"), None)
        if current is None:
            self._current_task_id = ""
            self.current_run_title.setText("暂无运行中的任务")
            self.current_run_detail.setText("后台服务空闲")
            self.current_run_progress.clear()
            self.view_task_button.setEnabled(False)
        else:
            self._current_task_id = str(current.get("id", ""))
            self.current_run_title.setText(str(current.get("name", current.get("run_name", current.get("id", "")))))
            if current.get("status") == "ready":
                self.current_run_detail.setText(f"{current.get('discipline', '')} · 等待后台启动")
                self.current_run_progress.setText("准备运行")
            else:
                self.current_run_detail.setText(f"{current.get('discipline', '')} · 正在采集")
                self.current_run_progress.setText("运行中")
            self.view_task_button.setEnabled(True)

    def set_live_progress(self, event: dict[str, object]) -> None:
        """Show the latest crawler heartbeat for the task currently on screen."""
        if str(event.get("task_id", "")) != self._current_task_id:
            return
        message = str(event.get("message", ""))
        school_name = str(event.get("school_name", ""))
        url = str(event.get("url", ""))
        target = self._display_target(url)
        labels = {
            "school_started": "开始采集学校目录",
            "directory_page_started": "正在抓取目录页",
            "profile_page_started": "正在抓取教师页",
            "directory_candidate_saved": "已保存目录候选记录",
            "candidate_saved": "已保存教师记录",
            "profile_fetch_review": "教师页需要人工复核",
            "school_finished": "已完成学校采集",
        }
        description = labels.get(message, "正在处理采集任务")
        details = " · ".join(part for part in (school_name, target) if part)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.current_run_progress.setText(f"{timestamp} · {description}{f'：{details}' if details else ''}")

    @staticmethod
    def _display_target(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.netloc:
            return ""
        path = parsed.path.rstrip("/")
        if len(path) > 42:
            path = f"{path[:39]}…"
        return f"{parsed.netloc}{path}"

    @staticmethod
    def _status_text(status: object) -> str:
        return {
            "queued": "排队中",
            "running": "运行中",
            "completed": "已完成",
            "needs_verification": "等待人工验证",
            "review": "建议复核",
            "failed": "失败",
            "cancelled": "已终止",
            "paused_budget": "已暂停",
        }.get(str(status), str(status))
