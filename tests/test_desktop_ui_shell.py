from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_ui.main_window import MainWindow
from desktop_ui.models import AiSettingsView, AiUsageView
from desktop_ui.pages.settings import SettingsPage
from desktop_ui.widgets.status_badge import BackgroundStatus


APP = QApplication.instance() or QApplication([])


class ShellFacade:
    def ai_settings(self) -> AiSettingsView:
        return AiSettingsView(False, "local", "", "", False)

    def ai_usage(self) -> AiUsageView:
        return AiUsageView(0, 0, 0, 0, 0, 0.0)

    def ai_usage_details(self) -> tuple[object, ...]:
        return ()


class DesktopUiShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = MainWindow(facade=ShellFacade())
        self.window.resize(1440, 900)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)

    def tearDown(self) -> None:
        self.window.close()

    def test_shell_has_six_primary_destinations(self) -> None:
        self.assertEqual(self.window.minimumSize().width(), 1180)
        self.assertEqual(
            self.window.page_ids(),
            ("overview", "tasks", "verification", "runs", "sessions", "settings"),
        )

    def test_navigation_replaces_the_current_page(self) -> None:
        self.window.navigate("runs")

        self.assertEqual(self.window.current_page_id(), "runs")
        self.assertTrue(self.window.navigation_button("runs").isChecked())

    def test_ctrl_comma_opens_settings(self) -> None:
        QTest.keyClick(self.window, Qt.Key_Comma, Qt.ControlModifier)

        self.assertEqual(self.window.current_page_id(), "settings")

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

        self.assertIn("Waiting for verification", self.window.background_status_text())

    def test_collapsed_navigation_hides_group_labels_and_compacts_status(self) -> None:
        self.window.set_navigation_collapsed(True)

        self.assertTrue(all(label.isHidden() for label in self.window.navigation_group_labels()))
        self.assertTrue(self.window.background_status.is_compact())
        self.assertFalse(self.window.background_status.visible_text_label().isVisible())
        self.assertIn("Idle", self.window.background_status.toolTip())


if __name__ == "__main__":
    unittest.main()
