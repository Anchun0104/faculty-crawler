import unittest

from crawler.models import PageKind, RecommendedAction
from crawler.page_state import classify_page


class PageStateTests(unittest.TestCase):
    def assess(self, *, status=200, title="", text="", html_length=400, candidate_count=0):
        return classify_page(
            url="https://example.edu/faculty",
            status=status,
            title=title,
            text=text,
            html_length=html_length,
            candidate_count=candidate_count,
        )

    def test_candidates_take_precedence_over_generic_security_words(self):
        result = self.assess(text="Faculty security research", candidate_count=12)
        self.assertEqual(result.kind, PageKind.DIRECTORY)
        self.assertEqual(result.action, RecommendedAction.PARSE)

    def test_429_is_rate_limited(self):
        result = self.assess(status=429, text="Too many requests")
        self.assertEqual(result.kind, PageKind.RATE_LIMITED)
        self.assertEqual(result.action, RecommendedAction.RETRY_LATER)

    def test_challenge_enters_human_queue(self):
        result = self.assess(title="Just a moment", text="Verify you are human")
        self.assertEqual(result.kind, PageKind.HUMAN_VERIFICATION)
        self.assertEqual(result.action, RecommendedAction.QUEUE_VERIFICATION)

    def test_403_without_challenge_stops_after_policy_decision(self):
        result = self.assess(status=403, title="Access denied", text="Forbidden")
        self.assertEqual(result.kind, PageKind.ACCESS_DENIED)
        self.assertEqual(result.action, RecommendedAction.RETRY_OR_STOP)


if __name__ == "__main__":
    unittest.main()
