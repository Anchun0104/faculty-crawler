from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook
from PySide6.QtTest import QSignalSpy
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
        self.created_xlsx: list[tuple[Path, NewCrawlRequest]] = []

    def prepare_urls(self, raw: str) -> UrlPreparation:
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

    def create_xlsx_task(self, path: str | Path, request: NewCrawlRequest) -> str:
        self.created_xlsx.append((Path(path), request))
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
        """A pasted 20-line list must remain uncapped and ready to submit."""
        urls = "\n".join(f"https://school-{index}.edu/faculty" for index in range(20))

        self.dialog.url_editor.setPlainText(urls)

        self.assertEqual(self.dialog.summary_label.text(), "20 个有效 · 将创建 20 个独立任务")
        self.assertEqual(self.dialog.start_button.text(), "开始 20 个任务")
        self.assertTrue(self.dialog.start_button.isEnabled())

    def test_duplicate_urls_are_ignored_without_blocking_valid_submission(self) -> None:
        """Removing duplicate handling would create redundant crawl work."""
        self.dialog.url_editor.setPlainText(
            "https://one.edu/faculty\nhttps://one.edu/faculty\nhttps://two.edu/people"
        )

        self.assertEqual(self.dialog.summary_label.text(), "2 个有效 · 1 个重复已忽略 · 将创建 2 个独立任务")
        self.assertTrue(self.dialog.start_button.isEnabled())

    def test_invalid_lines_block_submission_and_name_every_line(self) -> None:
        """Submitting malformed URLs would let a partial paste silently run."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty\nwrong\nalso-wrong")

        self.assertFalse(self.dialog.start_button.isEnabled())
        self.assertEqual(self.dialog.validation_label.text(), "第 2、3 行 URL 无效")

    def test_valid_submission_emits_and_creates_the_prepared_request(self) -> None:
        """The start action must use the facade's normalized unique URLs."""
        self.dialog.url_editor.setPlainText("https://one.edu/faculty\nhttps://one.edu/faculty")
        spy = QSignalSpy(self.dialog.requested)

        self.dialog.start_button.click()

        self.assertEqual(spy.count(), 1)
        self.assertEqual(len(self.facade.created_direct), 1)
        self.assertEqual(
            self.facade.created_direct[0].urls,
            ("https://one.edu/faculty",),
        )

    def test_xlsx_mode_uses_the_facade_importer_validation_and_creation(self) -> None:
        """The dialog must delegate spreadsheet handling instead of parsing it itself."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schools.xlsx"
            workbook = Workbook()
            workbook.active.append(["school", "directory_url"])
            workbook.active.append(["One University", "https://one.edu/faculty"])
            workbook.save(path)
            workbook.close()

            self.dialog.select_xlsx_mode()
            self.dialog.set_xlsx_path(path)

            self.assertEqual(self.dialog.summary_label.text(), "2 所学校已验证 · 将创建 1 个采集任务")
            self.assertTrue(self.dialog.start_button.isEnabled())
            self.dialog.start_button.click()

            self.assertEqual(len(self.facade.created_xlsx), 1)
            self.assertEqual(self.facade.created_xlsx[0][0], path)

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

            schools = facade.prepare_schools_file(path)
            task_id = facade.create_xlsx_task(
                path,
                NewCrawlRequest(urls=(), output_dir=root / "output", discipline="Physics"),
            )

            self.assertEqual([school.name for school in schools], ["One University"])
            self.assertEqual(task_id, "xlsx-task")
            self.assertEqual(
                [school.name for school in service.commands[0]["schools"]],
                ["One University"],
            )


if __name__ == "__main__":
    unittest.main()
