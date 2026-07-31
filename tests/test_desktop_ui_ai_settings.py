from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crawler.app_paths import AppPaths
from desktop_ui.workflow_facade import WorkflowFacade
from faculty_workflow.ai_settings import AiSettingsStore
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import DisciplinePolicy, SchoolInput


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
