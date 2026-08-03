from pathlib import Path
import unittest


class DesktopUiTokensTests(unittest.TestCase):
    def test_approved_light_tokens_are_stable(self):
        from desktop_ui.tokens import LIGHT_TOKENS, load_theme_qss

        self.assertEqual(LIGHT_TOKENS.app_background, "#F4F7FA")
        self.assertEqual(LIGHT_TOKENS.primary, "#1769AA")
        self.assertEqual(LIGHT_TOKENS.nav_expanded, 220)
        self.assertEqual(LIGHT_TOKENS.nav_collapsed, 56)
        self.assertEqual(LIGHT_TOKENS.inspector_width, 360)
        self.assertNotIn("@APP_BACKGROUND@", load_theme_qss())

    def test_modern_tokens_match_approved_spec(self):
        from desktop_ui.tokens import LIGHT_TOKENS

        self.assertEqual(LIGHT_TOKENS.nav_background, "#EDF2F7")
        self.assertEqual(LIGHT_TOKENS.surface_primary, "#FFFFFF")
        self.assertEqual(LIGHT_TOKENS.surface_secondary, "#F8FAFC")
        self.assertEqual(LIGHT_TOKENS.text_primary, "#18212F")
        self.assertEqual(LIGHT_TOKENS.border_default, "#DFE5EC")
        self.assertEqual(LIGHT_TOKENS.control_md, 34)
        self.assertEqual(LIGHT_TOKENS.table_row, 40)

    def test_theme_has_shared_control_and_table_contracts(self):
        from desktop_ui.tokens import load_theme_qss

        qss = load_theme_qss()
        self.assertNotIn("@TOKEN@", qss)
        for selector in (
            "QPushButton",
            "QLineEdit",
            "QTableWidget",
            "QToolButton",
            "QTableWidget::item:selected",
        ):
            self.assertIn(selector, qss)
        self.assertIn("#1769AA", qss)

    def test_primary_navigation_labels_are_chinese(self):
        from desktop_ui.icons import NAVIGATION_ITEMS

        self.assertEqual(
            tuple(item.label for item in NAVIGATION_ITEMS),
            ("概览", "任务", "人工验证", "运行历史", "站点会话", "设置"),
        )

    def test_pyside6_and_notice_are_declared(self):
        self.assertIn("PySide6==6.11.1", Path("requirements.txt").read_text("utf-8"))
        self.assertIn("LGPL-3.0", Path("THIRD_PARTY_NOTICES.md").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
