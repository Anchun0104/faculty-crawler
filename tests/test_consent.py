import unittest

from playwright.sync_api import sync_playwright

from crawler.consent import dismiss_cookie_overlay


class FakePage:
    def __init__(self, result):
        self.result = result

    def evaluate(self, script):
        return self.result


class ConsentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def test_returns_clicked_label(self):
        self.assertEqual(
            dismiss_cookie_overlay(FakePage("Accept necessary")), "Accept necessary"
        )

    def test_returns_none_when_no_trusted_control_exists(self):
        self.assertIsNone(dismiss_cookie_overlay(FakePage(None)))

    def test_leaves_unrelated_dialog_untouched(self):
        self.page.set_content(
            '<div role="dialog"><button onclick="window.clicked = true">'
            'Necessary only</button></div>'
        )

        self.assertIsNone(dismiss_cookie_overlay(self.page))
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_clicks_trusted_label_in_explicit_consent_scope(self):
        self.page.set_content(
            '<div id="privacy-consent"><button onclick="window.clicked = true">'
            'Reject all</button></div>'
        )

        self.assertEqual(dismiss_cookie_overlay(self.page), "Reject all")
        self.assertTrue(self.page.evaluate("window.clicked"))

    def test_leaves_accept_all_untouched(self):
        self.page.set_content(
            '<div class="cookie-banner"><button onclick="window.clicked = true">'
            'Accept all</button></div>'
        )

        self.assertIsNone(dismiss_cookie_overlay(self.page))
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_leaves_disabled_trusted_labels_untouched(self):
        self.page.set_content(
            '<div class="consent-banner">'
            '<button disabled onclick="window.nativeClicked = true">Necessary only</button>'
            '<button aria-disabled="true" onclick="window.ariaClicked = true">Reject all</button>'
            '</div>'
        )

        self.assertIsNone(dismiss_cookie_overlay(self.page))
        self.assertIsNone(self.page.evaluate("window.nativeClicked"))
        self.assertIsNone(self.page.evaluate("window.ariaClicked"))

    def test_uses_aria_label_as_accessible_label(self):
        self.page.set_content(
            '<div aria-label="Cookie preferences"><button aria-label="Necessary only" '
            'onclick="window.clicked = true"></button></div>'
        )

        self.assertEqual(dismiss_cookie_overlay(self.page), "Necessary only")
        self.assertTrue(self.page.evaluate("window.clicked"))

    def test_aria_label_overrides_visible_text(self):
        self.page.set_content(
            '<div class="consent-banner"><button aria-label="Accept all" '
            'onclick="window.clicked = true">Reject all</button></div>'
        )

        self.assertIsNone(dismiss_cookie_overlay(self.page))
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_clicks_trusted_aria_label_on_enabled_role_button(self):
        self.page.set_content(
            '<div data-cookie><div role="button" aria-label="Necessary only" '
            'onclick="window.clicked = true"></div></div>'
        )

        self.assertEqual(dismiss_cookie_overlay(self.page), "Necessary only")
        self.assertTrue(self.page.evaluate("window.clicked"))

    def test_leaves_aria_disabled_role_button_untouched(self):
        self.page.set_content(
            '<div data-cookie><div role="button" aria-label="Necessary only" '
            'aria-disabled="true" onclick="window.clicked = true"></div></div>'
        )

        self.assertIsNone(dismiss_cookie_overlay(self.page))
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_normalizes_whitespace_before_exact_label_match(self):
        self.page.set_content(
            '<div data-consent-dialog><button onclick="window.clicked = true">'
            ' Continue&nbsp;without   accepting </button></div>'
        )

        self.assertEqual(
            dismiss_cookie_overlay(self.page), "Continue\u00a0without accepting"
        )
        self.assertTrue(self.page.evaluate("window.clicked"))
