from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_ui.main_window import MainWindow
from desktop_ui.tokens import load_theme_qss
from desktop_ui.widgets.status_badge import BackgroundStatus


APP = QApplication.instance() or QApplication([])


class DesktopUiAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = MainWindow(facade=object())
        self.window.resize(1180, 720)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)

    def tearDown(self) -> None:
        self.window.close()

    def test_navigation_controls_have_accessible_names_and_tooltips(self) -> None:
        toggle = self.window.navigation_toggle
        self.assertEqual(toggle.accessibleName(), "展开导航")
        self.assertTrue(toggle.toolTip())
        expected = {
            "overview": "导航到概览",
            "tasks": "导航到任务",
            "verification": "导航到人工验证",
            "runs": "导航到运行历史",
            "sessions": "导航到站点会话",
            "settings": "导航到设置",
        }
        for page_id in self.window.page_ids():
            button = self.window.navigation_button(page_id)
            self.assertEqual(button.accessibleName(), expected[page_id])
            self.assertTrue(button.toolTip())

    def test_page_stack_and_background_status_are_named_for_assistive_technology(self) -> None:
        self.assertEqual(self.window.page_stack.accessibleName(), "Main content")
        self.assertEqual(self.window.background_status.accessibleName(), "后台状态：空闲")
        self.window.set_background_status(BackgroundStatus.RUNNING)
        self.assertEqual(self.window.background_status.accessibleName(), "后台状态：运行中")

    def test_focus_order_starts_with_navigation_toggle(self) -> None:
        self.window.navigation_toggle.setFocus()
        QTest.keyClick(self.window.navigation_toggle, Qt.Key_Tab)

        self.assertTrue(any(button.hasFocus() for button in self.window.navigation_buttons()))

    def test_tool_buttons_have_a_visible_focus_style_contract(self) -> None:
        self.assertIn("QToolButton:focus", load_theme_qss())
        self.assertIn("border: 2px solid #1769AA", load_theme_qss())


if __name__ == "__main__":
    unittest.main()
