from __future__ import annotations

import unittest

from faculty_workflow.discovery import (
    DiscoveryHint,
    DiscoveryLimits,
    EmptyDiscoveryProvider,
    OfficialSourceGraph,
)


class OfficialSourceGraphTests(unittest.TestCase):
    def test_queue_is_official_bounded_deduplicated_and_fifo(self) -> None:
        graph = OfficialSourceGraph(
            "example.edu",
            DiscoveryLimits(max_depth=1, max_pages=2),
        )

        self.assertTrue(graph.enqueue("https://www.example.edu/faculty", "faculty_directory"))
        self.assertTrue(
            graph.enqueue(
                "https://research.example.edu/labs/quantum",
                "research_unit",
                discovered_from="https://www.example.edu/faculty",
                depth=1,
            )
        )
        self.assertFalse(graph.enqueue("https://www.example.edu/faculty#people", "faculty_directory"))
        self.assertFalse(graph.enqueue("https://outside.test/people", "faculty_directory"))
        self.assertFalse(graph.enqueue("https://www.example.edu/research/deeper", "research_unit", depth=2))
        self.assertFalse(graph.enqueue("https://www.example.edu/people/third", "faculty_directory"))

        first = graph.pop()
        second = graph.pop()

        self.assertEqual(first.url, "https://www.example.edu/faculty")
        self.assertEqual(second.url, "https://research.example.edu/labs/quantum")
        self.assertEqual(second.discovered_from, "https://www.example.edu/faculty")
        self.assertIsNone(graph.pop())
        self.assertEqual(graph.stop_reason, "page_budget_reached")

    def test_search_hints_carry_urls_not_evidence_content(self) -> None:
        hint = DiscoveryHint(url="https://www.example.edu/people/ada", query="Ada Example University")

        self.assertEqual(hint.url, "https://www.example.edu/people/ada")
        self.assertFalse(hasattr(hint, "snippet"))
        with self.assertRaises(TypeError):
            DiscoveryHint(  # type: ignore[call-arg]
                url="https://www.example.edu/people/ada",
                query="Ada Example University",
                snippet="ada@example.edu",
            )

    def test_default_discovery_provider_is_inert(self) -> None:
        self.assertEqual(
            EmptyDiscoveryProvider().discover(
                name="Ada Lovelace",
                school="Example University",
                official_domain="example.edu",
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
