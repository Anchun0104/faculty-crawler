import unittest
from datetime import datetime, timezone

from crawler.access_policy import retry_decision
from crawler.models import PageAssessment, PageKind, RecommendedAction


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

    def test_honors_retry_after_seconds(self):
        assessment = PageAssessment(PageKind.RATE_LIMITED, RecommendedAction.RETRY_LATER)
        result = retry_decision(attempt=1, assessment=assessment, retry_after="12", now=self.now)
        self.assertTrue(result.should_retry)
        self.assertEqual(result.delay_seconds, 12)

    def test_honors_retry_after_http_date(self):
        assessment = PageAssessment(PageKind.RATE_LIMITED, RecommendedAction.RETRY_LATER)
        result = retry_decision(
            attempt=0,
            assessment=assessment,
            retry_after="Wed, 22 Jul 2026 12:00:12 GMT",
            now=self.now,
        )
        self.assertTrue(result.should_retry)
        self.assertEqual(result.delay_seconds, 12)

    def test_stops_after_three_attempts(self):
        assessment = PageAssessment(PageKind.TEMPORARY_FAILURE, RecommendedAction.RETRY_LATER)
        result = retry_decision(attempt=3, assessment=assessment, retry_after=None, now=self.now)
        self.assertFalse(result.should_retry)
        self.assertEqual(result.reason, "retry_limit")

    def test_never_retries_human_verification(self):
        assessment = PageAssessment(PageKind.HUMAN_VERIFICATION, RecommendedAction.QUEUE_VERIFICATION)
        result = retry_decision(attempt=0, assessment=assessment, retry_after=None, now=self.now)
        self.assertFalse(result.should_retry)
        self.assertEqual(result.delay_seconds, 0)

    def test_uses_backoff_for_malformed_or_negative_retry_after(self):
        assessment = PageAssessment(PageKind.RATE_LIMITED, RecommendedAction.RETRY_LATER)
        for retry_after in ("not-a-date", "-5", "NaN", "Infinity"):
            with self.subTest(retry_after=retry_after):
                result = retry_decision(
                    attempt=1,
                    assessment=assessment,
                    retry_after=retry_after,
                    now=self.now,
                )
                self.assertTrue(result.should_retry)
                self.assertEqual(result.delay_seconds, 2)


if __name__ == "__main__":
    unittest.main()
