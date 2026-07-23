from __future__ import annotations

import ctypes
import hashlib
import inspect
import ipaddress
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import idna

from crawler.models import PageAssessment, PageKind, RecommendedAction, TaskStatus
from crawler.page_state import classify_page


_SCHEMA_VERSION = 2
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_QUEUE_STATUSES = {
    TaskStatus.VERIFICATION_REQUIRED,
    TaskStatus.READY_TO_RESUME,
    TaskStatus.FETCHING,
    TaskStatus.FAILED,
}
MAX_VERIFICATION_ATTEMPTS = 3
_ITEM_FIELDS = {
    "run_id",
    "task_id",
    "url",
    "hostname",
    "detected_at",
    "reason",
    "attempts",
    "status",
}
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_INFINITE = 0xFFFFFFFF
_DIRECTORY_SELECTOR = (
    "main [itemtype*='Person'] a[href], main a[href*='/people/'], "
    "main a[href*='/profile/'], main a[href*='/profiles/']"
)
logger = logging.getLogger(__name__)


class VerificationReason(StrEnum):
    CHALLENGE = "challenge"
    LOGIN = "login"
    VERIFICATION_REQUIRED = "verification_required"


@dataclass(frozen=True)
class VerificationResult:
    status: TaskStatus
    storage_state: bytes | None = field(repr=False)
    assessment: PageAssessment


class VerificationService:
    def __init__(
        self,
        *,
        task_store=None,
        url_resolver: Callable[[str, str], str] | None = None,
        queue=None,
        session_store=None,
        browser_runner: Callable[..., object] | None = None,
        playwright_factory: Callable[[], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[threading.Event, float], bool] | None = None,
        poll_interval: float = 0.25,
        max_duration: float = 600.0,
    ) -> None:
        if url_resolver is None and task_store is not None:
            url_resolver = task_store.resolve_original_url
        if url_resolver is None:
            raise TypeError("task_store or url_resolver is required")
        if poll_interval <= 0 or max_duration <= 0:
            raise ValueError("verification timing must be positive")
        self._resolve_url = url_resolver
        self._task_store = task_store
        self._queue = queue
        self._session_store = session_store
        self._browser_runner = browser_runner
        self._playwright_factory = playwright_factory
        self._clock = clock
        self._wait = wait or (lambda event, seconds: event.wait(seconds))
        self._poll_interval = poll_interval
        self._max_duration = max_duration

    def verify(
        self,
        item: VerificationItem,
        *,
        completion_event: threading.Event,
        cancel_event: threading.Event,
    ) -> VerificationResult:
        pending = _pending_assessment()
        if cancel_event.is_set():
            logger.info("Verification deferred: code=cancelled")
            return self._defer(item, pending)
        try:
            original_url = self.resolve_original_url(item)
            hostname, is_ipv6 = _canonical_url_hostname(original_url)
        except Exception:
            logger.error("Verification failed: code=authoritative_url_unavailable")
            return self._defer(item, pending)

        initial_state: dict[str, object] | None = None
        if self._session_store is not None and not is_ipv6:
            try:
                saved = self._session_store.load(hostname)
            except Exception:
                logger.warning("Verification session unavailable: code=session_load_unavailable")
            else:
                if saved is not None:
                    try:
                        initial_state = scope_storage_state(saved, hostname)
                    except (TypeError, ValueError):
                        try:
                            self._session_store.clear_site(hostname)
                        except Exception:
                            logger.warning(
                                "Verification session cleanup unavailable: "
                                "code=session_cleanup_unavailable"
                            )
                        logger.warning(
                            "Verification session invalid: code=session_state_invalid"
                        )

        try:
            raw_result = self._invoke_runner(
                original_url,
                completion_event,
                cancel_event,
                initial_state,
            )
            completed, storage_state, assessment = _coerce_runner_result(raw_result)
        except Exception:
            logger.error("Verification failed: code=browser_runner_failed")
            return self._defer(item, pending)

        if cancel_event.is_set() or not completed or storage_state is None:
            logger.info("Verification deferred: code=not_completed")
            return self._defer(item, assessment)
        if assessment.kind is not PageKind.DIRECTORY:
            logger.info("Verification deferred: code=directory_not_confirmed")
            return self._defer(item, assessment)

        if is_ipv6 and self._queue is not None:
            logger.info("Verification deferred: code=ipv6_session_unsupported")
            return self._defer(item, assessment)

        try:
            scoped_state = scope_storage_state(storage_state, hostname)
            scoped_bytes = encode_storage_state(scoped_state)
            if is_ipv6:
                logger.info("Verification session skipped: code=ipv6_session_handoff")
            elif self._session_store is not None:
                self._session_store.save(hostname, scoped_bytes)
            elif self._queue is not None:
                logger.error("Verification failed: code=session_store_required")
                return self._defer(item, assessment)
            if self._queue is not None:
                self._update_task_status(item, TaskStatus.READY_TO_RESUME)
                try:
                    self._queue.mark_ready(item.run_id, item.task_id)
                except Exception:
                    self._update_task_status(
                        item,
                        TaskStatus.VERIFICATION_REQUIRED,
                    )
                    raise
        except Exception:
            logger.error("Verification failed: code=session_commit_failed")
            return self._defer(item, assessment)

        logger.info("Verification completed: code=ready_to_resume")
        return VerificationResult(TaskStatus.READY_TO_RESUME, scoped_bytes, assessment)

    def _defer(
        self,
        item: VerificationItem,
        assessment: PageAssessment,
    ) -> VerificationResult:
        status = TaskStatus.VERIFICATION_REQUIRED
        if self._queue is not None:
            try:
                status = self._queue.defer(item.run_id, item.task_id).status
                self._update_task_status(item, status)
            except Exception:
                logger.error("Verification failed: code=queue_transition_failed")
        return VerificationResult(status, None, assessment)

    def _update_task_status(
        self,
        item: VerificationItem,
        status: TaskStatus,
    ) -> None:
        if self._task_store is not None:
            self._task_store.update_task(item.run_id, item.task_id, status)

    def resolve_original_url(self, item: VerificationItem) -> str:
        if not isinstance(item, VerificationItem):
            raise TypeError("item must be a VerificationItem")
        return self._resolve_url(item.run_id, item.task_id)

    def _invoke_runner(
        self,
        url: str,
        completion_event: threading.Event,
        cancel_event: threading.Event,
        storage_state: dict[str, object] | None,
    ) -> object:
        if self._browser_runner is None:
            return self._run_visible_browser(
                url,
                completion_event,
                cancel_event,
                storage_state,
            )
        parameters = inspect.signature(self._browser_runner).parameters.values()
        accepts_four = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in parameters
        ) or len(tuple(parameters)) >= 4
        if accepts_four:
            return self._browser_runner(
                url,
                completion_event,
                cancel_event,
                storage_state,
            )
        return self._browser_runner(url, completion_event, cancel_event)

    def _run_visible_browser(
        self,
        url: str,
        completion_event: threading.Event,
        cancel_event: threading.Event,
        storage_state: dict[str, object] | None,
    ) -> tuple[bool, bytes | None, PageAssessment]:
        if self._playwright_factory is None:
            from playwright.sync_api import sync_playwright

            factory = sync_playwright
        else:
            factory = self._playwright_factory

        assessment = _pending_assessment()
        with factory() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = None
            try:
                options = {"storage_state": storage_state} if storage_state else {}
                context = browser.new_context(**options)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                started = self._clock()
                while self._clock() - started < self._max_duration:
                    if cancel_event.is_set() or page.is_closed():
                        return False, None, assessment
                    title = page.title()
                    visible_text = page.locator("body").evaluate(
                        _VISIBLE_NON_FORM_TEXT_SCRIPT
                    )
                    candidate_count = page.locator(_DIRECTORY_SELECTOR).count()
                    strong_assessment = classify_page(
                        url=page.url,
                        status=None,
                        title=title,
                        text=visible_text,
                        html_length=max(100, len(visible_text)),
                        candidate_count=0,
                    )
                    if strong_assessment.action is RecommendedAction.QUEUE_VERIFICATION:
                        assessment = strong_assessment
                        if completion_event.is_set():
                            return False, None, assessment
                    else:
                        assessment = classify_page(
                            url=page.url,
                            status=None,
                            title=title,
                            text=visible_text,
                            html_length=max(100, len(visible_text)),
                            candidate_count=candidate_count,
                        )
                        if assessment.kind is PageKind.DIRECTORY:
                            encoded = json.dumps(
                                context.storage_state(),
                                ensure_ascii=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                            return True, encoded, assessment
                    if completion_event.is_set():
                        return False, None, assessment
                    self._wait(cancel_event, self._poll_interval)
                return False, None, assessment
            finally:
                _close_browser_resources(context, browser)


_VISIBLE_NON_FORM_TEXT_SCRIPT = """
element => {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const parts = [];
  while (walker.nextNode()) {
    const parent = walker.currentNode.parentElement;
    if (!parent || parent.closest('form')) continue;
    const style = getComputedStyle(parent);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const value = walker.currentNode.nodeValue.trim();
    if (value) parts.push(value);
  }
  return parts.join(' ');
}
"""


def parse_storage_state(value: bytes) -> dict[str, object]:
    if not isinstance(value, bytes):
        raise TypeError("storage state must be bytes")
    try:
        payload = json.loads(
            value.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("storage state is invalid") from exc
    _validate_storage_payload(payload)
    return payload


def _validate_storage_payload(payload: object) -> None:
    if (
        not isinstance(payload, dict)
        or set(payload) - {"cookies", "origins"}
        or not isinstance(payload.get("cookies"), list)
        or ("origins" in payload and not isinstance(payload["origins"], list))
    ):
        raise ValueError("storage state is invalid")
    for cookie in payload["cookies"]:
        if not _valid_storage_cookie(cookie):
            raise ValueError("storage state is invalid")
    for origin in payload.get("origins", []):
        if not _valid_storage_origin(origin):
            raise ValueError("storage state is invalid")


def scope_storage_state(
    value: bytes | dict[str, object],
    hostname: str,
) -> dict[str, object]:
    payload = parse_storage_state(value) if isinstance(value, bytes) else value
    _validate_storage_payload(payload)
    canonical_hostname, _ = _canonical_hostname(hostname)
    cookies = [
        cookie
        for cookie in payload["cookies"]
        if _cookie_matches_hostname(cookie, canonical_hostname)
    ]
    origins = [
        origin
        for origin in payload.get("origins", [])
        if _origin_matches_hostname(origin, canonical_hostname)
    ]
    return {"cookies": cookies, "origins": origins}


def encode_storage_state(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _cookie_matches_hostname(value: object, hostname: str) -> bool:
    if not _valid_storage_cookie(value):
        raise ValueError("storage state is invalid")
    domain = value["domain"]
    if domain.startswith("."):
        return False
    try:
        canonical, _ = _canonical_hostname(domain)
    except (TypeError, ValueError, idna.IDNAError):
        return False
    if canonical != hostname:
        return False
    partition_key = value.get("partitionKey")
    return partition_key is None or _site_matches_hostname(
        partition_key,
        hostname,
    )


def _origin_matches_hostname(value: object, hostname: str) -> bool:
    if not _valid_storage_origin(value):
        raise ValueError("storage state is invalid")
    try:
        parsed = urlparse(value["origin"])
        canonical, _ = _canonical_hostname(parsed.hostname or "")
        parsed.port
    except (TypeError, ValueError, idna.IDNAError):
        return False
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and canonical == hostname
    )


def _site_matches_hostname(value: object, hostname: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        canonical, _ = _canonical_hostname(parsed.hostname or "")
        parsed.port
    except (TypeError, ValueError, idna.IDNAError):
        return False
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and canonical == hostname
    )


def _reject_json_constant(_value: str):
    raise ValueError("storage state is invalid")


def _close_browser_resources(context, browser) -> None:
    failed = False
    if context is not None:
        try:
            context.close()
        except Exception:
            failed = True
            logger.error("Verification cleanup failed: code=context_close_failed")
    try:
        browser.close()
    except Exception:
        failed = True
        logger.error("Verification cleanup failed: code=browser_close_failed")
    if failed:
        raise RuntimeError("verification_cleanup_failed") from None


def _valid_storage_cookie(value: object) -> bool:
    required = {"name", "value", "domain", "path"}
    optional = {"expires", "httpOnly", "secure", "sameSite", "partitionKey"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - required - optional
        or any(not isinstance(value[key], str) for key in required)
    ):
        return False
    if "expires" in value and (
        isinstance(value["expires"], bool)
        or not isinstance(value["expires"], (int, float))
        or not math.isfinite(value["expires"])
    ):
        return False
    if any(
        key in value and type(value[key]) is not bool
        for key in ("httpOnly", "secure")
    ):
        return False
    if "sameSite" in value and value["sameSite"] not in {"Strict", "Lax", "None"}:
        return False
    return "partitionKey" not in value or isinstance(value["partitionKey"], str)


def _valid_storage_origin(value: object) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"origin", "localStorage"}
        or not isinstance(value["origin"], str)
        or not isinstance(value["localStorage"], list)
    ):
        return False
    return all(
        isinstance(entry, dict)
        and set(entry) == {"name", "value"}
        and isinstance(entry["name"], str)
        and isinstance(entry["value"], str)
        for entry in value["localStorage"]
    )


def _coerce_runner_result(
    value: object,
) -> tuple[bool, bytes | None, PageAssessment]:
    if not isinstance(value, tuple) or len(value) not in {2, 3}:
        raise TypeError("browser runner returned an invalid result")
    completed, storage_state = value[:2]
    if type(completed) is not bool:
        raise TypeError("browser runner returned an invalid result")
    if storage_state is not None and not isinstance(storage_state, bytes):
        raise TypeError("browser runner returned an invalid result")
    assessment = value[2] if len(value) == 3 else (
        PageAssessment(PageKind.DIRECTORY, RecommendedAction.PARSE)
        if completed and storage_state is not None
        else _pending_assessment()
    )
    if not isinstance(assessment, PageAssessment):
        raise TypeError("browser runner returned an invalid result")
    return completed, storage_state, assessment


def _pending_assessment() -> PageAssessment:
    return PageAssessment(
        PageKind.HUMAN_VERIFICATION,
        RecommendedAction.QUEUE_VERIFICATION,
    )


def _canonical_url_hostname(url: str) -> tuple[str, bool]:
    try:
        parsed = urlparse(url)
        hostname, is_ipv6 = _canonical_hostname(parsed.hostname or "")
        parsed.port
    except (TypeError, ValueError, idna.IDNAError) as exc:
        raise ValueError("url must be a valid HTTP URL") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("url must be a valid HTTP URL")
    return hostname, is_ipv6


@dataclass(frozen=True)
class VerificationItem:
    run_id: str
    task_id: str
    url: str
    hostname: str
    detected_at: str
    reason: VerificationReason
    attempts: int = 0
    status: TaskStatus = TaskStatus.VERIFICATION_REQUIRED

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id must be a safe identifier")
        if not isinstance(self.task_id, str) or not _TASK_ID.fullmatch(self.task_id):
            raise ValueError("task_id must be a safe identifier")
        if not isinstance(self.url, str):
            raise TypeError("url must be a string")

        display_url, url_hostname = _display_origin(self.url)

        if not isinstance(self.hostname, str):
            raise TypeError("hostname must be a string")
        safe_hostname = _normalize_hostname(self.hostname)
        if safe_hostname != url_hostname:
            raise ValueError("hostname must match the URL")

        if not isinstance(self.detected_at, str):
            raise TypeError("detected_at must be a string")
        try:
            detected_at = datetime.fromisoformat(self.detected_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("detected_at must be an ISO-8601 timestamp") from exc
        if detected_at.tzinfo is None:
            raise ValueError("detected_at must include a timezone")

        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        safe_reason = _reason_code(self.reason)
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise TypeError("attempts must be an integer")
        if self.attempts < 0:
            raise ValueError("attempts must not be negative")
        try:
            status = TaskStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("status is not valid for a verification item") from exc
        if status not in _QUEUE_STATUSES:
            raise ValueError("status is not valid for a verification item")

        object.__setattr__(self, "url", display_url)
        object.__setattr__(self, "hostname", safe_hostname)
        object.__setattr__(self, "reason", safe_reason)
        object.__setattr__(self, "status", status)


class VerificationQueue:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_digest = hashlib.sha256(
            str(self.path).casefold().encode("utf-8")
        ).hexdigest()
        lock_name = f"Local\\FacultyCrawlerVerificationQueue-{lock_digest}"
        self._cross_process_lock = lambda: _windows_named_mutex(lock_name)
        with _LOCKS_LOCK:
            self._lock = _LOCKS.setdefault(self.path, threading.Lock())

    def enqueue(self, item: VerificationItem) -> VerificationItem:
        if not isinstance(item, VerificationItem):
            raise TypeError("item must be a VerificationItem")
        safe_item = VerificationItem(**asdict(item))
        if (
            safe_item.status != TaskStatus.VERIFICATION_REQUIRED
            or safe_item.attempts != 0
        ):
            raise ValueError("enqueue requires a new verification item")
        with self._locked():
            items = self._read_unlocked()
            for index, existing in enumerate(items):
                if (existing.run_id, existing.task_id) == (
                    safe_item.run_id,
                    safe_item.task_id,
                ):
                    if existing.status not in {
                        TaskStatus.VERIFICATION_REQUIRED,
                        TaskStatus.FETCHING,
                    }:
                        raise ValueError("terminal verification item cannot be re-enqueued")
                    safe_item = replace(
                        safe_item,
                        attempts=existing.attempts,
                    )
                    items[index] = safe_item
                    break
            else:
                items.append(safe_item)
            self._write_unlocked(items)
        return safe_item

    def pending(self, run_id: str | None = None) -> list[VerificationItem]:
        if run_id is not None and (
            not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id)
        ):
            raise ValueError("run_id must be a safe identifier")
        with self._locked():
            return [
                item
                for item in self._read_unlocked()
                if item.status == TaskStatus.VERIFICATION_REQUIRED
                and (run_id is None or item.run_id == run_id)
            ]

    def items(self) -> list[VerificationItem]:
        with self._locked():
            return self._read_unlocked()

    def mark_ready(self, run_id: str, task_id: str) -> VerificationItem:
        return self._transition(
            run_id,
            task_id,
            TaskStatus.READY_TO_RESUME,
            expected={TaskStatus.VERIFICATION_REQUIRED},
        )

    def defer(self, run_id: str, task_id: str) -> VerificationItem:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a safe identifier")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id must be a safe identifier")
        with self._locked():
            items = self._read_unlocked()
            for index, item in enumerate(items):
                if (item.run_id, item.task_id) != (run_id, task_id):
                    continue
                if item.status != TaskStatus.VERIFICATION_REQUIRED:
                    raise ValueError("task is not awaiting verification")
                attempts = item.attempts + 1
                updated = replace(
                    item,
                    status=(
                        TaskStatus.FAILED
                        if attempts >= MAX_VERIFICATION_ATTEMPTS
                        else TaskStatus.VERIFICATION_REQUIRED
                    ),
                    attempts=attempts,
                )
                items[index] = updated
                self._write_unlocked(items)
                return updated
        raise KeyError("verification task was not found")

    def mark_failed(self, run_id: str, task_id: str) -> VerificationItem:
        return self._transition(
            run_id,
            task_id,
            TaskStatus.FAILED,
            expected={
                TaskStatus.VERIFICATION_REQUIRED,
                TaskStatus.READY_TO_RESUME,
                TaskStatus.FETCHING,
            },
        )

    def begin_resume(self, run_id: str, task_id: str) -> VerificationItem:
        return self._transition(
            run_id,
            task_id,
            TaskStatus.FETCHING,
            expected={TaskStatus.READY_TO_RESUME},
        )

    def retry_failed(self, run_id: str, task_id: str) -> VerificationItem:
        return self._transition(
            run_id,
            task_id,
            TaskStatus.VERIFICATION_REQUIRED,
            expected={TaskStatus.FAILED},
            reset_attempts=True,
        )

    def complete_resume(self, run_id: str, task_id: str) -> None:
        with self._locked():
            items = self._read_unlocked()
            for index, item in enumerate(items):
                if (item.run_id, item.task_id) != (run_id, task_id):
                    continue
                if item.status != TaskStatus.FETCHING:
                    raise ValueError("task is not being resumed")
                del items[index]
                self._write_unlocked(items)
                return
        raise KeyError("verification task was not found")

    def remove_terminal(self, run_id: str, task_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a safe identifier")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id must be a safe identifier")
        with self._locked():
            items = self._read_unlocked()
            for index, item in enumerate(items):
                if (item.run_id, item.task_id) == (run_id, task_id):
                    del items[index]
                    self._write_unlocked(items)
                    return
        raise KeyError("verification task was not found")

    def remove_run(self, run_id: str) -> int:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a safe identifier")
        with self._locked():
            items = self._read_unlocked()
            retained = [item for item in items if item.run_id != run_id]
            removed = len(items) - len(retained)
            if removed:
                self._write_unlocked(retained)
            return removed

    def recover_interrupted_resumes(self) -> list[VerificationItem]:
        recovered: list[VerificationItem] = []
        with self._locked():
            items = self._read_unlocked()
            for index, item in enumerate(items):
                if item.status == TaskStatus.FETCHING:
                    item = replace(item, status=TaskStatus.READY_TO_RESUME)
                    items[index] = item
                    recovered.append(item)
            if recovered:
                self._write_unlocked(items)
        return recovered

    def _transition(
        self,
        run_id: str,
        task_id: str,
        status: TaskStatus,
        *,
        reset_attempts: bool = False,
        expected: set[TaskStatus],
    ) -> VerificationItem:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a safe identifier")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id must be a safe identifier")
        with self._locked():
            items = self._read_unlocked()
            for index, item in enumerate(items):
                if (item.run_id, item.task_id) != (run_id, task_id):
                    continue
                if item.status not in expected:
                    raise ValueError("task is not awaiting verification")
                updated = replace(
                    item,
                    status=status,
                    attempts=(
                        0
                        if reset_attempts
                        else item.attempts
                    ),
                )
                items[index] = updated
                self._write_unlocked(items)
                return updated
        raise KeyError("verification task was not found")

    def _read_unlocked(self) -> list[VerificationItem]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "items",
            }:
                raise ValueError("verification queue has an invalid schema")
            if (
                type(payload["schema_version"]) is not int
                or payload["schema_version"] != _SCHEMA_VERSION
            ):
                raise ValueError(
                    "unsupported verification queue schema; clear queue manually"
                )
            raw_items = payload["items"]
            if not isinstance(raw_items, list):
                raise ValueError("verification queue items must be a list")

            items: list[VerificationItem] = []
            identities: set[tuple[str, str]] = set()
            for raw_item in raw_items:
                if not isinstance(raw_item, dict) or set(raw_item) != _ITEM_FIELDS:
                    raise ValueError("verification queue item has an invalid schema")
                if raw_item["reason"] not in {
                    reason.value for reason in VerificationReason
                }:
                    raise ValueError("verification queue item has an invalid reason")
                item = VerificationItem(**raw_item)
                if (
                    raw_item["url"] != item.url
                    or raw_item["hostname"] != item.hostname
                    or raw_item["reason"] != item.reason.value
                    or raw_item["status"] != item.status.value
                ):
                    raise ValueError("verification queue item is not canonical")
                identity = (item.run_id, item.task_id)
                if identity in identities:
                    raise ValueError("verification queue contains duplicate identities")
                identities.add(identity)
                items.append(item)
            return items
        except (json.JSONDecodeError, UnicodeError, TypeError, KeyError) as exc:
            raise ValueError("verification queue is corrupt") from exc

    def _write_unlocked(self, items: list[VerificationItem]) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "items": [
                {**asdict(item), "status": item.status.value} for item in items
            ],
        }
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    @contextmanager
    def _locked(self):
        with self._lock:
            with self._cross_process_lock():
                yield


def _display_origin(value: str) -> tuple[str, str]:
    try:
        parsed = urlparse(value)
        hostname, is_ipv6 = _canonical_hostname(parsed.hostname or "")
        port = parsed.port
    except (TypeError, ValueError, idna.IDNAError) as exc:
        raise ValueError("url must be a valid HTTP URL") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("url must be a valid HTTP URL")
    port_text = ""
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        port_text = f":{port}"
    display_hostname = f"[{hostname}]" if is_ipv6 else hostname
    return f"{scheme}://{display_hostname}{port_text}", hostname


def _normalize_hostname(hostname: str) -> str:
    try:
        canonical, _ = _canonical_hostname(hostname)
        return canonical
    except (TypeError, ValueError, idna.IDNAError) as exc:
        raise ValueError("hostname must be a canonical host name") from exc


def _canonical_hostname(hostname: str) -> tuple[str, bool]:
    if not isinstance(hostname, str) or not hostname or hostname != hostname.strip():
        raise ValueError("hostname must be a canonical host name")
    if "%" in hostname:
        raise ValueError("hostname must be a canonical host name")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        return str(address), isinstance(address, ipaddress.IPv6Address)

    terminal_dot = hostname.endswith(".")
    source = hostname[:-1] if terminal_dot else hostname
    if not source:
        raise ValueError("hostname must be a canonical host name")
    canonical = idna.encode(
        source,
        uts46=True,
        transitional=False,
        std3_rules=True,
    ).decode("ascii").casefold()
    if terminal_dot:
        canonical += "."
    if len(canonical) > 253:
        raise ValueError("hostname must be a canonical host name")
    return canonical, False


def _reason_code(value: str) -> VerificationReason:
    normalized = value.casefold()
    allowed = {reason.value for reason in VerificationReason}
    if normalized in allowed:
        return VerificationReason(normalized)
    if "login" in normalized or "sign in" in normalized:
        return VerificationReason.LOGIN
    if any(
        marker in normalized
        for marker in ("challenge", "captcha", "verify you are human")
    ):
        return VerificationReason.CHALLENGE
    return VerificationReason.VERIFICATION_REQUIRED


@contextmanager
def _windows_named_mutex(name: str):
    if os.name != "nt":
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise OSError("verification queue lock creation failed")
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, _INFINITE)
        if result not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            raise OSError("verification queue lock acquisition failed")
        acquired = True
        yield
    finally:
        release_failed = acquired and not kernel32.ReleaseMutex(handle)
        close_failed = not kernel32.CloseHandle(handle)
        if release_failed or close_failed:
            raise OSError("verification queue lock release failed")
