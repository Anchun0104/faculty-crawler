from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMessageBox


class FakeFacade:
    def task_rows(self, **_kwargs):
        return ({"id": "task-1", "discipline": "Physics", "status": "completed", "created_at": "now", "updated_at": "now", "output_dir": "C:/output"},)
    def task_detail(self, task_id):
        return {"id": task_id, "discipline": "Physics", "status": "completed", "schools": 1, "records": 0, "output_dir": "C:/output"}
    def verification_rows(self, **_kwargs):
        return ({"id": "1", "task_id": "task-1", "school": "Stanford", "url": "https://cs.stanford.edu", "reason": "challenge", "status": "pending"},)
    def session_rows(self):
        return ({"hostname": "cs.stanford.edu", "saved_at": "now", "expires_at": "later"},)
    def storage_summary(self):
        return {"bytes": 1024, "files": 2}


class DesktopPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_task_selection_opens_360px_inspector(self):
        from desktop_ui.pages.tasks import TasksPage
        page = TasksPage(FakeFacade())
        page.show()
        page.select_task("task-1")
        self.assertTrue(page.inspector.isVisible())
        self.assertEqual(page.inspector.width(), 360)

    def test_verification_page_states_compliance_boundary(self):
        from desktop_ui.pages.verification import VerificationPage
        page = VerificationPage(FakeFacade())
        self.assertIn("不会自动破解 CAPTCHA", page.info_bar.text())

    def test_session_clear_emits_exact_hostname(self):
        from desktop_ui.pages.sessions import SessionsPage
        page = SessionsPage(FakeFacade())
        spy = QSignalSpy(page.clear_requested)
        page.request_clear("cs.stanford.edu")
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0), ["cs.stanford.edu"])

    def test_overview_and_runs_refresh_without_data_access(self):
        from desktop_ui.pages.overview import OverviewPage
        from desktop_ui.pages.runs import RunsPage
        facade = FakeFacade()
        overview = OverviewPage(facade)
        runs = RunsPage(facade)
        self.assertEqual(overview.task_count.text(), "1")
        self.assertEqual(runs.table.rowCount(), 1)

    def test_storage_refresh_renders_safe_summary(self):
        from desktop_ui.pages.storage import StoragePage
        page = StoragePage(FakeFacade())
        self.assertIn("1.0 KB", page.usage_label.text())

    def test_temporary_cleanup_requires_confirmation(self):
        from desktop_ui.pages.storage import StoragePage
        page = StoragePage(FakeFacade())
        spy = QSignalSpy(page.clear_temporary_requested)
        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *_args: QMessageBox.No)
        try:
            page.clear_temp_button.click()
            self.assertEqual(spy.count(), 0)
            QMessageBox.question = staticmethod(lambda *_args: QMessageBox.Yes)
            page.clear_temp_button.click()
        finally:
            QMessageBox.question = original
        self.assertEqual(spy.count(), 1)

    def test_verification_has_selected_site_workflow_pane(self):
        from desktop_ui.pages.verification import VerificationPage
        page = VerificationPage(FakeFacade())
        page.select_review("1")
        self.assertIn("https://cs.stanford.edu", page.selected_site_label.text())
        self.assertIn("Visible browser", page.browser_status_label.text())
        self.assertIn("1.", page.instructions_label.text())

    def test_refresh_clears_stale_session_and_verification_selections(self):
        from desktop_ui.pages.sessions import SessionsPage
        from desktop_ui.pages.verification import VerificationPage
        facade = FakeFacade()
        sessions = SessionsPage(facade)
        verification = VerificationPage(facade)
        sessions._select("cs.stanford.edu")
        verification.select_review("1")
        facade.session_rows = lambda: ()
        facade.verification_rows = lambda **_kwargs: ()
        sessions.refresh(); verification.refresh()
        self.assertFalse(sessions.clear_button.isEnabled())
        self.assertFalse(verification.start_button.isEnabled())

    def test_task_filter_offers_policy_confirmation_status(self):
        from desktop_ui.pages.tasks import TasksPage
        page = TasksPage(FakeFacade())
        self.assertGreaterEqual(page.status_filter.findText("needs_policy_confirmation"), 0)

    def test_task_export_emits_the_selected_completed_batch(self):
        from desktop_ui.pages.tasks import TasksPage
        page = TasksPage(FakeFacade())
        spy = QSignalSpy(page.export_requested)

        page.select_task("task-1")
        page.export_button.click()

        self.assertEqual(spy.at(0), ["task-1"])

    def test_run_history_exports_the_selected_completed_batch(self):
        from desktop_ui.pages.runs import RunsPage
        page = RunsPage(FakeFacade())
        spy = QSignalSpy(page.export_requested)

        page._select("task-1")
        page.export_button.click()

        self.assertEqual(spy.at(0), ["task-1"])

    def test_data_table_uses_soft_row_treatment_without_grid(self):
        from desktop_ui.widgets.data_table import DataTable
        table = DataTable(("Value",))
        self.assertFalse(table.showGrid())
