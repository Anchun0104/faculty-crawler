from __future__ import annotations

import ast
import os
import tempfile
import tkinter as tk
import threading
import time
import unittest
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from crawler.diagnostics import ReportRecord, write_report_metadata
from crawler.app_paths import AppPaths
from crawler.models import TaskStatus
from crawler.retention import RetentionService
from crawler.settings_store import AppSettings
from crawler.translation_settings import TranslationSettings
from crawler.task_store import StoredRun, StoredTask, TaskStore
from crawler.verification import VerificationItem, VerificationQueue
from desktop_app import (
    DesktopApp,
    LocalReportStore,
    SystemOpener,
    _discover_failed_run_records,
    _purge_due_retention,
    _recover_desktop_tasks,
)
from ui.controller import AppController, TaskView
from ui.tasks_page import TasksPage


NOW = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Item:
    run_id: str
    task_id: str
    url: str
    hostname: str
    detected_at: str
    reason: str
    status: str


class VerificationQueueFake:
    def __init__(self) -> None:
        self.values = [
            Item("run-a", "task-a", "https://a.edu/private", "a.edu", "2026-07-23T08:00:00Z", "challenge", "verification_required"),
            Item("run-b", "task-b", "https://b.edu/private", "b.edu", "2026-07-23T08:01:00Z", "login", "ready_to_resume"),
            Item("run-c", "task-c", "https://c.edu/private", "c.edu", "2026-07-23T08:02:00Z", "challenge", "verification_required"),
        ]

    def items(self):
        return list(self.values)

    def pending(self):
        return [item for item in self.values if item.status == "verification_required"]


class VerificationStarterFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.active = 0
        self.maximum_concurrent_calls = 0

    def __call__(self, run_id: str, task_id: str) -> bool:
        self.calls.append((run_id, task_id))
        self.active += 1
        self.maximum_concurrent_calls = max(self.maximum_concurrent_calls, self.active)
        return True

    def finish(self) -> None:
        self.active -= 1


class SessionsFake:
    def __init__(self) -> None:
        self.clear_calls: list[str] = []

    def list_sessions(self):
        return [
            type("Session", (), {
                "hostname": "example.edu",
                "saved_at": NOW,
                "last_used_at": NOW,
                "expires_at": NOW,
                "storage_state": b"COOKIE-SECRET",
            })()
        ]

    def clear_site(self, hostname: str) -> None:
        self.clear_calls.append(hostname)

    def clear_all(self) -> None:
        self.clear_calls.append("*")


class ReportsFake:
    def __init__(self, root: Path) -> None:
        self.record = ReportRecord("report-a", root / "report-a.zip", NOW, None)
        self.marked: list[str] = []

    def list_reports(self):
        return [self.record]

    def by_id(self, report_id: str):
        if report_id != self.record.report_id:
            raise KeyError(report_id)
        return self.record

    def mark_submitted(self, report_id: str):
        self.marked.append(report_id)
        self.record = replace(self.record, submitted_at=NOW)
        return self.record


class OpenerFake:
    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.urls: list[str] = []
        self.files: list[Path] = []

    def reveal(self, path: Path) -> None:
        self.paths.append(path)

    def open_url(self, url: str) -> None:
        self.urls.append(url)

    def open_file(self, path: Path) -> None:
        self.files.append(path)


class SettingsFake:
    def __init__(self, root: Path) -> None:
        self.value = AppSettings(str(root / "output"), "https://example.feishu.cn/drive/folder/abc", False)
        self.saved: list[AppSettings] = []

    def load(self):
        return self.value

    def save(self, value: AppSettings) -> None:
        if not value.feishu_folder_url.startswith("https://"):
            raise ValueError("feishu_folder_url must be an HTTPS URL")
        self.saved.append(value)
        self.value = value


class RetentionFake:
    def __init__(self) -> None:
        self.temporary_calls = 0
        self.internal_calls = 0

    def usage(self):
        return type("Usage", (), {"bytes": 4096, "files": 3})()

    def clear_temporary(self):
        self.temporary_calls += 1
        return [Path("temporary.tmp")]

    def clear_internal_data(self):
        self.internal_calls += 1
        return [Path("tasks/run.json")]


class WorkflowControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = VerificationQueueFake()
        self.starter = VerificationStarterFake()
        self.sessions = SessionsFake()
        self.reports = ReportsFake(self.root)
        self.opener = OpenerFake()
        self.settings = SettingsFake(self.root)
        self.retention = RetentionFake()
        self.runner_calls: list[int] = []
        self.controller = AppController(
            self.root / "output",
            runner=lambda _tasks, *, timeout: self.runner_calls.append(timeout) or True,
            verification_queue=self.queue,
            verification_starter=self.starter,
            session_store=self.sessions,
            report_store=self.reports,
            settings_store=self.settings,
            retention_service=self.retention,
            opener=self.opener,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_verification_badge_counts_only_pending_items(self) -> None:
        self.assertEqual(self.controller.verification_badge_count(), 2)

    def test_process_all_verifications_is_sequential_and_keeps_compound_identity(self) -> None:
        self.controller.process_all_verifications()
        self.assertEqual(self.starter.calls, [("run-a", "task-a")])
        self.assertEqual(self.starter.maximum_concurrent_calls, 1)

        self.starter.finish()
        self.controller.verification_finished("run-a", "task-a", "ready_to_resume")
        self.assertEqual(self.starter.calls[-1], ("run-c", "task-c"))
        self.assertEqual(self.starter.maximum_concurrent_calls, 1)

    def test_start_one_verification_uses_selected_compound_identity(self) -> None:
        self.assertTrue(self.controller.start_verification("run-c", "task-c"))

        self.assertEqual(self.starter.calls, [("run-c", "task-c")])
        self.assertEqual(self.controller.active_verification, ("run-c", "task-c"))

    def test_process_all_stops_and_retains_remaining_on_defer(self) -> None:
        self.controller.process_all_verifications()
        self.starter.finish()
        self.controller.verification_finished("run-a", "task-a", "verification_required")

        self.assertEqual(self.starter.calls, [("run-a", "task-a")])
        self.assertEqual(self.controller.verification_badge_count(), 2)

    def test_wrong_verification_identity_cannot_advance_sequence(self) -> None:
        self.controller.process_all_verifications()
        with self.assertRaises(ValueError):
            self.controller.verification_finished("run-a", "other-task", "ready_to_resume")
        self.assertEqual(self.starter.calls, [("run-a", "task-a")])

    def test_clear_one_and_all_sessions_require_confirmation(self) -> None:
        self.assertFalse(self.controller.clear_session("example.edu", confirmed=False))
        self.assertFalse(self.controller.clear_all_sessions(confirmed=False))
        self.assertEqual(self.sessions.clear_calls, [])

        self.assertTrue(self.controller.clear_session("example.edu", confirmed=True))
        self.assertTrue(self.controller.clear_all_sessions(confirmed=True))
        self.assertEqual(self.sessions.clear_calls, ["example.edu", "*"])

    def test_session_views_never_expose_state_bytes_or_cookie_fields(self) -> None:
        rendered = repr(self.controller.session_views())
        self.assertNotIn("COOKIE-SECRET", rendered)
        self.assertNotIn("storage_state", rendered)
        self.assertNotIn("cookie", rendered.casefold())

    def test_report_handoff_reveals_zip_and_opens_feishu_without_marking(self) -> None:
        self.controller.open_report_handoff("report-a")

        self.assertEqual(self.opener.paths, [self.reports.record.path])
        self.assertEqual(self.opener.urls, [self.settings.value.feishu_folder_url])
        self.assertEqual(self.reports.marked, [])
        self.assertIsNone(self.reports.record.submitted_at)

    def test_mark_submitted_updates_only_selected_report(self) -> None:
        result = self.controller.mark_report_submitted("report-a")

        self.assertEqual(self.reports.marked, ["report-a"])
        self.assertEqual(result.report_id, "report-a")
        self.assertIsNotNone(result.submitted_at)

    def test_settings_round_trip_and_validation_error_are_exposed(self) -> None:
        state = self.controller.save_settings(
            str(self.root / "new-output"),
            "http://unsafe.example/folder",
            True,
        )
        self.assertEqual(state.error, "飞书文件夹网址必须是有效的 HTTPS 地址。")
        self.assertEqual(self.settings.saved, [])

        state = self.controller.save_settings(
            str(self.root / "new-output"),
            "https://example.feishu.cn/drive/folder/new",
            True,
        )
        self.assertEqual(state.error, "")
        self.assertTrue(state.detailed_logs)

    def test_settings_output_draft_does_not_prepare_urls_and_is_saved(self) -> None:
        chosen = str(self.root / "chosen-output")
        draft = self.controller.change_settings_output_dir(chosen)

        self.assertEqual(draft.output_dir, chosen)
        self.assertEqual(self.controller.tasks, ())
        saved = self.controller.save_settings(
            draft.output_dir,
            draft.feishu_folder_url,
            draft.detailed_logs,
        )
        self.assertEqual(saved.output_dir, chosen)
        self.assertEqual(self.settings.saved[-1].output_dir, chosen)

    def test_advanced_timeout_applies_to_next_batch_without_affecting_default(self) -> None:
        self.controller.save_settings(
            str(self.root / "output"),
            "https://example.feishu.cn/drive/folder/abc",
            False,
            timeout_ms=45_000,
        )
        self.controller.prepare("https://example.edu/faculty")
        self.controller.start_batch()

        self.assertEqual(self.runner_calls, [45_000])

    def test_translation_settings_round_trip_through_controller(self) -> None:
        translation = TranslationSettings(
            endpoint="http://localhost:5500",
            cache_path=str(self.root / "translation.sqlite3"),
            connect_timeout=3.0,
            response_timeout=12.0,
            retries=2,
        )

        saved = self.controller.save_settings(
            str(self.root / "output"),
            "https://example.feishu.cn/drive/folder/abc",
            False,
            translation=translation,
        )

        self.assertEqual(saved.translation, translation)
        self.assertEqual(self.controller.load_settings().translation, translation)

    def test_storage_summary_excludes_excel_and_cleanup_requires_confirmation(self) -> None:
        summary = self.controller.storage_usage()
        self.assertNotIn("Excel", repr(summary))
        self.assertNotIn(".xlsx", repr(summary).casefold())
        self.assertIn("问题报告 ZIP 和元数据", summary.categories)

        self.assertFalse(self.controller.clear_temporary(confirmed=False).confirmed)
        self.assertFalse(self.controller.clear_internal_data(confirmed=False).confirmed)
        self.assertEqual((self.retention.temporary_calls, self.retention.internal_calls), (0, 0))

        self.assertTrue(self.controller.clear_temporary(confirmed=True).confirmed)
        self.assertTrue(self.controller.clear_internal_data(confirmed=True).confirmed)
        self.assertEqual((self.retention.temporary_calls, self.retention.internal_calls), (1, 1))


class WorkflowPageBoundaryTests(unittest.TestCase):
    PAGE_MODULES = (
        "tasks_page.py",
        "verification_page.py",
        "sessions_page.py",
        "runs_page.py",
        "settings_page.py",
    )

    def test_page_modules_do_not_import_crawler_services(self) -> None:
        ui_dir = Path(__file__).parents[1] / "ui"
        for filename in self.PAGE_MODULES:
            with self.subTest(filename=filename):
                tree = ast.parse((ui_dir / filename).read_text(encoding="utf-8"))
                imports = [
                    node.module or ""
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                ]
                imports.extend(
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                )
                self.assertFalse(any(name == "crawler" or name.startswith("crawler.") for name in imports))

    def test_all_wide_tables_offer_horizontal_scrolling(self) -> None:
        ui_dir = Path(__file__).parents[1] / "ui"
        for filename in self.PAGE_MODULES[:-1]:
            with self.subTest(filename=filename):
                text = (ui_dir / filename).read_text(encoding="utf-8")
                self.assertIn("xscrollcommand", text)
                self.assertIn("orient=tk.HORIZONTAL", text)

    def test_expanded_task_details_refresh_when_selection_changes(self) -> None:
        page = object.__new__(TasksPage)
        page._details_visible = True
        page.detail_text = Mock()
        page._selected = Mock(
            return_value=TaskView(
                "1", "example.edu", "https://example.edu", "x", "失败", 0,
                "result.xlsx", "查看技术信息", "新的技术信息",
            )
        )

        page._refresh_details()

        page.detail_text.set.assert_called_once_with("新的技术信息")


class ProductionWorkflowTests(unittest.TestCase):
    def test_windows_reveal_uses_explorer_select_without_shell(self) -> None:
        target = Path("C:/reports/problem.zip")
        with patch("desktop_app.os.name", "nt"), patch(
            "desktop_app.subprocess.Popen"
        ) as popen:
            SystemOpener().reveal(target)

        popen.assert_called_once_with(["explorer", "/select,", str(target)])

    def test_settings_chooser_updates_settings_only_without_url_preparation(self) -> None:
        app = object.__new__(DesktopApp)
        app.settings_page = Mock()
        app.settings_page.output_dir.get.return_value = "C:/old"
        app.controller = Mock()
        app.controller.change_settings_output_dir.return_value = type(
            "State", (), {"output_dir": "D:/chosen"}
        )()
        app._prepare = Mock()
        with patch("desktop_app.filedialog.askdirectory", return_value="D:/chosen"):
            app._browse_settings_output()

        app.controller.change_settings_output_dir.assert_called_once_with("D:/chosen")
        app.settings_page.set_output_dir.assert_called_once_with("D:/chosen")
        app._prepare.assert_not_called()

    def test_show_page_marks_only_current_navigation_item_active(self) -> None:
        app = object.__new__(DesktopApp)
        app.pages = {"start": Mock(), "tasks": Mock()}
        app.nav_buttons = {"start": Mock(), "tasks": Mock()}
        app._refresh_workflow_pages = Mock()
        app.after_idle = Mock()

        app._show_page("tasks")

        app.nav_buttons["start"].configure.assert_called_with(style="Nav.TButton")
        app.nav_buttons["tasks"].configure.assert_called_with(
            style="ActiveNav.TButton"
        )

    def test_process_all_waits_for_real_role_thread_before_advancing(self) -> None:
        queue_fake = VerificationQueueFake()
        first_terminal = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        controller = None

        def worker(identity: tuple[str, str]) -> None:
            if identity == ("run-a", "task-a"):
                first_terminal.set()
                release_first.wait(2)
            else:
                second_started.set()

        def starter(run_id: str, task_id: str) -> bool:
            return controller.launch_worker(
                "verification",
                target=worker,
                args=((run_id, task_id),),
            )

        controller = AppController(
            self._testMethodName,
            runner=lambda _tasks, *, timeout: True,
            verification_queue=queue_fake,
            verification_starter=starter,
        )
        self.assertTrue(controller.process_all_verifications())
        self.assertTrue(first_terminal.wait(1))

        self.assertFalse(
            controller.verification_finished(
                "run-a", "task-a", TaskStatus.READY_TO_RESUME
            )
        )
        self.assertTrue(controller.verification_sequence_pending)
        self.assertFalse(controller.process_all_verifications())
        self.assertFalse(controller.start_verification("run-c", "task-c"))
        self.assertTrue(controller.verification_sequence_pending)
        self.assertFalse(controller.continue_verification_sequence())
        self.assertFalse(second_started.is_set())

        release_first.set()
        controller.worker("verification").join(1)
        self.assertTrue(controller.continue_verification_sequence())
        controller.worker("verification").join(1)
        self.assertTrue(second_started.is_set())

    def test_production_retention_uses_only_terminal_failed_task_records(self) -> None:
        now = NOW
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AppPaths.for_user(root / "internal")
            output = root / "output"
            output.mkdir()
            excel = output / "faculty.xlsx"
            excel.write_bytes(b"xlsx")
            queue_path = paths.runs / "verification-queue.json"
            session_path = paths.sessions / "saved.session"
            session_path.write_bytes(b"protected")
            store = TaskStore(paths.tasks)
            terminal = StoredRun(
                "run-terminal",
                [
                    StoredTask("failed", "https://a.edu", str(excel), TaskStatus.FAILED),
                    StoredTask("done", "https://b.edu", str(excel), TaskStatus.SUCCEEDED),
                ],
            )
            mixed = StoredRun(
                "run-mixed",
                [
                    StoredTask("failed", "https://c.edu", str(excel), TaskStatus.FAILED),
                    StoredTask("verify", "https://d.edu", str(excel), TaskStatus.READY_TO_RESUME),
                ],
            )
            store.save(terminal)
            store.save(mixed)
            verification_queue = VerificationQueue(
                paths.runs / "verification-queue.json"
            )
            for run_id, task_id, hostname in (
                ("run-terminal", "failed", "a.edu"),
                ("run-terminal", "done", "b.edu"),
                ("run-terminal", "ghost-task", "ghost.edu"),
                ("run-mixed", "verify", "d.edu"),
            ):
                verification_queue.enqueue(
                    VerificationItem(
                        run_id,
                        task_id,
                        f"https://{hostname}",
                        hostname,
                        "2026-07-23T08:00:00Z",
                        "challenge",
                    )
                )
            verification_queue.mark_ready("run-mixed", "verify")
            malformed = paths.tasks / "malformed.json"
            malformed.write_text("not-json", encoding="utf-8")
            old = (now - timedelta(days=91)).timestamp()
            os.utime(paths.tasks / "run-terminal.json", (old, old))
            os.utime(paths.tasks / "run-mixed.json", (old, old))
            os.utime(malformed, (old, old))

            submitted = ReportRecord(
                "submitted",
                paths.reports / "submitted.zip",
                now - timedelta(days=40),
                now - timedelta(days=31),
            )
            submitted.path.write_bytes(b"report")
            write_report_metadata(submitted)
            unsubmitted = ReportRecord(
                "unsubmitted",
                paths.reports / "unsubmitted.zip",
                now - timedelta(days=400),
                None,
            )
            unsubmitted.path.write_bytes(b"report")
            write_report_metadata(unsubmitted)

            run_records = _discover_failed_run_records(store, paths)
            self.assertEqual(
                [record.run_id for record in run_records], ["run-terminal"]
            )
            self.assertTrue(
                all(record.path.parent == paths.tasks for record in run_records)
            )

            removed = _purge_due_retention(
                RetentionService(paths, clock=lambda: now),
                LocalReportStore(paths, store),
                store,
                paths,
                verification_queue,
            )

            self.assertIn(paths.tasks / "run-terminal.json", removed)
            self.assertFalse((paths.tasks / "run-terminal.json").exists())
            self.assertTrue((paths.tasks / "run-mixed.json").exists())
            self.assertFalse(submitted.path.exists())
            self.assertTrue(unsubmitted.path.exists())
            self.assertTrue(excel.exists())
            self.assertTrue(queue_path.exists())
            self.assertTrue(session_path.exists())
            self.assertTrue(malformed.exists())
            self.assertEqual(
                [
                    (item.run_id, item.task_id)
                    for item in verification_queue.items()
                ],
                [("run-mixed", "verify")],
            )
            malformed.unlink()
            recovered, identities = _recover_desktop_tasks(
                store,
                verification_queue,
            )
            self.assertTrue(recovered)
            self.assertNotIn(("run-terminal", "failed"), identities)
            self.assertNotIn(("run-terminal", "done"), identities)
            self.assertFalse(
                any(
                    item.run_id == "run-terminal"
                    for item in verification_queue.items()
                )
            )

    def test_queue_cleanup_failure_preserves_authoritative_task_run(self) -> None:
        now = NOW
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths.for_user(Path(temp_dir) / "internal")
            store = TaskStore(paths.tasks)
            store.save(
                StoredRun(
                    "run-failed",
                    [
                        StoredTask(
                            "task-failed",
                            "https://a.edu",
                            "D:/output/faculty.xlsx",
                            TaskStatus.FAILED,
                        )
                    ],
                )
            )
            run_path = paths.tasks / "run-failed.json"
            old = (now - timedelta(days=91)).timestamp()
            os.utime(run_path, (old, old))
            verification_queue = Mock()
            verification_queue.remove_run.side_effect = OSError("locked")

            with self.assertRaises(OSError):
                _purge_due_retention(
                    RetentionService(paths, clock=lambda: now),
                    LocalReportStore(paths, store),
                    store,
                    paths,
                    verification_queue,
                )

            self.assertTrue(run_path.exists())

    def test_remove_run_queue_write_failure_preserves_all_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = VerificationQueue(Path(temp_dir) / "queue.json")
            for run_id, task_id, hostname in (
                ("run-purge", "known", "known.edu"),
                ("run-purge", "ghost", "ghost.edu"),
                ("run-keep", "other", "other.edu"),
            ):
                queue.enqueue(
                    VerificationItem(
                        run_id,
                        task_id,
                        f"https://{hostname}",
                        hostname,
                        "2026-07-23T08:00:00Z",
                        "challenge",
                    )
                )
            before = [
                (item.run_id, item.task_id) for item in queue.items()
            ]

            with patch.object(
                queue,
                "_write_unlocked",
                side_effect=OSError("locked"),
            ):
                with self.assertRaises(OSError):
                    queue.remove_run("run-purge")

            self.assertEqual(
                [(item.run_id, item.task_id) for item in queue.items()],
                before,
            )

    def test_verification_controls_reenable_only_after_role_thread_exits(self) -> None:
        class Controller:
            def __init__(self) -> None:
                self.states = iter((True, False))
                self.verification_sequence_pending = False

            @property
            def verification_worker_alive(self) -> bool:
                return next(self.states)

        app = object.__new__(DesktopApp)
        app.controller = Controller()
        app.after = Mock()
        app._set_verification_controls = Mock()

        app._continue_verification_sequence()
        app._set_verification_controls.assert_not_called()
        app.after.assert_called_once_with(25, app._continue_verification_sequence)

        app._continue_verification_sequence()
        app._set_verification_controls.assert_called_once_with(False)


class DesktopLayoutSmokeTests(unittest.TestCase):
    def test_minimum_window_navigation_and_page_focus_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AppPaths.for_user(root / "internal")
            owner = type("Owner", (), {"acquired": True, "close": lambda self: None})()
            queue = VerificationQueueFake()
            sessions = SessionsFake()
            reports = ReportsFake(root)
            settings = SettingsFake(root)
            retention = RetentionFake()
            try:
                app = DesktopApp(
                    verification_queue=queue,
                    verification_service=object(),
                    session_store=sessions,
                    workflow_owner=owner,
                    app_paths=paths,
                    settings_store=settings,
                    retention_service=retention,
                    report_store=reports,
                    opener=OpenerFake(),
                )
            except tk.TclError as exc:
                self.skipTest(f"Tk display unavailable: {exc}")
            try:
                app.geometry("900x650")
                app.update()
                self.assertEqual(set(app.pages), {"start", "tasks", "verification", "sessions", "runs", "settings"})
                self.assertEqual(app.minsize(), (900, 650))
                for name in app.pages:
                    app._show_page(name)
                    app.update()
                    self.assertTrue(app.pages[name].winfo_ismapped())
                    self.assertLessEqual(
                        app.pages[name].winfo_width(), app.page_host.winfo_width()
                    )
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
