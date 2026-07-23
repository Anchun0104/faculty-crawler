import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler.app_paths import AppPaths
from crawler.models import TaskStatus
from crawler.task_store import StoredRun, StoredTask, TaskStore, TaskStoreConflictError


class TaskStoreTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows cross-process RMW regression")
    def test_two_processes_serialize_updates_without_lost_state(self):
        worker = """
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from crawler.models import TaskStatus
from crawler.task_store import TaskStore

root = Path(sys.argv[1])
task_id = sys.argv[2]
store = TaskStore(root / "tasks")
events = []
original_lock = store._cross_process_lock
original_load = store._load_unlocked
def observed_load(run_id):
    events.append("load-enter")
    try:
        return original_load(run_id)
    finally:
        events.append("load-exit")
@contextmanager
def observed_lock():
    with original_lock():
        events.append("lock-enter")
        marker = root / "critical-section"
        owns_marker = False
        try:
            marker.open("x").close()
            owns_marker = True
        except FileExistsError:
            (root / "overlap").touch()
        (root / f"{task_id}.entered").touch()
        deadline = time.monotonic() + 5
        while not (root / "release").exists() and time.monotonic() < deadline:
            pass
        try:
            yield
        finally:
            events.append("lock-exit")
            if owns_marker:
                marker.unlink(missing_ok=True)
store._cross_process_lock = observed_lock
store._load_unlocked = observed_load
deadline = time.monotonic() + 5
while not (root / "start").exists() and time.monotonic() < deadline:
    pass
store.update_task("run-shared", task_id, TaskStatus.SUCCEEDED)
(root / f"{task_id}.trace").write_text("\\n".join(events), encoding="utf-8")
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root / "tasks")
            store.save(
                StoredRun(
                    "run-shared",
                    [
                        StoredTask(
                            task_id,
                            f"https://example.edu/{task_id}",
                            f"{task_id}.xlsx",
                            TaskStatus.PENDING,
                        )
                        for task_id in ("task-a", "task-b")
                    ],
                )
            )
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        worker,
                        str(root),
                        task_id,
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for task_id in ("task-a", "task-b")
            ]
            (root / "start").touch()
            deadline = time.monotonic() + 5
            while (
                not list(root.glob("*.entered"))
                and time.monotonic() < deadline
            ):
                pass
            entered = bool(list(root.glob("*.entered")))
            (root / "release").touch()
            outputs = [process.communicate(timeout=15) for process in processes]
            self.assertEqual(
                [process.returncode for process in processes],
                [0, 0],
                outputs,
            )
            statuses = [task.status for task in store.load("run-shared").tasks]
            overlapped = (root / "overlap").exists()
            traces = [
                (root / f"{task_id}.trace").read_text(encoding="utf-8").splitlines()
                for task_id in ("task-a", "task-b")
            ]

        self.assertTrue(entered)
        self.assertFalse(overlapped)
        self.assertEqual(
            traces,
            [[
                "lock-enter",
                "load-enter",
                "load-exit",
                "load-enter",
                "load-exit",
                "lock-exit",
            ]] * 2,
        )
        self.assertEqual(statuses, [TaskStatus.SUCCEEDED, TaskStatus.SUCCEEDED])

    def test_update_failure_preserves_committed_json_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            store.save(
                StoredRun(
                    "run-update",
                    [
                        StoredTask(
                            "task-update",
                            "https://example.edu",
                            "out.xlsx",
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )
            before = (root / "run-update.json").read_bytes()

            with patch("crawler.task_store.os.replace", side_effect=OSError("SECRET")):
                with self.assertRaises(OSError):
                    store.update_task(
                        "run-update",
                        "task-update",
                        TaskStatus.SUCCEEDED,
                    )

            after = (root / "run-update.json").read_bytes()

        self.assertEqual(after, before)
        self.assertEqual(list(root.glob("*.tmp")), [])

    def test_list_runs_uses_strict_loader_and_sorted_safe_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TaskStore(Path(temp_dir))
            store.save(StoredRun("run-b", []))
            store.save(StoredRun("run-a", []))

            self.assertEqual(
                [run.run_id for run in store.list_runs()],
                ["run-a", "run-b"],
            )

            (Path(temp_dir) / "not a run.json").write_text("SECRET", encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                store.list_runs()
            self.assertNotIn("SECRET", str(error.exception))

    def test_round_trip_and_recover_all_interrupted_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TaskStore(Path(temp_dir))
            run = StoredRun(
                "run-1",
                [
                    StoredTask(
                        f"task-{status.value}",
                        "https://example.edu/faculty",
                        "out.xlsx",
                        status,
                    )
                    for status in (
                        TaskStatus.FETCHING,
                        TaskStatus.EXPANDING,
                        TaskStatus.PARSING,
                        TaskStatus.RETRY_WAIT,
                    )
                ],
            )
            store.save(run)
            loaded = store.load("run-1")
            recovered = store.recover_interrupted()
            reloaded = store.load("run-1")
        self.assertEqual(loaded.tasks[0].status, TaskStatus.FETCHING)
        self.assertEqual(
            [task.status for task in recovered[0].tasks],
            [TaskStatus.PENDING] * 4,
        )
        self.assertEqual(
            [task.status for task in reloaded.tasks],
            [TaskStatus.PENDING] * 4,
        )

    def test_state_file_never_contains_cookie_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            store.save(
                StoredRun(
                    "run-2",
                    [
                        StoredTask(
                            "task-2",
                            "https://example.edu",
                            "out.xlsx",
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )
            text = (root / "run-2.json").read_text(encoding="utf-8")
        self.assertNotIn("cookie", text.casefold())

    def test_save_flushes_file_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events = []
            original_replace = os.replace
            store = TaskStore(Path(temp_dir))
            run = StoredRun("run-fsync", [])
            with (
                patch("crawler.task_store.os.fsync", side_effect=lambda _: events.append("fsync")),
                patch(
                    "crawler.task_store.os.replace",
                    side_effect=lambda source, target: (
                        events.append("replace"),
                        original_replace(source, target),
                    )[1],
                ),
            ):
                store.save(run)
        self.assertEqual(events, ["fsync", "replace"])

    def test_save_removes_temporary_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            with patch("crawler.task_store.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    store.save(StoredRun("run-cleanup", []))
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_two_stores_concurrently_save_without_temp_collisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = TaskStore(root)
            second = TaskStore(root)
            barrier = threading.Barrier(2)
            errors = []
            temporary_paths = []
            original_replace = os.replace

            def record_replace(source, target):
                temporary_paths.append(Path(source))
                return original_replace(source, target)

            def save(store, task_id):
                try:
                    barrier.wait(timeout=5)
                    store.save(
                        StoredRun(
                            "shared-run",
                            [
                                StoredTask(
                                    task_id,
                                    "https://example.edu",
                                    "out.xlsx",
                                    TaskStatus.PENDING,
                                )
                            ],
                        )
                    )
                except Exception as error:
                    errors.append(error)

            with patch("crawler.task_store.os.replace", side_effect=record_replace):
                threads = [
                    threading.Thread(target=save, args=(first, "task-shared")),
                    threading.Thread(target=save, args=(second, "task-shared")),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            self.assertFalse(errors)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(len(set(temporary_paths)), 2)
            self.assertEqual(first.load("shared-run").tasks[0].task_id, "task-shared")
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_saved_identity_is_immutable_but_runtime_fields_can_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            original = StoredTask(
                "task-1",
                "https://example.edu/private?token=ORIGINAL",
                "out.xlsx",
                TaskStatus.PENDING,
            )
            store.save(StoredRun("run-1", [original]))
            store.save(
                StoredRun(
                    "run-1",
                    [
                        StoredTask(
                            original.task_id,
                            original.url,
                            original.output_path,
                            TaskStatus.FAILED,
                            3,
                            "fixed error",
                        )
                    ],
                )
            )
            self.assertEqual(
                store.resolve_original_url("run-1", "task-1"),
                original.url,
            )

            invalid_runs = (
                StoredRun(
                    "run-1",
                    [
                        StoredTask(
                            "task-1",
                            "https://attacker.edu/changed",
                            "out.xlsx",
                            TaskStatus.PENDING,
                        )
                    ],
                ),
                StoredRun("run-1", []),
                StoredRun("run-1", [original, original]),
            )
            for invalid in invalid_runs:
                with self.subTest(tasks=invalid.tasks), self.assertRaises(
                    (TaskStoreConflictError, ValueError)
                ):
                    store.save(invalid)
            resolved_after = store.resolve_original_url("run-1", "task-1")

        self.assertEqual(resolved_after, original.url)

    def test_unknown_or_duplicate_task_cannot_be_resolved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            store.save(StoredRun("run-1", []))
            with self.assertRaises(KeyError):
                store.resolve_original_url("run-1", "missing")

            duplicate_payload = {
                "run_id": "run-duplicate",
                "tasks": [
                    {
                        "task_id": "task-1",
                        "url": "https://example.edu",
                        "output_path": "out.xlsx",
                        "status": "pending",
                        "record_count": 0,
                        "error": "",
                    }
                ]
                * 2,
                "schema_version": 1,
            }
            (root / "run-duplicate.json").write_text(
                json.dumps(duplicate_payload), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                store.load("run-duplicate")
            with self.assertRaises(ValueError):
                store.resolve_original_url("run-duplicate", "task-1")

    @unittest.skipUnless(os.name == "nt", "Windows named mutex regression")
    def test_other_process_cannot_change_saved_original_url(self):
        worker = """
import sys
from pathlib import Path
from crawler.models import TaskStatus
from crawler.task_store import StoredRun, StoredTask, TaskStore, TaskStoreConflictError

store = TaskStore(Path(sys.argv[1]))
try:
    store.save(StoredRun("run-1", [StoredTask(
        "task-1",
        "https://attacker.edu/changed",
        "out.xlsx",
        TaskStatus.PENDING,
    )]))
except TaskStoreConflictError:
    raise SystemExit(0)
raise SystemExit(2)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            original_url = "https://example.edu/private?token=ORIGINAL"
            store.save(
                StoredRun(
                    "run-1",
                    [
                        StoredTask(
                            "task-1",
                            original_url,
                            "out.xlsx",
                            TaskStatus.PENDING,
                        )
                    ],
                )
            )
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.run(
                [sys.executable, "-c", worker, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            resolved = store.resolve_original_url("run-1", "task-1")

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertEqual(process.stderr, "")
        self.assertEqual(resolved, original_url)

    def test_save_and_load_reject_unsafe_run_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TaskStore(Path(temp_dir))
            for run_id in ("../escape", "nested/run", "nested\\run", ""):
                with self.subTest(run_id=run_id):
                    with self.assertRaises(ValueError):
                        store.save(StoredRun(run_id, []))
                    with self.assertRaises(ValueError):
                        store.load(run_id)


class AppPathsTests(unittest.TestCase):
    def test_for_user_creates_all_declared_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths.for_user(Path(temp_dir))
            for path in paths.__dict__.values():
                self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
