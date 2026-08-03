from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from crawler.app_paths import AppPaths
from desktop_ui.models import AiSettingsView, AiUsageView, SaveAiSettings
from desktop_ui.pages.ai_settings import AiSettingsPage
from desktop_ui.workflow_facade import WorkflowFacade
from faculty_workflow.ai_settings import AiSettingsStore
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import DisciplinePolicy, SchoolInput


APP = QApplication.instance() or QApplication([])


class AiSettingsFacade:
    """A UI-only facade fixture that never contains an API key."""

    def __init__(self) -> None:
        self.settings = AiSettingsView(
            enabled=True,
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            key_configured=True,
        )
        self.usage = AiUsageView(128, 126, 2, 1_620_000, 220_000, 2.74)
        self.saved: list[SaveAiSettings] = []
        self.deleted = False
        self.connection_tests = 0

    def ai_settings(self) -> AiSettingsView:
        return self.settings

    def ai_usage(self) -> AiUsageView:
        return self.usage

    def save_ai_settings(self, command: SaveAiSettings) -> AiSettingsView:
        self.saved.append(command)
        self.settings = AiSettingsView(
            command.enabled,
            command.provider if command.enabled else "local",
            command.base_url if command.enabled else "",
            command.model if command.enabled else "",
            self.settings.key_configured if command.api_key is None else bool(command.api_key),
        )
        return self.settings

    def delete_ai_key(self) -> AiSettingsView:
        self.deleted = True
        self.settings = AiSettingsView(
            self.settings.enabled,
            self.settings.provider,
            self.settings.base_url,
            self.settings.model,
            False,
        )
        return self.settings

    def test_ai_connection(self) -> object:
        self.connection_tests += 1
        return object()

    def ai_usage_details(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "created_at": "2026-07-31T14:32:00+00:00",
                "task_id": "task-1",
                "operation": "extract_profile",
                "model": "deepseek-v4-flash",
                "input_tokens": 1200,
                "output_tokens": 180,
                "estimated_cost_usd": 0.02,
                "status": "succeeded",
            },
        )


class AiSettingsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = AiSettingsFacade()
        self.page = AiSettingsPage(self.facade)
        self.page.show()
        QTest.qWaitForWindowExposed(self.page)

    def tearDown(self) -> None:
        self.page.close()

    def test_saved_key_is_masked_and_never_inserted_into_editor(self) -> None:
        self.page.refresh()

        self.assertEqual(self.page.key_status.text(), "已配置")
        self.page.open_replace_key_dialog()
        self.assertEqual(self.page.key_dialog.key_edit.text(), "")
        self.assertEqual(self.page.key_dialog.key_edit.echoMode(), QLineEdit.Password)

    def test_usage_cards_render_database_values(self) -> None:
        self.page.refresh()

        self.assertEqual(self.page.calls_value.text(), "128")
        self.assertEqual(self.page.tokens_value.text(), "1.84M")
        self.assertEqual(self.page.cost_value.text(), "$2.74")
        self.assertIn("126", self.page.calls_note.text())
        self.assertEqual(self.page.usage_table.rowCount(), 1)

    def test_metadata_save_uses_none_and_never_the_masked_status_as_a_key(self) -> None:
        self.page.refresh()
        self.page.model_edit.setText("deepseek-v4-pro")
        self.page.save_settings()

        command = self.facade.saved[-1]
        self.assertIsNone(command.api_key)
        self.assertEqual(command.model, "deepseek-v4-pro")

    def test_replace_key_submits_only_transient_editor_text_then_clears_it(self) -> None:
        self.page.open_replace_key_dialog()
        self.page.key_dialog.key_edit.setText("replace-me")
        self.page.key_dialog.accept()

        self.assertEqual(self.facade.saved[-1].api_key, "replace-me")
        self.assertEqual(self.page.key_dialog.key_edit.text(), "")
        self.assertEqual(self.page.key_status.text(), "已配置")

    def test_delete_key_uses_the_explicit_facade_action(self) -> None:
        self.page.delete_key()

        self.assertTrue(self.facade.deleted)
        self.assertEqual(self.page.key_status.text(), "未配置")

    def test_connection_test_is_non_blocking_and_updates_status(self) -> None:
        self.page.test_connection()
        thread = self.page._connection_thread
        self.assertIsNotNone(thread)
        self.assertTrue(thread.wait(1000))
        APP.processEvents()

        self.assertEqual(self.facade.connection_tests, 1)
        self.assertEqual(self.page.connection_status.text(), "测试成功")


class AiUsageFacadeTests(unittest.TestCase):
    def test_ai_usage_exposes_current_month_database_totals(self) -> None:
        """The AI settings screen must receive totals from recorded API calls."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AppPaths.for_user(root / "app")
            database = WorkflowDatabase(root / "workflow.sqlite3")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University")],
                output_dir=root / "output",
                policy_confirmed=True,
            )
            database.record_api_call(
                task_id,
                operation="parse",
                model="model-a",
                input_tokens=100,
                output_tokens=25,
                estimated_cost_usd=0.04,
                status="succeeded",
            )
            facade = WorkflowFacade(
                service=object(),
                database=database,
                ai_settings_store=AiSettingsStore(paths.settings),
                app_paths=paths,
            )

            usage = facade.ai_usage()

            self.assertEqual(usage.calls, 1)
            self.assertEqual(usage.succeeded, 1)
            self.assertEqual(usage.failed, 0)
            self.assertEqual(usage.input_tokens, 100)
            self.assertEqual(usage.output_tokens, 25)
            self.assertEqual(usage.estimated_cost_usd, 0.04)


if __name__ == "__main__":
    unittest.main()
