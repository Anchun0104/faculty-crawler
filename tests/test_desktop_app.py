from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from crawler.batch import CrawlTask
from crawler.models import (
    CrawlOutcome,
    PageAssessment,
    PageKind,
    RecommendedAction,
    TaskStatus,
)
from crawler.parsers import FacultyRecord
from crawler.session_store import SessionStore
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import VerificationItem, VerificationQueue, VerificationResult
from ui.controller import AppController, STATUS_LABELS
from desktop_app import (
    BatchVerificationContext,
    BatchLogSession,
    DesktopApp,
    DesktopWorkflowOwner,
    QueueLogHandler,
    UiEvent,
    VerificationDependencies,
    _recover_desktop_tasks,
    _default_verification_dependencies,
    run_batch_worker,
    run_verification_worker,
)


class DesktopWorkerTests(unittest.TestCase):
    def test_terminal_store_failure_keeps_resume_claim_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = CrawlTask(
                "https://example.edu/faculty",
                root / "faculty.xlsx",
            )
            task_store = TaskStore(root / "tasks")
            task_store.save(
                StoredRun(
                    "run-crash",
                    [
                        StoredTask(
                            "task-crash",
                            task.url,
                            str(task.output_path),
                            TaskStatus.READY_TO_RESUME,
                        )
                    ],
                )
            )
            verification_queue = VerificationQueue(root / "queue.json")
            item = verification_queue.enqueue(
                VerificationItem(
                    "run-crash",
                    "task-crash",
                    task.url,
                    "example.edu",
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )
            verification_queue.mark_ready(item.run_id, item.task_id)
            verification_queue.begin_resume(item.run_id, item.task_id)
            original_update = task_store.update_task

            def fail_terminal(run_id, task_id, status, **kwargs):
                if status in {
                    TaskStatus.SUCCEEDED,
                    TaskStatus.REVIEW_RECOMMENDED,
                    TaskStatus.FAILED,
                }:
                    raise OSError("SECRET disk")
                return original_update(run_id, task_id, status, **kwargs)

            class Crawler:
                def __init__(self, _timeout):
                    pass

                def crawl_outcome(self, _url):
                    return CrawlOutcome(
                        TaskStatus.SUCCEEDED,
                        (FacultyRecord("Ada", "Professor", "profile"),),
                    )

            context = BatchVerificationContext(
                "run-crash",
                ("task-crash",),
                verification_queue,
                task_store,
                Mock(),
                Crawler,
                (0,),
                True,
            )
            with self.assertLogs("desktop_app", level="ERROR") as captured:
                with patch.object(task_store, "update_task", side_effect=fail_terminal):
                    run_batch_worker(
                        [task],
                        queue.Queue(),
                        timeout=100,
                        verification_context=context,
                    )
            before_restart = verification_queue.items()[0]
            recovered_tasks, _ = _recover_desktop_tasks(
                task_store,
                verification_queue,
            )

        self.assertEqual(before_restart.status, TaskStatus.FETCHING)
        self.assertEqual(recovered_tasks[0].status, TaskStatus.READY_TO_RESUME.value)
        self.assertNotIn("SECRET", "\n".join(captured.output))

    def test_batch_purge_failure_does_not_change_success(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        task = CrawlTask("https://example.edu", Path("out.xlsx"))
        session_store = Mock()
        session_store.purge_expired.side_effect = OSError("SECRET path")

        def runner(tasks, **kwargs):
            tasks[0].status = TaskStatus.SUCCEEDED.value
            kwargs["on_update"](0, tasks[0])

        context = BatchVerificationContext(
            "run-purge",
            ("task-purge",),
            object(),
            object(),
            session_store,
            lambda _timeout: object(),
        )
        with self.assertLogs("desktop_app", level="WARNING") as captured:
            run_batch_worker(
                [task],
                events,
                timeout=100,
                runner=runner,
                verification_context=context,
            )

        self.assertEqual(task.status, TaskStatus.SUCCEEDED.value)
        self.assertEqual(
            [events.get_nowait().kind, events.get_nowait().kind],
            ["task", "finished"],
        )
        self.assertNotIn("SECRET", "\n".join(captured.output))

    def test_verification_worker_emits_failed_for_terminal_attempt(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()

        class Service:
            def verify(self, *_args, **_kwargs):
                return VerificationResult(
                    TaskStatus.FAILED,
                    None,
                    PageAssessment(
                        PageKind.HUMAN_VERIFICATION,
                        RecommendedAction.QUEUE_VERIFICATION,
                    ),
                )

        run_verification_worker(
            self._verification_item(),
            events,
            service=Service(),
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(
            [events.get_nowait().kind, events.get_nowait().kind],
            ["verification_started", "verification_failed"],
        )

    def test_verification_worker_emits_started_and_ready_without_state(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        item = self._verification_item()

        class Service:
            def verify(self, item_arg, *, completion_event, cancel_event):
                self.called = (item_arg, completion_event, cancel_event)
                return VerificationResult(
                    TaskStatus.READY_TO_RESUME,
                    b'{"cookies":[]}',
                    PageAssessment(PageKind.DIRECTORY, RecommendedAction.PARSE),
                )

        service = Service()
        completion = threading.Event()
        cancel = threading.Event()
        run_verification_worker(
            item,
            events,
            service=service,
            completion_event=completion,
            cancel_event=cancel,
        )
        received = [events.get_nowait(), events.get_nowait()]

        self.assertEqual(
            [event.kind for event in received],
            ["verification_started", "verification_ready"],
        )
        self.assertEqual(received[1].run_id, "run-desktop")
        self.assertEqual(received[1].task_id, "task-desktop")
        self.assertFalse(any(hasattr(event, "storage_state") for event in received))

    def test_verification_worker_emits_deferred_and_never_auto_resumes(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        calls: list[str] = []

        class Service:
            def verify(self, *_args, **_kwargs):
                calls.append("verify")
                return VerificationResult(
                    TaskStatus.VERIFICATION_REQUIRED,
                    None,
                    PageAssessment(
                        PageKind.HUMAN_VERIFICATION,
                        RecommendedAction.QUEUE_VERIFICATION,
                    ),
                )

        run_verification_worker(
            self._verification_item(),
            events,
            service=Service(),
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(calls, ["verify"])
        self.assertEqual(
            [events.get_nowait().kind, events.get_nowait().kind],
            ["verification_started", "verification_deferred"],
        )

    def test_verification_worker_failure_is_fixed_and_sanitized(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()

        class Service:
            def verify(self, *_args, **_kwargs):
                raise RuntimeError("private browser content")

        with self.assertLogs("desktop_app", level="ERROR") as captured:
            run_verification_worker(
                self._verification_item(),
                events,
                service=Service(),
                completion_event=threading.Event(),
                cancel_event=threading.Event(),
            )
        received = [events.get_nowait(), events.get_nowait()]

        self.assertEqual(received[1].kind, "verification_failed")
        self.assertEqual(received[1].error, "verification_failed")
        self.assertNotIn("private browser content", "\n".join(captured.output))

    @staticmethod
    def _verification_item() -> VerificationItem:
        return VerificationItem(
            "run-desktop",
            "task-desktop",
            "https://example.edu/private",
            "example.edu",
            "2026-07-22T10:00:00Z",
            "challenge",
        )

    def test_worker_only_enqueues_task_and_finished_events(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        tasks = [CrawlTask("https://example.edu/faculty", Path("faculty.xlsx"))]

        def fake_runner(tasks_arg, *, timeout, on_update) -> None:
            tasks_arg[0].status = "running"
            on_update(0, tasks_arg[0])
            tasks_arg[0].status = "succeeded"
            tasks_arg[0].record_count = 3
            on_update(0, tasks_arg[0])

        run_batch_worker(tasks, events, timeout=1500, runner=fake_runner)

        received = [events.get_nowait(), events.get_nowait(), events.get_nowait()]
        self.assertEqual([event.kind for event in received], ["task", "task", "finished"])
        self.assertEqual(received[0].status, "running")
        self.assertEqual(received[1].record_count, 3)

    def test_stop_event_prevents_subsequent_task_execution(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        stop_event = threading.Event()
        tasks = [
            CrawlTask("https://one.example.edu", Path("one.xlsx")),
            CrawlTask("https://two.example.edu", Path("two.xlsx")),
        ]
        visited: list[str] = []

        def fake_runner(tasks_arg, *, timeout, on_update, should_stop) -> None:
            for task in tasks_arg:
                if should_stop():
                    break
                visited.append(task.url)
                stop_event.set()

        run_batch_worker(
            tasks,
            events,
            timeout=1500,
            runner=fake_runner,
            stop_event=stop_event,
        )

        self.assertEqual(visited, ["https://one.example.edu"])

    def test_controller_stop_reaches_real_batch_adapter_between_urls(self) -> None:
        started = threading.Event()
        release = threading.Event()
        visited: list[str] = []

        class Crawler:
            def __init__(self, _timeout):
                pass

            def crawl_outcome(self, url):
                visited.append(url)
                started.set()
                release.wait(2)
                return CrawlOutcome(
                    TaskStatus.SUCCEEDED,
                    (FacultyRecord("Ada", "Professor", url + "/ada"),),
                )

        def runner(tasks, **kwargs):
            from crawler.batch import run_tasks

            return run_tasks(
                tasks,
                crawler_factory=Crawler,
                exporter=lambda _records, _path: None,
                **kwargs,
            )

        controller = None

        def starter(tasks, *, timeout):
            return controller.launch_worker(
                "batch",
                target=run_batch_worker,
                args=(tasks, controller.events),
                kwargs={"timeout": timeout, "runner": runner},
                use_stop_event=True,
            )

        controller = AppController(Path("output"), runner=starter)
        controller.prepare(
            "https://one.example.edu/faculty\n"
            "https://two.example.edu/faculty"
        )
        controller.start_batch()
        self.assertTrue(started.wait(2))

        controller.stop_after_current()
        release.set()
        controller.worker("batch").join(2)

        final_state = controller.finish_batch(
            "批量任务结束：成功 1，已停止 1。",
            stopped=True,
        )

        self.assertEqual(visited, ["https://one.example.edu/faculty"])
        self.assertEqual(controller.tasks[1].status, TaskStatus.CANCELLED.value)
        self.assertEqual(final_state.status_symbol, "■")
        self.assertIn("已停止 1", final_state.status_text)

    def test_worker_forwards_persistent_verification_context(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        tasks = [CrawlTask("https://example.edu/faculty", Path("faculty.xlsx"))]
        verification_queue = object()
        task_store = object()
        session_store = Mock()
        crawler = object()
        captured: dict[str, object] = {}

        def crawler_factory(timeout: int):
            captured["crawler_timeout"] = timeout
            return crawler

        def fake_runner(tasks_arg, **kwargs) -> None:
            captured["tasks"] = tasks_arg
            captured.update(kwargs)
            kwargs["on_verification"](DesktopWorkerTests._verification_item())

        context = BatchVerificationContext(
            "run-desktop",
            ("task-desktop",),
            verification_queue,
            task_store,
            session_store,
            crawler_factory,
        )

        run_batch_worker(
            tasks,
            events,
            timeout=1500,
            runner=fake_runner,
            verification_context=context,
        )

        self.assertIs(captured["tasks"], tasks)
        self.assertEqual(captured["timeout"], 1500)
        self.assertEqual(captured["run_id"], "run-desktop")
        self.assertEqual(captured["task_ids"], ("task-desktop",))
        self.assertIs(captured["verification_queue"], verification_queue)
        self.assertIs(captured["task_store"], task_store)
        self.assertIs(captured["crawler_factory"](1500), crawler)
        self.assertEqual(captured["crawler_timeout"], 1500)
        self.assertEqual(events.get_nowait().kind, "verification_required")
        self.assertEqual(events.get_nowait().kind, "finished")
        session_store.purge_expired.assert_called_once_with()

    def test_unexpected_worker_failure_is_sanitized_and_has_stack(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()

        def failing_runner(tasks_arg, *, timeout, on_update) -> None:
            raise RuntimeError("Cookie: secret <html>private page</html>")

        with self.assertLogs("desktop_app", level="ERROR") as captured:
            run_batch_worker([], events, timeout=1500, runner=failing_runner)

        fatal_event = events.get_nowait()
        self.assertEqual(fatal_event.kind, "fatal")
        self.assertEqual(fatal_event.error, "batch_worker_failed")
        self.assertNotIn("secret", fatal_event.error)
        log_text = "\n".join(captured.output)
        self.assertIn("Traceback", log_text)
        self.assertNotIn("secret", log_text)
        self.assertNotIn("private page", log_text)


class DesktopVerificationWiringTests(unittest.TestCase):
    def test_production_start_delegates_worker_creation_to_controller(self) -> None:
        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Text:
            def configure(self, **_kwargs):
                pass

            def delete(self, *_args):
                pass

        class LogSession:
            def start(self):
                pass

            def close(self):
                pass

        app = object.__new__(DesktopApp)
        app.workflow_owner = Mock(acquired=True)
        app.verification_in_progress = False
        app.verification_queue = None
        app.task_store = None
        app.session_store = None
        app.verification_tasks = {}
        app.events = queue.Queue()
        app.log_text = Text()
        app.output_dir = Value("output")
        app.detailed_logs = Value(False)
        app.status_text = Value("")
        app._set_running_controls = Mock()
        app.controller = Mock()
        app.controller.launch_worker.return_value = True
        worker = object()
        app.controller.worker.return_value = worker

        with patch("desktop_app.BatchLogSession", return_value=LogSession()):
            started = app._start_prepared_batch(
                [CrawlTask("https://example.edu/faculty", Path("out.xlsx"))],
                timeout=30000,
            )

        self.assertTrue(started)
        self.assertIs(app.worker, worker)
        launch = app.controller.launch_worker.call_args
        self.assertIs(launch.kwargs["target"], run_batch_worker)
        self.assertTrue(launch.kwargs["use_stop_event"])

    def test_desktop_event_pump_uses_controller_kind_routing(self) -> None:
        controller = AppController(Path("output"), runner=lambda *_args, **_kwargs: True)
        app = object.__new__(DesktopApp)
        app.controller = controller
        app.messages = []
        app._append_log = app.messages.append
        app.after = lambda *_args: None
        controller.events.put(UiEvent(kind="log", message="safe message"))

        app._drain_events()

        self.assertEqual(app.messages, ["safe message"])

    @unittest.skipUnless(os.name == "nt", "Windows desktop owner regression")
    def test_process_owner_blocks_claim_until_owner_process_exits(self) -> None:
        owner_process = """
import sys
from pathlib import Path
from crawler.models import TaskStatus
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import VerificationItem, VerificationQueue
from desktop_app import DesktopWorkflowOwner

root = Path(sys.argv[1])
owner = DesktopWorkflowOwner()
if not owner.acquired:
    print("owner-failed", flush=True)
    raise SystemExit(2)
store = TaskStore(root / "tasks")
store.save(StoredRun("run-owner", [StoredTask(
    "task-owner", "https://example.edu/faculty", "out.xlsx",
    TaskStatus.READY_TO_RESUME,
)]))
queue = VerificationQueue(root / "queue.json")
item = queue.enqueue(VerificationItem(
    "run-owner", "task-owner", "https://example.edu/faculty",
    "example.edu", "2026-07-22T10:00:00Z", "challenge",
))
queue.mark_ready(item.run_id, item.task_id)
queue.begin_resume(item.run_id, item.task_id)
print("owner-ready", flush=True)
sys.stdin.readline()
"""
        contender = """
import sys
from pathlib import Path
from crawler.verification import VerificationQueue
from desktop_app import DesktopWorkflowOwner

root = Path(sys.argv[1])
owner = DesktopWorkflowOwner()
if owner.acquired:
    VerificationQueue(root / "queue.json").defer("run-owner", "task-owner")
print("acquired" if owner.acquired else "blocked")
owner.close()
"""
        recovery = """
import sys
from pathlib import Path
from crawler.verification import VerificationQueue
from desktop_app import DesktopWorkflowOwner

root = Path(sys.argv[1])
owner = DesktopWorkflowOwner()
if owner.acquired:
    VerificationQueue(root / "queue.json").recover_interrupted_resumes()
print("acquired" if owner.acquired else "blocked")
owner.close()
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            p1 = subprocess.Popen(
                [sys.executable, "-c", owner_process, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(p1.stdout.readline().strip(), "owner-ready")
            p2 = subprocess.run(
                [sys.executable, "-c", contender, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            during = VerificationQueue(root / "queue.json").items()[0]
            p1.terminate()
            p1.communicate(timeout=15)
            p3 = subprocess.run(
                [sys.executable, "-c", recovery, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            after = VerificationQueue(root / "queue.json").items()[0]

        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertEqual(p2.stdout.strip(), "blocked")
        self.assertEqual(during.status, TaskStatus.FETCHING)
        self.assertEqual(during.attempts, 0)
        self.assertEqual(p3.returncode, 0, p3.stderr)
        self.assertEqual(p3.stdout.strip(), "acquired")
        self.assertEqual(after.status, TaskStatus.READY_TO_RESUME)

    @unittest.skipUnless(os.name == "nt", "Windows desktop owner regression")
    def test_close_keeps_owner_while_persistent_workers_are_alive(self) -> None:
        owner_process = """
import sys
import threading
from unittest.mock import patch
from desktop_app import DesktopApp, DesktopWorkflowOwner

owner = DesktopWorkflowOwner()
if not owner.acquired:
    print("owner-failed", flush=True)
    raise SystemExit(2)
close_calls = []
original_close = owner.close
def tracked_close():
    close_calls.append(True)
    original_close()
owner.close = tracked_close
blocker = threading.Event()
batch = threading.Thread(target=blocker.wait, daemon=True)
verification = threading.Thread(target=blocker.wait, daemon=True)
batch.start()
verification.start()
app = object.__new__(DesktopApp)
app.worker = batch
app.verification_worker = verification
app.verification_cancel_event = threading.Event()
app.log_session = None
app.workflow_owner = owner
app.destroyed = False
app.destroy = lambda: setattr(app, "destroyed", True)
with patch("desktop_app.messagebox.askyesno", return_value=True):
    app._on_close()
print(
    "closed"
    if (
        app.destroyed
        and owner.acquired
        and not close_calls
        and batch.is_alive()
        and verification.is_alive()
    )
    else "unsafe",
    flush=True,
)
sys.stdin.readline()
"""
        contender = """
from desktop_app import DesktopWorkflowOwner
owner = DesktopWorkflowOwner()
print("acquired" if owner.acquired else "blocked")
owner.close()
"""
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        p1 = subprocess.Popen(
            [sys.executable, "-c", owner_process],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            close_result = p1.stdout.readline().strip()
            p2 = subprocess.run(
                [sys.executable, "-c", contender],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
        finally:
            p1.terminate()
            _, owner_stderr = p1.communicate(timeout=15)
        p3 = subprocess.run(
            [sys.executable, "-c", contender],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

        self.assertEqual(close_result, "closed")
        self.assertIn("shutdown_waiting_for_process_exit", owner_stderr)
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertEqual(p2.stdout.strip(), "blocked")
        self.assertEqual(p3.returncode, 0, p3.stderr)
        self.assertEqual(p3.stdout.strip(), "acquired")

    @unittest.skipUnless(os.name == "nt", "Windows desktop owner regression")
    def test_non_owner_thread_cannot_release_workflow_owner(self) -> None:
        contender = """
from desktop_app import DesktopWorkflowOwner
owner = DesktopWorkflowOwner()
print("acquired" if owner.acquired else "blocked")
owner.close()
"""
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        owner = DesktopWorkflowOwner()
        self.assertTrue(owner.acquired)
        try:
            closer = threading.Thread(target=owner.close)
            closer.start()
            closer.join(timeout=15)
            blocked = subprocess.run(
                [sys.executable, "-c", contender],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
        finally:
            owner.close()
        acquired = subprocess.run(
            [sys.executable, "-c", contender],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

        self.assertFalse(closer.is_alive())
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        self.assertEqual(blocked.stdout.strip(), "blocked")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        self.assertEqual(acquired.stdout.strip(), "acquired")

    def test_non_owner_cannot_start_or_process_persistent_work(self) -> None:
        app = self._app(service=object())
        app.workflow_owner = type("Owner", (), {"acquired": False})()
        app.task_store = object()
        app.session_store = object()

        with (
            patch("desktop_app.messagebox.showinfo") as info,
            patch("desktop_app.threading.Thread") as thread,
        ):
            app._start()
            app._process_verification_queue()

        thread.assert_not_called()
        self.assertEqual(info.call_count, 2)
        self.assertTrue(
            all("application_already_running" in call.args[1] for call in info.call_args_list)
        )

    def test_terminal_task_store_state_cleans_stale_queue_without_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root / "tasks")
            store.save(
                StoredRun(
                    "run-terminal",
                    [
                        StoredTask(
                            "task-terminal",
                            "https://example.edu/faculty",
                            str(root / "existing.xlsx"),
                            TaskStatus.SUCCEEDED,
                            3,
                        )
                    ],
                )
            )
            verification_queue = VerificationQueue(root / "queue.json")
            item = verification_queue.enqueue(
                VerificationItem(
                    "run-terminal",
                    "task-terminal",
                    "https://example.edu/faculty",
                    "example.edu",
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )
            verification_queue.mark_ready(item.run_id, item.task_id)

            tasks, identities = _recover_desktop_tasks(store, verification_queue)
            remaining = verification_queue.items()
            saved_status = store.load("run-terminal").tasks[0].status

        self.assertEqual(tasks, [])
        self.assertEqual(identities, {})
        self.assertEqual(remaining, [])
        self.assertEqual(saved_status, TaskStatus.SUCCEEDED)

    def test_stale_queue_cleanup_failure_never_downgrades_terminal_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root / "tasks")
            store.save(
                StoredRun(
                    "run-terminal",
                    [
                        StoredTask(
                            "task-terminal",
                            "https://example.edu/faculty",
                            "existing.xlsx",
                            TaskStatus.SUCCEEDED,
                        )
                    ],
                )
            )
            verification_queue = VerificationQueue(root / "queue.json")
            item = verification_queue.enqueue(
                VerificationItem(
                    "run-terminal",
                    "task-terminal",
                    "https://example.edu/faculty",
                    "example.edu",
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )
            with (
                patch.object(
                    verification_queue,
                    "remove_terminal",
                    side_effect=OSError("SECRET queue"),
                    create=True,
                ),
                self.assertLogs("desktop_app", level="ERROR") as captured,
            ):
                tasks, _ = _recover_desktop_tasks(store, verification_queue)
            saved_status = store.load("run-terminal").tasks[0].status
            remaining = verification_queue.items()

        self.assertEqual(tasks, [])
        self.assertEqual(saved_status, TaskStatus.SUCCEEDED)
        self.assertEqual(len(remaining), 1)
        self.assertNotIn("SECRET", "\n".join(captured.output))

    def test_default_startup_physically_purges_unaccessed_expired_session(self) -> None:
        class Protector:
            def protect(self, data: bytes) -> bytes:
                return data

            def unprotect(self, data: bytes) -> bytes:
                return data

        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            SessionStore(
                root / "sessions",
                Protector(),
                clock=lambda: old,
            ).save("expired.example.edu", b"state")
            current_store = SessionStore(
                root / "sessions",
                Protector(),
                clock=lambda: old + timedelta(days=31),
            )
            paths = type(
                "Paths",
                (),
                {
                    "runs": root / "runs",
                    "tasks": root / "tasks",
                    "sessions": root / "sessions",
                },
            )()
            with (
                patch("desktop_app.AppPaths.for_user", return_value=paths),
                patch("desktop_app.SessionStore", return_value=current_store),
            ):
                dependencies = _default_verification_dependencies()
            remaining = list((root / "sessions").iterdir())

        self.assertIs(dependencies.session_store, current_store)
        self.assertEqual(remaining, [])

    def test_process_exit_then_new_app_recovers_interrupted_resume(self) -> None:
        worker = """
import sys
from pathlib import Path
from crawler.models import TaskStatus
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import VerificationItem, VerificationQueue

root = Path(sys.argv[1])
store = TaskStore(root / "tasks")
queue = VerificationQueue(root / "queue.json")
store.save(StoredRun("run-process", [StoredTask(
    "task-process", "https://example.edu/faculty", "existing.xlsx",
    TaskStatus.READY_TO_RESUME, 4, "saved diagnostic",
)]))
item = queue.enqueue(VerificationItem(
    "run-process", "task-process", "https://example.edu/faculty",
    "example.edu", "2026-07-22T10:00:00Z", "challenge",
))
queue.mark_ready(item.run_id, item.task_id)
queue.begin_resume(item.run_id, item.task_id)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", worker, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            app = object.__new__(DesktopApp)
            app.tasks, app.verification_tasks = _recover_desktop_tasks(
                TaskStore(root / "tasks"),
                VerificationQueue(root / "queue.json"),
            )

        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual(app.tasks[0].status, TaskStatus.READY_TO_RESUME.value)
        self.assertEqual(app.tasks[0].record_count, 4)
        self.assertEqual(app.tasks[0].error, "saved diagnostic")

    def test_new_desktop_instance_recovers_disk_state_and_reconciles_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root / "tasks")
            verification_queue = VerificationQueue(root / "queue.json")
            output = root / "existing.xlsx"
            store.save(
                StoredRun(
                    "run-restart",
                    [
                        StoredTask(
                            "task-ready",
                            "https://example.edu/ready",
                            str(output),
                            TaskStatus.READY_TO_RESUME,
                            7,
                            "saved diagnostic",
                        ),
                        StoredTask(
                            "task-interrupted",
                            "https://example.edu/interrupted",
                            str(root / "interrupted.xlsx"),
                            TaskStatus.FETCHING,
                        ),
                    ],
                )
            )
            ready = verification_queue.enqueue(
                VerificationItem(
                    "run-restart",
                    "task-ready",
                    "https://example.edu/ready",
                    "example.edu",
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )
            verification_queue.mark_ready(ready.run_id, ready.task_id)
            verification_queue.begin_resume(ready.run_id, ready.task_id)
            verification_queue.enqueue(
                VerificationItem(
                    "run-orphan",
                    "task-orphan",
                    "https://orphan.edu/private",
                    "orphan.edu",
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )

            first = object.__new__(DesktopApp)
            first.tasks, first.verification_tasks = _recover_desktop_tasks(
                store,
                verification_queue,
            )
            del first
            second = object.__new__(DesktopApp)
            second.tasks, second.verification_tasks = _recover_desktop_tasks(
                TaskStore(root / "tasks"),
                VerificationQueue(root / "queue.json"),
            )
            saved = store.load("run-restart")
            queue_items = verification_queue.items()

        self.assertEqual(second.tasks[0].output_path, output)
        self.assertEqual(second.tasks[0].record_count, 7)
        self.assertEqual(second.tasks[0].error, "saved diagnostic")
        self.assertEqual(second.tasks[0].status, TaskStatus.READY_TO_RESUME.value)
        self.assertEqual(second.tasks[1].status, TaskStatus.PENDING.value)
        self.assertIs(
            second.verification_tasks[("run-restart", "task-ready")],
            second.tasks[0],
        )
        self.assertEqual(saved.tasks[0].status, TaskStatus.READY_TO_RESUME)
        self.assertEqual(saved.tasks[1].status, TaskStatus.PENDING)
        self.assertEqual(
            next(item for item in queue_items if item.task_id == "task-orphan").status,
            TaskStatus.FAILED,
        )

    def test_default_dependencies_wire_queue_task_store_and_session_store(self) -> None:
        paths = type(
            "Paths",
            (),
            {"runs": Path("runs"), "tasks": Path("tasks"), "sessions": Path("sessions")},
        )()
        queue_object = object()
        task_store = object()
        session_store = Mock()
        service = object()
        with (
            patch("desktop_app.AppPaths.for_user", return_value=paths),
            patch("desktop_app.VerificationQueue", return_value=queue_object) as queue_factory,
            patch("desktop_app.TaskStore", return_value=task_store) as task_factory,
            patch("desktop_app.SessionStore", return_value=session_store) as session_factory,
            patch("desktop_app.VerificationService", return_value=service) as service_factory,
        ):
            result = _default_verification_dependencies()

        self.assertEqual(
            result,
            VerificationDependencies(
                queue_object,
                service,
                task_store,
                session_store,
            ),
        )
        queue_factory.assert_called_once_with(Path("runs") / "verification-queue.json")
        task_factory.assert_called_once_with(Path("tasks"))
        session_factory.assert_called_once_with(Path("sessions"))
        session_store.purge_expired.assert_called_once_with()
        service_factory.assert_called_once_with(
            task_store=task_store,
            queue=queue_object,
            session_store=session_store,
        )

    def test_default_dependency_failure_safely_disables_verification(self) -> None:
        with (
            patch("desktop_app.AppPaths.for_user", side_effect=OSError("private path")),
            self.assertLogs("desktop_app", level="ERROR") as captured,
        ):
            result = _default_verification_dependencies()

        self.assertEqual(result, VerificationDependencies(None, None, None, None))
        self.assertNotIn("private path", "\n".join(captured.output))

    def test_user_command_starts_independent_worker_and_completion_signal(self) -> None:
        started = threading.Event()
        worker_threads: list[int] = []

        class Service:
            def verify(self, _item, *, completion_event, cancel_event):
                worker_threads.append(threading.get_ident())
                started.set()
                completion_event.wait(2)
                return VerificationResult(
                    TaskStatus.READY_TO_RESUME,
                    b'{"cookies":[]}',
                    PageAssessment(PageKind.DIRECTORY, RecommendedAction.PARSE),
                )

        app = self._app(Service())
        self.assertFalse(started.is_set())

        app._process_verification_queue()
        self.assertTrue(started.wait(2))
        self.assertNotEqual(worker_threads, [threading.get_ident()])
        app._complete_verification()
        app.verification_worker.join(2)

        self.assertTrue(app.verification_completion_event.is_set())
        self.assertFalse(app.verification_cancel_event.is_set())

    def test_cancel_command_reaches_worker_and_keeps_item_deferred(self) -> None:
        started = threading.Event()

        class Service:
            def verify(self, _item, *, completion_event, cancel_event):
                started.set()
                cancel_event.wait(2)
                return VerificationResult(
                    TaskStatus.VERIFICATION_REQUIRED,
                    None,
                    PageAssessment(
                        PageKind.HUMAN_VERIFICATION,
                        RecommendedAction.QUEUE_VERIFICATION,
                    ),
                )

        app = self._app(Service())
        app._process_verification_queue()
        self.assertTrue(started.wait(2))
        app._cancel_verification()
        app.verification_worker.join(2)

        self.assertTrue(app.verification_cancel_event.is_set())
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait().kind)
        self.assertEqual(events, ["verification_started", "verification_deferred"])

    def test_event_pump_consumes_all_verification_events_on_main_thread(self) -> None:
        app = self._app(service=object())
        main_thread = threading.get_ident()
        handled_threads: list[int] = []
        original = app._handle_verification_event

        def handle(event):
            handled_threads.append(threading.get_ident())
            original(event)

        app._handle_verification_event = handle
        for kind, status, error in (
            ("verification_started", "", ""),
            ("verification_ready", "ready_to_resume", ""),
            ("verification_deferred", "verification_required", ""),
            ("verification_failed", "", "verification_failed"),
        ):
            app.events.put(
                UiEvent(
                    kind=kind,
                    run_id="run-desktop",
                    task_id="task-desktop",
                    task_index=0,
                    status=status,
                    error=error,
                )
            )

        app._drain_events()

        self.assertEqual(handled_threads, [main_thread] * 4)
        self.assertEqual(app.tasks[0].status, "failed")
        self.assertEqual(app.tasks[0].error, "verification_failed")
        self.assertEqual(len(app.row_events), 3)
        self.assertFalse(any(hasattr(event, "storage_state") for event in app.handled_events))

    def test_default_missing_dependencies_does_not_start_worker(self) -> None:
        app = self._app(service=None, verification_queue=None)

        with patch("desktop_app.messagebox.showinfo"):
            app._process_verification_queue()

        self.assertIsNone(app.verification_worker)

    def test_duplicate_process_command_does_not_start_second_worker(self) -> None:
        started = threading.Event()

        class Service:
            def __init__(self):
                self.calls = 0

            def verify(self, _item, *, completion_event, cancel_event):
                self.calls += 1
                started.set()
                cancel_event.wait(2)
                return VerificationResult(
                    TaskStatus.VERIFICATION_REQUIRED,
                    None,
                    PageAssessment(
                        PageKind.HUMAN_VERIFICATION,
                        RecommendedAction.QUEUE_VERIFICATION,
                    ),
                )

        service = Service()
        app = self._app(service)
        app._process_verification_queue()
        self.assertTrue(started.wait(2))
        first_worker = app.verification_worker
        app._process_verification_queue()
        app._cancel_verification()
        first_worker.join(2)

        self.assertIs(app.verification_worker, first_worker)
        self.assertEqual(service.calls, 1)

    def test_verification_disables_inputs_until_terminal_event(self) -> None:
        started = threading.Event()

        class Service:
            def verify(self, _item, *, completion_event, cancel_event):
                started.set()
                cancel_event.wait(2)
                return VerificationResult(
                    TaskStatus.VERIFICATION_REQUIRED,
                    None,
                    PageAssessment(
                        PageKind.HUMAN_VERIFICATION,
                        RecommendedAction.QUEUE_VERIFICATION,
                    ),
                )

        app = self._app(Service())
        app._process_verification_queue()
        self.assertTrue(started.wait(2))
        for name in (
            "browse_button",
            "timeout_entry",
            "prepare_button",
            "rename_entry",
            "rename_button",
            "start_button",
            "url_text",
        ):
            self.assertEqual(getattr(app, name).state, "disabled")

        app._cancel_verification()
        app.verification_worker.join(2)
        terminal = None
        while not app.events.empty():
            event = app.events.get_nowait()
            if event.kind == "verification_deferred":
                terminal = event
        app._handle_verification_event(terminal)

        for name in (
            "browse_button",
            "timeout_entry",
            "prepare_button",
            "rename_entry",
            "rename_button",
            "start_button",
            "url_text",
        ):
            self.assertEqual(getattr(app, name).state, "normal")

    def test_same_host_task_events_use_stable_run_and_task_identity(self) -> None:
        app = self._app(service=object())
        app.tasks = [
            CrawlTask("https://example.edu/first", Path("first.xlsx")),
            CrawlTask("https://example.edu/second", Path("second.xlsx")),
        ]
        app.verification_tasks = {
            ("run-1", "task-1"): app.tasks[0],
            ("run-1", "task-2"): app.tasks[1],
        }

        app._handle_verification_event(
            UiEvent(
                kind="verification_ready",
                run_id="run-1",
                task_id="task-2",
            )
        )

        self.assertEqual(app.tasks[0].status, "pending")
        self.assertEqual(app.tasks[1].status, "ready_to_resume")
        self.assertEqual(app.row_events[0].task_index, 1)

    def test_unmapped_verification_event_never_guesses_task_row(self) -> None:
        app = self._app(service=object())
        app.verification_tasks = {}

        app._handle_verification_event(
            UiEvent(
                kind="verification_ready",
                run_id="run-other",
                task_id="task-other",
            )
        )

        self.assertEqual(app.tasks[0].status, "verification_required")
        self.assertEqual(app.row_events, [])

    def test_verification_blocks_prepare_and_start_commands(self) -> None:
        app = self._app(service=object())
        original_tasks = app.tasks
        app.verification_in_progress = True
        app.url_text = object()
        app.timeout_value = object()

        with (
            patch("desktop_app.prepare_tasks") as prepare,
            patch("desktop_app.threading.Thread") as thread,
        ):
            app._prepare()
            app._start()

        self.assertIs(app.tasks, original_tasks)
        prepare.assert_not_called()
        thread.assert_not_called()

    def test_manual_verification_persists_and_explicit_restart_uses_session(self) -> None:
        class Protector:
            def protect(self, data: bytes) -> bytes:
                return data

            def unprotect(self, data: bytes) -> bytes:
                return data

        class Value:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Text:
            def configure(self, **_kwargs):
                pass

            def delete(self, *_args):
                pass

        class Button:
            def configure(self, **_kwargs):
                pass

        class Tree:
            def selection(self):
                return ("0",)

        class LogSession:
            log_path = Path("run.log")

            def start(self):
                pass

            def close(self):
                pass

        class ImmediateThread:
            def __init__(self, *, target, args, kwargs, **_options):
                self.target = target
                self.args = args
                self.kwargs = kwargs
                self.alive = False

            def start(self):
                self.alive = True
                try:
                    self.target(*self.args, **self.kwargs)
                finally:
                    self.alive = False

            def is_alive(self):
                return self.alive

            def join(self, _timeout=None):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            verification_queue = VerificationQueue(root / "queue.json")
            task_store = TaskStore(root / "tasks")
            session_store = SessionStore(root / "sessions", Protector())
            crawler_stores: list[SessionStore] = []

            class Crawler:
                def __init__(self, _timeout, *, session_store=None):
                    crawler_stores.append(session_store)
                    self.session_store = session_store

                def crawl_outcome(self, _url):
                    if self.session_store.load("example.edu") is None:
                        return CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED)
                    return CrawlOutcome(
                        TaskStatus.SUCCEEDED,
                        (FacultyRecord("Ada", "Professor", "https://example.edu/ada"),),
                    )

            class Service:
                def __init__(self):
                    self.ready_item = None

                def verify(self, item, **_kwargs):
                    session_store.save(
                        "example.edu",
                        b'{"cookies":[],"origins":[]}',
                    )
                    self.ready_item = verification_queue.mark_ready(
                        item.run_id,
                        item.task_id,
                    )
                    return VerificationResult(
                        TaskStatus.READY_TO_RESUME,
                        b'{"cookies":[],"origins":[]}',
                        PageAssessment(PageKind.DIRECTORY, RecommendedAction.PARSE),
                    )

            service = Service()
            app = object.__new__(DesktopApp)
            app.tasks = [
                CrawlTask(
                    "https://example.edu/faculty/one",
                    root / "faculty-one.xlsx",
                ),
                CrawlTask(
                    "https://example.edu/faculty/two",
                    root / "faculty-two.xlsx",
                ),
            ]
            app.events = queue.Queue()
            app.verification_queue = verification_queue
            app.verification_service = service
            app.task_store = task_store
            app.session_store = session_store
            app.verification_tasks = {}
            app.verification_in_progress = False
            app.verification_worker = None
            app.verification_completion_event = None
            app.verification_cancel_event = None
            app.current_verification_item = None
            app.worker = None
            app.log_session = None
            app.output_dir = Value(str(root))
            app.timeout_value = Value("1500")
            app.detailed_logs = Value(False)
            app.status_text = Value()
            app.log_text = Text()
            app.task_tree = Tree()
            app.process_verification_button = Button()
            app.verification_complete_button = Button()
            app.verification_cancel_button = Button()
            app._set_running_controls = lambda _running: None
            app._update_task_row = lambda _event: None

            with (
                patch("desktop_app.FacultyCrawler", Crawler),
                patch("desktop_app.BatchLogSession", return_value=LogSession()),
                patch("desktop_app.threading.Thread", ImmediateThread),
            ):
                app._start()
                identities = list(app.verification_tasks)
                first_run, first_task = identities[0]
                second_run, second_task = identities[1]

                self.assertEqual(len(crawler_stores), 2)
                self.assertIs(crawler_stores[0], session_store)
                self.assertEqual(
                    task_store.resolve_original_url(first_run, first_task),
                    app.tasks[0].url,
                )
                self.assertEqual(
                    [item.task_id for item in verification_queue.pending()],
                    [first_task, second_task],
                )

                app._process_verification_queue()
                self.assertEqual(len(crawler_stores), 2)
                self.assertEqual(
                    service.ready_item.status,
                    TaskStatus.READY_TO_RESUME,
                )
                while not app.events.empty():
                    event = app.events.get_nowait()
                    if event.kind == "verification_ready":
                        app._handle_verification_event(event)

                app._start()

            self.assertEqual(len(crawler_stores), 3)
            self.assertIs(crawler_stores[2], session_store)
            self.assertEqual(app.tasks[0].status, TaskStatus.SUCCEEDED.value)
            self.assertEqual(
                app.tasks[1].status,
                TaskStatus.VERIFICATION_REQUIRED.value,
            )
            remaining = verification_queue.items()
            self.assertEqual(len(remaining), 1)
            self.assertEqual((remaining[0].run_id, remaining[0].task_id), (second_run, second_task))

    def test_close_cancels_active_verification(self) -> None:
        app = self._app(service=object())
        app.translation_service = Mock()
        app.verification_cancel_event = threading.Event()
        joined = []

        class Worker:
            alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout):
                joined.append(timeout)
                self.alive = False

        app.verification_worker = Worker()
        app.workflow_owner = Mock(acquired=True)
        app.destroyed = False
        app.destroy = lambda: setattr(app, "destroyed", True)

        with patch("desktop_app.messagebox.askyesno", return_value=True):
            app._on_close()

        self.assertTrue(app.verification_cancel_event.is_set())
        self.assertEqual(joined, [1.0])
        app.workflow_owner.close.assert_called_once_with()
        app.translation_service.stop.assert_called_once_with()
        self.assertTrue(app.destroyed)

    @classmethod
    def _app(cls, service, verification_queue=True):
        item = DesktopWorkerTests._verification_item()

        class Queue:
            def pending(self):
                return [item]

        class Value:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

            def get(self):
                return self.value

        class Button:
            def __init__(self):
                self.state = None

            def configure(self, **kwargs):
                self.state = kwargs.get("state", self.state)

        app = object.__new__(DesktopApp)
        app.tasks = [
            CrawlTask("https://example.edu/private", Path("faculty.xlsx"), status="verification_required")
        ]
        app.events = queue.Queue()
        app.verification_queue = Queue() if verification_queue else None
        app.verification_service = service
        app.verification_worker = None
        app.verification_completion_event = None
        app.verification_cancel_event = None
        app.current_verification_item = None
        app.verification_in_progress = False
        app.verification_tasks = {
            (item.run_id, item.task_id): app.tasks[0],
        }
        app.process_verification_button = Button()
        app.verification_complete_button = Button()
        app.verification_cancel_button = Button()
        app.browse_button = Button()
        app.timeout_entry = Button()
        app.prepare_button = Button()
        app.rename_entry = Button()
        app.rename_button = Button()
        app.start_button = Button()
        app.url_text = Button()
        app.status_text = Value()
        app.log_session = None
        app.worker = None
        app.output_dir = Value()
        app.after = lambda *_args: None
        app.row_events = []
        app.handled_events = []

        def update_row(event):
            app.row_events.append(event)

        app._update_task_row = update_row
        original_handle = DesktopApp._handle_verification_event.__get__(app, DesktopApp)

        def record_handle(event):
            app.handled_events.append(event)
            original_handle(event)

        app._handle_verification_event = record_handle
        return app


class DesktopStatusTests(unittest.TestCase):
    def test_desktop_status_labels_use_controller_copy(self) -> None:
        self.assertIs(DesktopApp.STATUS_LABELS, STATUS_LABELS)

    def test_review_recommended_has_plain_chinese_label(self) -> None:
        self.assertEqual(
            DesktopApp.STATUS_LABELS["review_recommended"],
            "已完成，建议检查",
        )

    def test_review_recommended_event_updates_row_with_chinese_label(self) -> None:
        task = CrawlTask("https://example.edu/faculty", Path("faculty.xlsx"))
        row_values: list[tuple[object, ...]] = []

        class TaskTree:
            def item(self, item_id: str, *, values: tuple[object, ...]) -> None:
                self.item_id = item_id
                row_values.append(values)

        app = object.__new__(DesktopApp)
        app.tasks = [task]
        app.task_tree = TaskTree()

        app._update_task_row(
            UiEvent(
                kind="task",
                task_index=0,
                status="review_recommended",
                record_count=2,
            )
        )

        self.assertEqual(row_values[0][2], "已完成，建议检查")
        self.assertEqual(row_values[0][3], 2)

    def test_finish_batch_counts_all_terminal_statuses_distinctly(self) -> None:
        tasks = [
            CrawlTask("https://one.example.edu", Path("one.xlsx"), status="succeeded"),
            CrawlTask(
                "https://review.example.edu",
                Path("review.xlsx"),
                status="review_recommended",
            ),
            CrawlTask("https://fail.example.edu", Path("fail.xlsx"), status="failed"),
            CrawlTask(
                "https://stopped.example.edu",
                Path("stopped.xlsx"),
                status="cancelled",
            ),
        ]

        class Value:
            def __init__(self, value: str = "") -> None:
                self.value = value

            def get(self) -> str:
                return self.value

            def set(self, value: str) -> None:
                self.value = value

        app = object.__new__(DesktopApp)
        app.tasks = tasks
        app.log_session = None
        app.output_dir = Value("output")
        app.status_text = Value()
        app._set_running_controls = lambda running: None

        app._finish_batch()

        self.assertEqual(
            app.status_text.get(),
            "批量任务结束：成功 1，建议检查 1，失败 1，已停止 1。"
            "日志：output\\logs",
        )


class DesktopLoggingTests(unittest.TestCase):
    def test_queue_handler_emits_formatted_log_event(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        handler = QueueLogHandler(events)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)

        handler.emit(record)

        event = events.get_nowait()
        self.assertEqual(event.kind, "log")
        self.assertEqual(event.message, "INFO hello")

    def test_log_session_writes_environment_and_redacted_failure_details(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        with tempfile.TemporaryDirectory() as temp_dir:
            session = BatchLogSession(Path(temp_dir), events, detailed=False)
            session.start()
            logging.getLogger("crawler.batch").error(
                "Task failed: url=https://example.edu stage=crawl exception_type=RuntimeError error=failed"
            )
            log_path = session.log_path
            session.close()
            text = log_path.read_text(encoding="utf-8")

        self.assertIn("Python", text)
        self.assertIn("Operating system", text)
        self.assertIn("Playwright", text)
        self.assertIn("OpenPyXL", text)
        self.assertIn("https://example.edu", text)
        self.assertNotIn("Cookie", text)
        self.assertTrue(log_path.name.startswith("run_"))

    def test_log_session_excludes_third_party_logs_and_redacts_internal_messages(self) -> None:
        events: queue.Queue[UiEvent] = queue.Queue()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            session = BatchLogSession(output_dir, events, detailed=True)
            session.start()
            logging.getLogger("urllib3").debug("third-party-token=DO-NOT-CAPTURE")
            logging.getLogger("crawler.faculty_crawler").info(
                "Opening https://user:pass@example.edu/faculty?token=TOPSECRET output=%s",
                output_dir / "faculty.xlsx",
            )
            log_path = session.log_path
            session.close()
            text = log_path.read_text(encoding="utf-8")

        self.assertNotIn("DO-NOT-CAPTURE", text)
        self.assertNotIn("TOPSECRET", text)
        self.assertNotIn("user:pass", text)
        self.assertNotIn(temp_dir, text)
        self.assertIn("example.edu", text)


if __name__ == "__main__":
    unittest.main()
