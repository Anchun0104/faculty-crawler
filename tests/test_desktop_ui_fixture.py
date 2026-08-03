from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktop_ui.app import _resolve_facade
from desktop_ui.fixture import FixtureFacade
from desktop_ui.main_window import MainWindow


class DesktopUiFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_fixture_is_deterministic_and_covers_approved_data_states(self) -> None:
        facade = FixtureFacade()

        self.assertEqual(
            tuple(row["status"] for row in facade.task_rows()),
            ("running", "needs_verification", "completed", "queued"),
        )
        self.assertEqual(len(facade.verification_rows()), 3)
        self.assertEqual(len(facade.session_rows()), 3)
        self.assertEqual(facade.storage_summary()["snapshot_bytes"], 438 * 1024 * 1024)
        self.assertEqual(facade.ai_usage().calls, 128)

    def test_fixture_resolver_requires_explicit_opt_in(self) -> None:
        explicit = _resolve_facade(None, fixture=True)
        self.assertIsInstance(explicit, FixtureFacade)
        with patch.dict(os.environ, {"FACULTY_CRAWLER_UI_FIXTURE": "1"}):
            self.assertIsInstance(_resolve_facade(), FixtureFacade)

    def test_fixture_facade_can_construct_real_shell_without_workflow_dependencies(self) -> None:
        window = MainWindow(facade=FixtureFacade())
        self.addCleanup(window.shutdown)
        self.assertEqual(window.windowTitle(), "教师目录采集器")
        self.assertEqual(window.overview_page.table.rowCount(), 4)
        self.assertEqual(window.runs_page.timeline.objectName(), "runTimeline")
        self.assertEqual(window.settings_page.ai_page.key_status.text(), "已配置")
