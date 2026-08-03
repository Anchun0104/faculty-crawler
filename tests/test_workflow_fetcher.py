from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from faculty_workflow.fetcher import FetchError, FetchPolicy, PageFetcher
from tests.test_workflow_pdf_documents import make_text_pdf


class _FixtureHandler(BaseHTTPRequestHandler):
    pdf = make_text_pdf("Ada Lovelace Professor ada@example.edu", title="Ada Profile")

    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            content_type = "text/plain"
        elif self.path == "/profile.pdf":
            body = self.pdf
            content_type = "application/pdf"
        else:
            body = b"not found"
            content_type = "text/plain"
            self.send_response(404)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class WorkflowFetcherTests(unittest.TestCase):
    def test_person_profile_policy_is_fast_fail(self) -> None:
        self.assertEqual(FetchPolicy.person_profile(), FetchPolicy(10_000, 1, False))

    def test_directory_policy_keeps_coverage_defaults(self) -> None:
        self.assertEqual(FetchPolicy.directory(), FetchPolicy(30_000, 3, True))

    def test_html_larger_than_snapshot_limit_is_rejected_without_cache(self) -> None:
        class AllowAllRobots:
            def set_url(self, url: str) -> None:
                pass

            def read(self) -> None:
                pass

            def can_fetch(self, user_agent: str, url: str) -> bool:
                return True

        class Page:
            url = "https://example.edu/faculty"

            def set_default_timeout(self, timeout: int) -> None:
                pass

            def goto(self, url: str, **kwargs: object):
                return type("Response", (), {"status": 200})()

            def wait_for_load_state(self, state: str, **kwargs: object) -> None:
                pass

            def wait_for_timeout(self, timeout: int) -> None:
                pass

            def content(self) -> str:
                return "<html><body>" + ("x" * 128) + "</body></html>"

            def title(self) -> str:
                return "Faculty"

        class Context:
            def new_page(self) -> Page:
                return Page()

            def close(self) -> None:
                pass

        class Browser:
            def new_context(self, **kwargs: object) -> Context:
                return Context()

            def close(self) -> None:
                pass

        class Playwright:
            def __enter__(self) -> "Playwright":
                return self

            def __exit__(self, *args: object) -> None:
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("playwright.sync_api.sync_playwright", return_value=Playwright()):
                with patch.object(PageFetcher, "_launch_browser", return_value=Browser()):
                    fetcher = PageFetcher(
                        min_domain_interval=0,
                        max_attempts=1,
                        max_snapshot_bytes=32,
                        robots_factory=AllowAllRobots,
                    )
                    with self.assertRaisesRegex(FetchError, "snapshot limit"):
                        fetcher.fetch("https://example.edu/faculty", temp_dir)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_person_page_can_skip_snapshot_persistence(self) -> None:
        class AllowAllRobots:
            def set_url(self, url: str) -> None: pass
            def read(self) -> None: pass
            def can_fetch(self, user_agent: str, url: str) -> bool: return True

        class Page:
            url = "https://example.edu/people/ada"
            def set_default_timeout(self, timeout: int) -> None: pass
            def goto(self, url: str, **kwargs: object): return type("Response", (), {"status": 200})()
            def wait_for_load_state(self, state: str, **kwargs: object) -> None: pass
            def wait_for_timeout(self, timeout: int) -> None: pass
            def content(self) -> str: return "<html><body>Ada</body></html>"
            def title(self) -> str: return "Ada"

        class Context:
            def new_page(self) -> Page: return Page()
            def close(self) -> None: pass
        class Browser:
            def new_context(self, **kwargs: object) -> Context: return Context()
            def close(self) -> None: pass
        class Playwright:
            def __enter__(self): return self
            def __exit__(self, *args: object) -> None: pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("playwright.sync_api.sync_playwright", return_value=Playwright()):
                with patch.object(PageFetcher, "_launch_browser", return_value=Browser()):
                    page = PageFetcher(min_domain_interval=0, max_attempts=1, robots_factory=AllowAllRobots).fetch(
                        "https://example.edu/people/ada", temp_dir, persist_snapshot=False
                    )
            self.assertIsNone(page.snapshot_path)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_pdf_download_extracts_text_and_never_starts_browser(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                url = f"http://127.0.0.1:{server.server_port}/profile.pdf"
                with patch.object(PageFetcher, "_launch_browser", side_effect=AssertionError("browser used")):
                    page = PageFetcher(min_domain_interval=0, max_attempts=1).fetch(url, temp_dir)

                self.assertEqual(page.http_status, 200)
                self.assertEqual(page.title, "Ada Profile")
                self.assertEqual(page.html, "")
                self.assertIn("ada@example.edu", page.text)
                self.assertEqual(page.snapshot_path.suffix, ".pdf")
                self.assertTrue(page.snapshot_path.read_bytes().startswith(b"%PDF-"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
