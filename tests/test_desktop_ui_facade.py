from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crawler.app_paths import AppPaths
from desktop_ui.models import NewCrawlRequest, SaveAiSettings
from desktop_ui.workflow_facade import WorkflowFacade
from faculty_workflow.ai_settings import AiSettingsStore, ProviderConfiguration
from faculty_workflow.database import WorkflowDatabase


class ReversibleProtector:
    def protect(self, value: bytes) -> bytes:
        return value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        return value[::-1]


class DirectTaskService:
    def __init__(self) -> None:
        self.commands: list[dict[str, object]] = []
        self.provider = object()

    def create_direct_url_task(self, **command: object) -> str:
        self.commands.append(command)
        return "task-1"

    def create_task_from_schools(self, **command: object) -> str:
        self.commands.append(command)
        return "task-xlsx"

    def export(self, task_id: str, output_dir=None):
        self.exported = (task_id, output_dir)
        return {"accepted": Path("output") / "accepted.xlsx"}

    def cancel_access_verification(self) -> None:
        self.cancelled_verification = True


class WorkflowFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = AppPaths.for_user(self.root / "app")
        self.database = WorkflowDatabase(self.root / "workflow.sqlite3")
        self.settings = AiSettingsStore(self.paths.settings, protector=ReversibleProtector())
        self.service = DirectTaskService()
        self.facade = WorkflowFacade(
            self.service, self.database, self.settings, self.paths
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_prepare_urls_reports_valid_duplicate_and_invalid_lines(self) -> None:
        result = self.facade.prepare_urls(
            "https://a.edu/faculty\nhttps://a.edu/faculty\nnot-a-url"
        )

        self.assertEqual(result.valid_urls, ("https://a.edu/faculty",))
        self.assertEqual(result.duplicate_lines, ((2, "https://a.edu/faculty"),))
        self.assertEqual(result.invalid_lines, ((3, "not-a-url"),))
        self.assertFalse(result.can_start)

    def test_ai_view_never_returns_plaintext_key(self) -> None:
        self.settings.save(ProviderConfiguration.deepseek(), "secret-key")

        view = self.facade.ai_settings()

        self.assertTrue(view.key_configured)
        self.assertFalse(hasattr(view, "api_key"))

    def test_create_direct_tasks_creates_one_task_for_prepared_urls(self) -> None:
        task_id = self.facade.create_direct_tasks(
            NewCrawlRequest(
                urls=("https://a.edu/faculty", "https://b.edu/people"),
                output_dir=self.paths.reports,
                discipline="Physics",
            )
        )

        self.assertEqual(task_id, "task-1")
        self.assertEqual(
            self.service.commands[0]["directory_urls"],
            ("https://a.edu/faculty", "https://b.edu/people"),
        )

    def test_save_ai_settings_retains_existing_key_when_key_is_omitted(self) -> None:
        self.settings.save(ProviderConfiguration.deepseek(), "secret-key")

        view = self.facade.save_ai_settings(
            SaveAiSettings(
                enabled=True,
                provider="deepseek",
                base_url="https://api.deepseek.com",
                model="deepseek-v4-pro",
            )
        )

        configuration, key = self.settings.load()
        self.assertTrue(view.key_configured)
        self.assertEqual(configuration.model, "deepseek-v4-pro")
        self.assertEqual(key, "secret-key")

    def test_delete_ai_key_disables_ai_and_removes_only_the_explicit_key(self) -> None:
        self.settings.save(ProviderConfiguration.deepseek(), "secret-key")

        view = self.facade.delete_ai_key()
        configuration, key = self.settings.load()

        self.assertFalse(view.enabled)
        self.assertFalse(view.key_configured)
        self.assertEqual(configuration, ProviderConfiguration.local())
        self.assertEqual(key, "")

    def test_xlsx_task_is_confirmed_for_the_immediate_desktop_run(self) -> None:
        school = type("School", (), {})()
        self.facade.create_xlsx_task((school,), NewCrawlRequest((), self.paths.reports))

        self.assertTrue(self.service.commands[0]["policy_confirmed"])

    def test_save_and_delete_replace_the_live_provider_without_returning_key(self) -> None:
        self.facade.save_ai_settings(
            SaveAiSettings(True, "deepseek", "https://api.deepseek.com", "deepseek-v4-pro", "secret-key")
        )
        configured = self.service.provider
        self.assertEqual(getattr(configured, "api_key"), "secret-key")

        self.facade.delete_ai_key()

        self.assertNotEqual(self.service.provider, configured)
        self.assertEqual(getattr(self.service.provider, "api_key", ""), "")

    def test_export_and_defer_are_worker_safe_facade_operations(self) -> None:
        exported = self.facade.export_task("task-1")
        self.facade.defer_verification("7")

        self.assertEqual(exported["accepted"], Path("output") / "accepted.xlsx")
        self.assertTrue(self.service.cancelled_verification)

    def test_task_detail_redacts_secret_bearing_diagnostics(self) -> None:
        self.database.summary = lambda _task_id: {
            "id": "task", "discipline": "Physics", "status": "failed", "output_dir": "out",
            "created_at": "now", "updated_at": "now", "schools": {}, "candidates": {},
            "spent_usd": 0, "budget_usd": 20, "warning": "token=secret", "error": "api_key: abc",
        }

        detail = self.facade.task_detail("task")

        self.assertNotIn("secret", detail["warning"])
        self.assertNotIn("abc", detail["error"])


if __name__ == "__main__":
    unittest.main()
