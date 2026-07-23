import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from crawler.faculty_crawler import FacultyRecord, TitlePendingRecord
from crawler.models import CrawlOutcome, TaskStatus
from main import main


class CliTests(unittest.TestCase):
    def test_main_uses_typed_outcome_without_duplicate_crawl(self):
        record = FacultyRecord(
            "Alan Turing", "Professor", "https://example.edu/people/alan"
        )

        class OutcomeCrawler:
            def __init__(self, timeout: int) -> None:
                pass

            def crawl(self, url: str) -> list[FacultyRecord]:
                raise AssertionError("crawl must not run when crawl_outcome is available")

            def crawl_outcome(self, url: str) -> CrawlOutcome:
                return CrawlOutcome(TaskStatus.REVIEW_RECOMMENDED, (record,))

        with (
            patch("main.FacultyCrawler", OutcomeCrawler),
            patch("main.export_to_excel") as main_export,
            patch("main.export_title_pending_to_excel", return_value=None) as pending_export,
            self.assertLogs("main", level="WARNING") as logs,
        ):
            exit_code = main(
                ["https://example.edu/faculty", "--output", "output/result.xlsx"]
            )

        self.assertEqual(exit_code, 0)
        main_export.assert_called_once_with([record], "output/result.xlsx")
        pending_export.assert_called_once_with([], "output/result.xlsx")
        self.assertIn("Review recommended", "\n".join(logs.output))

    def test_main_exports_pending_titles_from_typed_outcome(self):
        record = FacultyRecord("Alan Turing", "Professor", "https://example.edu/alan")
        pending = TitlePendingRecord(
            name="Ada Lovelace",
            directory_title="Dr.",
            profile_url="https://example.edu/ada",
            section="Academic Staff",
            source_url="https://example.edu/faculty",
            pending_reason="honorific_only_title",
        )

        class OutcomeCrawler:
            def __init__(self, timeout: int) -> None:
                pass

            def crawl_outcome(self, url: str) -> CrawlOutcome:
                return CrawlOutcome(TaskStatus.SUCCEEDED, (record,), (pending,))

        with (
            patch("main.FacultyCrawler", OutcomeCrawler),
            patch("main.export_to_excel"),
            patch("main.export_title_pending_to_excel", return_value=None) as pending_export,
        ):
            exit_code = main(["https://example.edu/faculty"])

        self.assertEqual(exit_code, 0)
        pending_export.assert_called_once_with([pending], "output/faculty_data.xlsx")

    def test_main_sanitizes_typed_failure_reason_before_logging(self):
        class OutcomeCrawler:
            def __init__(self, timeout: int) -> None:
                pass

            def crawl_outcome(self, url: str) -> CrawlOutcome:
                return CrawlOutcome(
                    TaskStatus.FAILED,
                    diagnostics={
                        "Failure reason": (
                            "Bearer TOPSECRET C:\\Users\\PrivateAlice\\file.txt "
                            "<html>PRIVATE BODY</html>"
                        )
                    },
                )

        with (
            patch("main.FacultyCrawler", OutcomeCrawler),
            self.assertLogs(level="ERROR") as logs,
        ):
            exit_code = main(["https://example.edu/faculty"])

        log_text = "\n".join(logs.output)
        self.assertEqual(exit_code, 1)
        self.assertNotIn("TOPSECRET", log_text)
        self.assertNotIn("PrivateAlice", log_text)
        self.assertNotIn("PRIVATE BODY", log_text)

    def test_invalid_url_exits_cleanly(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = main(["not-a-url"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Invalid URL", stderr.getvalue())

    def test_main_automatically_exports_and_logs_title_pending_records(self):
        crawler = Mock()
        crawler.crawl.return_value = [
            FacultyRecord("Alan Turing", "Professor", "https://example.edu/people/alan")
        ]
        crawler.title_pending_records = [
            TitlePendingRecord(
                name="Ada Lovelace",
                directory_title="Dr.",
                profile_url="https://example.edu/people/ada",
                section="Academic Staff",
                source_url="https://example.edu/faculty",
                pending_reason="honorific_only_title",
            )
        ]
        pending_path = Path("output/pending_title/result_title_pending.xlsx")

        with (
            patch("main.FacultyCrawler", return_value=crawler),
            patch("main.export_to_excel") as main_export,
            patch("main.export_title_pending_to_excel", return_value=pending_path) as pending_export,
            self.assertLogs("main", level="INFO") as logs,
        ):
            exit_code = main(["https://example.edu/faculty", "--output", "output/result.xlsx"])

        self.assertEqual(exit_code, 0)
        main_export.assert_called_once_with(crawler.crawl.return_value, "output/result.xlsx")
        pending_export.assert_called_once_with(crawler.title_pending_records, "output/result.xlsx")
        self.assertIn("Title pending records: 1", "\n".join(logs.output))
        self.assertIn(f"Title pending output: {pending_path}", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
