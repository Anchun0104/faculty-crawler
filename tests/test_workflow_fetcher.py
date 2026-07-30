from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from faculty_workflow.fetcher import PageFetcher
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
