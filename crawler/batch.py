from __future__ import annotations

import logging
import re
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import unquote, urlparse
from uuid import uuid4

from crawler.diagnostics import DiagnosticEvent, _safe_event, _safe_text
from crawler.faculty_crawler import FacultyCrawler, export_to_excel
from crawler.models import CrawlOutcome, TaskStatus
from crawler.parsers import FacultyRecord
from crawler.privacy import redact_log_text, safe_exception_message, safe_url_for_log
from crawler.task_store import TaskStore
from crawler.verification import VerificationItem, VerificationQueue


logger = logging.getLogger(__name__)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EmptyCrawlResultError(RuntimeError):
    pass


@dataclass
class CrawlTask:
    url: str
    output_path: Path
    status: str = "pending"
    record_count: int = 0
    error: str = ""


@dataclass
class PreparationResult:
    tasks: list[CrawlTask] = field(default_factory=list)
    invalid_urls: list[str] = field(default_factory=list)
    duplicate_urls: list[str] = field(default_factory=list)


def prepare_tasks(raw_urls: str, output_dir: Path) -> PreparationResult:
    result = PreparationResult()
    seen_urls: set[str] = set()
    used_names = (
        {path.name.casefold() for path in output_dir.glob("*.xlsx")}
        if output_dir.is_dir()
        else set()
    )

    for line in raw_urls.splitlines():
        url = line.strip()
        if not url:
            continue

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            result.invalid_urls.append(url)
            continue

        duplicate_key = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            fragment="",
        ).geturl()
        if duplicate_key in seen_urls:
            result.duplicate_urls.append(url)
            continue
        seen_urls.add(duplicate_key)

        filename = make_output_filename(url, used_names)
        result.tasks.append(CrawlTask(url=url, output_path=output_dir / filename))

    return result


def make_output_filename(url: str, used_names: set[str] | None = None) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "faculty").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    path_parts = [part for part in unquote(parsed.path).split("/") if part]
    path_label = path_parts[-1] if path_parts else "faculty"
    base = sanitize_filename(f"{hostname}_{path_label}", default="faculty")
    used = used_names if used_names is not None else set()

    candidate = f"{base}.xlsx"
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{base}_{suffix}.xlsx"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def sanitize_filename(value: str, default: str = "faculty") -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", value).strip().rstrip(". ")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = default
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def rename_task_output(tasks: list[CrawlTask], index: int, requested_name: str) -> str:
    value = requested_name.strip()
    if value.lower().endswith(".xlsx"):
        value = value[:-5]
    base = sanitize_filename(value, default="faculty")
    used_names = {
        task.output_path.name.casefold()
        for task_index, task in enumerate(tasks)
        if task_index != index
    }
    output_dir = tasks[index].output_path.parent
    if output_dir.is_dir():
        used_names.update(path.name.casefold() for path in output_dir.glob("*.xlsx"))
    candidate = f"{base}.xlsx"
    suffix = 2
    while candidate.casefold() in used_names:
        candidate = f"{base}_{suffix}.xlsx"
        suffix += 1
    tasks[index].output_path = tasks[index].output_path.with_name(candidate)
    return candidate


def run_tasks(
    tasks: list[CrawlTask],
    *,
    timeout: int = 30000,
    crawler_factory: Callable[[int], FacultyCrawler] = FacultyCrawler,
    exporter: Callable[[list[FacultyRecord], str | Path], None] = export_to_excel,
    on_update: Callable[[int, CrawlTask], None] | None = None,
    on_diagnostic: Callable[[DiagnosticEvent], None] | None = None,
    run_id: str | None = None,
    task_ids: Sequence[str] | None = None,
    verification_queue: VerificationQueue | None = None,
    on_verification: Callable[[VerificationItem], None] | None = None,
    task_store: TaskStore | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    actual_run_id = run_id if run_id is not None else f"run-{uuid4().hex}"
    actual_task_ids = (
        tuple(task_ids)
        if task_ids is not None
        else tuple(f"task-{uuid4().hex}" for _ in tasks)
    )
    if len(actual_task_ids) != len(tasks):
        raise ValueError("task_ids must contain one ID for each task")
    if len(set(actual_task_ids)) != len(actual_task_ids):
        raise ValueError("task_ids must be unique")
    if task_store is not None:
        if run_id is None or task_ids is None or task_store is None:
            raise ValueError(
                "persistent tasks require run_id and task_ids"
            )
        _validate_task_store_mapping(task_store, run_id, actual_task_ids, tasks)
    if verification_queue is not None and task_store is None:
        raise ValueError("persistent verification requires task_store")

    for index, task in enumerate(tasks):
        task_id = actual_task_ids[index]
        if should_stop is not None and should_stop():
            task.status = TaskStatus.CANCELLED.value
            task.record_count = 0
            task.error = ""
            _persist_task(
                task_store,
                actual_run_id,
                task_id,
                task,
                TaskStatus.CANCELLED,
            )
            _notify(on_update, index, task)
            continue
        task.status = "running"
        task.record_count = 0
        task.error = ""
        _persist_task(
            task_store,
            actual_run_id,
            task_id,
            task,
            TaskStatus.FETCHING,
        )
        _notify(on_update, index, task)
        safe_url = safe_url_for_log(task.url)
        logger.info(
            "Task started: url=%s output=%s timeout_ms=%s",
            safe_url,
            task.output_path.name,
            timeout,
        )

        stage = "crawl"
        try:
            crawler = crawler_factory(timeout)
            outcome_method = getattr(type(crawler), "crawl_outcome", None)
            if callable(outcome_method):
                outcome = outcome_method(crawler, task.url)
            else:
                records = crawler.crawl(task.url)
                diagnostics = getattr(crawler, "last_diagnostics", {})
                if not isinstance(diagnostics, dict):
                    diagnostics = {}
                outcome = CrawlOutcome(
                    TaskStatus.SUCCEEDED if records else TaskStatus.FAILED,
                    tuple(records),
                    diagnostics=dict(diagnostics),
                )
            records = list(outcome.records)
            if outcome.status == TaskStatus.VERIFICATION_REQUIRED:
                diagnostics = outcome.diagnostics
                stage = str(diagnostics.get("Failure stage") or "verification")
                reason = str(
                    diagnostics.get("Failure reason")
                    or "Human verification required"
                )
                try:
                    item = VerificationItem(
                        actual_run_id,
                        task_id,
                        task.url,
                        urlparse(task.url).hostname or "",
                        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                        reason,
                    )
                    if verification_queue is not None:
                        if task_store is None or (
                            task_store.resolve_original_url(
                                actual_run_id, task_id
                            )
                            != task.url
                        ):
                            raise ValueError
                        item = verification_queue.enqueue(item)
                except Exception:
                    task.status = TaskStatus.FAILED.value
                    task.error = "verification_queue_unavailable"
                    task.record_count = len(records)
                    _persist_task(
                        task_store,
                        actual_run_id,
                        task_id,
                        task,
                        TaskStatus.FAILED,
                    )
                    logger.error("Verification queue unavailable")
                    event = _safe_event(
                        DiagnosticEvent(
                            actual_run_id,
                            task_id,
                            "verification_queue",
                            task.status,
                            task.error,
                            {"url": safe_url},
                        )
                    )
                    _invoke_verification_callback(
                        "diagnostic", on_diagnostic, event
                    )
                    _invoke_verification_callback(
                        "update", on_update, index, task
                    )
                    continue

                task.status = outcome.status.value
                task.record_count = len(records)
                _persist_task(
                    task_store,
                    actual_run_id,
                    task_id,
                    task,
                    TaskStatus.VERIFICATION_REQUIRED,
                )
                logger.info(
                    "Task requires verification: url=%s records=%s",
                    safe_url,
                    len(records),
                )
                event = _safe_event(
                    DiagnosticEvent(
                        actual_run_id,
                        task_id,
                        stage,
                        task.status,
                        "Human verification required",
                        {"url": safe_url, "record_count": len(records)},
                    )
                )
                _invoke_verification_callback(
                    "diagnostic", on_diagnostic, event
                )
                _invoke_verification_callback(
                    "verification", on_verification, item
                )
                _invoke_verification_callback(
                    "update", on_update, index, task
                )
                continue
            if outcome.status not in {
                TaskStatus.SUCCEEDED,
                TaskStatus.REVIEW_RECOMMENDED,
            }:
                diagnostics = outcome.diagnostics
                stage = str(diagnostics.get("Failure stage") or "parse")
                reason = str(diagnostics.get("Failure reason") or "No faculty records were parsed")
                raise EmptyCrawlResultError(reason)
            stage = "export"
            exporter(records, task.output_path)
        except Exception as exc:
            task.status = "failed"
            task.error = safe_exception_message(exc)
            _persist_task(
                task_store,
                actual_run_id,
                task_id,
                task,
                TaskStatus.FAILED,
            )
            safe_stage = _safe_text(stage)
            stack = format_exception_stack(exc)
            logger.error(
                "Task failed: url=%s stage=%s exception_type=%s error=%s\n"
                "Traceback (most recent call last):\n%s",
                safe_url,
                safe_stage,
                type(exc).__name__,
                task.error,
                stack,
            )
            _emit_diagnostic(
                on_diagnostic,
                DiagnosticEvent(
                    actual_run_id,
                    task_id,
                    safe_stage,
                    task.status,
                    task.error,
                    {
                        "url": safe_url,
                        "exception_type": type(exc).__name__,
                    },
                ),
            )
            _notify(on_update, index, task)
            continue

        task.status = outcome.status.value
        task.record_count = len(records)
        _persist_task(
            task_store,
            actual_run_id,
            task_id,
            task,
            outcome.status,
        )
        if outcome.status == TaskStatus.SUCCEEDED:
            logger.info(
                "Task succeeded: url=%s records=%s output=%s",
                safe_url,
                len(records),
                task.output_path.name,
            )
            message = "Task succeeded"
        else:
            logger.info(
                "Task completed: url=%s status=%s records=%s output=%s",
                safe_url,
                task.status,
                len(records),
                task.output_path.name,
            )
            message = "Review recommended"
        _emit_diagnostic(
            on_diagnostic,
            DiagnosticEvent(
                actual_run_id,
                task_id,
                stage,
                task.status,
                message,
                {"url": safe_url, "record_count": len(records)},
            ),
        )
        _notify(on_update, index, task)


def format_exception_stack(exc: Exception) -> str:
    lines: list[str] = []
    for frame in traceback.extract_tb(exc.__traceback__):
        frame_path = Path(frame.filename)
        try:
            display_path = frame_path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            display_path = frame_path.name
        lines.append(f'  File "{display_path}", line {frame.lineno}, in {frame.name}\n')
    return "".join(lines)


def _notify(
    on_update: Callable[[int, CrawlTask], None] | None,
    index: int,
    task: CrawlTask,
) -> None:
    if on_update is None:
        return
    try:
        on_update(index, task)
    except Exception:
        logger.error("Verification callback failed: callback=update")


def _persist_task(
    task_store: TaskStore | None,
    run_id: str,
    task_id: str,
    task: CrawlTask,
    status: TaskStatus,
) -> None:
    if task_store is None:
        return
    try:
        task_store.update_task(
            run_id,
            task_id,
            status,
            output_path=str(task.output_path),
            record_count=task.record_count,
            error=task.error,
        )
    except KeyError:
        raise ValueError("persistent task mapping is invalid") from None


def _emit_diagnostic(
    callback: Callable[[DiagnosticEvent], None] | None,
    event: DiagnosticEvent,
) -> None:
    if callback is not None:
        callback(_safe_event(event))


def _validate_task_store_mapping(
    task_store: TaskStore,
    run_id: str,
    task_ids: Sequence[str],
    tasks: Sequence[CrawlTask],
) -> None:
    try:
        for task_id, task in zip(task_ids, tasks, strict=True):
            if task_store.resolve_original_url(run_id, task_id) != task.url:
                raise ValueError
    except Exception:
        raise ValueError("verification task repository mapping is invalid") from None


def _invoke_verification_callback(
    name: str,
    callback: Callable[..., None] | None,
    *args: object,
) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:
        logger.error("Verification callback failed: callback=%s", name)
