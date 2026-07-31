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

    def test_pyside6_and_notice_are_declared(self):
        self.assertIn("PySide6==6.11.1", Path("requirements.txt").read_text("utf-8"))
        self.assertIn("LGPL-3.0", Path("THIRD_PARTY_NOTICES.md").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
