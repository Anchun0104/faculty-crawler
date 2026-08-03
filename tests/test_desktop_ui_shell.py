from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_ui.main_window import MainWindow
from desktop_ui.models import AiSettingsView, AiUsageView, NewCrawlRequest, UrlPreparation
from desktop_ui.pages.settings import SettingsPage
from desktop_ui.widgets.status_badge import BackgroundStatus


APP = QApplication.instance() or QApplication([])


class ShellFacade:
    def __init__(self) -> None:
        self.created: list[NewCrawlRequest] = []
        self.run_progress: list[str] = []

    def ai_settings(self) -> AiSettingsView:
        return AiSettingsView(False, "local", "", "", False)

    def ai_usage(self) -> AiUsageView:
        return AiUsageView(0, 0, 0, 0, 0, 0.0)

    def ai_usage_details(self) -> tuple[object, ...]:
        return ()

    def create_direct_tasks(self, request: NewCrawlRequest) -> str:
        self.created.append(request)
        return "task-1"

    def create_xlsx_task(self, schools: tuple[object, ...], request: NewCrawlRequest) -> str:
        self.created.append(request)
        return "task-xlsx"

    def run_task(self, task_id: str, *, on_progress):
        on_progress({"task_id": task_id, "message": "school_started"})
        self.run_progress.append(task_id)
        return {"id": task_id, "status": "completed"}

    def task_rows(self):
        return ()

    def verification_rows(self):
        return ()

    def session_rows(self):
        return ()

    def prepare_urls(self, _raw: str) -> UrlPreparation:
        return UrlPreparation((), (), ())


class DesktopUiShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = ShellFacade()
        self.window = MainWindow(facade=self.facade)
        self.window.resize(1440, 900)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)

    def tearDown(self) -> None:
        self.window.worker_pool.shutdown()
        APP.processEvents()
        self.window._close_when_idle = False
        self.window.close()

    def test_shell_has_six_primary_destinations(self) -> None:
        self.assertEqual(self.window.minimumSize().width(), 1180)
        self.assertEqual(self.window.windowTitle(), "教师目录采集器")
        self.assertEqual(
            self.window.page_ids(),
            ("overview", "tasks", "verification", "runs", "sessions", "settings"),
        )

    def test_shell_uses_chinese_group_and_navigation_copy(self) -> None:
        self.assertEqual(
            tuple(label.text() for label in self.window.navigation_group_labels()),
            ("工作", "记录", "系统"),
        )
        self.assertEqual(
            tuple(button.text() for button in self.window.navigation_buttons()),
            ("概览", "任务", "人工验证", "运行历史", "站点会话", "设置"),
        )
        self.assertEqual(self.window.background_status_text(), "空闲")

    def test_shell_can_construct_with_a_bare_facade(self) -> None:
        """Shell/accessibility consumers need not implement settings operations."""
        window = MainWindow(facade=object())
        self.addCleanup(window.close)

        self.assertEqual(window.page_ids(), self.window.page_ids())
        self.assertFalse(window.settings_page.ai_page.isEnabled())

    def test_navigation_replaces_the_current_page(self) -> None:
        self.window.navigate("runs")

        self.assertEqual(self.window.current_page_id(), "runs")
        self.assertTrue(self.window.navigation_button("runs").isChecked())

    def test_tasks_primary_button_opens_new_crawl_dialog(self) -> None:
        self.window.navigate("tasks")
        with patch.object(self.window, "_open_new_crawl") as open_new_crawl:
            self.window.tasks_page.page_header.primary_button.click()
        open_new_crawl.assert_called_once_with()

    def test_ctrl_comma_opens_settings(self) -> None:
        QTest.keyClick(self.window, Qt.Key_Comma, Qt.ControlModifier)

        self.assertEqual(self.window.current_page_id(), "settings")

    def test_ctrl_n_opens_new_crawl_and_ctrl_f_focuses_task_search(self) -> None:
        QTest.keyClick(self.window, Qt.Key_N, Qt.ControlModifier)
        self.assertTrue(self.window._new_crawl_dialog.isVisible())
        QTest.keyClick(self.window, Qt.Key_Escape)
        QTest.qWait(10)
        self.window.navigate("tasks")
        self.window._focus_current_search()
        self.assertEqual(self.window._find_shortcut.context(), Qt.ApplicationShortcut)
        self.assertTrue(self.window.tasks_page.search.focusPolicy() & Qt.StrongFocus)

    def test_ctrl_f_focuses_settings_search_and_budget_is_persisted(self) -> None:
        from PySide6.QtCore import QSettings

        self.window.navigate("settings")
        self.window._focus_current_search()
        self.assertTrue(self.window.settings_page.search_edit.focusPolicy() & Qt.StrongFocus)
        self.window._set_default_budget(37.5)
        settings = QSettings(QSettings.IniFormat, QSettings.UserScope, "FacultyCrawler", "FacultyCrawler")
        self.assertEqual(settings.value("desktop/default_budget_usd", type=float), 37.5)

    def test_settings_navigation_uses_the_real_ai_settings_page(self) -> None:
        self.window.navigate("settings")
        self.assertIsInstance(self.window.settings_page, SettingsPage)

        self.window.settings_page.navigate("ai")

        self.assertEqual(self.window.settings_page.current_section(), "ai")
        self.assertEqual(self.window.settings_page.ai_page.key_status.text(), "未配置")

    def test_ai_settings_content_scrolls_at_supported_minimum_size(self) -> None:
        self.window.resize(1180, 720)
        self.window.navigate("settings")
        self.window.settings_page.navigate("ai")
        QTest.qWait(10)

        self.assertGreater(self.window.settings_page.ai_scroll.verticalScrollBar().maximum(), 0)

    def test_navigation_can_collapse_and_expand(self) -> None:
        self.window.set_navigation_collapsed(True)
        self.assertEqual(self.window.navigation_width(), 56)
        self.assertTrue(self.window.is_navigation_collapsed())

        self.window.set_navigation_collapsed(False)
        self.assertEqual(self.window.navigation_width(), 220)
        self.assertFalse(self.window.is_navigation_collapsed())

    def test_resize_below_breakpoint_collapses_navigation(self) -> None:
        self.window.resize(self.window.navigation_breakpoint() - 1, 720)
        QTest.qWait(10)

        self.assertTrue(self.window.is_navigation_collapsed())
        self.assertEqual(self.window.navigation_width(), 56)

    def test_resize_at_breakpoint_expands_navigation(self) -> None:
        self.window.set_navigation_collapsed(True)
        self.window.resize(self.window.navigation_breakpoint(), 720)
        QTest.qWait(10)

        self.assertFalse(self.window.is_navigation_collapsed())
        self.assertEqual(self.window.navigation_width(), 220)

    def test_background_status_is_rendered_in_the_shell(self) -> None:
        self.window.set_background_status(BackgroundStatus.WAITING_FOR_VERIFICATION)

        self.assertEqual(self.window.background_status_text(), "等待人工验证")

    def test_collapsed_navigation_hides_group_labels_and_compacts_status(self) -> None:
        self.window.set_navigation_collapsed(True)

        self.assertTrue(all(label.isHidden() for label in self.window.navigation_group_labels()))
        self.assertTrue(self.window.background_status.is_compact())
        self.assertFalse(self.window.background_status.visible_text_label().isVisible())
        self.assertIn("空闲", self.window.background_status.toolTip())

    def test_request_close_with_active_work_can_minimize_to_tray(self) -> None:
        release = threading.Event()
        self.window.worker_pool.submit(lambda: release.wait(1))
        self.assertTrue(self.window.worker_pool.has_active_work())

        self.assertFalse(self.window.request_close("minimize"))
        self.assertEqual(self.window.isHidden(), self.window.tray_available())
        release.set()
        self.window.worker_pool.wait_for_done(1000)
        APP.processEvents()

    def test_request_close_after_current_defers_exit_until_workers_are_idle(self) -> None:
        release = threading.Event()
        self.window.worker_pool.submit(lambda: release.wait(1))
        self.assertFalse(self.window.request_close("after_current"))
        self.assertTrue(self.window.close_when_idle())
        release.set()
        self.window.worker_pool.wait_for_done(1000)
        APP.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_start_batch_creates_and_runs_in_the_worker_pool(self) -> None:
        request = NewCrawlRequest(("https://one.edu/faculty",), output_dir="output")
        self.window._start_direct_batch(request)

        self.assertTrue(
            self._wait_until(
                lambda: self.facade.run_progress == ["task-1"]
                and "已完成" in self.window.operation_info.message()
            )
        )
        self.assertEqual(self.facade.created, [request])
        self.assertIn("已完成", self.window.operation_info.message())

    def test_failed_verification_start_rolls_back_waiting_state_and_uses_safe_message(self) -> None:
        self.facade.begin_verification = lambda _review_id: (_ for _ in ()).throw(RuntimeError("token=secret"))
        self.window._submit_verification_start("7")

        self.assertTrue(self._wait_until(lambda: "失败" in self.window.operation_info.message()))
        self.assertNotIn("secret", self.window.operation_info.message())
        self.assertIn("空闲", self.window.background_status_text())

    def test_minimize_choice_does_not_hide_without_a_system_tray(self) -> None:
        original = self.window.tray_available
        self.window.tray_available = lambda: False
        release = threading.Event()
        self.window.worker_pool.submit(lambda: release.wait(1))
        try:
            self.assertFalse(self.window.request_close("minimize"))
            self.assertFalse(self.window.isHidden())
        finally:
            release.set()
            self.window.tray_available = original

    def test_shutdown_is_idempotent_and_waits_for_the_active_worker(self) -> None:
        release = threading.Event()
        self.window.worker_pool.submit(lambda: release.wait(1))
        threading.Timer(0.02, release.set).start()

        self.window.shutdown()
        self.window.shutdown()

        self.assertTrue(self.window.worker_pool.wait_for_done(0))

    @staticmethod
    def _wait_until(predicate, timeout_seconds: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            APP.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return False


if __name__ == "__main__":
    unittest.main()
