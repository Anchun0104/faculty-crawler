from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_ui.main_window import MainWindow
from desktop_ui.widgets.status_badge import BackgroundStatus


APP = QApplication.instance() or QApplication([])


class DesktopUiShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = MainWindow(facade=object())
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

    def test_navigation_can_collapse_and_expand(self) -> None:
        self.window.set_navigation_collapsed(True)
        self.assertEqual(self.window.navigation_width(), 56)
        self.assertTrue(self.window.is_navigation_collapsed())

        self.window.set_navigation_collapsed(False)
        self.assertEqual(self.window.navigation_width(), 220)
        self.assertFalse(self.window.is_navigation_collapsed())

    def test_background_status_is_rendered_in_the_shell(self) -> None:
        self.window.set_background_status(BackgroundStatus.WAITING_FOR_VERIFICATION)

        self.assertIn("Waiting for verification", self.window.background_status_text())


if __name__ == "__main__":
    unittest.main()
