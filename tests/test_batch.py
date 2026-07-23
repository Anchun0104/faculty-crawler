from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from unittest.mock import patch

from crawler.batch import (
    CrawlTask,
    prepare_tasks,
    rename_task_output,
    run_tasks,
    safe_exception_message,
    safe_url_for_log,
)
from crawler.diagnostics import DiagnosticEvent
from crawler.models import CrawlOutcome, TaskStatus
from crawler.parsers import FacultyRecord
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import (
    VerificationItem,
    VerificationQueue,
    VerificationReason,
)


class BatchPreparationTests(unittest.TestCase):
    def test_prepare_tasks_ignores_blanks_reports_invalid_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = prepare_tasks(
                "\nhttps://www.example.edu/faculty/\nnot-a-url\n"
                "https://www.example.edu/faculty/#people\nhttps://law.example.edu/staff\n",
                Path(temp_dir),
            )

        self.assertEqual(
            [task.url for task in result.tasks],
            ["https://www.example.edu/faculty/", "https://law.example.edu/staff"],
        )
        self.assertEqual(result.invalid_urls, ["not-a-url"])
        self.assertEqual(result.duplicate_urls, ["https://www.example.edu/faculty/#people"])

    def test_prepare_tasks_creates_legal_unique_excel_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = prepare_tasks(
                "https://example.edu/people?group=law\n"
                "https://example.edu/people?group=sociology\n"
                "https://bad.example.edu/a%3Ab%2Ac",
                Path(temp_dir),
            )

        names = [task.output_path.name for task in result.tasks]
        self.assertEqual(names[0], "example.edu_people.xlsx")
        self.assertEqual(names[1], "example.edu_people_2.xlsx")
        self.assertEqual(names[2], "bad.example.edu_a_b_c.xlsx")
        self.assertTrue(all(not set('<>:"/\\|?*') & set(name) for name in names))

    def test_rename_task_output_adds_extension_sanitizes_and_avoids_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = prepare_tasks(
                "https://one.example.edu/faculty\nhttps://two.example.edu/faculty",
                Path(temp_dir),
            )
            first_name = rename_task_output(result.tasks, 0, "Law: Faculty")
            second_name = rename_task_output(result.tasks, 1, "law: faculty.xlsx")

        self.assertEqual(first_name, "Law_ Faculty.xlsx")
        self.assertEqual(second_name, "law_ faculty_2.xlsx")
        self.assertEqual(result.tasks[1].output_path.name, "law_ faculty_2.xlsx")

    def test_prepare_tasks_does_not_overwrite_existing_excel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "example.edu_people.xlsx").touch()

            result = prepare_tasks("https://example.edu/people", output_dir)

        self.assertEqual(result.tasks[0].output_path.name, "example.edu_people_2.xlsx")


class BatchRunnerTests(unittest.TestCase):
    def test_persistent_status_survives_failing_update_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = CrawlTask("https://example.edu/faculty", root / "faculty.xlsx")
            store = TaskStore(root / "tasks")
            store.save(
                StoredRun(
                    "run-persist",
                    [
                        StoredTask(
                            "task-persist",
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )

            class Crawler:
                def __init__(self, _timeout):
                    persisted = store.load("run-persist").tasks[0]
                    self.seen_status = persisted.status

                def crawl_outcome(self, _url):
                    return CrawlOutcome(
                        TaskStatus.SUCCEEDED,
                        (FacultyRecord("Ada", "Professor", "profile"),),
                    )

            callbacks = []

            def failing_update(_index, updated):
                callbacks.append(updated.status)
                raise RuntimeError("SECRET callback")

            run_tasks(
                [task],
                crawler_factory=Crawler,
                exporter=lambda _records, _path: None,
                task_store=store,
                run_id="run-persist",
                task_ids=["task-persist"],
                on_update=failing_update,
            )
            saved = store.load("run-persist").tasks[0]

        self.assertEqual(callbacks, ["running", "succeeded"])
        self.assertEqual(saved.status, TaskStatus.SUCCEEDED)
        self.assertEqual(saved.record_count, 1)
        self.assertEqual(saved.error, "")

    def test_verification_required_task_is_queued_and_does_not_stop_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tasks = [
                CrawlTask("https://one.edu", root / "one.xlsx"),
                CrawlTask(
                    "https://user:password@verify.edu/faculty?token=SECRET#body",
                    root / "verify.xlsx",
                ),
                CrawlTask("https://two.edu", root / "two.xlsx"),
            ]
            outcomes = iter(
                [
                    CrawlOutcome(
                        TaskStatus.SUCCEEDED,
                        (FacultyRecord("Ada", "Professor", "https://one.edu/ada"),),
                    ),
                    CrawlOutcome(
                        TaskStatus.VERIFICATION_REQUIRED,
                        diagnostics={"Failure reason": "Cookie: COOKIE-SECRET"},
                    ),
                    CrawlOutcome(
                        TaskStatus.SUCCEEDED,
                        (FacultyRecord("Grace", "Professor", "https://two.edu/grace"),),
                    ),
                ]
            )
            queue = VerificationQueue(root / "queue.json")
            task_store = TaskStore(root / "tasks")
            task_store.save(
                StoredRun(
                    "run-fixed",
                    [
                        StoredTask(
                            task_id,
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                        for task_id, task in zip(
                            ("task-1", "task-verify", "task-2"),
                            tasks,
                            strict=True,
                        )
                    ],
                )
            )
            verification_notifications: list[VerificationItem] = []
            events: list[DiagnosticEvent] = []
            exported: list[str] = []

            class FakeOutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return next(outcomes)

            run_tasks(
                tasks,
                crawler_factory=FakeOutcomeCrawler,
                exporter=lambda records, path: exported.append(Path(path).name),
                on_diagnostic=events.append,
                verification_queue=queue,
                task_store=task_store,
                on_verification=verification_notifications.append,
                run_id="run-fixed",
                task_ids=["task-1", "task-verify", "task-2"],
            )
            queued = queue.pending("run-fixed")
            raw_queue = queue.path.read_text(encoding="utf-8")
            resolved_original = task_store.resolve_original_url(
                queued[0].run_id,
                queued[0].task_id,
            )

        self.assertEqual(
            [task.status for task in tasks],
            ["succeeded", "verification_required", "succeeded"],
        )
        self.assertEqual(exported, ["one.xlsx", "two.xlsx"])
        self.assertEqual([item.task_id for item in queued], ["task-verify"])
        self.assertEqual(queued[0].run_id, "run-fixed")
        self.assertEqual(verification_notifications, queued)
        self.assertEqual(queued[0].hostname, "verify.edu")
        self.assertEqual(queued[0].url, "https://verify.edu")
        self.assertEqual(queued[0].reason, VerificationReason.VERIFICATION_REQUIRED)
        self.assertIn("user:password@", resolved_original)
        self.assertIn("token=SECRET", resolved_original)
        self.assertNotIn("password", raw_queue)
        self.assertNotIn("SECRET", raw_queue)
        self.assertNotIn("COOKIE-SECRET", raw_queue)
        self.assertEqual(
            [event.category for event in events],
            ["succeeded", "verification_required", "succeeded"],
        )

    def test_persistent_queue_requires_stable_task_store_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            queue = VerificationQueue(root / "queue.json")
            task_store = TaskStore(root / "tasks")
            task = CrawlTask("https://verify.edu/private", root / "verify.xlsx")
            task_store.save(
                StoredRun(
                    "run-fixed",
                    [
                        StoredTask(
                            "task-verify",
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )

            cases = (
                {"task_ids": ["task-verify"], "task_store": task_store},
                {"run_id": "run-fixed", "task_store": task_store},
                {"run_id": "run-fixed", "task_ids": ["task-verify"]},
                {
                    "run_id": "run-fixed",
                    "task_ids": ["task-verify", "task-verify"],
                    "task_store": task_store,
                    "tasks": [task, task],
                },
            )
            for case in cases:
                case_tasks = case.pop("tasks", [task])
                with self.subTest(case=case), self.assertRaises(ValueError):
                    run_tasks(
                        case_tasks,
                        verification_queue=queue,
                        crawler_factory=lambda timeout: self.fail("crawler ran"),
                        **case,
                    )

            mismatched = CrawlTask("https://other.edu/private", root / "other.xlsx")
            with self.assertRaises(ValueError):
                run_tasks(
                    [mismatched],
                    verification_queue=queue,
                    task_store=task_store,
                    run_id="run-fixed",
                    task_ids=["task-verify"],
                    crawler_factory=lambda timeout: self.fail("crawler ran"),
                )

            corrupt_store = TaskStore(root / "corrupt-tasks")
            (corrupt_store.directory / "run-fixed.json").write_text(
                json.dumps(
                    {
                        "run_id": "different-run",
                        "tasks": [
                            {
                                "task_id": "task-verify",
                                "url": task.url,
                                "output_path": str(task.output_path),
                                "status": "pending",
                                "record_count": 0,
                                "error": "",
                            }
                        ],
                        "schema_version": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                run_tasks(
                    [task],
                    verification_queue=queue,
                    task_store=corrupt_store,
                    run_id="run-fixed",
                    task_ids=["task-verify"],
                    crawler_factory=lambda timeout: self.fail("crawler ran"),
                )

        self.assertFalse(queue.path.exists())

    def test_duplicate_task_ids_are_rejected_without_persistent_queue(self) -> None:
        tasks = [
            CrawlTask("https://one.edu", Path("one.xlsx")),
            CrawlTask("https://two.edu", Path("two.xlsx")),
        ]
        with self.assertRaises(ValueError):
            run_tasks(
                tasks,
                task_ids=["same-task", "same-task"],
                crawler_factory=lambda timeout: self.fail("crawler ran"),
            )

    def test_verification_required_without_queue_keeps_existing_batch_compatibility(self) -> None:
        tasks = [
            CrawlTask("https://one.edu", Path("one.xlsx")),
            CrawlTask("https://verify.edu/private?q=secret", Path("verify.xlsx")),
            CrawlTask("https://two.edu", Path("two.xlsx")),
        ]
        outcomes = iter(
            [
                CrawlOutcome(TaskStatus.SUCCEEDED, (FacultyRecord("A", "P", "a"),)),
                CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED),
                CrawlOutcome(TaskStatus.SUCCEEDED, (FacultyRecord("B", "P", "b"),)),
            ]
        )

        class OutcomeCrawler:
            def __init__(self, timeout: int) -> None:
                pass

            def crawl_outcome(self, url: str) -> CrawlOutcome:
                return next(outcomes)

        run_tasks(
            tasks,
            crawler_factory=OutcomeCrawler,
            exporter=lambda records, path: None,
        )

        self.assertEqual(
            [task.status for task in tasks],
            ["succeeded", "verification_required", "succeeded"],
        )

    def test_verification_terminal_callbacks_are_isolated(self) -> None:
        for failing_callback in ("verification", "diagnostic", "update"):
            with (
                self.subTest(failing_callback=failing_callback),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                tasks = [
                    CrawlTask("https://one.edu", root / "one.xlsx"),
                    CrawlTask("https://verify.edu/private", root / "verify.xlsx"),
                    CrawlTask("https://two.edu", root / "two.xlsx"),
                ]
                task_ids = ["task-1", "task-verify", "task-2"]
                task_store = TaskStore(root / "tasks")
                task_store.save(
                    StoredRun(
                        "run-callbacks",
                        [
                            StoredTask(
                                task_id,
                                task.url,
                                str(task.output_path),
                                TaskStatus.PENDING,
                            )
                            for task_id, task in zip(task_ids, tasks, strict=True)
                        ],
                    )
                )
                outcomes = iter(
                    [
                        CrawlOutcome(
                            TaskStatus.SUCCEEDED,
                            (FacultyRecord("A", "P", "a"),),
                        ),
                        CrawlOutcome(
                            TaskStatus.VERIFICATION_REQUIRED,
                            diagnostics={
                                "Failure reason": "Challenge response body: PRIVATE-BODY-BYTES"
                            },
                        ),
                        CrawlOutcome(
                            TaskStatus.SUCCEEDED,
                            (FacultyRecord("B", "P", "b"),),
                        ),
                    ]
                )
                events: list[DiagnosticEvent] = []
                terminal_attempts: list[str] = []

                class OutcomeCrawler:
                    def __init__(self, timeout: int) -> None:
                        pass

                    def crawl_outcome(self, url: str) -> CrawlOutcome:
                        return next(outcomes)

                def fail() -> None:
                    raise RuntimeError("session token PRIVATE-BODY-BYTES")

                def on_verification(item: VerificationItem) -> None:
                    terminal_attempts.append("verification")
                    if failing_callback == "verification":
                        fail()

                def on_diagnostic(event: DiagnosticEvent) -> None:
                    if event.category == "verification_required":
                        terminal_attempts.append("diagnostic")
                        if failing_callback == "diagnostic":
                            fail()
                    events.append(event)

                def on_update(index: int, task: CrawlTask) -> None:
                    if task.status == "verification_required":
                        terminal_attempts.append("update")
                        if failing_callback == "update":
                            fail()

                with self.assertLogs("crawler.batch", level="ERROR") as logs:
                    run_tasks(
                        tasks,
                        crawler_factory=OutcomeCrawler,
                        exporter=lambda records, path: None,
                        verification_queue=VerificationQueue(root / "queue.json"),
                        task_store=task_store,
                        run_id="run-callbacks",
                        task_ids=task_ids,
                        on_verification=on_verification,
                        on_diagnostic=on_diagnostic,
                        on_update=on_update,
                    )

                self.assertEqual(
                    [task.status for task in tasks],
                    ["succeeded", "verification_required", "succeeded"],
                )
                self.assertEqual(
                    terminal_attempts,
                    ["diagnostic", "verification", "update"],
                )
                self.assertEqual(
                    sum(event.category == "verification_required" for event in events),
                    0 if failing_callback == "diagnostic" else 1,
                )
                self.assertNotIn("PRIVATE-BODY-BYTES", "\n".join(logs.output))

    def test_queue_failure_has_one_fixed_terminal_and_isolated_callbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tasks = [
                CrawlTask("https://one.edu", root / "one.xlsx"),
                CrawlTask("https://verify.edu/private", root / "verify.xlsx"),
                CrawlTask("https://two.edu", root / "two.xlsx"),
            ]
            task_ids = ["task-1", "task-verify", "task-2"]
            task_store = TaskStore(root / "tasks")
            task_store.save(
                StoredRun(
                    "run-queue-failure",
                    [
                        StoredTask(
                            task_id,
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                        for task_id, task in zip(task_ids, tasks, strict=True)
                    ],
                )
            )
            outcomes = iter(
                [
                    CrawlOutcome(TaskStatus.SUCCEEDED, (FacultyRecord("A", "P", "a"),)),
                    CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED),
                    CrawlOutcome(TaskStatus.SUCCEEDED, (FacultyRecord("B", "P", "b"),)),
                ]
            )
            queue = VerificationQueue(root / "queue.json")
            terminal_attempts: list[str] = []
            verification_items: list[VerificationItem] = []

            class OutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return next(outcomes)

            def on_diagnostic(event: DiagnosticEvent) -> None:
                if event.task_id == "task-verify":
                    terminal_attempts.append(f"diagnostic:{event.category}")
                    raise RuntimeError("diagnostic token PRIVATE-BODY")

            def on_update(index: int, task: CrawlTask) -> None:
                if index == 1 and task.status == "failed":
                    terminal_attempts.append(f"update:{task.status}")
                    raise RuntimeError("update token PRIVATE-BODY")

            with (
                patch.object(
                    queue,
                    "enqueue",
                    side_effect=OSError("queue token PRIVATE-BODY"),
                ),
                self.assertLogs("crawler.batch", level="ERROR") as logs,
            ):
                run_tasks(
                    tasks,
                    crawler_factory=OutcomeCrawler,
                    exporter=lambda records, path: None,
                    verification_queue=queue,
                    task_store=task_store,
                    run_id="run-queue-failure",
                    task_ids=task_ids,
                    on_verification=verification_items.append,
                    on_diagnostic=on_diagnostic,
                    on_update=on_update,
                )

        self.assertEqual(
            [task.status for task in tasks],
            ["succeeded", "failed", "succeeded"],
        )
        self.assertEqual(tasks[1].error, "verification_queue_unavailable")
        self.assertEqual(
            terminal_attempts,
            ["diagnostic:failed", "update:failed"],
        )
        self.assertEqual(verification_items, [])
        self.assertNotIn("PRIVATE-BODY", "\n".join(logs.output))

    def test_invalid_verification_origin_uses_fixed_queue_failure_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = CrawlTask("https://example.edu:invalid/private", root / "invalid.xlsx")
            task_store = TaskStore(root / "tasks")
            task_store.save(
                StoredRun(
                    "run-invalid-origin",
                    [
                        StoredTask(
                            "task-invalid-origin",
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )

            class OutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED)

            notifications: list[VerificationItem] = []
            run_tasks(
                [task],
                crawler_factory=OutcomeCrawler,
                verification_queue=VerificationQueue(root / "queue.json"),
                task_store=task_store,
                run_id="run-invalid-origin",
                task_ids=["task-invalid-origin"],
                on_verification=notifications.append,
            )

        self.assertEqual(task.status, TaskStatus.FAILED.value)
        self.assertEqual(task.error, "verification_queue_unavailable")
        self.assertEqual(notifications, [])

    def test_persistent_enqueue_resolves_original_url_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = CrawlTask("https://verify.edu/private", root / "verify.xlsx")
            task_store = TaskStore(root / "tasks")
            task_store.save(
                StoredRun(
                    "run-resolve",
                    [
                        StoredTask(
                            "task-verify",
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )

            class OutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED)

            with patch.object(
                task_store,
                "resolve_original_url",
                wraps=task_store.resolve_original_url,
            ) as resolve:
                run_tasks(
                    [task],
                    crawler_factory=OutcomeCrawler,
                    verification_queue=VerificationQueue(root / "queue.json"),
                    task_store=task_store,
                    run_id="run-resolve",
                    task_ids=["task-verify"],
                )

        self.assertEqual(resolve.call_count, 2)

    def test_idn_and_ipv6_verification_are_queued(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tasks = [
                CrawlTask("https://faß.de/private", root / "idn.xlsx"),
                CrawlTask("https://[2001:db8::1]:8443/private", root / "ipv6.xlsx"),
            ]
            task_ids = ["task-idn", "task-ipv6"]
            task_store = TaskStore(root / "tasks")
            task_store.save(
                StoredRun(
                    "run-origins",
                    [
                        StoredTask(
                            task_id,
                            task.url,
                            str(task.output_path),
                            TaskStatus.PENDING,
                        )
                        for task_id, task in zip(task_ids, tasks, strict=True)
                    ],
                )
            )

            class OutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED)

            queue = VerificationQueue(root / "queue.json")
            run_tasks(
                tasks,
                crawler_factory=OutcomeCrawler,
                verification_queue=queue,
                task_store=task_store,
                run_id="run-origins",
                task_ids=task_ids,
            )
            queued = queue.pending("run-origins")

        self.assertEqual(
            [task.status for task in tasks],
            ["verification_required", "verification_required"],
        )
        self.assertEqual(
            [item.url for item in queued],
            ["https://xn--fa-hia.de", "https://[2001:db8::1]:8443"],
        )

    def test_review_recommended_outcome_is_exported_with_distinct_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks("https://review.example.edu/faculty", Path(temp_dir))
            record = FacultyRecord(
                "Ada", "Professor", "https://review.example.edu/faculty/ada"
            )
            exported: list[FacultyRecord] = []
            events: list[DiagnosticEvent] = []

            class OutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    raise AssertionError("crawl must not run when crawl_outcome is available")

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return CrawlOutcome(
                        TaskStatus.REVIEW_RECOMMENDED,
                        (record,),
                        diagnostics={"Failure stage": "low_coverage_warning"},
                    )

            run_tasks(
                prepared.tasks,
                crawler_factory=OutcomeCrawler,
                exporter=lambda records, path: exported.extend(records),
                on_diagnostic=events.append,
            )

        self.assertEqual(exported, [record])
        self.assertEqual(prepared.tasks[0].status, "review_recommended")
        self.assertEqual(prepared.tasks[0].record_count, 1)
        self.assertEqual(events[0].category, "review_recommended")

    def test_typed_failed_outcome_uses_existing_failure_path_without_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks("https://fail.example.edu/faculty", Path(temp_dir))
            exported: list[FacultyRecord] = []

            class OutcomeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl_outcome(self, url: str) -> CrawlOutcome:
                    return CrawlOutcome(
                        TaskStatus.FAILED,
                        diagnostics={
                            "Failure stage": "fetch",
                            "Failure reason": "Access denied",
                        },
                    )

            with self.assertLogs("crawler.batch", level="ERROR") as logs:
                run_tasks(
                    prepared.tasks,
                    crawler_factory=OutcomeCrawler,
                    exporter=lambda records, path: exported.extend(records),
                )

        self.assertEqual(prepared.tasks[0].status, "failed")
        self.assertEqual(prepared.tasks[0].error, "Access denied")
        self.assertEqual(exported, [])
        self.assertIn("stage=fetch", "\n".join(logs.output))

    def test_shared_privacy_vocabulary_covers_direct_text_and_allowed_queries(self) -> None:
        cases = (
            ("client_secret=CLIENT-SECRET", "CLIENT-SECRET"),
            ("clientSecret=CAMEL-SECRET", "CAMEL-SECRET"),
            ("client-secret=DASH-SECRET", "DASH-SECRET"),
            ("auth_token=AUTH-SECRET", "AUTH-SECRET"),
            ("authToken=AUTH-CAMEL-SECRET", "AUTH-CAMEL-SECRET"),
            ("auth-token=AUTH-DASH-SECRET", "AUTH-DASH-SECRET"),
            ("credentials=CREDENTIALS-SECRET", "CREDENTIALS-SECRET"),
            ("x-api-key=API-SECRET", "API-SECRET"),
            ("private_key=PRIVATE-SECRET", "PRIVATE-SECRET"),
            ("Bearer BEARER-SECRET", "BEARER-SECRET"),
            ("auth=SHORT-AUTH-SECRET", "SHORT-AUTH-SECRET"),
            ("C:/Users/QueryAlice/private/file.txt", "QueryAlice"),
            (r"\\server\share\QueryBob\private\file.txt", "QueryBob"),
        )
        for value, seed in cases:
            with self.subTest(value=value):
                direct = safe_exception_message(RuntimeError(value))
                safe_url = safe_url_for_log(
                    f"https://example.edu/search?q={quote(value, safe='')}"
                )

                self.assertNotIn(seed, direct)
                self.assertNotIn(seed, unquote(safe_url))

        safe_plain = safe_url_for_log(
            "https://example.edu/search?page=2&q=faculty+law"
        )
        self.assertEqual(
            parse_qs(urlparse(safe_plain).query),
            {"page": ["2"], "q": ["faculty law"]},
        )

    def test_callback_uses_shared_privacy_vocabulary(self) -> None:
        cases = (
            ("clientSecret=CALLBACK-CLIENT-SECRET", "CALLBACK-CLIENT-SECRET"),
            ("authToken=CALLBACK-AUTH-SECRET", "CALLBACK-AUTH-SECRET"),
            ("credentials=CALLBACK-CREDENTIAL-SECRET", "CALLBACK-CREDENTIAL-SECRET"),
            ("x-api-key=CALLBACK-API-SECRET", "CALLBACK-API-SECRET"),
            ("private_key=CALLBACK-PRIVATE-SECRET", "CALLBACK-PRIVATE-SECRET"),
            ("Bearer CALLBACK-BEARER-SECRET", "CALLBACK-BEARER-SECRET"),
            (r"\\server\share\CallbackAlice\file.txt", "CallbackAlice"),
        )
        for value, seed in cases:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp_dir:
                prepared = prepare_tasks(
                    "https://fail.example.edu/faculty",
                    Path(temp_dir),
                )
                events: list[DiagnosticEvent] = []

                class EmptyCrawler:
                    last_diagnostics = {
                        "Failure stage": value,
                        "Failure reason": value,
                    }

                    def __init__(self, timeout: int) -> None:
                        pass

                    def crawl(self, url: str) -> list[FacultyRecord]:
                        return []

                with self.assertLogs("crawler.batch", level="ERROR") as captured:
                    run_tasks(
                        prepared.tasks,
                        crawler_factory=EmptyCrawler,
                        on_diagnostic=events.append,
                        run_id=value,
                        task_ids=[value],
                    )

                combined = " ".join(
                    (
                        "\n".join(captured.output),
                        str(events[0]),
                    )
                )
                self.assertNotIn(seed, combined)

    def test_privacy_redacts_forward_slash_drive_and_unc_paths(self) -> None:
        message = safe_exception_message(
            RuntimeError(
                "C:/Users/DirectAlice/private/file.txt "
                r"\\server\share\DirectBob\private\file.txt"
            )
        )

        self.assertNotIn("DirectAlice", message)
        self.assertNotIn("DirectBob", message)
        self.assertNotIn("server", message)
        self.assertIn("<local_path>", message)

    def test_safe_url_redacts_encoded_secret_assignments_in_allowed_query(self) -> None:
        for key in ("cookie", "password", "token"):
            with self.subTest(key=key):
                safe_url = safe_url_for_log(
                    f"https://example.edu/search?q={key}%3DURL-SECRET"
                )

                self.assertNotIn("URL-SECRET", unquote(safe_url))

    def test_failed_task_emits_one_redacted_terminal_diagnostic_before_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks(
                "https://fail.example.edu/faculty",
                Path(temp_dir),
            )
            events: list[DiagnosticEvent] = []
            notifications: list[str] = []

            class FailingCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    raise RuntimeError("Cookie: secret-value")

            def record(event: DiagnosticEvent) -> None:
                events.append(event)
                notifications.append("diagnostic")

            def update(index: int, task) -> None:
                if task.status == "failed":
                    notifications.append("update")

            with self.assertLogs("crawler.batch", level="ERROR"):
                run_tasks(
                    prepared.tasks,
                    crawler_factory=FailingCrawler,
                    on_update=update,
                    on_diagnostic=record,
                    run_id="run-fixed",
                    task_ids=["task-fixed"],
                )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].run_id, "run-fixed")
        self.assertEqual(events[0].task_id, "task-fixed")
        self.assertEqual(events[0].category, "failed")
        self.assertNotIn("secret-value", events[0].message)
        self.assertEqual(notifications, ["diagnostic", "update"])

    def test_each_task_emits_one_terminal_event_with_stable_generated_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks(
                "https://one.example.edu/faculty\n"
                "https://two.example.edu/faculty",
                Path(temp_dir),
            )
            events: list[DiagnosticEvent] = []

            class FakeCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    return [FacultyRecord("Ada", "Professor", f"{url}/ada")]

            run_tasks(
                prepared.tasks,
                crawler_factory=FakeCrawler,
                exporter=lambda records, path: None,
                on_diagnostic=events.append,
            )

        self.assertEqual([event.category for event in events], ["succeeded", "succeeded"])
        self.assertEqual(len({event.run_id for event in events}), 1)
        self.assertEqual(len({event.task_id for event in events}), 2)

    def test_terminal_callback_redacts_caller_ids_and_crawler_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks(
                "https://fail.example.edu/faculty",
                Path(temp_dir),
            )
            events: list[DiagnosticEvent] = []

            class EmptyCrawler:
                last_diagnostics = {
                    "Failure stage": "fetch <html>STAGE BODY</html>",
                    "Failure reason": "No candidates found",
                }

                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    return []

            with self.assertLogs("crawler.batch", level="ERROR"):
                run_tasks(
                    prepared.tasks,
                    crawler_factory=EmptyCrawler,
                    on_diagnostic=events.append,
                    run_id="run <html>RUN BODY</html>",
                    task_ids=["task <html>TASK BODY</html>"],
                )

        event_text = " ".join(
            (
                events[0].run_id,
                events[0].task_id,
                events[0].stage,
                events[0].category,
                events[0].message,
                str(events[0].details),
            )
        )
        self.assertNotIn("RUN BODY", event_text)
        self.assertNotIn("TASK BODY", event_text)
        self.assertNotIn("STAGE BODY", event_text)

    def test_failure_log_sanitizes_crawler_controlled_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks(
                "https://fail.example.edu/faculty",
                Path(temp_dir),
            )

            class EmptyCrawler:
                last_diagnostics = {
                    "Failure stage": (
                        "fetch Bearer BEARER-STAGE-SECRET "
                        "auth=AUTH-STAGE-SECRET "
                        "<html>PRIVATE STAGE BODY</html>"
                    ),
                    "Failure reason": "No candidates found",
                }

                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    return []

            with self.assertLogs("crawler.batch", level="ERROR") as captured:
                run_tasks(prepared.tasks, crawler_factory=EmptyCrawler)

        log_text = "\n".join(captured.output)
        self.assertNotIn("BEARER-STAGE-SECRET", log_text)
        self.assertNotIn("AUTH-STAGE-SECRET", log_text)
        self.assertNotIn("PRIVATE STAGE BODY", log_text)

    def test_run_tasks_is_sequential_and_continues_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks(
                "https://one.example.edu/faculty\n"
                "https://fail.example.edu/faculty\n"
                "https://two.example.edu/faculty",
                Path(temp_dir),
            )
            calls: list[tuple[str, str]] = []
            updates: list[tuple[int, str]] = []

            class FakeCrawler:
                def __init__(self, timeout: int) -> None:
                    self.timeout = timeout

                def crawl(self, url: str) -> list[FacultyRecord]:
                    calls.append(("crawl", url))
                    if "fail" in url:
                        raise RuntimeError("network failed")
                    return [FacultyRecord("Ada", "Professor", f"{url}/ada")]

            def fake_export(records: list[FacultyRecord], path: Path) -> None:
                calls.append(("export", path.name))

            with self.assertLogs("crawler.batch", level="ERROR"):
                run_tasks(
                    prepared.tasks,
                    timeout=1234,
                    crawler_factory=FakeCrawler,
                    exporter=fake_export,
                    on_update=lambda index, task: updates.append((index, task.status)),
                )

        self.assertEqual(
            calls,
            [
                ("crawl", "https://one.example.edu/faculty"),
                ("export", "one.example.edu_faculty.xlsx"),
                ("crawl", "https://fail.example.edu/faculty"),
                ("crawl", "https://two.example.edu/faculty"),
                ("export", "two.example.edu_faculty.xlsx"),
            ],
        )
        self.assertEqual([task.status for task in prepared.tasks], ["succeeded", "failed", "succeeded"])
        self.assertEqual([task.record_count for task in prepared.tasks], [1, 0, 1])
        self.assertIn((1, "failed"), updates)
        self.assertIn((2, "running"), updates)

    def test_failure_log_has_url_stage_and_stack_without_page_content_or_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks("https://fail.example.edu/faculty", Path(temp_dir))

            class FailingCrawler:
                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    raise RuntimeError("Cookie: secret-value <html>private page body</html>")

            with self.assertLogs("crawler.batch", level="ERROR") as captured:
                run_tasks(prepared.tasks, crawler_factory=FailingCrawler)

        log_text = "\n".join(captured.output)
        self.assertIn("https://fail.example.edu/faculty", log_text)
        self.assertIn("stage=crawl", log_text)
        self.assertIn("Traceback", log_text)
        self.assertNotIn("secret-value", log_text)
        self.assertNotIn("private page body", log_text)

    def test_empty_crawl_result_is_failed_and_is_not_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = prepare_tasks("https://empty.example.edu/faculty", Path(temp_dir))
            exported: list[Path] = []

            class EmptyCrawler:
                last_diagnostics = {"Failure stage": "parse", "Failure reason": "No candidates found"}

                def __init__(self, timeout: int) -> None:
                    pass

                def crawl(self, url: str) -> list[FacultyRecord]:
                    return []

            with self.assertLogs("crawler.batch", level="ERROR") as captured:
                run_tasks(
                    prepared.tasks,
                    crawler_factory=EmptyCrawler,
                    exporter=lambda records, path: exported.append(Path(path)),
                )

        self.assertEqual(prepared.tasks[0].status, "failed")
        self.assertIn("No candidates found", prepared.tasks[0].error)
        self.assertEqual(exported, [])
        self.assertIn("stage=parse", "\n".join(captured.output))

    def test_log_sanitizers_remove_headers_credentials_tokens_and_local_paths(self) -> None:
        message = safe_exception_message(
            RuntimeError(
                r"Authorization: Bearer TOPSECRET Cookie: session=abc; csrftoken=ALSOSECRET "
                r"C:\Users\PrivateName\project\file.py"
            )
        )
        safe_url = safe_url_for_log(
            "https://alice:password@example.edu/faculty?page=2&access_token=TOPSECRET&sig=SIGNEDSECRET#people"
        )
        structured = safe_exception_message(
            RuntimeError(
                '''headers={"Authorization": "Bearer JSONSECRET", "access_token": "DICTSECRET"}'''
            )
        )

        self.assertNotIn("TOPSECRET", message + safe_url)
        self.assertNotIn("SIGNEDSECRET", safe_url)
        self.assertNotIn("JSONSECRET", structured)
        self.assertNotIn("DICTSECRET", structured)
        self.assertNotIn("ALSOSECRET", message)
        self.assertNotIn("PrivateName", message)
        self.assertNotIn("alice", safe_url)
        self.assertNotIn("password", safe_url)
        self.assertIn("page=2", safe_url)
        self.assertIn("access_token", safe_url)


if __name__ == "__main__":
    unittest.main()
