from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crawler.models import PageAssessment, PageKind, RecommendedAction, TaskStatus
from crawler.session_store import SessionProtectionError, SessionStore
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import (
    VerificationItem,
    VerificationQueue,
    VerificationReason,
    VerificationService,
    parse_storage_state,
    scope_storage_state,
)


class VerificationQueueTests(unittest.TestCase):
    def test_concurrent_resume_claim_has_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            queue = VerificationQueue(path)
            item = queue.enqueue(self._item("task-claim"))
            queue.mark_ready(item.run_id, item.task_id)
            queues = (VerificationQueue(path), VerificationQueue(path))
            barrier = threading.Barrier(2)
            results = []

            def claim(candidate):
                barrier.wait(timeout=5)
                try:
                    results.append(candidate.begin_resume(item.run_id, item.task_id))
                except ValueError:
                    results.append("lost")

            threads = [threading.Thread(target=claim, args=(candidate,)) for candidate in queues]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sum(result == "lost" for result in results), 1)
        self.assertEqual(
            sum(
                isinstance(result, VerificationItem)
                and result.status is TaskStatus.FETCHING
                for result in results
            ),
            1,
        )

    def test_resume_rechallenge_complete_and_failed_retry_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            item = queue.enqueue(self._item("task-resume"))
            queue.mark_ready(item.run_id, item.task_id)
            claimed = queue.begin_resume(item.run_id, item.task_id)
            rechallenged = queue.enqueue(self._item("task-resume"))
            queue.mark_ready(item.run_id, item.task_id)
            queue.begin_resume(item.run_id, item.task_id)
            queue.complete_resume(item.run_id, item.task_id)

            failed = queue.enqueue(self._item("task-failed"))
            for _ in range(3):
                failed = queue.defer(failed.run_id, failed.task_id)
            retried = queue.retry_failed(failed.run_id, failed.task_id)
            remaining = queue.items()

        self.assertEqual(claimed.status, TaskStatus.FETCHING)
        self.assertEqual(rechallenged.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(
            remaining,
            [retried],
        )
        self.assertEqual(failed.status, TaskStatus.FAILED)
        self.assertEqual(failed.attempts, 3)
        self.assertEqual(retried.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(retried.attempts, 0)

    def test_enqueue_survives_repository_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            queue = VerificationQueue(path)
            queue.enqueue(
                VerificationItem(
                    "run-1",
                    "task-1",
                    "https://example.edu",
                    "example.edu",
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )
            loaded = VerificationQueue(path).pending()

        self.assertEqual([item.task_id for item in loaded], ["task-1"])
        self.assertEqual(loaded[0].status, TaskStatus.VERIFICATION_REQUIRED)

    def test_duplicate_task_id_updates_instead_of_duplicating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            first = VerificationItem(
                "run-1",
                "task-1",
                "https://example.edu",
                "example.edu",
                "2026-07-22T10:00:00Z",
                "challenge",
            )
            second = VerificationItem(
                "run-1",
                "task-1",
                "https://example.edu",
                "example.edu",
                "2026-07-22T10:01:00Z",
                "login",
            )
            queue.enqueue(first)
            queue.enqueue(second)
            loaded = queue.pending()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].reason, "login")
        self.assertEqual(loaded[0].detected_at, "2026-07-22T10:01:00Z")

    def test_enqueue_persists_only_origin_and_typed_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            queue = VerificationQueue(path)
            queue.enqueue(
                VerificationItem(
                    "run-1",
                    "task-privacy",
                    "https://user:password@example.edu:443/session/PATH-SECRET"
                    "?q=ALLOWLIST-SECRET&search=PRIVATE-SEARCH&token=URL-SECRET"
                    "#private-fragment",
                    "example.edu",
                    "2026-07-22T10:00:00Z",
                    "Challenge response body: PRIVATE-BODY-BYTES "
                    "session=SESSION-SECRET <html>PRIVATE BODY</html>",
                )
            )
            raw = path.read_text(encoding="utf-8")
            item = queue.pending()[0]

        for private_value in (
            "user",
            "password",
            "session",
            "PATH-SECRET",
            "ALLOWLIST-SECRET",
            "PRIVATE-SEARCH",
            "URL-SECRET",
            "private-fragment",
            "PRIVATE-BODY-BYTES",
            "SESSION-SECRET",
            "PRIVATE BODY",
        ):
            self.assertNotIn(private_value, raw)
        self.assertEqual(item.url, "https://example.edu")
        self.assertEqual(item.reason, VerificationReason.CHALLENGE)

    def test_display_origin_keeps_only_non_default_port(self) -> None:
        item = VerificationItem(
            "run-1",
            "task-port",
            "http://example.edu:8080/private?q=secret",
            "example.edu",
            "2026-07-22T10:00:00Z",
            "unknown private diagnostic bytes",
        )

        self.assertEqual(item.url, "http://example.edu:8080")
        self.assertEqual(item.reason, VerificationReason.VERIFICATION_REQUIRED)

    def test_state_transitions_preserve_items_and_count_deferrals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            queue.enqueue(self._item("task-ready"))
            queue.enqueue(self._item("task-deferred"))
            queue.enqueue(self._item("task-failed"))

            ready = queue.mark_ready("run-1", "task-ready")
            deferred = queue.defer("run-1", "task-deferred")
            failed = queue.mark_failed("run-1", "task-failed")
            reloaded = VerificationQueue(queue.path)
            pending_ids = [item.task_id for item in reloaded.pending()]
            persisted_count = len(
                json.loads(queue.path.read_text(encoding="utf-8"))["items"]
            )

        self.assertEqual(ready.status, TaskStatus.READY_TO_RESUME)
        self.assertEqual(ready.attempts, 0)
        self.assertEqual(deferred.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(deferred.attempts, 1)
        self.assertEqual(failed.status, TaskStatus.FAILED)
        self.assertEqual(pending_ids, ["task-deferred"])
        self.assertEqual(persisted_count, 3)

    def test_unknown_task_and_illegal_transition_do_not_change_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            queue.enqueue(self._item("task-1"))
            with self.assertRaises(KeyError) as missing:
                queue.mark_ready("run-1", "missing-token-secret")
            self.assertNotIn("missing-token-secret", str(missing.exception))
            queue.mark_ready("run-1", "task-1")
            before = queue.path.read_bytes()
            with self.assertRaises(ValueError) as illegal:
                queue.defer("run-1", "task-1")
            self.assertNotIn("task-1", str(illegal.exception))
            after = queue.path.read_bytes()

        self.assertEqual(after, before)

    def test_invalid_item_fields_are_rejected_without_writing(self) -> None:
        invalid = (
            {"task_id": "../escape"},
            {"hostname": "other.edu"},
            {"detected_at": "not-a-time"},
            {"attempts": -1},
            {"status": "unknown"},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            for overrides in invalid:
                with self.subTest(overrides=overrides), self.assertRaises(
                    (TypeError, ValueError)
                ):
                    VerificationQueue(path).enqueue(
                        VerificationItem(
                            **{
                                "task_id": "task-1",
                                "run_id": "run-1",
                                "url": "https://example.edu/faculty",
                                "hostname": "example.edu",
                                "detected_at": "2026-07-22T10:00:00Z",
                                "reason": "challenge",
                                **overrides,
                            }
                        )
                    )
            self.assertFalse(path.exists())

    def test_corrupt_json_schema_and_items_fail_without_overwriting(self) -> None:
        payloads = (
            "not-json",
            json.dumps({"schema_version": 3, "items": []}),
            json.dumps({"schema_version": 2, "items": {}}),
            json.dumps(
                {
                    "schema_version": 2,
                    "items": [
                        {
                            "run_id": "run-1",
                            "task_id": "task-1",
                            "url": "https://example.edu",
                            "hostname": "example.edu",
                            "detected_at": "bad-time",
                            "reason": "challenge",
                            "attempts": 0,
                            "status": "verification_required",
                        }
                    ],
                }
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            for raw in payloads:
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        VerificationQueue(path).pending()
                    self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_extra_fields_and_duplicate_persisted_ids_are_rejected(self) -> None:
        item = {
            "run_id": "run-1",
            "task_id": "task-1",
            "url": "https://example.edu",
            "hostname": "example.edu",
            "detected_at": "2026-07-22T10:00:00Z",
            "reason": "challenge",
            "attempts": 0,
            "status": "verification_required",
        }
        payloads = (
            {"schema_version": 2, "items": [{**item, "private_body": "SECRET"}]},
            {"schema_version": 2, "items": [item, item]},
            {
                "schema_version": 2,
                "items": [
                    {
                        **item,
                        "url": "https://example.edu/session/SECRET?q=PRIVATE",
                    }
                ],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            for payload in payloads:
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    before = path.read_bytes()
                    with self.assertRaises(ValueError):
                        VerificationQueue(path).pending()
                    self.assertEqual(path.read_bytes(), before)

    def test_v1_queue_is_rejected_with_controlled_cleanup_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            raw = json.dumps({"schema_version": 1, "items": []})
            path.write_text(raw, encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "unsupported verification queue schema; clear queue manually",
            ):
                VerificationQueue(path).pending()

            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_write_flushes_before_atomic_replace_and_cleans_failed_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            queue = VerificationQueue(root / "queue.json")
            events: list[str] = []
            original_replace = os.replace
            with (
                patch(
                    "crawler.verification.os.fsync",
                    side_effect=lambda _: events.append("fsync"),
                ),
                patch(
                    "crawler.verification.os.replace",
                    side_effect=lambda source, target: (
                        events.append("replace"),
                        original_replace(source, target),
                    )[1],
                ),
            ):
                queue.enqueue(self._item("task-atomic"))

            committed = queue.path.read_bytes()
            with patch(
                "crawler.verification.os.replace", side_effect=OSError("disk error")
            ):
                with self.assertRaises(OSError):
                    queue.enqueue(self._item("task-failed-write"))
            after_failure = queue.path.read_bytes()
            temporary_files = list(root.glob("*.tmp"))

        self.assertEqual(events, ["fsync", "replace"])
        self.assertEqual(after_failure, committed)
        self.assertEqual(temporary_files, [])

    def test_two_instances_concurrently_enqueue_without_losing_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queue.json"
            queues = (VerificationQueue(path), VerificationQueue(path))
            barrier = threading.Barrier(2)
            errors: list[Exception] = []

            def enqueue(queue: VerificationQueue, task_id: str) -> None:
                try:
                    barrier.wait(timeout=5)
                    queue.enqueue(self._item(task_id))
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=enqueue, args=(queues[0], "task-1")),
                threading.Thread(target=enqueue, args=(queues[1], "task-2")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            loaded = VerificationQueue(path).pending()

        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual({item.task_id for item in loaded}, {"task-1", "task-2"})

    @unittest.skipUnless(os.name == "nt", "Windows named mutex regression")
    def test_two_os_processes_enqueue_without_losing_items(self) -> None:
        worker = """
import sys
import time
from pathlib import Path
from crawler.verification import VerificationItem, VerificationQueue

path = Path(sys.argv[1])
gate = Path(sys.argv[2])
prefix = sys.argv[3]
while not gate.exists():
    time.sleep(0.005)
queue = VerificationQueue(path)
for index in range(20):
    queue.enqueue(VerificationItem(
        prefix,
        f"{prefix}-{index}",
        "https://example.edu/private?q=secret",
        "example.edu",
        "2026-07-22T10:00:00Z",
        "challenge",
    ))
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "queue.json"
            gate = root / "start"
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", worker, str(path), str(gate), prefix],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for prefix in ("first", "second")
            ]
            gate.touch()
            results = [process.communicate(timeout=15) for process in processes]
            return_codes = [process.returncode for process in processes]
            loaded = VerificationQueue(path).pending()

        self.assertEqual(return_codes, [0, 0], results)
        self.assertEqual(results, [("", ""), ("", "")])
        self.assertEqual(len(loaded), 40)
        self.assertEqual(
            {item.task_id for item in loaded},
            {
                f"{prefix}-{index}"
                for prefix in ("first", "second")
                for index in range(20)
            },
        )

    @staticmethod
    def _item(task_id: str, run_id: str = "run-1") -> VerificationItem:
        return VerificationItem(
            run_id,
            task_id,
            "https://example.edu/faculty",
            "example.edu",
            "2026-07-22T10:00:00Z",
            "challenge",
        )

    def test_same_task_id_in_different_runs_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            queue.enqueue(self._item("shared-task", "run-1"))
            queue.enqueue(self._item("shared-task", "run-2"))
            loaded = queue.pending()

        self.assertEqual(
            {(item.run_id, item.task_id) for item in loaded},
            {("run-1", "shared-task"), ("run-2", "shared-task")},
        )

    def test_enqueue_rejects_terminal_status_and_terminal_redetection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            for status in (TaskStatus.READY_TO_RESUME, TaskStatus.FAILED):
                with self.subTest(status=status), self.assertRaises(ValueError):
                    queue.enqueue(
                        VerificationItem(
                            "run-terminal",
                            f"task-{status.value}",
                            "https://example.edu/private",
                            "example.edu",
                            "2026-07-22T10:00:00Z",
                            "challenge",
                            status=status,
                        )
                    )

            queue.enqueue(self._item("task-done", "run-terminal"))
            queue.mark_failed("run-terminal", "task-done")
            before = queue.path.read_bytes()
            with self.assertRaises(ValueError):
                queue.enqueue(self._item("task-done", "run-terminal"))
            after = queue.path.read_bytes()

        self.assertEqual(after, before)

    def test_idna_terminal_dot_and_ipv6_origins_are_canonical(self) -> None:
        cases = (
            (
                "https://faß.de/private",
                "faß.de",
                "https://xn--fa-hia.de",
                "xn--fa-hia.de",
            ),
            (
                "https://Example.EDU./private",
                "Example.EDU.",
                "https://example.edu.",
                "example.edu.",
            ),
            (
                "https://[2001:0db8:0:0:0:0:0:1]:8443/private",
                "2001:0db8:0:0:0:0:0:1",
                "https://[2001:db8::1]:8443",
                "2001:db8::1",
            ),
        )
        for source, hostname, expected_url, expected_hostname in cases:
            with self.subTest(source=source):
                item = VerificationItem(
                    "run-origin",
                    "task-origin",
                    source,
                    hostname,
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
                self.assertEqual(item.url, expected_url)
                self.assertEqual(item.hostname, expected_hostname)


class VerificationServiceTests(unittest.TestCase):
    def test_incomplete_verification_defers_then_fails_at_max_attempts(self) -> None:
        service = VerificationService(
            url_resolver=lambda _run, _task: "https://example.edu/faculty",
            queue=self.queue,
            browser_runner=lambda *_args: (
                False,
                None,
                PageAssessment(
                    PageKind.HUMAN_VERIFICATION,
                    RecommendedAction.QUEUE_VERIFICATION,
                ),
            ),
        )

        results = [
            service.verify(
                self.item,
                completion_event=threading.Event(),
                cancel_event=threading.Event(),
            )
            for _ in range(3)
        ]
        persisted = VerificationQueue(self.queue.path).items()[0]

        self.assertEqual(
            [result.status for result in results],
            [
                TaskStatus.VERIFICATION_REQUIRED,
                TaskStatus.VERIFICATION_REQUIRED,
                TaskStatus.FAILED,
            ],
        )
        self.assertEqual(persisted.status, TaskStatus.FAILED)
        self.assertEqual(persisted.attempts, 3)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.queue = VerificationQueue(root / "queue.json")
        self.task_store = TaskStore(root / "tasks")
        self.original_url = "https://example.edu/private/directory?source=resume"
        self.task_store.save(
            StoredRun(
                "run-service",
                [
                    StoredTask(
                        "task-service",
                        self.original_url,
                        "faculty.xlsx",
                        TaskStatus.VERIFICATION_REQUIRED,
                    )
                ],
            )
        )
        self.item = self.queue.enqueue(
            VerificationItem(
                "run-service",
                "task-service",
                self.original_url,
                "example.edu",
                "2026-07-22T10:00:00Z",
                "challenge",
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_verified_directory_uses_authoritative_url_and_saves_before_ready(self) -> None:
        calls: list[tuple[str, object]] = []

        class Store:
            def load(self, hostname: str):
                calls.append(("load", hostname))
                return None

            def save(self, hostname: str, state: bytes):
                calls.append(("save", hostname))

        original_mark_ready = self.queue.mark_ready

        def mark_ready(run_id: str, task_id: str):
            calls.append(("ready", (run_id, task_id)))
            return original_mark_ready(run_id, task_id)

        self.queue.mark_ready = mark_ready
        captured_urls: list[str] = []
        service = VerificationService(
            task_store=self.task_store,
            queue=self.queue,
            session_store=Store(),
            browser_runner=lambda url, done, cancel, state: (
                captured_urls.append(url),
                (True, b'{"cookies":[],"origins":[]}'),
            )[1],
        )

        result = service.verify(
            self.item,
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(captured_urls, [self.original_url])
        self.assertEqual(result.status, TaskStatus.READY_TO_RESUME)
        self.assertEqual(result.assessment.kind, PageKind.DIRECTORY)
        self.assertEqual([call[0] for call in calls], ["load", "save", "ready"])

    def test_cancel_close_and_incomplete_count_attempts_until_failed(self) -> None:
        for attempt, (runner_result, cancelled) in enumerate((
            ((False, None), False),
            ((False, None), True),
            ((True, None), False),
        ), start=1):
            with self.subTest(runner_result=runner_result, cancelled=cancelled):
                cancel = threading.Event()
                if cancelled:
                    cancel.set()
                service = VerificationService(
                    task_store=self.task_store,
                    queue=self.queue,
                    browser_runner=lambda *_args, value=runner_result: value,
                )
                result = service.verify(
                    self.item,
                    completion_event=threading.Event(),
                    cancel_event=cancel,
                )
                expected = (
                    TaskStatus.FAILED
                    if attempt == 3
                    else TaskStatus.VERIFICATION_REQUIRED
                )
                self.assertEqual(result.status, expected)
                persisted = self.queue.items()[0]
                self.assertEqual(persisted.attempts, attempt)
                self.assertEqual(persisted.status, expected)

    def test_save_failure_does_not_mark_ready_or_log_state(self) -> None:
        state = b'{"cookies":[],"origins":[]}'

        class Store:
            def load(self, hostname: str):
                return None

            def save(self, hostname: str, value: bytes):
                raise OSError("disk unavailable")

        service = VerificationService(
            task_store=self.task_store,
            queue=self.queue,
            session_store=Store(),
            browser_runner=lambda *_args: (True, state),
        )
        with self.assertLogs("crawler.verification", level="INFO") as captured:
            result = service.verify(
                self.item,
                completion_event=threading.Event(),
                cancel_event=threading.Event(),
            )

        self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(self.queue.pending()[0].attempts, 1)
        self.assertNotIn(state.decode(), "\n".join(captured.output))

    def test_idn_is_saved_under_alabel_and_ipv6_skips_store(self) -> None:
        calls: list[tuple[str, str]] = []

        class Store:
            def load(self, hostname: str):
                calls.append(("load", hostname))
                return None

            def save(self, hostname: str, _value: bytes):
                calls.append(("save", hostname))

        for run_id, task_id, url, hostname, expected in (
            (
                "run-idn",
                "task-idn",
                "https://fa\u00df.de/private",
                "fa\u00df.de",
                TaskStatus.READY_TO_RESUME,
            ),
            (
                "run-ipv6",
                "task-ipv6",
                "https://[2001:db8::1]/private",
                "2001:db8::1",
                TaskStatus.VERIFICATION_REQUIRED,
            ),
        ):
            self.task_store.save(
                StoredRun(
                    run_id,
                    [StoredTask(task_id, url, "out.xlsx", TaskStatus.VERIFICATION_REQUIRED)],
                )
            )
            item = self.queue.enqueue(
                VerificationItem(
                    run_id,
                    task_id,
                    url,
                    hostname,
                    "2026-07-22T10:00:00Z",
                    "challenge",
                )
            )
            result = VerificationService(
                task_store=self.task_store,
                queue=self.queue,
                session_store=Store(),
                browser_runner=lambda *_args: (True, b'{"cookies":[]}'),
            ).verify(
                item,
                completion_event=threading.Event(),
                cancel_event=threading.Event(),
            )
            self.assertEqual(result.status, expected)

        self.assertIn(("save", "xn--fa-hia.de"), calls)
        self.assertFalse(any(host == "2001:db8::1" for _, host in calls))

    def test_default_runner_launches_visible_and_stops_after_completion(self) -> None:
        completion = threading.Event()
        completion.set()
        launch_options: list[dict[str, object]] = []

        class Page:
            url = self.original_url

            def goto(self, url: str, **_kwargs):
                self.url = url

            def title(self):
                return "Faculty directory"

            def locator(self, selector: str):
                if selector == "body":
                    return SimpleNamespace(evaluate=lambda _script: "Faculty directory")
                return SimpleNamespace(count=lambda: 2)

            def is_closed(self):
                return False

        class Context:
            def new_page(self):
                return Page()

            def storage_state(self):
                return {"cookies": [], "origins": []}

            def close(self):
                pass

        class Browser:
            def new_context(self, **_kwargs):
                return Context()

            def close(self):
                pass

        class Chromium:
            def launch(self, **kwargs):
                launch_options.append(kwargs)
                return Browser()

        class Playwright:
            chromium = Chromium()

        class Manager:
            def __enter__(self):
                return Playwright()

            def __exit__(self, *_args):
                return None

        service = VerificationService(
            task_store=self.task_store,
            playwright_factory=lambda: Manager(),
            wait=lambda _event, _seconds: False,
            clock=iter((0.0, 0.0, 0.1)).__next__,
        )
        result = service.verify(
            self.item,
            completion_event=completion,
            cancel_event=threading.Event(),
        )

        self.assertEqual(launch_options, [{"headless": False}])
        self.assertEqual(result.status, TaskStatus.READY_TO_RESUME)

    def test_terminal_dot_scope_remains_security_distinct(self) -> None:
        scoped = scope_storage_state(
            json.dumps(
                {
                    "cookies": [
                        self._cookie("dotted", "example.edu."),
                        self._cookie("plain", "example.edu"),
                    ],
                    "origins": [
                        {"origin": "https://example.edu.", "localStorage": []},
                        {"origin": "https://example.edu", "localStorage": []},
                    ],
                }
            ).encode(),
            "example.edu.",
        )

        self.assertEqual([cookie["name"] for cookie in scoped["cookies"]], ["dotted"])
        self.assertEqual(
            [origin["origin"] for origin in scoped["origins"]],
            ["https://example.edu."],
        )

    def test_storage_json_rejects_non_finite_constants_and_expiry(self) -> None:
        payloads = (
            b'{"cookies":[],"origins":[],"extra":NaN}',
            b'{"cookies":[{"name":"n","value":"v","domain":"example.edu","path":"/","expires":Infinity}]}',
            b'{"cookies":[{"name":"n","value":"v","domain":"example.edu","path":"/","expires":1e999}]}',
        )

        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_storage_state(payload)

    def test_partitioned_cookies_are_limited_to_exact_canonical_site(self) -> None:
        cookies = []
        for name, partition_key in (
            ("exact", "https://example.edu"),
            ("idn", "https://fa\u00df.de"),
            ("parent", "https://parent.edu"),
            ("sibling", "https://login.example.edu"),
            ("invalid", "not a site"),
        ):
            domain = "xn--fa-hia.de" if name == "idn" else "example.edu"
            cookies.append(
                {
                    **self._cookie(name, domain),
                    "partitionKey": partition_key,
                }
            )

        example = scope_storage_state(
            json.dumps({"cookies": cookies, "origins": []}).encode(),
            "example.edu",
        )
        idn = scope_storage_state(
            json.dumps({"cookies": cookies, "origins": []}).encode(),
            "xn--fa-hia.de",
        )

        self.assertEqual([cookie["name"] for cookie in example["cookies"]], ["exact"])
        self.assertEqual([cookie["name"] for cookie in idn["cookies"]], ["idn"])

    def test_saved_state_is_filtered_to_exact_hostname_before_queue_ready(self) -> None:
        class Protector:
            def protect(self, data: bytes) -> bytes:
                return data[::-1]

            def unprotect(self, data: bytes) -> bytes:
                return data[::-1]

        root = Path(self.temporary.name)
        store = SessionStore(root / "sessions", Protector())
        state = json.dumps(
            {
                "cookies": [
                    self._cookie("exact", "example.edu"),
                    self._cookie("parent", ".example.edu"),
                    self._cookie("other", "other.edu"),
                ],
                "origins": [
                    {"origin": "https://example.edu", "localStorage": []},
                    {"origin": "https://login.example.edu", "localStorage": []},
                    {"origin": "https://sso.edu", "localStorage": []},
                ],
            }
        ).encode()
        result = VerificationService(
            task_store=self.task_store,
            queue=self.queue,
            session_store=store,
            browser_runner=lambda *_args: (True, state),
        ).verify(
            self.item,
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )
        saved = json.loads(store.load("example.edu"))

        self.assertEqual(result.status, TaskStatus.READY_TO_RESUME)
        self.assertEqual([cookie["name"] for cookie in saved["cookies"]], ["exact"])
        self.assertEqual(
            [origin["origin"] for origin in saved["origins"]],
            ["https://example.edu"],
        )

    def test_persistent_dns_queue_requires_session_store_before_ready(self) -> None:
        result = VerificationService(
            task_store=self.task_store,
            queue=self.queue,
            browser_runner=lambda *_args: (True, b'{"cookies":[]}'),
        ).verify(
            self.item,
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(
            next(
                queued
                for queued in VerificationQueue(self.queue.path).pending()
                if queued.task_id == self.item.task_id
            ).attempts,
            1,
        )

    def test_ipv6_queue_stays_pending_without_reusable_session_store(self) -> None:
        self.task_store.save(
            StoredRun(
                "run-ipv6-gate",
                [
                    StoredTask(
                        "task-ipv6-gate",
                        "https://[2001:db8::1]/private",
                        "out.xlsx",
                        TaskStatus.VERIFICATION_REQUIRED,
                    )
                ],
            )
        )
        item = self.queue.enqueue(
            VerificationItem(
                "run-ipv6-gate",
                "task-ipv6-gate",
                "https://[2001:db8::1]/private",
                "2001:db8::1",
                "2026-07-22T10:00:00Z",
                "challenge",
            )
        )

        result = VerificationService(
            task_store=self.task_store,
            queue=self.queue,
            browser_runner=lambda *_args: (True, b'{"cookies":[]}'),
        ).verify(
            item,
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(
            next(
                queued
                for queued in VerificationQueue(self.queue.path).pending()
                if queued.task_id == item.task_id
            ).attempts,
            1,
        )

    def test_corrupt_loaded_state_is_cleared_but_temporary_error_is_preserved(self) -> None:
        for load_result, expected_clears in (
            (b"not-json-private", ["example.edu"]),
            (SessionProtectionError("temporary"), []),
        ):
            with self.subTest(load_result=type(load_result).__name__):
                cleared: list[str] = []

                class Store:
                    def load(self, hostname: str):
                        if isinstance(load_result, Exception):
                            raise load_result
                        return load_result

                    def clear_site(self, hostname: str):
                        cleared.append(hostname)

                    def save(self, hostname: str, state: bytes):
                        pass

                received_states: list[object] = []
                service = VerificationService(
                    task_store=self.task_store,
                    session_store=Store(),
                    browser_runner=lambda _url, _done, _cancel, state: (
                        received_states.append(state),
                        (False, None),
                    )[1],
                )
                service.verify(
                    self.item,
                    completion_event=threading.Event(),
                    cancel_event=threading.Event(),
                )

                self.assertEqual(cleared, expected_clears)
                self.assertEqual(received_states, [None])

    def test_challenge_or_login_with_misleading_candidates_stays_pending(self) -> None:
        for visible_text in (
            "Verify you are human Faculty profile",
            "Sign in to continue Faculty profile",
        ):
            with self.subTest(visible_text=visible_text):
                service = VerificationService(
                    task_store=self.task_store,
                    playwright_factory=self._page_factory(
                        text=visible_text,
                        candidate_count=4,
                    ),
                    wait=lambda _event, _seconds: False,
                    clock=iter((0.0, 0.0, 0.1)).__next__,
                )
                done = threading.Event()
                done.set()
                result = service.verify(
                    self.item,
                    completion_event=done,
                    cancel_event=threading.Event(),
                )

                self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)

    def test_profile_href_candidates_can_complete_verification(self) -> None:
        service = VerificationService(
            task_store=self.task_store,
            playwright_factory=self._page_factory(
                text="Faculty directory",
                candidate_count=2,
            ),
            wait=lambda _event, _seconds: False,
            clock=iter((0.0, 0.0, 0.1)).__next__,
        )
        done = threading.Event()
        done.set()

        result = service.verify(
            self.item,
            completion_event=done,
            cancel_event=threading.Event(),
        )

        self.assertEqual(result.status, TaskStatus.READY_TO_RESUME)

    def test_safe_directory_redirect_completes_before_user_signal(self) -> None:
        service = VerificationService(
            task_store=self.task_store,
            playwright_factory=self._page_factory(
                text="Faculty directory",
                candidate_count=2,
            ),
            wait=lambda _event, _seconds: False,
            clock=iter((0.0, 0.0, 0.1)).__next__,
        )

        result = service.verify(
            self.item,
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(result.status, TaskStatus.READY_TO_RESUME)

    def test_runner_attempts_browser_close_after_context_close_failure(self) -> None:
        closed: list[str] = []

        def close_context():
            closed.append("context")
            raise RuntimeError("private context bytes")

        service = VerificationService(
            task_store=self.task_store,
            playwright_factory=self._page_factory(
                text="Faculty directory",
                candidate_count=2,
                context_close=close_context,
                browser_close=lambda: closed.append("browser"),
            ),
            wait=lambda _event, _seconds: False,
            clock=iter((0.0, 0.0, 0.1)).__next__,
        )
        done = threading.Event()
        done.set()
        with self.assertLogs("crawler.verification", level="ERROR") as captured:
            result = service.verify(
                self.item,
                completion_event=done,
                cancel_event=threading.Event(),
            )

        self.assertEqual(closed, ["context", "browser"])
        self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertNotIn("private context bytes", "\n".join(captured.output))

    def test_runner_closes_browser_when_context_creation_fails(self) -> None:
        closed: list[str] = []
        service = VerificationService(
            task_store=self.task_store,
            playwright_factory=self._page_factory(
                text="",
                candidate_count=0,
                context_error=RuntimeError("private state error"),
                browser_close=lambda: closed.append("browser"),
            ),
        )

        result = service.verify(
            self.item,
            completion_event=threading.Event(),
            cancel_event=threading.Event(),
        )

        self.assertEqual(closed, ["browser"])
        self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)

    @staticmethod
    def _cookie(name: str, domain: str) -> dict[str, object]:
        return {"name": name, "value": "value", "domain": domain, "path": "/"}

    def _page_factory(
        self,
        *,
        text: str,
        candidate_count: int,
        context_close=None,
        browser_close=None,
        context_error: Exception | None = None,
    ):
        original_url = self.original_url

        class Page:
            url = original_url

            def goto(self, url: str, **_kwargs):
                self.url = url

            def title(self):
                return "Directory"

            def locator(self, selector: str):
                if selector == "body":
                    return SimpleNamespace(evaluate=lambda _script: text)
                return SimpleNamespace(count=lambda: candidate_count)

            def is_closed(self):
                return False

        class Context:
            def new_page(self):
                return Page()

            def storage_state(self):
                return {"cookies": [], "origins": []}

            def close(self):
                if context_close:
                    context_close()

        class Browser:
            def new_context(self, **_kwargs):
                if context_error:
                    raise context_error
                return Context()

            def close(self):
                if browser_close:
                    browser_close()

        class Chromium:
            def launch(self, **_kwargs):
                return Browser()

        class Playwright:
            chromium = Chromium()

        class Manager:
            def __enter__(self):
                return Playwright()

            def __exit__(self, *_args):
                pass

        return lambda: Manager()


if __name__ == "__main__":
    unittest.main()
