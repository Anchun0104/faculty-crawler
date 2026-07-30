from __future__ import annotations

import unittest

from faculty_workflow.adapters import AdapterRegistry, CloudflareEmailAdapter
from faculty_workflow.directory_adapters import UniversalDirectoryAdapter
from faculty_workflow.fetcher import html_to_text


def encode_cfemail(value: str, key: int = 0x42) -> str:
    return bytes([key, *(ord(character) ^ key for character in value)]).hex()


class AdapterTests(unittest.TestCase):
    def test_cloudflare_email_is_decoded_before_text_extraction(self) -> None:
        token = encode_cfemail("professor@example.edu")
        html = f'<a href="/cdn-cgi/l/email-protection#{token}" data-cfemail="{token}">hidden</a>'
        result = AdapterRegistry([CloudflareEmailAdapter()]).preprocess_html("https://example.edu/p", html)
        self.assertIn("mailto:professor@example.edu", result)
        self.assertIn("professor@example.edu", html_to_text(result))

    def test_invalid_token_is_left_unchanged(self) -> None:
        html = '<span data-cfemail="xyz">hidden</span>'
        self.assertEqual(CloudflareEmailAdapter().preprocess_html("https://example.edu", html), html)

    def test_email_cards_split_parenthesized_academic_title_from_name(self) -> None:
        html = """
        <main>
          <div class="row"><div><h5>Karl Gordon (Visiting Professor)</h5>
            <a href="/web/person/karl-gordon/en">research page</a>
            <a href="mailto:Karl.Gordon@example.edu">Karl.Gordon@example.edu</a>
          </div></div>
          <div class="row"><div><h5>Veronique Van Speybroeck (associate professor)</h5>
            <a href="/web/person/veronique/en">research page</a>
            <a href="mailto:Veronique.Van.Speybroeck@example.edu">Veronique.Van.Speybroeck@example.edu</a>
          </div></div>
        </main>
        """

        result = UniversalDirectoryAdapter().extract(html, "https://example.edu/directory")

        self.assertTrue(result.authoritative)
        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [
                ("Karl Gordon", "Visiting Professor"),
                ("Veronique Van Speybroeck", "associate professor"),
            ],
        )

    def test_email_cards_do_not_emit_lab_labels_as_people(self) -> None:
        html = """
        <main>
          <div><h5>QG Lab</h5><p>Professor</p>
            <a href="mailto:qg@example.edu">qg@example.edu</a></div>
          <div><h5>Ada Lovelace</h5><p>Professor</p>
            <a href="mailto:ada@example.edu">ada@example.edu</a></div>
          <div><h5>Grace Hopper</h5><p>Associate Professor</p>
            <a href="mailto:grace@example.edu">grace@example.edu</a></div>
        </main>
        """

        result = UniversalDirectoryAdapter().extract(html, "https://example.edu/faculty")

        self.assertTrue(result.authoritative)
        self.assertEqual(
            {record.name for record in result.records},
            {"Ada Lovelace", "Grace Hopper"},
        )

    def test_staff_directory_heading_is_not_a_single_person_profile(self) -> None:
        html = """
        <main>
          <h1 itemprop="name">Head of Divison</h1>
          <div class="profile-title">Professor</div>
          <a href="mailto:head@example.edu">head@example.edu</a>
        </main>
        """

        result = UniversalDirectoryAdapter().extract(
            html,
            "https://example.edu/research/chemical-physics/staff-at-chemical-physics/",
        )

        self.assertFalse(result.authoritative)
        self.assertEqual(result.records, ())

    def test_generic_group_heading_is_not_emitted_as_a_person(self) -> None:
        html = """
        <main>
          <div><h5>About the group</h5><p>Postdoc positions</p>
            <a href="mailto:group@example.edu">group@example.edu</a></div>
          <div><h5>Leave feedback</h5><p>Professor</p>
            <a href="mailto:feedback@example.edu">feedback@example.edu</a></div>
          <div><h5>Physics and Astronomy</h5><p>Professor</p>
            <a href="mailto:department@example.edu">department@example.edu</a></div>
          <div><h5>Current members of the Johansson research group</h5><p>Researchers</p>
            <a href="mailto:group-lead@example.edu">group-lead@example.edu</a></div>
          <div><h5>Related content</h5><p>Professor</p>
            <a href="mailto:related@example.edu">related@example.edu</a></div>
          <div><h5>Content on this page</h5><p>Researchers</p>
            <a href="mailto:contents@example.edu">contents@example.edu</a></div>
          <div><h5>Release of Project 1.0</h5><p>Postdoc positions</p>
            <a href="mailto:release@example.edu">release@example.edu</a></div>
          <div><h5>Research projects</h5><p>Researchers</p>
            <a href="mailto:projects@example.edu">projects@example.edu</a></div>
          <div><h5>Unravelling the spiral structure of narwhal tusk</h5><p>Researchers</p>
            <a href="mailto:article@example.edu">article@example.edu</a></div>
          <div><h5>Bio-based materials structure</h5><p>Researchers</p>
            <a href="mailto:topic@example.edu">topic@example.edu</a></div>
          <div><h5>María de la Cruz</h5><p>Professor</p>
            <a href="mailto:maria@example.edu">maria@example.edu</a></div>
          <div><h5>Ada Lovelace</h5><p>Professor</p>
            <a href="mailto:ada@example.edu">ada@example.edu</a></div>
        </main>
        """

        result = UniversalDirectoryAdapter().extract(html, "https://example.edu/research/group/")

        self.assertEqual(
            [record.name for record in result.records],
            ["María de la Cruz", "Ada Lovelace"],
        )

    def test_duplicate_email_cards_are_not_authoritative_after_deduplication(self) -> None:
        html = """
        <main>
          <div><h5>Ada Lovelace</h5><p>Professor</p>
            <a href="mailto:ada@example.edu">ada@example.edu</a></div>
          <div><h5>Ada Lovelace</h5><p>Professor</p>
            <a href="mailto:ada@example.edu">ada@example.edu</a></div>
        </main>
        """

        result = UniversalDirectoryAdapter().extract(html, "https://example.edu/faculty/")

        self.assertFalse(result.authoritative)
        self.assertEqual([record.name for record in result.records], ["Ada Lovelace"])

    def test_single_unlinked_email_contact_on_research_page_is_not_a_person_card(self) -> None:
        html = """
        <main>
          <section><h3>Experimental Subatomic Physics</h3>
            <p>Andreas Heinz, Associate Professor</p>
            <a href="mailto:andreas@example.edu">andreas@example.edu</a>
            <a href="/departments/physics/research/aop/staff/">Physics staff</a>
          </section>
        </main>
        """

        result = UniversalDirectoryAdapter().extract(
            html,
            "https://example.edu/research/materials/liebi-research-group/",
        )

        self.assertFalse(result.authoritative)
        self.assertEqual(result.records, ())


if __name__ == "__main__":
    unittest.main()
