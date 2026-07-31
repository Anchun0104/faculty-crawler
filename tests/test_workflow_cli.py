from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import workflow
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import CandidateExtraction, DisciplinePolicy, SchoolInput


class WorkflowCliTests(unittest.TestCase):
    def test_reopen_unresolved_passes_ids_and_reason_to_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                workflow.WorkflowService,
                "reopen_unresolved",
                return_value={"reopened": 1, "school_ids": [3]},
            ) as reopen:
                result = workflow.main([
                    "--database", str(Path(temp_dir) / "workflow.db"),
                    "reopen-unresolved", "--task", "task-1", "--candidate", "41", "42",
                    "--reason", "email decoder upgraded",
                ])

        self.assertEqual(result, 0)
        reopen.assert_called_once_with(
            "task-1", candidate_ids=[41, 42], reason="email decoder upgraded"
        )

    def test_compatible_provider_reads_key_from_named_environment_variable(self) -> None:
        previous = os.environ.get("TEST_WORKFLOW_API_KEY")
        os.environ["TEST_WORKFLOW_API_KEY"] = "test-key"
        try:
            args = workflow.build_parser().parse_args([
                "--ai-provider", "compatible",
                "--ai-base-url", "https://gateway.example/v1",
                "--ai-model", "custom-model",
                "--ai-key-env", "TEST_WORKFLOW_API_KEY",
                "url", "--output-dir", "output", "https://example.edu/faculty",
            ])
            provider = workflow.provider_from_args(args)
        finally:
            if previous is None:
                os.environ.pop("TEST_WORKFLOW_API_KEY", None)
            else:
                os.environ["TEST_WORKFLOW_API_KEY"] = previous

        self.assertEqual(provider.endpoint, "https://gateway.example/v1/chat/completions")
        self.assertEqual(provider.api_key, "test-key")

    def test_url_command_creates_and_runs_a_direct_evidence_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "workflow.db"
            with patch.object(
                workflow.WorkflowService,
                "create_direct_url_task",
                return_value="direct-task",
            ) as create_task, patch.object(
                workflow.WorkflowService,
                "run_task",
                return_value={"task_id": "direct-task", "status": "completed"},
            ) as run_task:
                result = workflow.main([
                    "--database", str(database_path),
                    "url", "--output-dir", str(Path(temp_dir) / "output"),
                    "--school", "Example University",
                    "--discipline", "Physics",
                    "https://example.edu/faculty",
                ])

            self.assertEqual(result, 0)
            create_task.assert_called_once_with(
                directory_urls=["https://example.edu/faculty"],
                output_dir=str(Path(temp_dir) / "output"),
                school_name="Example University",
                discipline="Physics",
                use_ai=False,
                routine_model="deepseek-v4-flash",
                escalation_model="deepseek-v4-pro",
                budget_usd=20.0,
            )
            run_task.assert_called_once_with("direct-task")

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
            run_task.assert_called_once_with(task_id, school_ids=(school_id,))
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
