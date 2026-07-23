from __future__ import annotations

import queue
import re
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qsl, urlparse

from crawler.batch import CrawlTask, prepare_tasks
from crawler.diagnostics import ReportRecord
from crawler.models import TaskStatus
from crawler.privacy import (
    SAFE_QUERY_KEYS,
    is_sensitive_key,
    redact_log_text,
    safe_url_for_log,
)
from crawler.settings_store import AppSettings


DEFAULT_TIMEOUT_MS = 30_000

STATUS_LABELS = {
    "pending": "等待",
    "running": "采集中",
    "fetching": "正在打开网页",
    "expanding": "正在加载更多内容",
    "parsing": "正在整理信息",
    "retry_wait": "稍后重试",
    "verification_required": "等待人工验证",
    "ready_to_resume": "可以继续采集",
    "succeeded": "已完成",
    "review_recommended": "已完成，建议检查",
    "failed": "失败",
    "cancelled": "已停止",
}


@dataclass(frozen=True)
class AppViewState:
    invalid_lines: tuple[tuple[int, str], ...] = ()
    valid_count: int = 0
    output_dir: str = ""
    can_start: bool = False
    running: bool = False
    stop_requested: bool = False
    status_symbol: str = "○"
    status_text: str = "请粘贴教师名录页网址。"


@dataclass(frozen=True)
class TaskView:
    key: str
    site: str
    safe_url: str
    status_symbol: str
    status_text: str
    record_count: int
    output_name: str
    next_action: str
    technical_info: str = ""


@dataclass(frozen=True)
class VerificationView:
    run_id: str
    task_id: str
    hostname: str
    detected_at: str
    reason: str
    status_text: str


@dataclass(frozen=True)
class SessionView:
    hostname: str
    saved_at: datetime
    last_used_at: datetime
    cleanup_at: datetime


@dataclass(frozen=True)
class RunView:
    run_id: str
    summary: str
    result_folder: str


@dataclass(frozen=True)
class ReportView:
    report_id: str
    path: str
    created_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True)
class SettingsView:
    output_dir: str
    feishu_folder_url: str
    detailed_logs: bool
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    error: str = ""


@dataclass(frozen=True)
class StorageSummary:
    total_bytes: int
    files: int
    categories: tuple[str, ...] = (
        "任务状态",
        "保存的会话",
        "运行日志",
        "问题报告 ZIP 和元数据",
        "临时截图",
    )


@dataclass(frozen=True)
class CleanupSummary:
    confirmed: bool
    removed_files: int
    message: str


class AppController:
    """Tk-independent state and command boundary for the desktop shell."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        runner: Callable[..., bool],
        stop_after_current: Callable[[], None] | None = None,
        verification_queue=None,
        verification_starter: Callable[[str, str], bool] | None = None,
        verification_defer: Callable[[str, str], None] | None = None,
        session_store=None,
        task_store=None,
        report_store=None,
        settings_store=None,
        retention_service=None,
        opener=None,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._timeout_ms = DEFAULT_TIMEOUT_MS
        self._settings_output_draft: str | None = None
        self._runner = runner
        self._stop = stop_after_current
        self._verification_queue = verification_queue
        self._verification_starter = verification_starter
        self._verification_defer = verification_defer
        self._session_store = session_store
        self._task_store = task_store
        self._report_store = report_store
        self._settings_store = settings_store
        self._retention = retention_service
        self._opener = opener
        self._active_verification: tuple[str, str] | None = None
        self._verification_sequence: deque[tuple[str, str]] = deque()
        self._stop_event = threading.Event()
        self._workers: dict[str, threading.Thread] = {}
        self.events: queue.Queue[object] = queue.Queue()
        self._tasks: list[CrawlTask] = []
        self._state = AppViewState(output_dir=str(self._output_dir))

    @property
    def state(self) -> AppViewState:
        return self._state

    @property
    def tasks(self) -> tuple[CrawlTask, ...]:
        return tuple(self._tasks)

    def task_views(self) -> tuple[TaskView, ...]:
        return tuple(_task_view(index, task) for index, task in enumerate(self._tasks))

    def verification_views(self) -> tuple[VerificationView, ...]:
        if self._verification_queue is None:
            return ()
        return tuple(_verification_view(item) for item in self._verification_queue.items())

    @property
    def active_verification(self) -> tuple[str, str] | None:
        return self._active_verification

    def verification_badge_count(self) -> int:
        if self._verification_queue is None:
            return 0
        return sum(
            _status_value(item.status) == TaskStatus.VERIFICATION_REQUIRED.value
            for item in self._verification_queue.items()
        )

    def start_verification(self, run_id: str, task_id: str) -> bool:
        if (
            self._active_verification is not None
            or self._verification_sequence
            or self.verification_worker_alive
        ):
            return False
        identity = (run_id, task_id)
        pending = {
            (item.run_id, item.task_id)
            for item in self._pending_verifications()
        }
        if identity not in pending:
            raise KeyError("verification item is not pending")
        return self._start_verification_identity(identity)

    def process_all_verifications(self) -> bool:
        if (
            self._active_verification is not None
            or self._verification_sequence
            or self.verification_worker_alive
        ):
            return False
        self._verification_sequence = deque(
            (item.run_id, item.task_id) for item in self._pending_verifications()
        )
        return self._start_next_verification()

    def defer_verification(self, run_id: str, task_id: str) -> None:
        identity = (run_id, task_id)
        if self._active_verification != identity:
            raise ValueError("verification identity does not match active item")
        if self._verification_defer is not None:
            self._verification_defer(run_id, task_id)
        self._verification_sequence.clear()

    def verification_finished(
        self,
        run_id: str,
        task_id: str,
        status: TaskStatus | str,
    ) -> bool:
        identity = (run_id, task_id)
        if self._active_verification != identity:
            raise ValueError("verification identity does not match active item")
        self._active_verification = None
        value = _status_value(status)
        if value != TaskStatus.READY_TO_RESUME.value:
            self._verification_sequence.clear()
            return False
        if self._verification_worker_alive():
            return False
        return self._start_next_verification()

    @property
    def verification_sequence_pending(self) -> bool:
        return bool(self._verification_sequence)

    @property
    def verification_worker_alive(self) -> bool:
        return self._verification_worker_alive()

    def continue_verification_sequence(self) -> bool:
        if self._active_verification is not None or not self._verification_sequence:
            return False
        if self._verification_worker_alive():
            return False
        return self._start_next_verification()

    def session_views(self) -> tuple[SessionView, ...]:
        if self._session_store is None:
            return ()
        return tuple(
            SessionView(
                item.hostname,
                item.saved_at,
                item.last_used_at,
                item.expires_at,
            )
            for item in self._session_store.list_sessions()
        )

    def clear_session(self, hostname: str, *, confirmed: bool) -> bool:
        if not confirmed:
            return False
        if self._session_store is None:
            raise RuntimeError("session store is unavailable")
        self._session_store.clear_site(hostname)
        return True

    def clear_all_sessions(self, *, confirmed: bool) -> bool:
        if not confirmed:
            return False
        if self._session_store is None:
            raise RuntimeError("session store is unavailable")
        self._session_store.clear_all()
        return True

    def run_views(self) -> tuple[RunView, ...]:
        if self._task_store is None:
            return ()
        views = []
        for run in reversed(self._task_store.list_runs()):
            counts: dict[str, int] = {}
            folders = {str(Path(task.output_path).parent) for task in run.tasks}
            for task in run.tasks:
                label = self.status_label(task.status)
                counts[label] = counts.get(label, 0) + 1
            summary = "，".join(f"{label} {count}" for label, count in counts.items())
            result_folder = next(iter(folders)) if len(folders) == 1 else "多个保存位置"
            views.append(RunView(run.run_id, summary or "没有任务", result_folder))
        return tuple(views)

    def report_views(self) -> tuple[ReportView, ...]:
        if self._report_store is None:
            return ()
        return tuple(_report_view(record) for record in self._report_store.list_reports())

    def generate_problem_report(self, run_id: str) -> ReportView:
        if self._report_store is None:
            raise RuntimeError("report store is unavailable")
        return _report_view(self._report_store.generate(run_id))

    def open_report_handoff(self, report_id: str) -> ReportView:
        if self._report_store is None or self._settings_store is None or self._opener is None:
            raise RuntimeError("report handoff is unavailable")
        record = self._report_store.by_id(report_id)
        settings = self._settings_store.load()
        if settings is None:
            raise ValueError("请先设置飞书共享文件夹网址")
        self._opener.reveal(record.path)
        self._opener.open_url(settings.feishu_folder_url)
        return _report_view(record)

    def mark_report_submitted(self, report_id: str) -> ReportView:
        if self._report_store is None:
            raise RuntimeError("report store is unavailable")
        return _report_view(self._report_store.mark_submitted(report_id))

    def load_settings(self) -> SettingsView:
        if self._settings_store is None:
            return SettingsView(
                self._settings_output_draft or str(self._output_dir), "", False
            )
        settings = self._settings_store.load()
        if settings is None:
            return SettingsView(
                self._settings_output_draft or str(self._output_dir), "", False
            )
        return SettingsView(
            self._settings_output_draft or settings.output_dir,
            settings.feishu_folder_url,
            settings.detailed_logs,
            self._timeout_ms,
        )

    def change_settings_output_dir(self, output_dir: str | Path) -> SettingsView:
        value = str(Path(output_dir))
        self._settings_output_draft = value
        return replace(self.load_settings(), output_dir=value)

    def save_settings(
        self,
        output_dir: str,
        feishu_folder_url: str,
        detailed_logs: bool,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> SettingsView:
        if self._settings_store is None:
            raise RuntimeError("settings store is unavailable")
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            return SettingsView(output_dir, feishu_folder_url, detailed_logs, timeout_ms, "超时时间必须是大于 0 的整数")
        settings = AppSettings(output_dir, feishu_folder_url, detailed_logs)
        try:
            self._settings_store.save(settings)
        except (TypeError, ValueError):
            return SettingsView(
                output_dir,
                feishu_folder_url,
                detailed_logs,
                timeout_ms,
                "飞书文件夹网址必须是有效的 HTTPS 地址。",
            )
        self.set_output_dir(output_dir)
        self._settings_output_draft = output_dir
        self._timeout_ms = timeout_ms
        return SettingsView(output_dir, feishu_folder_url, detailed_logs, timeout_ms)

    def storage_usage(self) -> StorageSummary:
        if self._retention is None:
            return StorageSummary(0, 0)
        usage = self._retention.usage()
        return StorageSummary(usage.bytes, usage.files)

    def clear_temporary(self, *, confirmed: bool) -> CleanupSummary:
        if not confirmed:
            return CleanupSummary(False, 0, "未清理任何文件")
        if self._retention is None:
            raise RuntimeError("retention service is unavailable")
        removed = self._retention.clear_temporary()
        return CleanupSummary(True, len(removed), f"已清理 {len(removed)} 个临时文件")

    def clear_internal_data(self, *, confirmed: bool) -> CleanupSummary:
        if not confirmed:
            return CleanupSummary(False, 0, "未清理任何文件")
        if self._retention is None:
            raise RuntimeError("retention service is unavailable")
        removed = self._retention.clear_internal_data()
        return CleanupSummary(
            True,
            len(removed),
            f"已清除 {len(removed)} 个内部数据文件；Excel 和问题报告 ZIP 已保留",
        )

    def set_output_dir(self, output_dir: str | Path) -> AppViewState:
        self._output_dir = Path(output_dir)
        self._state = replace(self._state, output_dir=str(self._output_dir))
        return self._state

    def set_tasks(self, tasks) -> None:
        self._tasks = list(tasks)

    def prepare(self, raw_urls: str) -> AppViewState:
        invalid_lines = tuple(
            (line_number, _safe_invalid_display(value))
            for line_number, line in enumerate(raw_urls.splitlines(), start=1)
            if (value := line.strip()) and not _is_safe_http_url(value)
        )
        accepted = "\n".join(
            line.strip()
            for line in raw_urls.splitlines()
            if line.strip() and _is_safe_http_url(line.strip())
        )
        result = prepare_tasks(accepted, self._output_dir)
        self._tasks = result.tasks
        count = len(self._tasks)
        if invalid_lines:
            symbol = "!"
            status = f"请检查标记的 {len(invalid_lines)} 行；已识别 {count} 个网址。"
        elif count:
            symbol = "✓"
            status = f"已识别 {count} 个网址，可以开始采集。"
        else:
            symbol = "○"
            status = "请粘贴教师名录页网址。"
        self._state = AppViewState(
            invalid_lines=invalid_lines,
            valid_count=count,
            output_dir=str(self._output_dir),
            can_start=bool(count),
            status_symbol=symbol,
            status_text=status,
        )
        return self._state

    def start_batch(self) -> AppViewState:
        if not self._tasks:
            raise ValueError("没有可采集的网址")
        if self._state.running:
            return self._state
        self._state = replace(
            self._state,
            can_start=False,
            running=True,
            stop_requested=False,
            status_symbol="●",
            status_text="正在顺序采集，请勿关闭窗口。",
        )
        try:
            started = self._runner(self._tasks, timeout=self._timeout_ms)
        except BaseException:
            self._rollback_start()
            raise
        if not started:
            self._rollback_start()
        return self._state

    def stop_after_current(self) -> AppViewState:
        if not self._state.running or self._state.stop_requested:
            return self._state
        self._stop_event.set()
        if self._stop is not None:
            self._stop()
        self._state = replace(
            self._state,
            stop_requested=True,
            status_symbol="■",
            status_text="完成当前网址后停止。",
        )
        return self._state

    def launch_worker(
        self,
        role: str,
        *,
        target: Callable[..., None],
        args: tuple[object, ...] = (),
        kwargs: Mapping[str, object] | None = None,
        use_stop_event: bool = False,
        name: str | None = None,
    ) -> bool:
        existing = self._workers.get(role)
        if existing is not None and existing.is_alive():
            return False
        worker_kwargs = dict(kwargs or {})
        if use_stop_event:
            self._stop_event = threading.Event()
            worker_kwargs["stop_event"] = self._stop_event
        worker = threading.Thread(
            target=target,
            args=args,
            kwargs=worker_kwargs,
            daemon=True,
            name=name,
        )
        self._workers[role] = worker
        try:
            worker.start()
        except BaseException:
            self._workers.pop(role, None)
            raise
        return True

    def worker(self, role: str) -> threading.Thread | None:
        return self._workers.get(role)

    def drain_events(
        self,
        handlers: Mapping[str, Callable[[object], None]],
        *,
        default: Callable[[object], None] | None = None,
    ) -> int:
        count = 0
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return count
            handler = handlers.get(str(getattr(event, "kind", "")), default)
            if handler is not None:
                handler(event)
            count += 1

    def finish_batch(
        self,
        status_text: str,
        *,
        stopped: bool = False,
    ) -> AppViewState:
        self._state = replace(
            self._state,
            can_start=bool(self._tasks),
            running=False,
            stop_requested=False,
            status_symbol="■" if stopped else "✓",
            status_text=status_text,
        )
        return self._state

    @staticmethod
    def status_label(status: TaskStatus | str) -> str:
        value = status.value if isinstance(status, TaskStatus) else status
        return STATUS_LABELS.get(value, value)

    def _rollback_start(self) -> None:
        self._state = replace(
            self._state,
            can_start=True,
            running=False,
            stop_requested=False,
            status_symbol="×",
            status_text="未能开始采集，请查看提示后重试。",
        )

    def _pending_verifications(self):
        if self._verification_queue is None:
            return ()
        return tuple(self._verification_queue.pending())

    def _start_verification_identity(self, identity: tuple[str, str]) -> bool:
        if self._verification_starter is None:
            raise RuntimeError("verification starter is unavailable")
        self._active_verification = identity
        try:
            started = self._verification_starter(*identity)
        except BaseException:
            self._active_verification = None
            raise
        if not started:
            self._active_verification = None
        return bool(started)

    def _start_next_verification(self) -> bool:
        if not self._verification_sequence:
            return False
        identity = self._verification_sequence.popleft()
        started = self._start_verification_identity(identity)
        if not started:
            self._verification_sequence.clear()
        return started

    def _verification_worker_alive(self) -> bool:
        worker = self.worker("verification")
        return worker is not None and worker.is_alive()


def _is_safe_http_url(value: str) -> bool:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    query = parse_qsl(parsed.query, keep_blank_values=True)
    fragment = parse_qsl(parsed.fragment, keep_blank_values=True)
    return not any(
        key.casefold() not in SAFE_QUERY_KEYS
        or is_sensitive_key(key)
        or redact_log_text(item) != item
        for key, item in query
    ) and not any(
        is_sensitive_key(key) or redact_log_text(item) != item
        for key, item in fragment
    )


def _safe_invalid_display(value: str) -> str:
    value = re.sub(
        r"(?i)\b[^\s/:@]+:[^\s/@]+@",
        "<credentials>@",
        value,
    )
    parsed = urlparse(value)
    if parsed.scheme:
        return redact_log_text(safe_url_for_log(value))
    return redact_log_text(value)


def _status_value(status: TaskStatus | str) -> str:
    return status.value if isinstance(status, TaskStatus) else str(status)


def _task_view(index: int, task: CrawlTask) -> TaskView:
    status = _status_value(task.status)
    symbols = {
        TaskStatus.SUCCEEDED.value: "✓",
        TaskStatus.REVIEW_RECOMMENDED.value: "!",
        TaskStatus.FAILED.value: "×",
        TaskStatus.CANCELLED.value: "■",
        TaskStatus.VERIFICATION_REQUIRED.value: "!",
        TaskStatus.READY_TO_RESUME.value: "●",
    }
    actions = {
        TaskStatus.SUCCEEDED.value: "打开结果文件夹",
        TaskStatus.REVIEW_RECOMMENDED.value: "打开结果文件夹",
        TaskStatus.VERIFICATION_REQUIRED.value: "开始验证",
        TaskStatus.READY_TO_RESUME.value: "继续采集",
        TaskStatus.FAILED.value: "查看技术信息",
    }
    safe_url = safe_url_for_log(task.url)
    return TaskView(
        str(index),
        urlparse(safe_url).hostname or "未知站点",
        safe_url,
        symbols.get(status, "○"),
        STATUS_LABELS.get(status, status),
        task.record_count,
        task.output_path.name,
        actions.get(status, "等待"),
        redact_log_text(task.error),
    )


def _verification_view(item) -> VerificationView:
    reasons = {
        "challenge": "页面要求人工点击或确认",
        "login": "需要人工登录",
        "verification_required": "页面要求人工验证",
    }
    reason = getattr(item.reason, "value", item.reason)
    return VerificationView(
        item.run_id,
        item.task_id,
        item.hostname,
        item.detected_at,
        reasons.get(str(reason), "需要人工确认页面"),
        STATUS_LABELS.get(_status_value(item.status), _status_value(item.status)),
    )


def _report_view(record: ReportRecord) -> ReportView:
    return ReportView(
        record.report_id,
        str(record.path),
        record.created_at,
        record.submitted_at,
    )
