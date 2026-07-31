from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import CandidateExtraction, DisciplinePolicy, SchoolInput
from faculty_workflow.reporting import RunReporter


class RunReporterTests(unittest.TestCase):
    def test_report_summarizes_review_causes_and_caps_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            for number in range(3):
                database.add_candidate(
                    task_id, school["id"], CandidateExtraction(name=f"Ada {number}"),
                    direction="Physics", source_url=f"https://example.edu/{number}",
                    status="review", review_reason="missing_email",
                )
                source_id = database.add_source(task_id, school["id"], f"https://example.edu/{number}", "person_profile")
                database.update_source(source_id, fetch_state="failed", failure_reason="timeout")

            report = RunReporter(max_events_per_kind=2).build(database, task_id)

            self.assertEqual(report["outcomes"]["review"], 3)
            self.assertEqual(len(report["diagnostics"]["failed_sources"]), 2)
            self.assertIn("email_missing_dominates_review", {item["code"] for item in report["optimization_signals"]})
            self.assertIn("profile_timeouts_dominate", {item["code"] for item in report["optimization_signals"]})


if __name__ == "__main__":
    unittest.main()
