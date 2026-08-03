from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from desktop_ui.dialogs.new_crawl import NewCrawlDialog
from desktop_ui.models import NewCrawlRequest, UrlPreparation
from desktop_ui.workflow_facade import WorkflowFacade
from crawler.app_paths import AppPaths
from faculty_workflow.ai_settings import AiSettingsStore
from faculty_workflow.database import WorkflowDatabase


APP = QApplication.instance() or QApplication([])


class RecordingFacade:
    def __init__(self) -> None:
        self.created_direct: list[NewCrawlRequest] = []
        self.created_xlsx: list[tuple[tuple[object, ...], NewCrawlRequest]] = []
        self.prepare_url_calls = 0

    def prepare_urls(self, raw: str) -> UrlPreparation:
        self.prepare_url_calls += 1
        valid: list[str] = []
        duplicates: list[tuple[int, str]] = []
        invalid: list[tuple[int, str]] = []
        seen: set[str] = set()
        for number, line in enumerate(raw.splitlines(), start=1):
            value = line.strip()
            if not value:
                continue
            if not value.startswith("https://"):
                invalid.append((number, value))
            elif value in seen:
                duplicates.append((number, value))
            else:
                seen.add(value)
                valid.append(value)
        return UrlPreparation(tuple(valid), tuple(duplicates), tuple(invalid))

    def prepare_schools_file(self, path: str | Path) -> tuple[object, ...]:
        if Path(path).suffix.casefold() != ".xlsx":
            raise ValueError("请选择 XLSX 文件")
        return (object(), object())

    def create_direct_tasks(self, request: NewCrawlRequest) -> str:
        self.created_direct.append(request)
        return "direct-task"

    def create_xlsx_task(self, schools: tuple[object, ...], request: NewCrawlRequest) -> str:
        self.created_xlsx.append((schools, request))
        return "xlsx-task"


class SpreadsheetTaskService:
    def __init__(self) -> None:
        self.commands: list[dict[str, object]] = []

    def create_task_from_schools(self, **command: object) -> str:
        self.commands.append(command)
        return "xlsx-task"


class NewCrawlDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = RecordingFacade()
        self.dialog = NewCrawlDialog(self.facade, default_output_dir=Path("output"))

    def tearDown(self) -> None:
        self.dialog.close()

    def test_twenty_valid_urls_enable_exact_task_count(self) -> None:
        """A pasted 20-line list must remain uncapped in one workflow batch."""
        urls = "\n".join(f"https://school-{index}.edu/faculty" for index in range(20))

        self.dialog.url_editor.setPlainText(urls)
        QTest.qWait(160)

        self.assertEqual(self.dialog.summary_label.text(), "20 个有效 · 将创建 1 个批次任务，包含 20 所学校")
        self.assertEqual(self.dialog.start_button.text(), "开始批次（20 所学校）")
        self.assertTrue(self.dialog.start_button.isEnabled())
        self.assertIn("输出目录：output", self.dialog.confirmation_label.text())

    def test_duplicate_urls_are_ignored_without_blocking_valid_submission(self) -> None:
        """Removing duplicate handling would create redundant crawl work."""
        self.dialog.url_editor.setPlainText(
            "https://one.edu/faculty\nhttps://one.edu/faculty\nhttps://two.edu/people"
        )
        QTest.qWait(160)

        self.assertEqual(self.dialog.summary_label.text(), "2 个有效 · 1 个重复已忽略 · 将创建 1 个批次任务，包含 2 所学校")
        self.assertTrue(self.dialog.start_button.isEnabled())
        self.dialog.duplicate_details_button.click()
        self.assertEqual(
            self.dialog.duplicate_details_label.text(),
            "第 2 行：https://one.edu/faculty",
        )
        self.assertFalse(self.dialog.duplicate_details_label.isHidden())

    def test_invalid_lines_block_submission_and_name_every_line(self) -> None:
        """Submitting malformed URLs would let a partial paste silently run."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty\nwrong\nalso-wrong")
        QTest.qWait(160)

        self.assertFalse(self.dialog.start_button.isEnabled())
        self.assertEqual(self.dialog.validation_label.text(), "第 2、3 行 URL 无效")

    def test_valid_submission_emits_the_prepared_request_without_ui_thread_creation(self) -> None:
        """The window owns background task creation after the dialog emits intent."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty\nhttps://one.edu/faculty")
        QTest.qWait(160)
        spy = QSignalSpy(self.dialog.requested)

        self.dialog.start_button.click()

        self.assertEqual(spy.count(), 1)
        self.assertEqual(self.facade.created_direct, [])
        self.assertEqual(
            spy.at(0)[0].urls,
            ("https://one.edu/faculty",),
        )

    def test_xlsx_mode_emits_prevalidated_source_without_ui_thread_creation(self) -> None:
        """The dialog validates XLSX then leaves task creation to the window worker."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schools.xlsx"
            workbook = Workbook()
            workbook.active.append(["school", "directory_url"])
            workbook.active.append(["One University", "https://one.edu/faculty"])
            workbook.save(path)
            workbook.close()

            self.dialog.select_xlsx_mode()
            self.dialog.set_xlsx_path(path)

            self.assertEqual(self.dialog.summary_label.text(), "2 所学校已验证 · 将创建 1 个批次任务，包含 2 所学校")
            self.assertTrue(self.dialog.start_button.isEnabled())
            spy = QSignalSpy(self.dialog.xlsx_requested)
            self.dialog.start_button.click()

            self.assertEqual(self.facade.created_xlsx, [])
            self.assertEqual(spy.count(), 1)
            self.assertEqual(spy.at(0)[0], str(path))

    def test_multiple_urls_with_school_override_block_submission(self) -> None:
        """A school override applied to several URLs would violate service validation."""
        self.dialog.school_name_edit.setText("One University")
        self.dialog.url_editor.setPlainText("https://one.edu/faculty\nhttps://two.edu/faculty")
        QTest.qWait(160)

        self.assertFalse(self.dialog.start_button.isEnabled())
        self.assertEqual(self.dialog.validation_label.text(), "学校名称仅可用于单个 URL")

    def test_direct_start_does_not_bypass_multi_url_school_override_validation(self) -> None:
        """A programmatic start must enforce the same override rule as the disabled UI."""
        self.dialog.school_name_edit.setText("One University")
        self.dialog.url_editor.setPlainText("https://one.edu/faculty\nhttps://two.edu/faculty")
        QTest.qWait(160)

        self.dialog._start()

        self.assertEqual(self.facade.created_direct, [])

    def test_url_validation_is_debounced_after_editing(self) -> None:
        """Calling the facade on every keystroke would make a large paste unnecessarily expensive."""
        initial_calls = self.facade.prepare_url_calls
        self.dialog.url_editor.setPlainText("https://one.edu/faculty")

        self.assertEqual(self.facade.prepare_url_calls, initial_calls)
        QTest.qWait(160)
        self.assertEqual(self.facade.prepare_url_calls, initial_calls + 1)

    def test_start_revalidates_when_an_edit_is_still_waiting_for_debounce(self) -> None:
        """A click after an invalid edit must not submit the prior valid URL state."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty")
        QTest.qWait(160)
        self.dialog.url_editor.setPlainText("not-a-url")

        self.dialog.start_button.click()

        self.assertEqual(self.facade.created_direct, [])

    def test_pending_url_debounce_cannot_overwrite_xlsx_state(self) -> None:
        """Switching source modes must cancel URL work before it updates XLSX controls."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty")
        self.dialog.select_xlsx_mode()
        self.dialog.set_xlsx_path(Path("schools.xlsx"))

        QTest.qWait(160)

        self.assertEqual(self.dialog.summary_label.text(), "2 所学校已验证 · 将创建 1 个批次任务，包含 2 所学校")
        self.assertEqual(self.dialog.start_button.text(), "开始批次（2 所学校）")

    def test_output_edit_refreshes_batch_confirmation(self) -> None:
        """The explicit output confirmation must follow manual directory edits."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty")
        QTest.qWait(160)

        self.dialog.output_dir_edit.setText("manual-output")

        self.assertIn("输出目录：manual-output", self.dialog.confirmation_label.text())

    def test_access_compliance_infobar_is_visible_before_batch_start(self) -> None:
        """Operators need an explicit access reminder before initiating a crawl batch."""
        self.assertIn("robots", self.dialog.compliance_info.message())
        self.assertFalse(self.dialog.compliance_info.isHidden())

    def test_facade_validates_xlsx_with_the_existing_school_importer(self) -> None:
        """A second spreadsheet parser could accept files the workflow later rejects."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "schools.xlsx"
            workbook = Workbook()
            workbook.active.append(["school", "directory_url"])
            workbook.active.append(["One University", "https://one.edu/faculty"])
            workbook.save(path)
            workbook.close()
            service = SpreadsheetTaskService()
            paths = AppPaths.for_user(root / "app")
            facade = WorkflowFacade(
                service=service,
                database=WorkflowDatabase(root / "workflow.sqlite3"),
                ai_settings_store=AiSettingsStore(paths.settings),
                app_paths=paths,
            )

            with patch("desktop_ui.workflow_facade.load_schools", wraps=__import__("faculty_workflow.importers", fromlist=["load_schools"]).load_schools) as importer:
                schools = facade.prepare_schools_file(path)
                task_id = facade.create_xlsx_task(
                    schools,
                    NewCrawlRequest(urls=(), output_dir=root / "output", discipline="Physics"),
                )

            self.assertEqual([school.name for school in schools], ["One University"])
            self.assertEqual(task_id, "xlsx-task")
            self.assertEqual(importer.call_count, 1)
            self.assertIs(service.commands[0]["schools"], schools)
            self.assertEqual(
                [school.name for school in service.commands[0]["schools"]],
                ["One University"],
            )


if __name__ == "__main__":
    unittest.main()
