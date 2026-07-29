from __future__ import annotations

import importlib.metadata
import copy
import ctypes
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from ctypes import wintypes
from pathlib import Path
from typing import Callable
from uuid import uuid4

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from crawler.batch import (
    CrawlTask,
    format_exception_stack,
    prepare_tasks,
    rename_task_output,
    redact_log_text,
    run_tasks,
)
from crawler.app_paths import AppPaths
from crawler.faculty_crawler import FacultyCrawler
from crawler.local_translation_service import (
    LocalTranslationService,
    bundled_translation_service_path,
)
from crawler.diagnostics import (
    DiagnosticEvent,
    ReportRecord,
    build_problem_report,
    load_report_metadata,
    mark_report_submitted,
)
from crawler.models import TaskStatus
from crawler.retention import RetentionService, RunRecord
from crawler.session_store import SessionStore
from crawler.settings_store import SettingsStore
from crawler.translation_settings import TranslationSettings
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import (
    VerificationItem,
    VerificationQueue,
    VerificationService,
)
from ui.controller import AppController, AppViewState, RunView, SettingsView, STATUS_LABELS, TaskView
from ui.runs_page import RunsPage
from ui.sessions_page import SessionsPage
from ui.settings_page import SettingsPage
from ui.start_page import StartPage
from ui.tasks_page import TasksPage
from ui.theme import apply_theme
from ui.verification_page import VerificationPage


APP_VERSION = "desktop-batch-v1"
logger = logging.getLogger(__name__)
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_WAIT_TIMEOUT = 0x102


class DesktopWorkflowOwner:
    _NAME = "Local\\FacultyCrawlerDesktopWorkflowOwner"

    def __init__(self) -> None:
        self.acquired = False
        self._handle = None
        self._owner_thread_id = None
        if os.name != "nt":
            self.acquired = True
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
            ]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.CreateMutexW(None, False, self._NAME)
            if not handle:
                return
            result = kernel32.WaitForSingleObject(handle, 0)
            if result in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
                self._handle = handle
                self._kernel32 = kernel32
                self._owner_thread_id = threading.get_ident()
                self.acquired = True
            else:
                kernel32.CloseHandle(handle)
        except Exception:
            self.acquired = False
            self._handle = None

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        if self._owner_thread_id != threading.get_ident():
            return
        self._handle = None
        try:
            if self.acquired:
                self._kernel32.ReleaseMutex(handle)
        finally:
            self._kernel32.CloseHandle(handle)
            self.acquired = False


@dataclass(frozen=True)
class UiEvent:
    kind: str
    run_id: str = ""
    task_id: str = ""
    task_index: int = -1
    status: str = ""
    record_count: int = 0
    error: str = ""
    message: str = ""


@dataclass(frozen=True)
class VerificationDependencies:
    verification_queue: VerificationQueue | None
    verification_service: object | None
    task_store: TaskStore | None
    session_store: SessionStore | None


@dataclass(frozen=True)
class BatchVerificationContext:
    run_id: str
    task_ids: tuple[str, ...]
    verification_queue: object
    task_store: object
    session_store: object
    crawler_factory: Callable[[int], object] | None = None
    ui_indices: tuple[int, ...] | None = None
    resuming: bool = False


class LocalReportStore:
    def __init__(self, paths: AppPaths, task_store: TaskStore | None) -> None:
        self._paths = paths
        self._task_store = task_store

    def list_reports(self) -> list[ReportRecord]:
        reports: list[ReportRecord] = []
        for path in sorted(Path(self._paths.reports).glob("*.zip"), reverse=True):
            try:
                reports.append(load_report_metadata(path))
            except ValueError:
                logger.warning("Report metadata skipped: code=report_metadata_invalid")
        return reports

    def by_id(self, report_id: str) -> ReportRecord:
        for record in self.list_reports():
            if record.report_id == report_id:
                return record
        raise KeyError("report was not found")

    def generate(self, run_id: str) -> ReportRecord:
        events: list[DiagnosticEvent] = []
        if self._task_store is not None:
            run = self._task_store.load(run_id)
            for task in run.tasks:
                if task.status in {TaskStatus.FAILED, TaskStatus.REVIEW_RECOMMENDED}:
                    events.append(
                        DiagnosticEvent(
                            run_id,
                            task.task_id,
                            "collection",
                            task.status.value,
                            task.error or "需要检查此任务",
                            {},
                        )
                    )
        report_id = f"{run_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        path = Path(self._paths.reports) / f"{report_id}.zip"
        suffix = 2
        while path.exists():
            report_id = f"{run_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}"
            path = Path(self._paths.reports) / f"{report_id}.zip"
            suffix += 1
        build_problem_report(run_id, events, path)
        return load_report_metadata(path, expected_report_id=report_id)

    def mark_submitted(self, report_id: str) -> ReportRecord:
        return mark_report_submitted(self.by_id(report_id))


class SystemOpener:
    def reveal(self, path: Path) -> None:
        target = Path(path)
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            webbrowser.open(target.parent.as_uri())

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def open_file(self, path: Path) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(Path(path).as_uri())


def _discover_failed_run_records(
    task_store: TaskStore,
    paths: AppPaths,
) -> list[RunRecord]:
    terminal = {
        TaskStatus.SUCCEEDED,
        TaskStatus.REVIEW_RECOMMENDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
    records: list[RunRecord] = []
    for path in sorted(Path(paths.tasks).glob("*.json")):
        try:
            run = task_store.load(path.stem)
            statuses = {task.status for task in run.tasks}
            modified_at = datetime.fromtimestamp(
                path.stat().st_mtime,
                timezone.utc,
            )
        except (OSError, TypeError, ValueError):
            continue
        if (
            run.tasks
            and statuses.issubset(terminal)
            and TaskStatus.FAILED in statuses
        ):
            records.append(
                RunRecord(run.run_id, path, modified_at, TaskStatus.FAILED.value)
            )
    return records


def _purge_due_retention(
    retention_service,
    report_store,
    task_store: TaskStore | None,
    paths: AppPaths,
    verification_queue: VerificationQueue | None = None,
) -> list[Path]:
    reports = report_store.list_reports()
    runs = (
        _discover_failed_run_records(task_store, paths)
        if task_store is not None
        else []
    )
    before_remove = None
    if task_store is not None and verification_queue is not None:
        before_remove = lambda run: _remove_run_verification_items(
            run,
            task_store,
            verification_queue,
        )
    return retention_service.purge_due(
        reports,
        runs,
        before_remove_run=before_remove,
    )


def _remove_run_verification_items(
    run_record: RunRecord,
    task_store: TaskStore,
    verification_queue: VerificationQueue,
) -> None:
    stored_run = task_store.load(run_record.run_id)
    expected_path = Path(task_store.directory) / f"{stored_run.run_id}.json"
    statuses = {task.status for task in stored_run.tasks}
    terminal = {
        TaskStatus.SUCCEEDED,
        TaskStatus.REVIEW_RECOMMENDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
    current_mtime = datetime.fromtimestamp(
        expected_path.stat().st_mtime,
        timezone.utc,
    )
    if (
        run_record.path != expected_path
        or current_mtime != run_record.created_at
        or not stored_run.tasks
        or not statuses.issubset(terminal)
        or TaskStatus.FAILED not in statuses
    ):
        raise RuntimeError("retention run changed after discovery")
    verification_queue.remove_run(stored_run.run_id)


def _recover_desktop_tasks(
    task_store: TaskStore,
    verification_queue: VerificationQueue,
) -> tuple[list[CrawlTask], dict[tuple[str, str], CrawlTask]]:
    task_store.recover_interrupted()
    verification_queue.recover_interrupted_resumes()
    runs = task_store.list_runs()
    stored_tasks = {
        (run.run_id, task.task_id): task
        for run in runs
        for task in run.tasks
    }
    queue_items = verification_queue.items()
    queue_by_identity = {
        (item.run_id, item.task_id): item
        for item in queue_items
    }

    changed_runs: set[str] = set()
    for item in queue_items:
        identity = (item.run_id, item.task_id)
        stored = stored_tasks.get(identity)
        if stored is None:
            if item.status is not TaskStatus.FAILED:
                verification_queue.mark_failed(*identity)
                logger.error(
                    "Verification reconciliation failed: code=task_mapping_unavailable"
                )
            continue
        if stored.status in {
            TaskStatus.SUCCEEDED,
            TaskStatus.REVIEW_RECOMMENDED,
            TaskStatus.CANCELLED,
        }:
            try:
                verification_queue.remove_terminal(*identity)
            except Exception:
                logger.error(
                    "Verification reconciliation failed: code=queue_cleanup_unavailable"
                )
            continue
        if stored.status is TaskStatus.FAILED:
            if item.status is not TaskStatus.FAILED:
                try:
                    verification_queue.mark_failed(*identity)
                except Exception:
                    logger.error(
                        "Verification reconciliation failed: code=queue_transition_unavailable"
                    )
            continue
        if stored.status != item.status:
            stored.status = item.status
            changed_runs.add(item.run_id)

    for identity, stored in stored_tasks.items():
        if stored.status not in {
            TaskStatus.VERIFICATION_REQUIRED,
            TaskStatus.READY_TO_RESUME,
        }:
            continue
        if identity not in queue_by_identity:
            stored.status = TaskStatus.FAILED
            stored.error = "verification_state_unavailable"
            changed_runs.add(identity[0])
            logger.error(
                "Verification reconciliation failed: code=queue_item_unavailable"
            )

    for run in runs:
        if run.run_id in changed_runs:
            task_store.save(run)

    tasks: list[CrawlTask] = []
    identities: dict[tuple[str, str], CrawlTask] = {}
    completed = {
        TaskStatus.SUCCEEDED,
        TaskStatus.REVIEW_RECOMMENDED,
        TaskStatus.CANCELLED,
    }
    for run in runs:
        if run.tasks and all(task.status in completed for task in run.tasks):
            continue
        for stored in run.tasks:
            task = CrawlTask(
                stored.url,
                Path(stored.output_path),
                stored.status.value,
                stored.record_count,
                stored.error,
            )
            tasks.append(task)
            identities[(run.run_id, stored.task_id)] = task
    return tasks, identities


class QueueLogHandler(logging.Handler):
    def __init__(self, event_queue: queue.Queue[UiEvent]) -> None:
        super().__init__()
        self.event_queue = event_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.event_queue.put(UiEvent(kind="log", message=self.format(record)))
        except Exception:
            self.handleError(record)


class RedactingFormatter(logging.Formatter):
    def __init__(self, *args: object, output_dir: Path, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.output_dir = output_dir

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.msg = redact_log_text(record.getMessage(), self.output_dir)
        safe_record.args = ()
        safe_record.exc_info = None
        safe_record.exc_text = None
        return super().format(safe_record)


class BatchLogSession:
    def __init__(
        self,
        output_dir: Path,
        event_queue: queue.Queue[UiEvent],
        *,
        detailed: bool,
    ) -> None:
        self.output_dir = output_dir
        self.event_queue = event_queue
        self.detailed = detailed
        self.log_path = Path()
        self._managed_loggers = [logging.getLogger("crawler"), logging.getLogger("desktop_app")]
        self._logger_states: list[tuple[logging.Logger, int, bool]] = []
        self._file_handler: logging.FileHandler | None = None
        self._queue_handler: QueueLogHandler | None = None

    def start(self) -> None:
        log_dir = self.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = _next_log_path(log_dir)
        formatter = RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            output_dir=self.output_dir,
        )

        self._file_handler = logging.FileHandler(self.log_path, encoding="utf-8")
        self._file_handler.setLevel(logging.DEBUG)
        self._file_handler.setFormatter(formatter)
        self._queue_handler = QueueLogHandler(self.event_queue)
        self._queue_handler.setLevel(logging.DEBUG if self.detailed else logging.INFO)
        self._queue_handler.setFormatter(formatter)

        self._logger_states = []
        for managed_logger in self._managed_loggers:
            self._logger_states.append((managed_logger, managed_logger.level, managed_logger.propagate))
            managed_logger.setLevel(logging.DEBUG)
            managed_logger.propagate = False
            managed_logger.addHandler(self._file_handler)
            managed_logger.addHandler(self._queue_handler)
        self._log_environment()

    def set_detailed(self, detailed: bool) -> None:
        self.detailed = detailed
        if self._queue_handler is not None:
            self._queue_handler.setLevel(logging.DEBUG if detailed else logging.INFO)

    def close(self) -> None:
        for managed_logger, previous_level, previous_propagate in self._logger_states:
            for handler in (self._file_handler, self._queue_handler):
                if handler is not None:
                    managed_logger.removeHandler(handler)
            managed_logger.setLevel(previous_level)
            managed_logger.propagate = previous_propagate
        for handler in (self._file_handler, self._queue_handler):
            if handler is not None:
                handler.close()
        self._logger_states = []
        self._file_handler = None
        self._queue_handler = None

    def _log_environment(self) -> None:
        logger.info("Application version: %s", APP_VERSION)
        logger.info("Python: %s", sys.version.replace("\n", " "))
        logger.info("Operating system: %s", platform.platform())
        logger.info("Playwright: %s", _package_version("playwright"))
        logger.info("OpenPyXL: %s", _package_version("openpyxl"))


def run_batch_worker(
    tasks: list[CrawlTask],
    event_queue: queue.Queue[UiEvent],
    *,
    timeout: int,
    runner: Callable[..., None] = run_tasks,
    verification_context: BatchVerificationContext | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    def on_update(index: int, task: CrawlTask) -> None:
        ui_index = index
        if (
            verification_context is not None
            and verification_context.ui_indices is not None
        ):
            ui_index = verification_context.ui_indices[index]
        event_queue.put(
            UiEvent(
                kind="task",
                task_index=ui_index,
                status=task.status,
                record_count=task.record_count,
                error=task.error,
            )
        )

    def on_verification(item: VerificationItem) -> None:
        event_queue.put(
            UiEvent(
                kind="verification_required",
                run_id=item.run_id,
                task_id=item.task_id,
                status=TaskStatus.VERIFICATION_REQUIRED.value,
            )
        )

    try:
        stop_kwargs = (
            {"should_stop": stop_event.is_set}
            if stop_event is not None
            else {}
        )
        if verification_context is None:
            runner(tasks, timeout=timeout, on_update=on_update, **stop_kwargs)
        else:
            crawler_factory = verification_context.crawler_factory
            if crawler_factory is None:
                session_store = verification_context.session_store
                crawler_factory = lambda value: FacultyCrawler(
                    value,
                    session_store=session_store,
                )
            runner(
                tasks,
                timeout=timeout,
                on_update=on_update,
                verification_queue=verification_context.verification_queue,
                task_store=verification_context.task_store,
                run_id=verification_context.run_id,
                task_ids=verification_context.task_ids,
                on_verification=on_verification,
                crawler_factory=crawler_factory,
                **stop_kwargs,
            )
    except Exception as exc:
        safe_error = "batch_worker_failed"
        logger.error(
            "Batch worker stopped unexpectedly: exception_type=%s code=%s\n"
            "Traceback (most recent call last):\n%s",
            type(exc).__name__,
            safe_error,
            format_exception_stack(exc),
        )
        event_queue.put(UiEvent(kind="fatal", error=safe_error))
    finally:
        if verification_context is not None:
            if verification_context.resuming:
                for task_id, _task in zip(
                    verification_context.task_ids,
                    tasks,
                    strict=True,
                ):
                    try:
                        run = verification_context.task_store.load(
                            verification_context.run_id
                        )
                        stored = next(
                            task for task in run.tasks if task.task_id == task_id
                        )
                        if stored.status in {
                            TaskStatus.SUCCEEDED,
                            TaskStatus.REVIEW_RECOMMENDED,
                        }:
                            verification_context.verification_queue.complete_resume(
                                verification_context.run_id,
                                task_id,
                            )
                        elif stored.status is TaskStatus.FAILED:
                            verification_context.verification_queue.mark_failed(
                                verification_context.run_id,
                                task_id,
                            )
                    except Exception:
                        logger.error(
                            "Verification resume transition failed: "
                            "code=resume_transition_unavailable"
                        )
            purge = getattr(
                verification_context.session_store,
                "purge_expired",
                None,
            )
            if callable(purge):
                try:
                    purge()
                except Exception:
                    logger.warning(
                        "Session cleanup failed: code=session_purge_unavailable"
                    )
        event_queue.put(UiEvent(kind="finished"))


def run_verification_worker(
    item: VerificationItem,
    event_queue: queue.Queue[UiEvent],
    *,
    service,
    completion_event: threading.Event,
    cancel_event: threading.Event,
) -> None:
    reference = {
        "run_id": item.run_id,
        "task_id": item.task_id,
    }
    event_queue.put(UiEvent(kind="verification_started", **reference))
    try:
        result = service.verify(
            item,
            completion_event=completion_event,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.error("Verification worker failed: code=verification_failed")
        event_queue.put(
            UiEvent(
                kind="verification_failed",
                error="verification_failed",
                **reference,
            )
        )
        return

    if result.status is TaskStatus.READY_TO_RESUME:
        event_queue.put(
            UiEvent(
                kind="verification_ready",
                status=TaskStatus.READY_TO_RESUME.value,
                **reference,
            )
        )
    elif result.status is TaskStatus.FAILED:
        event_queue.put(
            UiEvent(
                kind="verification_failed",
                status=TaskStatus.FAILED.value,
                error="verification_failed",
                **reference,
            )
        )
    else:
        event_queue.put(
            UiEvent(
                kind="verification_deferred",
                status=TaskStatus.VERIFICATION_REQUIRED.value,
                **reference,
            )
        )


def _default_verification_dependencies():
    try:
        paths = AppPaths.for_user()
        verification_queue = VerificationQueue(
            paths.runs / "verification-queue.json"
        )
        task_store = TaskStore(paths.tasks)
        session_store = SessionStore(paths.sessions)
        try:
            session_store.purge_expired()
        except Exception:
            logger.warning("Session cleanup failed: code=session_purge_unavailable")
        service = VerificationService(
            task_store=task_store,
            queue=verification_queue,
            session_store=session_store,
        )
        return VerificationDependencies(
            verification_queue,
            service,
            task_store,
            session_store,
        )
    except Exception:
        logger.error(
            "Verification initialization failed: "
            "code=verification_dependencies_unavailable"
        )
        return VerificationDependencies(None, None, None, None)


class DesktopApp(tk.Tk):
    STATUS_LABELS = STATUS_LABELS

    def __init__(
        self,
        *,
        verification_queue: VerificationQueue | None = None,
        verification_service=None,
        task_store: TaskStore | None = None,
        session_store: SessionStore | None = None,
        workflow_owner: object | None = None,
        app_paths: AppPaths | None = None,
        settings_store=None,
        retention_service=None,
        report_store=None,
        opener=None,
        translation_service: LocalTranslationService | None = None,
    ) -> None:
        super().__init__()
        self.app_paths = app_paths or AppPaths.for_user()
        self.workflow_owner = (
            DesktopWorkflowOwner()
            if workflow_owner is None
            else workflow_owner
        )
        owns_workflow = bool(getattr(self.workflow_owner, "acquired", False))
        if (
            verification_queue is None
            and verification_service is None
            and task_store is None
            and session_store is None
            and owns_workflow
        ):
            dependencies = _default_verification_dependencies()
            verification_queue = dependencies.verification_queue
            verification_service = dependencies.verification_service
            task_store = dependencies.task_store
            session_store = dependencies.session_store
        self.title("高校教师信息批量采集")
        self.geometry("1100x760")
        self.minsize(900, 650)
        apply_theme(self)

        self.tasks: list[CrawlTask] = []
        self.events: queue.Queue[UiEvent] = queue.Queue()
        self.log_session: BatchLogSession | None = None
        self.worker: threading.Thread | None = None
        self.verification_queue = verification_queue
        self.verification_service = verification_service
        self.task_store = task_store
        self.session_store = session_store
        self.settings_store = settings_store or SettingsStore(
            Path(self.app_paths.settings) / "settings.json"
        )
        self.retention_service = retention_service or RetentionService(self.app_paths)
        self.report_store = report_store or LocalReportStore(self.app_paths, task_store)
        self.opener = opener or SystemOpener()
        if owns_workflow:
            try:
                _purge_due_retention(
                    self.retention_service,
                    self.report_store,
                    self.task_store,
                    self.app_paths,
                    self.verification_queue,
                )
            except Exception:
                logger.warning(
                    "Retention cleanup failed: code=retention_purge_unavailable"
                )
        self.verification_worker: threading.Thread | None = None
        self.verification_completion_event: threading.Event | None = None
        self.verification_cancel_event: threading.Event | None = None
        self.current_verification_item: VerificationItem | None = None
        self.verification_in_progress = False
        self.verification_tasks: dict[tuple[str, str], CrawlTask] = {}
        self.verification_startup_error = (
            "application_already_running" if not owns_workflow else ""
        )
        if (
            owns_workflow
            and self.task_store is not None
            and self.verification_queue is not None
        ):
            try:
                self.tasks, self.verification_tasks = _recover_desktop_tasks(
                    self.task_store,
                    self.verification_queue,
                )
            except Exception:
                self.verification_startup_error = (
                    "Saved verification data requires cleanup or an application upgrade."
                )
                logger.error(
                    "Verification recovery failed: code=stored_state_upgrade_required"
                )

        self.output_dir = tk.StringVar(value=str(Path.cwd() / "output"))
        self.rename_value = tk.StringVar()
        self.timeout_value = tk.StringVar(value="30000")
        self.detailed_logs = tk.BooleanVar(value=False)
        self.translation_settings = TranslationSettings()
        self.translation_service = translation_service or self._bundled_translation_service()
        self.status_text = tk.StringVar(value="请粘贴网址并生成任务。")
        self.controller = AppController(
            self.output_dir.get(),
            runner=self._start_prepared_batch,
            verification_queue=self.verification_queue,
            verification_starter=self._start_verification_identity,
            verification_defer=self._cancel_verification_identity,
            session_store=self.session_store,
            task_store=self.task_store,
            report_store=self.report_store,
            settings_store=self.settings_store,
            retention_service=self.retention_service,
            opener=self.opener,
        )
        self.controller.set_tasks(self.tasks)
        try:
            saved_settings = self.controller.load_settings()
            if saved_settings.feishu_folder_url:
                self.output_dir.set(saved_settings.output_dir)
                self.controller.set_output_dir(saved_settings.output_dir)
                self.detailed_logs.set(saved_settings.detailed_logs)
                self.translation_settings = saved_settings.translation
        except Exception:
            logger.warning("Settings load failed: code=settings_load_unavailable")
        self._start_local_translation_service()
        self.events = self.controller.events

        self._build_widgets()
        self._populate_task_rows()
        if self.verification_startup_error:
            messagebox.showerror("Verification", self.verification_startup_error)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)

    def _start_local_translation_service(self) -> None:
        service = self.translation_service
        if service is None:
            return
        try:
            endpoint = service.start()
            self.translation_settings = replace(
                self.translation_settings,
                endpoint=endpoint,
            )
        except Exception:
            logger.warning(
                "Local translation service unavailable: "
                "code=translation_service_start_unavailable"
            )

    @staticmethod
    def _bundled_translation_service() -> LocalTranslationService | None:
        executable = bundled_translation_service_path()
        if not executable.is_file():
            return None
        return LocalTranslationService(executable)

    def _build_widgets(self) -> None:
        shell = ttk.Frame(self, style="Shell.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        sidebar = ttk.Frame(shell, width=176, style="Shell.TFrame", padding=(16, 22))
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="教师信息采集", style="Shell.TLabel").pack(anchor=tk.W)
        self.nav_buttons: dict[str, ttk.Button] = {}
        nav_items = (
            ("start", "开始采集"),
            ("tasks", "当前任务"),
            ("verification", "人工验证"),
            ("sessions", "保存的会话"),
            ("runs", "运行记录"),
            ("settings", "设置"),
        )
        for index, (key, label) in enumerate(nav_items):
            button = ttk.Button(
                sidebar,
                text=label,
                command=lambda selected=key: self._show_page(selected),
                style="Nav.TButton",
            )
            button.pack(anchor=tk.W, fill=tk.X, pady=((28 if index == 0 else 2), 0))
            self.nav_buttons[key] = button
        ttk.Label(
            sidebar,
            text="按网址顺序采集\n需要验证时会暂停",
            style="Shell.TLabel",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, side=tk.BOTTOM)

        container = ttk.Frame(shell)
        container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.page_host = ttk.Frame(container)
        self.page_host.pack(fill=tk.BOTH, expand=True)
        self.start_page = StartPage(
            self.page_host,
            output_dir=self.output_dir,
            status_text=self.status_text,
            on_validate=self._validate_urls,
            on_change_output=self._browse_output,
            on_start=self._prepare_and_start,
        )
        self.tasks_page = TasksPage(
            self.page_host,
            on_action=self._task_next_action,
            on_open_result=self._open_task_result,
            on_stop=self._stop_after_current,
        )
        self.verification_page = VerificationPage(
            self.page_host,
            on_start=self._start_selected_verification,
            on_process_all=self._process_all_verifications,
            on_defer=self._defer_selected_verification,
            on_complete=self._complete_selected_verification,
        )
        self.sessions_page = SessionsPage(
            self.page_host,
            on_clear=self._clear_session,
            on_clear_all=self._clear_all_sessions,
        )
        self.runs_page = RunsPage(
            self.page_host,
            on_open_results=self._open_run_results,
            on_generate_report=self._generate_problem_report,
            on_handoff=self._open_report_handoff,
            on_mark_submitted=self._mark_report_submitted,
        )
        self.settings_page = SettingsPage(
            self.page_host,
            on_save=self._save_settings,
            on_change_output=self._browse_settings_output,
            on_clear_temporary=self._clear_temporary,
            on_clear_internal=self._clear_internal_data,
        )
        self.pages = {
            "start": self.start_page,
            "tasks": self.tasks_page,
            "verification": self.verification_page,
            "sessions": self.sessions_page,
            "runs": self.runs_page,
            "settings": self.settings_page,
        }
        self.url_text = self.start_page.url_text
        self.browse_button = self.start_page.change_output_button
        self.start_button = self.start_page.start_button
        self.prepare_button = self.start_button
        self.task_tree = self.tasks_page.tree
        self.task_tree.bind(
            "<<TreeviewSelect>>",
            self._load_selected_filename,
            add="+",
        )
        legacy_controls = ttk.Frame(container)
        self.timeout_entry = ttk.Entry(legacy_controls, textvariable=self.timeout_value)
        rename_frame = ttk.Frame(legacy_controls)
        self.rename_entry = ttk.Entry(rename_frame, textvariable=self.rename_value)
        self.rename_button = ttk.Button(rename_frame, text="应用名称", command=self._rename_selected)
        self.verification_cancel_button = self.verification_page.defer_button
        self.verification_complete_button = self.verification_page.complete_button
        self.process_verification_button = self.verification_page.process_all_button
        self.log_text = scrolledtext.ScrolledText(legacy_controls, height=9, state=tk.DISABLED, wrap=tk.WORD)
        self.start_page.set_state(self.controller.state)
        self._refresh_workflow_pages()
        self._show_page("start")

    def _show_page(self, name: str) -> None:
        page = self.pages[name]
        for key, button in self.nav_buttons.items():
            button.configure(
                style="ActiveNav.TButton" if key == name else "Nav.TButton"
            )
        for candidate in self.pages.values():
            candidate.pack_forget()
        if name != "start":
            self._refresh_workflow_pages()
        page.pack(fill=tk.BOTH, expand=True)
        focus_primary = getattr(page, "focus_primary", None)
        if callable(focus_primary):
            self.after_idle(focus_primary)

    def _refresh_workflow_pages(self) -> None:
        self.tasks_page.set_records(self.controller.task_views())
        try:
            self.verification_page.set_records(
                self.controller.verification_views(),
                self.controller.verification_badge_count(),
            )
        except Exception:
            logger.warning("Verification view unavailable: code=verification_view_unavailable")
        try:
            self.sessions_page.set_records(self.controller.session_views())
        except Exception:
            logger.warning("Session view unavailable: code=session_view_unavailable")
        try:
            self.runs_page.set_records(
                self.controller.run_views(),
                self.controller.report_views(),
            )
        except Exception:
            logger.warning("Run view unavailable: code=run_view_unavailable")
        try:
            self.settings_page.set_state(
                self.controller.load_settings(),
                self.controller.storage_usage(),
            )
        except Exception:
            logger.warning("Settings view unavailable: code=settings_view_unavailable")

    def _task_next_action(self, record: TaskView) -> None:
        if record.next_action == "打开结果文件夹":
            self._open_task_result(record)
        elif record.next_action == "开始验证":
            self._show_page("verification")
        elif record.next_action == "继续采集":
            self.task_tree.selection_set(record.key)
            self._start()
        elif record.next_action == "查看技术信息":
            self.tasks_page.toggle_details()

    def _open_task_result(self, record: TaskView) -> None:
        task = self.tasks[int(record.key)]
        try:
            self.opener.reveal(task.output_path)
        except Exception:
            messagebox.showerror("打开结果文件夹", "无法打开结果位置，请在设置中检查保存位置。")

    def _stop_after_current(self) -> None:
        state = self.controller.stop_after_current()
        self.start_page.set_state(state)

    def _process_all_verifications(self) -> None:
        try:
            if not self.controller.process_all_verifications():
                messagebox.showinfo("人工验证", "没有等待处理的验证任务。")
        except Exception:
            logger.error("Verification start failed: code=verification_start_unavailable")
            messagebox.showerror("人工验证", "暂时无法开始验证，请稍后重试。")

    def _start_selected_verification(self, run_id: str, task_id: str) -> None:
        try:
            if not self.controller.start_verification(run_id, task_id):
                messagebox.showinfo("人工验证", "已有验证窗口正在处理，请先完成或暂不处理。")
        except (KeyError, RuntimeError):
            messagebox.showerror("人工验证", "此任务已不在待验证队列中，请刷新后重试。")

    def _defer_selected_verification(self, run_id: str, task_id: str) -> None:
        if self.controller.active_verification == (run_id, task_id):
            self.controller.defer_verification(run_id, task_id)
        self.status_text.set("已暂不处理此任务；其余任务仍保留在队列中。")

    def _complete_selected_verification(self, run_id: str, task_id: str) -> None:
        if self.controller.active_verification != (run_id, task_id):
            messagebox.showinfo("人工验证", "请先开始此任务的验证。")
            return
        self._complete_verification()

    def _clear_session(self, hostname: str) -> None:
        confirmed = messagebox.askyesno(
            "清除此站点会话",
            f"清除 {hostname} 保存的登录和验证状态？\n不会删除 Excel 或问题报告。",
        )
        if self.controller.clear_session(hostname, confirmed=confirmed):
            self._refresh_workflow_pages()

    def _clear_all_sessions(self) -> None:
        confirmed = messagebox.askyesno(
            "清除全部会话",
            "清除所有站点保存的登录和验证状态？\n不会删除 Excel 或问题报告。",
        )
        if self.controller.clear_all_sessions(confirmed=confirmed):
            self._refresh_workflow_pages()

    def _open_run_results(self, record: RunView) -> None:
        if record.result_folder == "多个保存位置":
            messagebox.showinfo("打开结果文件夹", "此批次使用了多个保存位置，请从当前任务中打开结果。")
            return
        self.opener.reveal(Path(record.result_folder))

    def _generate_problem_report(self, record: RunView) -> None:
        try:
            report = self.controller.generate_problem_report(record.run_id)
            self._refresh_workflow_pages()
            messagebox.showinfo("问题报告", f"已生成：{Path(report.path).name}")
        except Exception:
            logger.error("Report generation failed: code=report_generation_unavailable")
            messagebox.showerror("问题报告", "未能生成问题报告，请稍后重试。")

    def _open_report_handoff(self, report_id: str) -> None:
        try:
            self.controller.open_report_handoff(report_id)
        except ValueError as exc:
            messagebox.showerror("报告交接", str(exc))
        except Exception:
            logger.error("Report handoff failed: code=report_handoff_unavailable")
            messagebox.showerror("报告交接", "无法打开本地报告或飞书文件夹。")

    def _mark_report_submitted(self, report_id: str) -> None:
        if not messagebox.askyesno("标记为已提交", "确认已将此报告交给负责人？"):
            return
        self.controller.mark_report_submitted(report_id)
        self._refresh_workflow_pages()

    def _save_settings(
        self,
        output_dir: str,
        feishu_url: str,
        detailed: bool,
        timeout: int,
        *,
        translation_endpoint: str,
        translation_cache_path: str,
        translation_connect_timeout: float,
        translation_response_timeout: float,
        translation_retries: int,
    ):
        try:
            translation = TranslationSettings(
                endpoint=translation_endpoint,
                cache_path=translation_cache_path,
                connect_timeout=translation_connect_timeout,
                response_timeout=translation_response_timeout,
                retries=translation_retries,
            )
        except (TypeError, ValueError):
            return SettingsView(
                output_dir,
                feishu_url,
                detailed,
                timeout,
                "翻译设置必须为有效本机地址、非空缓存路径、正超时和非负重试次数",
            )
        state = self.controller.save_settings(
            output_dir,
            feishu_url,
            detailed,
            timeout_ms=timeout,
            translation=translation,
        )
        if not state.error:
            self.output_dir.set(state.output_dir)
            self.timeout_value.set(str(state.timeout_ms))
            self.detailed_logs.set(state.detailed_logs)
            self.translation_settings = state.translation
        return state

    def _browse_settings_output(self) -> None:
        selected = filedialog.askdirectory(
            initialdir=self.settings_page.output_dir.get()
        )
        if selected:
            state = self.controller.change_settings_output_dir(selected)
            self.settings_page.set_output_dir(state.output_dir)

    def _clear_temporary(self) -> None:
        confirmed = messagebox.askyesno(
            "清理临时文件",
            "清理未完成写入和临时截图？\n不会删除 Excel 或问题报告 ZIP。",
        )
        summary = self.controller.clear_temporary(confirmed=confirmed)
        if summary.confirmed:
            messagebox.showinfo("清理临时文件", summary.message)
            self._refresh_workflow_pages()

    def _clear_internal_data(self) -> None:
        confirmed = messagebox.askyesno(
            "清除内部数据",
            "清除任务状态、保存的会话和内部日志？\nExcel 与问题报告 ZIP 会保留。",
        )
        summary = self.controller.clear_internal_data(confirmed=confirmed)
        if summary.confirmed:
            messagebox.showinfo("清除内部数据", summary.message)
            self._refresh_workflow_pages()

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir.get())
        if selected:
            self.output_dir.set(selected)
            self.controller.set_output_dir(selected)
            self._prepare()

    def _validate_urls(self, raw_urls: str) -> AppViewState:
        self.controller.set_output_dir(self.output_dir.get())
        state = self.controller.prepare(raw_urls)
        self.tasks = list(self.controller.tasks)
        return state

    def _prepare_and_start(self) -> None:
        self._prepare()
        if self.tasks:
            self._start()

    def _prepare(self) -> None:
        if self.verification_in_progress:
            return
        controller = self.__dict__.get("controller")
        if controller is not None:
            state = self._validate_urls(self.url_text.get("1.0", "end-1c"))
            self.start_page.set_state(state)
            invalid_lines = state.invalid_lines
            self._populate_task_rows()
            if invalid_lines:
                details = "\n".join(
                    f"第 {number} 行：{value}" for number, value in invalid_lines
                )
                messagebox.showwarning("网址检查结果", f"请检查以下网址：\n{details}")
            self.status_text.set(f"已识别 {state.valid_count} 个网址。")
            return

        output_dir = Path(self.output_dir.get())
        result = prepare_tasks(self.url_text.get("1.0", tk.END), output_dir)
        self.tasks = result.tasks
        self._populate_task_rows()

        notices: list[str] = []
        if result.invalid_urls:
            notices.append("无效网址：\n" + "\n".join(result.invalid_urls))
        if result.duplicate_urls:
            notices.append("已忽略重复网址：\n" + "\n".join(result.duplicate_urls))
        if notices:
            messagebox.showwarning("网址检查结果", "\n\n".join(notices))
        self.status_text.set(f"已生成 {len(self.tasks)} 个任务。")

    def _populate_task_rows(self) -> None:
        controller = self.__dict__.get("controller")
        tasks_page = self.__dict__.get("tasks_page")
        if controller is not None and tasks_page is not None:
            controller.set_tasks(self.tasks)
            tasks_page.set_records(controller.task_views())
            return
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for index, task in enumerate(self.tasks):
            self.task_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    task.url,
                    task.output_path.name,
                    self.STATUS_LABELS.get(task.status, task.status),
                    task.record_count or "",
                    task.error,
                ),
            )

    def _load_selected_filename(self, _event: object | None = None) -> None:
        selected = self.task_tree.selection()
        if selected:
            self.rename_value.set(self.tasks[int(selected[0])].output_path.name)

    def _rename_selected(self) -> None:
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showinfo("修改文件名", "请先选择一个任务。")
            return
        index = int(selected[0])
        filename = rename_task_output(self.tasks, index, self.rename_value.get())
        self.rename_value.set(filename)
        task = self.tasks[index]
        self.task_tree.item(
            str(index),
            values=(task.url, filename, self.STATUS_LABELS[task.status], task.record_count or "", task.error),
        )

    def _start(self) -> None:
        controller = self.__dict__.get("controller")
        if controller is not None:
            if not self._owns_persistent_workflow():
                messagebox.showinfo("Verification", "application_already_running")
                return
            if self.verification_in_progress:
                return
            try:
                state = controller.start_batch()
            except ValueError:
                messagebox.showinfo("开始采集", "请先粘贴有效网址。")
                return
            except Exception:
                logger.error("Batch startup failed: code=worker_start_unavailable")
                messagebox.showerror("开始采集", "未能开始采集，请重试。")
                state = controller.state
            self.start_page.set_state(state)
            return

        if not self._owns_persistent_workflow():
            messagebox.showinfo("Verification", "application_already_running")
            return
        if self.verification_in_progress:
            return
        if not self.tasks:
            messagebox.showinfo("开始采集", "请先粘贴网址并生成任务。")
            return
        try:
            timeout = int(self.timeout_value.get())
            if timeout <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("超时设置", "超时必须是大于 0 的整数毫秒数。")
            return

        self._start_prepared_batch(self.tasks, timeout=timeout)

    def _start_prepared_batch(
        self,
        prepared_tasks: list[CrawlTask],
        *,
        timeout: int,
    ) -> bool:
        if not self._owns_persistent_workflow():
            messagebox.showinfo("Verification", "application_already_running")
            return False
        if self.verification_in_progress:
            return False

        self.tasks = prepared_tasks
        batch_tasks = self.tasks
        ui_indices = tuple(range(len(self.tasks)))
        verification_context = None
        if (
            self.verification_queue is not None
            and self.task_store is not None
            and self.session_store is not None
        ):
            session_store = self.session_store
            current_identities = {
                identity: task
                for identity, task in self.verification_tasks.items()
                if any(current is task for current in self.tasks)
            }
            if current_identities:
                tree = self.__dict__.get("task_tree")
                selected = tree.selection() if tree is not None else ()
                if not selected:
                    messagebox.showinfo(
                        "Verification",
                        "Select one saved task to resume or retry.",
                    )
                    return False
                selected_index = int(selected[0])
                selected_task = self.tasks[selected_index]
                identity = next(
                    (
                        identity
                        for identity, task in current_identities.items()
                        if task is selected_task
                    ),
                    None,
                )
                if identity is None:
                    return False
                run_id, task_id = identity
                if selected_task.status == TaskStatus.FAILED.value:
                    try:
                        self.verification_queue.retry_failed(run_id, task_id)
                        self.task_store.update_task(
                            run_id,
                            task_id,
                            TaskStatus.VERIFICATION_REQUIRED,
                        )
                    except Exception:
                        logger.error(
                            "Verification retry failed: code=retry_transition_unavailable"
                        )
                        return False
                    selected_task.status = TaskStatus.VERIFICATION_REQUIRED.value
                    self._populate_task_rows()
                    return False
                if selected_task.status not in {
                    TaskStatus.READY_TO_RESUME.value,
                    TaskStatus.PENDING.value,
                }:
                    messagebox.showinfo(
                        "Verification",
                        "The selected task is not ready to resume.",
                    )
                    return False
                resuming = selected_task.status == TaskStatus.READY_TO_RESUME.value
                if resuming:
                    try:
                        self.verification_queue.begin_resume(run_id, task_id)
                    except Exception:
                        logger.error(
                            "Verification resume failed: code=resume_claim_unavailable"
                        )
                        return False
                batch_tasks = [selected_task]
                ui_indices = (selected_index,)
                task_ids = (task_id,)
            else:
                resuming = False
                run_id = f"run-{uuid4().hex}"
                task_ids = tuple(f"task-{uuid4().hex}" for _ in batch_tasks)
                stored_run = StoredRun(
                    run_id,
                    [
                        StoredTask(
                            task_id,
                            task.url,
                            str(task.output_path),
                            TaskStatus(task.status),
                            task.record_count,
                            task.error,
                        )
                        for task_id, task in zip(task_ids, batch_tasks, strict=True)
                    ],
                )
                try:
                    self.task_store.save(stored_run)
                except Exception:
                    logger.error(
                        "Batch persistence failed: code=task_store_unavailable"
                    )
                    messagebox.showerror(
                        "Verification",
                        "Persistent task storage is unavailable.",
                    )
                    return False
                self.verification_tasks.update(
                    {
                        (run_id, task_id): task
                        for task_id, task in zip(task_ids, batch_tasks, strict=True)
                    }
                )
            def create_crawler(value: int) -> FacultyCrawler:
                kwargs = {"session_store": session_store}
                translation_settings = self.__dict__.get("translation_settings")
                if isinstance(translation_settings, TranslationSettings):
                    kwargs["translation_settings"] = translation_settings
                return FacultyCrawler(value, **kwargs)

            verification_context = BatchVerificationContext(
                run_id,
                task_ids,
                self.verification_queue,
                self.task_store,
                session_store,
                create_crawler,
                ui_indices,
                resuming,
            )

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log_session = BatchLogSession(
            Path(self.output_dir.get()),
            self.events,
            detailed=self.detailed_logs.get(),
        )
        self.log_session.start()
        logger.info("Batch prepared: task_count=%s timeout_ms=%s", len(batch_tasks), timeout)
        controller = self.__dict__.get("controller")
        if controller is not None:
            started = controller.launch_worker(
                "batch",
                target=run_batch_worker,
                args=(batch_tasks, self.events),
                kwargs={
                    "timeout": timeout,
                    "verification_context": verification_context,
                },
                use_stop_event=True,
                name="faculty-batch-worker",
            )
            self.worker = controller.worker("batch")
        else:
            self.worker = threading.Thread(
                target=run_batch_worker,
                args=(batch_tasks, self.events),
                kwargs={
                    "timeout": timeout,
                    "verification_context": verification_context,
                },
                daemon=True,
                name="faculty-batch-worker",
            )
            self.worker.start()
            started = True
        if not started:
            self.log_session.close()
            self.log_session = None
            return False
        self._set_running_controls(True)
        self.status_text.set("● 正在顺序采集，请勿关闭窗口。")
        return True

    def _process_verification_queue(self) -> None:
        if not self._owns_persistent_workflow():
            messagebox.showinfo("Verification", "application_already_running")
            return
        if self.verification_worker is not None and self.verification_worker.is_alive():
            return
        if self.verification_queue is None or self.verification_service is None:
            messagebox.showinfo("Verification", "Verification service is unavailable.")
            return
        try:
            pending = self.verification_queue.pending()
        except Exception:
            logger.error("Verification queue failed: code=verification_queue_unavailable")
            messagebox.showerror("Verification", "Verification queue is unavailable.")
            return
        if not pending:
            messagebox.showinfo("Verification", "No verification tasks are pending.")
            return
        self._launch_verification_item(pending[0])

    def _start_verification_identity(self, run_id: str, task_id: str) -> bool:
        if self.verification_queue is None:
            return False
        try:
            item = next(
                item
                for item in self.verification_queue.pending()
                if (item.run_id, item.task_id) == (run_id, task_id)
            )
        except (StopIteration, OSError, ValueError):
            return False
        return self._launch_verification_item(item)

    def _launch_verification_item(self, item: VerificationItem) -> bool:
        if not self._owns_persistent_workflow():
            messagebox.showinfo("Verification", "application_already_running")
            return False
        if self.verification_worker is not None and self.verification_worker.is_alive():
            return False
        if self.verification_service is None:
            return False
        completion_event = threading.Event()
        cancel_event = threading.Event()
        self.current_verification_item = item
        self.verification_completion_event = completion_event
        self.verification_cancel_event = cancel_event
        self.verification_in_progress = True
        self._set_verification_controls(True)
        controller = self.__dict__.get("controller")
        if controller is not None:
            started = controller.launch_worker(
                "verification",
                target=run_verification_worker,
                args=(item, self.events),
                kwargs={
                    "service": self.verification_service,
                    "completion_event": completion_event,
                    "cancel_event": cancel_event,
                },
                name="faculty-verification-worker",
            )
            self.verification_worker = controller.worker("verification")
            if not started:
                self.current_verification_item = None
                self.verification_completion_event = None
                self.verification_cancel_event = None
                self.verification_in_progress = False
                self._set_verification_controls(False)
                return False
        else:
            self.verification_worker = threading.Thread(
                target=run_verification_worker,
                args=(item, self.events),
                kwargs={
                    "service": self.verification_service,
                    "completion_event": completion_event,
                    "cancel_event": cancel_event,
                },
                daemon=True,
                name="faculty-verification-worker",
            )
            self.verification_worker.start()
        return True

    def _cancel_verification_identity(self, run_id: str, task_id: str) -> None:
        current = self.current_verification_item
        if current is not None and (current.run_id, current.task_id) == (run_id, task_id):
            self._cancel_verification()

    def _complete_verification(self) -> None:
        if (
            self.verification_worker is not None
            and self.verification_worker.is_alive()
            and self.verification_completion_event is not None
        ):
            self.verification_completion_event.set()

    def _cancel_verification(self) -> None:
        if self.verification_cancel_event is not None:
            self.verification_cancel_event.set()

    def _verification_task_index(self, run_id: str, task_id: str) -> int:
        mapped_task = self.verification_tasks.get((run_id, task_id))
        for index, task in enumerate(self.tasks):
            if task is mapped_task:
                return index
        return -1

    def _drain_events(self) -> None:
        controller = self.__dict__.get("controller")
        if controller is not None:
            controller.drain_events(
                {
                    "log": lambda event: self._append_log(event.message),
                    "task": self._update_task_row,
                    "fatal": lambda event: messagebox.showerror(
                        "批量任务异常", event.error
                    ),
                    "finished": lambda _event: self._finish_batch(),
                    "verification_required": self._handle_batch_verification_event,
                    "verification_started": self._handle_verification_event,
                    "verification_ready": self._handle_verification_event,
                    "verification_deferred": self._handle_verification_event,
                    "verification_failed": self._handle_verification_event,
                }
            )
            self.after(100, self._drain_events)
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "log":
                self._append_log(event.message)
            elif event.kind == "task":
                self._update_task_row(event)
            elif event.kind == "fatal":
                messagebox.showerror("批量任务异常", event.error)
            elif event.kind == "finished":
                self._finish_batch()
            elif event.kind == "verification_required":
                self._handle_batch_verification_event(event)
            elif event.kind in {
                "verification_started",
                "verification_ready",
                "verification_deferred",
                "verification_failed",
            }:
                self._handle_verification_event(event)
        self.after(100, self._drain_events)

    def _handle_verification_event(self, event: UiEvent) -> None:
        if event.kind == "verification_started":
            self.status_text.set("Verification browser is open.")
            return

        task_index = self._verification_task_index(event.run_id, event.task_id)
        if 0 <= task_index < len(self.tasks):
            task = self.tasks[task_index]
            if event.kind == "verification_ready":
                task.status = TaskStatus.READY_TO_RESUME.value
                task.error = ""
            elif event.kind == "verification_deferred":
                task.status = TaskStatus.VERIFICATION_REQUIRED.value
                task.error = ""
            else:
                task.status = TaskStatus.FAILED.value
                task.error = "verification_failed"
            self._update_task_row(
                UiEvent(
                    kind="task",
                    task_index=task_index,
                    status=task.status,
                    record_count=task.record_count,
                    error=task.error,
                )
            )

        status_messages = {
            "verification_ready": "Verification complete; ready to resume.",
            "verification_deferred": "Verification deferred.",
            "verification_failed": "Verification failed.",
        }
        self.status_text.set(status_messages[event.kind])
        self.verification_in_progress = False
        self.verification_worker = None
        controller = self.__dict__.get("controller")
        role_busy = bool(
            controller is not None and controller.verification_worker_alive
        )
        self._set_verification_controls(False, role_busy=role_busy)
        if (
            controller is not None
            and controller.active_verification == (event.run_id, event.task_id)
        ):
            try:
                controller.verification_finished(
                    event.run_id,
                    event.task_id,
                    event.status or (
                        TaskStatus.READY_TO_RESUME.value
                        if event.kind == "verification_ready"
                        else TaskStatus.VERIFICATION_REQUIRED.value
                    ),
                )
            except Exception:
                logger.error(
                    "Verification sequence failed: code=verification_sequence_unavailable"
                )
        if (
            controller is not None
            and (
                controller.verification_worker_alive
                or controller.verification_sequence_pending
            )
        ):
            self.after(25, self._continue_verification_sequence)
        if self.__dict__.get("tasks_page") is not None:
            self._refresh_workflow_pages()

    def _continue_verification_sequence(self) -> None:
        controller = self.__dict__.get("controller")
        if controller is None:
            return
        if controller.verification_worker_alive:
            self.after(25, self._continue_verification_sequence)
            return
        if not controller.verification_sequence_pending:
            self._set_verification_controls(False)
            return
        controller.continue_verification_sequence()
        if controller.verification_sequence_pending:
            self.after(25, self._continue_verification_sequence)

    def _handle_batch_verification_event(self, event: UiEvent) -> None:
        task_index = self._verification_task_index(event.run_id, event.task_id)
        if task_index < 0:
            return
        task = self.tasks[task_index]
        task.status = TaskStatus.VERIFICATION_REQUIRED.value
        self._update_task_row(
            UiEvent(
                kind="task",
                task_index=task_index,
                status=task.status,
                record_count=task.record_count,
                error=task.error,
            )
        )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _update_task_row(self, event: UiEvent) -> None:
        task = self.tasks[event.task_index]
        controller = self.__dict__.get("controller")
        tasks_page = self.__dict__.get("tasks_page")
        if controller is not None and tasks_page is not None:
            controller.set_tasks(self.tasks)
            tasks_page.set_records(controller.task_views())
            return
        values = (
            task.url,
            task.output_path.name,
            self.STATUS_LABELS.get(event.status, event.status),
            event.record_count or "",
            event.error,
        )
        self.task_tree.item(str(event.task_index), values=values)

    def _finish_batch(self) -> None:
        if self.log_session is not None:
            log_path = self.log_session.log_path
            logger.info("Batch finished. Log file: %s", log_path.name)
            self.log_session.close()
        else:
            log_path = Path(self.output_dir.get()) / "logs"
        self.log_session = None
        self._set_running_controls(False)
        succeeded = sum(task.status == "succeeded" for task in self.tasks)
        review_recommended = sum(
            task.status == "review_recommended" for task in self.tasks
        )
        failed = sum(task.status == "failed" for task in self.tasks)
        cancelled = sum(task.status == "cancelled" for task in self.tasks)
        summary = (
            f"批量任务结束：成功 {succeeded}，建议检查 {review_recommended}，"
            f"失败 {failed}，已停止 {cancelled}。日志：{log_path}"
        )
        self.status_text.set(summary)
        controller = self.__dict__.get("controller")
        start_page = self.__dict__.get("start_page")
        if controller is not None and start_page is not None:
            start_page.set_state(
                controller.finish_batch(summary, stopped=cancelled > 0)
            )

    def _set_running_controls(self, running: bool) -> None:
        state = (
            tk.DISABLED
            if running or self.verification_in_progress
            else tk.NORMAL
        )
        for widget in (
            self.browse_button,
            self.timeout_entry,
            self.prepare_button,
            self.rename_entry,
            self.rename_button,
            self.start_button,
            self.url_text,
        ):
            widget.configure(state=state)
        verification_state = (
            tk.DISABLED
            if running
            or self.verification_in_progress
            or not self._owns_persistent_workflow()
            or self.verification_queue is None
            or self.verification_service is None
            else tk.NORMAL
        )
        self.process_verification_button.configure(state=verification_state)

    def _set_verification_controls(
        self,
        active: bool,
        *,
        role_busy: bool = False,
    ) -> None:
        batch_active = self.worker is not None and self.worker.is_alive()
        input_state = tk.DISABLED if active or batch_active else tk.NORMAL
        for name in (
            "browse_button",
            "timeout_entry",
            "prepare_button",
            "rename_entry",
            "rename_button",
            "start_button",
            "url_text",
        ):
            widget = self.__dict__.get(name)
            if widget is not None:
                widget.configure(state=input_state)
        process_state = (
            tk.NORMAL
            if not active
            and not role_busy
            and not batch_active
            and self._owns_persistent_workflow()
            and self.verification_queue is not None
            and self.verification_service is not None
            else tk.DISABLED
        )
        self.process_verification_button.configure(state=process_state)
        self.verification_complete_button.configure(
            state=tk.NORMAL if active and not role_busy else tk.DISABLED
        )
        self.verification_cancel_button.configure(
            state=tk.DISABLED if role_busy else (tk.NORMAL if active else tk.DISABLED)
        )
        verification_page = self.__dict__.get("verification_page")
        if verification_page is not None:
            verification_page.set_active(active, role_busy=role_busy)

    def _update_log_detail(self) -> None:
        if self.log_session is not None:
            self.log_session.set_detailed(self.detailed_logs.get())

    def _owns_persistent_workflow(self) -> bool:
        owner = self.__dict__.get("workflow_owner")
        return owner is None or bool(getattr(owner, "acquired", False))

    def _open_log_dir(self) -> None:
        log_dir = Path(self.output_dir.get()) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(log_dir)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("打开日志目录", str(exc))

    def _on_close(self) -> None:
        batch_active = self.worker is not None and self.worker.is_alive()
        verification_active = (
            self.verification_worker is not None
            and self.verification_worker.is_alive()
        )
        if batch_active or verification_active:
            if not messagebox.askyesno("任务运行中", "关闭窗口会中止当前任务，确定关闭吗？"):
                return
        if verification_active and self.verification_cancel_event is not None:
            self.verification_cancel_event.set()
            try:
                self.verification_worker.join(timeout=1.0)
            except Exception:
                logger.warning(
                    "Verification cleanup failed: code=worker_join_unavailable"
                )
        if batch_active:
            try:
                self.worker.join(timeout=1.0)
            except Exception:
                logger.warning("Batch cleanup failed: code=worker_join_unavailable")
        if self.log_session is not None:
            self.log_session.close()
        translation_service = self.__dict__.get("translation_service")
        stop_translation_service = getattr(translation_service, "stop", None)
        if callable(stop_translation_service):
            try:
                stop_translation_service()
            except Exception:
                logger.warning(
                    "Local translation service cleanup failed: "
                    "code=translation_service_stop_unavailable"
                )
        owner = self.__dict__.get("workflow_owner")
        close_owner = getattr(owner, "close", None)
        persistent_worker_alive = (
            self.worker is not None and self.worker.is_alive()
        ) or (
            self.verification_worker is not None
            and self.verification_worker.is_alive()
        )
        if persistent_worker_alive:
            logger.warning(
                "Desktop shutdown deferred owner release: "
                "code=shutdown_waiting_for_process_exit"
            )
        elif callable(close_owner):
            try:
                close_owner()
            except Exception:
                logger.warning("Owner cleanup failed: code=owner_release_unavailable")
        self.destroy()


def _next_log_path(log_dir: Path) -> Path:
    stem = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    path = log_dir / f"{stem}.log"
    suffix = 2
    while path.exists():
        path = log_dir / f"{stem}_{suffix}.log"
        suffix += 1
    return path


def _package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def main() -> None:
    app = DesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()
