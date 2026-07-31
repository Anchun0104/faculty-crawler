from __future__ import annotations

import unittest

from workflow_desktop import REVIEW_VISIBLE_STATUSES


class WorkflowDesktopTests(unittest.TestCase):
    def test_review_list_includes_terminal_unresolved_records(self) -> None:
        self.assertEqual(REVIEW_VISIBLE_STATUSES, ("review", "candidate", "unresolved"))


if __name__ == "__main__":
    unittest.main()
