from __future__ import annotations

import unittest
from pathlib import Path

from faculty_workflow.email_resolver import OfficialEmailResolver
from faculty_workflow.fetcher import FetchedPage, html_to_text


def page(html: str) -> FetchedPage:
    return FetchedPage(
        requested_url="https://www.uni-giessen.de/people/ada",
        final_url="https://www.uni-giessen.de/people/ada",
        http_status=200,
        title="Ada Lovelace",
        html=html,
        text=html_to_text(html),
        content_hash="hash",
        snapshot_path=Path("snapshot.html.gz"),
    )


class OfficialEmailResolverTests(unittest.TestCase):
    def test_literal_official_email_from_pdf_text_is_accepted(self) -> None:
        pdf_page = FetchedPage(
            requested_url="https://phys.example.edu/ada.pdf",
            final_url="https://phys.example.edu/ada.pdf",
            http_status=200,
            title="Ada Lovelace",
            html="",
            text="Ada Lovelace Professor ada@example.edu",
            content_hash="pdf-hash",
            snapshot_path=Path("snapshot.pdf"),
        )

        result = OfficialEmailResolver().resolve(
            name="Ada Lovelace", page=pdf_page, official_domain="example.edu"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.email, "ada@example.edu")

    def test_obfuscated_pdf_email_is_not_reconstructed(self) -> None:
        pdf_page = FetchedPage(
            requested_url="https://phys.example.edu/ada.pdf",
            final_url="https://phys.example.edu/ada.pdf",
            http_status=200,
            title="Ada Lovelace",
            html="",
            text="Ada Lovelace Professor ada{a}example.edu; replace {a} with @",
            content_hash="pdf-hash",
            snapshot_path=Path("snapshot.pdf"),
        )

        result = OfficialEmailResolver().resolve(
            name="Ada Lovelace", page=pdf_page, official_domain="example.edu"
        )

        self.assertIsNone(result)

    def test_reconstructs_complete_page_present_split_mailto(self) -> None:
        html = """
        <main><h1>Ada Lovelace</h1>
          <a class="jluint email-link" href="mailto:ada?subject=Physics" rel="physik.uni">E-Mail</a>
        </main>
        """

        result = OfficialEmailResolver().resolve(
            name="Ada Lovelace",
            page=page(html),
            official_domain="uni-giessen.de",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.email, "ada@physik.uni-giessen.de")
        self.assertEqual(result.extraction_method, "split_mailto")
        self.assertIn(result.email, result.quote)

    def test_does_not_guess_domain_when_page_lacks_split_domain(self) -> None:
        html = """
        <main><h1>Ada Lovelace</h1>
          <a class="email-link" href="mailto:ada?subject=Physics">E-Mail</a>
        </main>
        """

        result = OfficialEmailResolver().resolve(
            name="Ada Lovelace",
            page=page(html),
            official_domain="uni-giessen.de",
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
