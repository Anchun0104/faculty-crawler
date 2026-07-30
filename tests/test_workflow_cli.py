from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workflow
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import CandidateExtraction, DisciplinePolicy, SchoolInput


class WorkflowCliTests(unittest.TestCase):
    def test_review_only_command_preserves_completed_and_resumes_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "workflow.db"
            database = WorkflowDatabase(database_path)
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput(
                    "Example University",
                    official_domain="example.edu",
                    directory_url="https://example.edu/faculty",
                )],
                output_dir=Path(temp_dir) / "output",
                policy_confirmed=True,
            )
            school_id = int(database.list_schools(task_id)[0]["id"])
            accepted_id = database.add_candidate(
                task_id,
                school_id,
                CandidateExtraction(name="Ada Lovelace", email="ada@example.edu"),
                direction="Physics",
                source_url="https://example.edu/ada",
                status="accepted",
            )
            review_id = database.add_candidate(
                task_id,
                school_id,
                CandidateExtraction(name="Grace Hopper"),
                direction="Physics",
                source_url="https://example.edu/grace",
                status="review",
                review_reason="missing_official_email",
            )
            summary = {"task_id": task_id, "status": "completed", "candidates": {"accepted": 2}}

            with patch.object(workflow.WorkflowService, "run_task", return_value=summary) as run_task:
                result = workflow.main([
                    "--database", str(database_path),
                    "reprocess-reviews", "--task", task_id,
                ])

            self.assertEqual(result, 0)
            run_task.assert_called_once_with(task_id)
            rows = {int(row["id"]): row for row in database.list_candidates(task_id)}
            self.assertEqual(rows[accepted_id]["status"], "accepted")
            self.assertEqual(rows[review_id]["status"], "rejected")
            generations = database.list_review_generations(task_id)
            self.assertEqual(len(generations), 1)
            self.assertEqual(generations[0]["status"], "completed")

            with patch.object(workflow.WorkflowService, "run_task") as second_run:
                result = workflow.main([
                    "--database", str(database_path),
                    "reprocess-reviews", "--task", task_id,
                ])
            self.assertEqual(result, 0)
            second_run.assert_not_called()
            self.assertEqual(len(database.list_review_generations(task_id)), 1)


if __name__ == "__main__":
    unittest.main()
