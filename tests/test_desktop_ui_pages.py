from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox


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

    def test_overview_shows_live_profile_progress_with_target(self):
        from desktop_ui.pages.overview import OverviewPage

        facade = FakeFacade()
        facade.task_rows = lambda **_kwargs: (
            {"id": "task-1", "discipline": "Linguistics", "status": "running", "name": "Stanford", "updated_at": "now"},
        )
        page = OverviewPage(facade)

        page.set_live_progress(
            {
                "task_id": "task-1",
                "message": "profile_page_started",
                "school_name": "Stanford Linguistics",
                "url": "https://linguistics.stanford.edu/people/faculty/jane-doe",
            }
        )

        self.assertIn("教师页", page.current_run_progress.text())
        self.assertIn("Stanford Linguistics", page.current_run_progress.text())
        self.assertIn("linguistics.stanford.edu", page.current_run_progress.text())

    def test_work_pages_use_chinese_headers_and_approved_composition(self):
        from desktop_ui.pages.overview import OverviewPage
        from desktop_ui.pages.tasks import TasksPage
        from desktop_ui.pages.verification import VerificationPage

        overview = OverviewPage(FakeFacade())
        tasks = TasksPage(FakeFacade())
        verification = VerificationPage(FakeFacade())

        self.assertEqual(overview.page_header.title.text(), "概览")
        self.assertEqual(overview.quick_start_card.objectName(), "quickStartCard")
        self.assertEqual(overview.current_run_card.objectName(), "currentRunCard")
        self.assertEqual(overview.attention_section.objectName(), "attentionSection")
        self.assertEqual(tasks.page_header.title.text(), "任务")
        self.assertEqual(tasks.search.accessibleName(), "搜索任务或站点")
        self.assertEqual(tasks.status_filter.itemText(0), "全部")
        self.assertEqual(tasks.inspector.width(), 360)
        self.assertEqual(verification.page_header.title.text(), "人工验证")
        self.assertEqual(verification.mock_browser.objectName(), "mockBrowserCard")
        self.assertIn("1. 打开可见浏览器", verification.instructions_label.text())
        self.assertIn("不会自动破解 CAPTCHA", verification.info_bar.text())

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
        self.assertIn("可见浏览器", page.browser_status_label.text())
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
        self.assertGreaterEqual(page.status_filter.findText("待确认口径"), 0)

    def test_settings_shows_only_implemented_categories(self):
        from desktop_ui.pages.settings import SettingsPage

        page = SettingsPage(FakeFacade())

        self.assertEqual(tuple(page._section_buttons), ("ai", "storage"))
        self.assertEqual(page.page_header.title.text(), "设置")
        self.assertEqual(
            tuple(button.text() for button in page._section_buttons.values()),
            ("翻译与 AI", "存储与诊断"),
        )
        self.assertEqual(page.search_edit.accessibleName(), "搜索设置")

    def test_ai_and_storage_pages_keep_technical_names_but_localize_controls(self):
        from desktop_ui.pages.ai_settings import AiSettingsPage
        from desktop_ui.pages.storage import StoragePage

        ai_page = AiSettingsPage(FakeFacade())
        storage_page = StoragePage(FakeFacade())

        self.assertEqual(ai_page.accessibleName(), "翻译与 AI 设置")
        self.assertEqual(ai_page.enabled_checkbox.text(), "启用外部 AI 辅助")
        self.assertEqual(ai_page.test_connection_button.text(), "测试连接")
        self.assertEqual(storage_page.section_title.text(), "存储与诊断")
        self.assertEqual(storage_page.export_button.text(), "导出诊断包")
        self.assertEqual(storage_page.clear_temp_button.text(), "清理临时数据")

    def test_internal_clear_copy_preserves_task_history_and_database(self):
        from desktop_ui.pages.storage import StoragePage

        page = StoragePage(FakeFacade())
        self.assertIn("工作流数据库", page.clear_internal_button.toolTip())

    def test_internal_clear_confirmation_states_diagnostic_zips_are_preserved(self):
        from desktop_ui.pages.storage import StoragePage

        page = StoragePage(FakeFacade())
        captured: list[str] = []
        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *_args: (captured.append(_args[2]), QMessageBox.No)[1])
        try:
            page._confirm_internal_clear()
        finally:
            QMessageBox.question = original

        self.assertIn("诊断 ZIP", captured[0])
        self.assertIn("工作流数据库", captured[0])

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

    def test_run_history_uses_batch_detail_and_timeline_composition(self):
        from desktop_ui.pages.runs import RunsPage

        page = RunsPage(FakeFacade())

        self.assertEqual(page.page_header.title.text(), "运行历史")
        self.assertEqual(page.search.accessibleName(), "搜索运行或站点")
        self.assertEqual(page.detail_panel.objectName(), "runDetailPanel")
        self.assertEqual(page.timeline.objectName(), "runTimeline")
        self.assertEqual(page.metrics[0].objectName(), "acceptedMetric")
        self.assertIn("已接受", page.metrics[0].findChild(QLabel).text())

    def test_site_sessions_uses_expiry_badges_and_chinese_destructive_copy(self):
        from desktop_ui.pages.sessions import SessionsPage

        page = SessionsPage(FakeFacade())

        self.assertEqual(page.page_header.title.text(), "站点会话")
        self.assertEqual(page.search.accessibleName(), "搜索站点")
        self.assertEqual(page.table.horizontalHeaderItem(0).text(), "站点")
        self.assertEqual(page.table.horizontalHeaderItem(3).text(), "计划清理")
        self.assertEqual(page.clear_button.text(), "清除所选会话")
        self.assertIn("加密", page.info_bar.text())

    def test_data_table_uses_soft_row_treatment_without_grid(self):
        from desktop_ui.widgets.data_table import DataTable
        table = DataTable(("Value",))
        self.assertFalse(table.showGrid())
        self.assertEqual(table.verticalHeader().defaultSectionSize(), 40)
        self.assertEqual(table.horizontalHeader().defaultSectionSize(), 36)

    def test_empty_state_has_a_line_icon_and_optional_primary_action(self):
        from desktop_ui.widgets.empty_state import EmptyState

        state = EmptyState("暂无任务", "创建一次采集即可开始。", "新建采集")
        self.assertEqual(state.icon.accessibleName(), "空状态图标")
        self.assertFalse(state.action_button.isHidden())
        self.assertEqual(state.action_button.text(), "新建采集")

    def test_page_header_exposes_one_primary_action(self):
        from desktop_ui.pages import PageHeader

        header = PageHeader("任务", "管理采集队列、状态与输出。", "新建采集")
        self.assertEqual(header.title.text(), "任务")
        self.assertEqual(header.description.text(), "管理采集队列、状态与输出。")
        self.assertEqual(header.primary_button.text(), "新建采集")
        self.assertFalse(header.primary_button.isHidden())
