"""Small Qt adapters for running workflow commands away from the GUI thread."""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRunnable, QThreadPool, Signal, Slot


logger = logging.getLogger(__name__)


class VerificationRequired(Exception):
    """A command may raise this to return control to manual verification."""

    def __init__(self, review_id: str) -> None:
        super().__init__("manual verification required")
        self.review_id = str(review_id)


class WorkerSignals(QObject):
    """Signals emitted by a single runnable; they are delivered queued to views."""

    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    verification_required = Signal(str)
    finished = Signal()


@dataclass(frozen=True)
class WorkerContext:
    """Cooperative controls exposed to commands without exposing Qt widgets."""

    _stop_event: threading.Event
    _publish: Callable[[str, object], None]

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def report_progress(self, value: object) -> None:
        self._publish("progress", value)

    def require_verification(self, review_id: str) -> None:
        raise VerificationRequired(review_id)


class _Runnable(QRunnable):
    def __init__(
        self,
        command: Callable[..., object],
        context: WorkerContext,
        should_start: Callable[[], bool],
    ) -> None:
        super().__init__()
        self.command = command
        self.context = context
        self.should_start = should_start
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            if not self.should_start():
                return
            result = self._call_command()
        except VerificationRequired as error:
            self.context._publish("verification_required", error.review_id)
        except Exception as error:  # Do not forward provider/browser/error text to the UI.
            logger.warning("Desktop worker failed with %s", type(error).__name__)
            self.context._publish("failed", "Operation failed. Check sanitized diagnostics for details.")
        else:
            self.context._publish("succeeded", result)
        finally:
            self.context._publish("finished", None)

    def _call_command(self) -> object:
        """Support a simple callable and an opt-in callable accepting WorkerContext."""
        try:
            signature = inspect.signature(self.command)
        except (TypeError, ValueError):
            return self.command()
        try:
            signature.bind()
        except TypeError:
            signature.bind(self.context)
            return self.command(self.context)
        return self.command()


class WorkerPool(QObject):
    """A serial worker pool with safe signal relays and cooperative stopping.

    Serial execution deliberately prevents concurrent crawler/database mutation.
    Calling :meth:`request_stop_after_current` never interrupts an in-flight
    browser operation; it only prevents queued commands from beginning.
    """

    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    verification_required = Signal(str)
    active_changed = Signal(bool)

    _EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, parent: QObject | None = None, *, max_thread_count: int = 1) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(1, int(max_thread_count)))
        self._stop_event = threading.Event()
        self._active = 0

    def submit(self, command: Callable[..., object]) -> None:
        """Schedule a command; it must not touch widgets or expose secrets in errors."""
        if not callable(command):
            raise TypeError("command must be callable")
        self._active += 1
        self._emit_active_changed()
        context = WorkerContext(self._stop_event, self._post_event)
        self._pool.start(_Runnable(command, context, self._claim_start))

    def request_stop_after_current(self) -> None:
        """Keep the current operation intact and skip all commands not yet started."""
        self._stop_event.set()

    def has_active_work(self) -> bool:
        return self._active > 0

    def wait_for_done(self, timeout_ms: int = -1) -> bool:
        return self._pool.waitForDone(timeout_ms)

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Request cooperative stopping and wait; never force-terminate a worker."""
        self.request_stop_after_current()
        return self.wait_for_done(timeout_ms)

    def _claim_start(self) -> bool:
        return not self._stop_event.is_set()

    def event(self, event: QEvent) -> bool:  # noqa: N802 - Qt override name
        if event.type() != self._EVENT_TYPE:
            return super().event(event)
        kind = event.kind
        if kind == "progress":
            self.progress.emit(event.payload)
        elif kind == "succeeded":
            self.succeeded.emit(event.payload)
        elif kind == "failed":
            self.failed.emit(str(event.payload))
        elif kind == "verification_required":
            self.verification_required.emit(str(event.payload))
        elif kind == "finished":
            self._finished()
        return True

    def _post_event(self, kind: str, payload: object) -> None:
        QCoreApplication.postEvent(self, _WorkerEvent(kind, payload))

    def _finished(self) -> None:
        self._active = max(0, self._active - 1)
        self._emit_active_changed()

    def _emit_active_changed(self) -> None:
        self.active_changed.emit(self.has_active_work())


class _WorkerEvent(QEvent):
    def __init__(self, kind: str, payload: object) -> None:
        super().__init__(WorkerPool._EVENT_TYPE)
        self.kind = kind
        self.payload = payload
