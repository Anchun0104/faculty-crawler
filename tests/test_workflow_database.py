from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.exporter import _build_audit
from faculty_workflow.importers import import_history, import_processed_schools, load_schools
from faculty_workflow.models import CandidateExtraction, DisciplinePolicy, Evidence, SchoolInput
from faculty_workflow.quality import evaluate_candidate


class WorkflowDatabaseTests(unittest.TestCase):
    def test_audit_counts_duplicate_active_identities(self) -> None:
        class AuditDatabase:
            def summary(self, task_id):
                return {
                    "discipline": "Physics", "status": "completed", "budget_usd": 20,
                    "spent_usd": 0, "schools": {}, "candidates": {}, "historical_people": 0,
                }

            def list_candidates(self, task_id):
                return [
                    {"school_id": 1, "status": "accepted", "name": "Ada Lovelace", "homepage": "", "normalized_person_identity": "adalovelace", "review_reason": ""},
                    {"school_id": 1, "status": "review", "name": "Ada Lovelace", "homepage": "", "normalized_person_identity": "adalovelace", "review_reason": ""},
                ]

            def list_sources(self, task_id):
                return []

            def list_review_generations(self, task_id):
                return []

            def list_schools(self, task_id):
                return [{"id": 1, "name": "Example University", "status": "completed"}]

        audit = _build_audit(AuditDatabase(), "task", [], [])

        self.assertEqual(audit["school_coverage"][0]["active_unique_people"], 1)
        self.assertEqual(audit["school_coverage"][0]["active_duplicate_count"], 1)

    def test_field_evidence_and_active_person_identities_are_persistent_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "workflow.db"
            database = WorkflowDatabase(database_path)
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school_id = int(database.list_schools(task_id)[0]["id"])
            candidate_id = database.add_candidate(
                task_id,
                school_id,
                CandidateExtraction(
                    name="Ada Lovelace",
                    title_raw="Professor",
                    homepage="https://example.edu/people/ada?utm_source=test",
                    evidence=(Evidence(
                        "title", "Professor", "https://example.edu/faculty",
                        "directory_card", "supported",
                    ),),
                ),
                direction="Physics",
                source_url="https://example.edu/faculty",
                status="review",
            )

            restarted = WorkflowDatabase(database_path)
            row = restarted.list_candidates(task_id)[0]
            self.assertEqual(row["normalized_person_identity"], "adalovelace")
            self.assertEqual(row["normalized_profile_identity"], "https://example.edu/people/ada")
            fact = restarted.list_field_evidence(candidate_id)[0]
            self.assertEqual(fact["field"], "title")
            self.assertEqual(fact["value"], "Professor")
            self.assertEqual(fact["source_url"], "https://example.edu/faculty")

            with self.assertRaises(sqlite3.IntegrityError):
                restarted.add_candidate(
                    task_id,
                    school_id,
                    CandidateExtraction(name="ADA LOVELACE", homepage="https://example.edu/other"),
                    direction="Physics",
                    source_url="https://example.edu/other",
                    status="review",
                )
            restarted.add_candidate(
                task_id,
                school_id,
                CandidateExtraction(name="ADA LOVELACE", homepage="https://example.edu/other"),
                direction="Physics",
                source_url="https://example.edu/other",
                status="rejected",
            )

    def test_candidate_translation_metadata_round_trips_without_touching_translation_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = WorkflowDatabase(root / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]

            database.add_candidate(
                task_id,
                school["id"],
                CandidateExtraction(
                    name="Ada Lovelace",
                    title_raw="Professora Associada",
                    normalized_title="Associate Professor",
                    title_translated="Associate Professor",
                    title_language="pt",
                    translation_status="translation_success",
                    translation_engine="libretranslate",
                    classification_rules_version="2026.07",
                ),
                direction="Physics",
                source_url="https://example.edu/people/ada",
                status="review",
            )

            row = WorkflowDatabase(root / "workflow.db").list_candidates(task_id)[0]
            self.assertEqual(row["title_raw"], "Professora Associada")
            self.assertEqual(row["title_translated"], "Associate Professor")
            self.assertEqual(row["title_language"], "pt")
            self.assertEqual(row["translation_status"], "translation_success")
            self.assertEqual(row["translation_engine"], "libretranslate")
            self.assertEqual(row["classification_rules_version"], "2026.07")
            self.assertFalse((root / "translation_cache.sqlite3").exists())

    def test_source_graph_metadata_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "workflow.db"
            database = WorkflowDatabase(database_path)
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]

            source_id = database.add_source(
                task_id,
                school["id"],
                "https://research.example.edu/labs/quantum",
                "research_unit",
                official=True,
                discovered_from="https://www.example.edu/faculty",
                depth=1,
                official_boundary="validated",
                fetch_state="queued",
            )
            database.update_source(source_id, fetch_state="fetched", stop_reason="exhausted")

            source = WorkflowDatabase(database_path).list_sources(task_id)[0]
            self.assertEqual(source["discovered_from"], "https://www.example.edu/faculty")
            self.assertEqual(source["depth"], 1)
            self.assertEqual(source["official_boundary"], "validated")
            self.assertEqual(source["fetch_state"], "fetched")
            self.assertEqual(source["stop_reason"], "exhausted")

    def test_review_generation_is_idempotent_and_preserves_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            accepted_id = database.add_candidate(
                task_id,
                school["id"],
                CandidateExtraction(name="Accepted Person", homepage="https://example.edu/accepted"),
                direction="Physics",
                source_url="https://example.edu/faculty",
                status="accepted",
            )
            database.add_candidate(
                task_id,
                school["id"],
                CandidateExtraction(name="Review Person", homepage="https://example.edu/review"),
                direction="Physics",
                source_url="https://example.edu/faculty",
                status="review",
            )
            database.update_school(school["id"], status="review")

            first = database.begin_review_generation(task_id)
            second = database.begin_review_generation(task_id)

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(json.loads(first["superseded_candidate_ids"]).__len__(), 1)
            self.assertEqual(json.loads(first["requeued_school_ids"]), [school["id"]])
            accepted = next(row for row in database.list_candidates(task_id) if row["id"] == accepted_id)
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(accepted["decision_note"], "")
            self.assertEqual(database.list_review_generations(task_id)[0]["status"], "running")

    def test_task_state_survives_restart_and_imports_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "workflow.db"
            database = WorkflowDatabase(database_path)
            policy = DisciplinePolicy("Environmental Science", ("climate", "ecology"), ("engineering",))
            task_id = database.create_task(
                policy,
                [SchoolInput("Example University", "201", "example.edu")],
                output_dir=root / "output",
            )
            history = root / "history.json"
            history.write_text(json.dumps([{
                "name": "Ada Lovelace",
                "email": "ada@example.edu",
                "school": "Example University",
                "homepage": "https://example.edu/ada",
            }]), encoding="utf-8")
            processed = root / "processed.txt"
            processed.write_text("Finished University\n", encoding="utf-8")

            import_history(database, task_id, [history])
            import_processed_schools(database, task_id, [processed])
            database.confirm_policy(task_id, policy)

            reopened = WorkflowDatabase(database_path)
            summary = reopened.summary(task_id)
            self.assertEqual(summary["status"], "ready")
            self.assertEqual(summary["historical_people"], 1)
            self.assertTrue(reopened.is_processed_school(task_id, "Finished University"))
            reasons = reopened.duplicate_reasons(
                task_id,
                school_id=reopened.list_schools(task_id)[0]["id"],
                name="Ada Lovelace",
                school="Example University",
                email="ADA@example.edu",
                homepage="https://example.edu/ada/",
            )
            self.assertIn("duplicate_historical_email", reasons)
            self.assertIn("duplicate_historical_name_school", reasons)
            self.assertIn("duplicate_historical_homepage", reasons)

    def test_quality_gate_accepts_supported_record_and_routes_missing_evidence_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            policy = DisciplinePolicy("Physics", ("physics",), ())
            task_id = database.create_task(
                policy,
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            evidence = tuple(
                Evidence(field, f"quote for {field}", "https://example.edu/ada")
                for field in ("name", "email", "title", "department", "professional_relevance")
            )
            extraction = CandidateExtraction(
                name="Ada Lovelace",
                email="ada@example.edu",
                last_name="Lovelace",
                title_raw="Professor of Physics",
                normalized_title="Professor",
                department="Department of Physics",
                homepage="https://example.edu/ada",
                professional_relevance="relevant",
                email_ownership="verified",
                homepage_identity="verified",
                official_source=True,
                evidence=evidence,
            )

            accepted = evaluate_candidate(database, task_id, school["id"], school["name"], extraction, policy)
            review = evaluate_candidate(
                database,
                task_id,
                school["id"],
                school["name"],
                CandidateExtraction(**{**extraction.__dict__, "evidence": ()}),
                policy,
            )

            self.assertEqual(accepted.status, "accepted")
            self.assertEqual(review.status, "review")
            self.assertIn("missing_evidence_email", review.reasons)

            cookie_banner = CandidateExtraction(
                name="What is a cookie?",
                email="tiedotus@example.edu",
                email_ownership="verified",
                official_source=True,
                evidence=(
                    Evidence("name", "What is a cookie?", "https://example.edu/people"),
                    Evidence("email", "tiedotus@example.edu", "https://example.edu/people"),
                ),
            )
            rejected = evaluate_candidate(
                database, task_id, school["id"], school["name"], cookie_banner, policy
            )
            self.assertEqual(rejected.status, "rejected")
            self.assertIn("invalid_person_name", rejected.reasons)
            self.assertIn("generic_email", rejected.reasons)

            identity_only = CandidateExtraction(
                name="Grace Hopper",
                email="grace@people.example.edu",
                email_ownership="verified",
                official_source=True,
                evidence=(
                    Evidence("name", "Grace Hopper", "https://people.example.edu/grace"),
                    Evidence("email", "grace@people.example.edu", "https://people.example.edu/grace"),
                ),
            )
            identity_decision = evaluate_candidate(
                database, task_id, school["id"], school["name"], identity_only, policy,
                official_domain="example.edu",
            )
            self.assertEqual(identity_decision.status, "review")
            self.assertIn("missing_included_academic_role", identity_decision.reasons)
            self.assertIn("missing_evidence_title", identity_decision.reasons)
            outside_domain = evaluate_candidate(
                database, task_id, school["id"], school["name"],
                CandidateExtraction(**{**identity_only.__dict__, "email": "grace@other.edu"}),
                policy,
                official_domain="example.edu",
            )
            self.assertIn("email_domain_not_official", outside_domain.reasons)

    def test_school_loader_supports_optional_seed_columns_and_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schools.csv"
            path.write_text(
                "学校,原始编号,官网域名,教师目录\nExample University,8,example.edu,https://example.edu/faculty\n",
                encoding="utf-8-sig",
            )
            schools = load_schools(path)
            self.assertEqual(schools, [SchoolInput("Example University", "8", "example.edu", "https://example.edu/faculty")])
            path.write_text(
                "school,directory_url\n"
                "Example University,https://example.edu/faculty\n"
                "Example University,https://example.edu/faculty\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Duplicate school"):
                load_schools(path)

    def test_school_loader_requires_a_verified_directory_url_for_each_school(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schools.csv"
            path.write_text("school\nExample University\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "directory_url.*Example University"):
                load_schools(path)

    def test_reprocess_rejects_old_candidate_and_resets_school(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            policy = DisciplinePolicy("Physics", ("physics",), ())
            task_id = database.create_task(
                policy, [SchoolInput("Example University")], output_dir=temp_dir, policy_confirmed=True
            )
            school = database.list_schools(task_id)[0]
            candidate_id = database.add_candidate(
                task_id,
                school["id"],
                CandidateExtraction(name="Ada", homepage="https://example.edu/ada"),
                direction="Physics",
                source_url="https://example.edu/ada",
                status="review",
            )
            database.update_school(school["id"], status="review")
            self.assertTrue(database.has_candidate_homepage(task_id, school["id"], "https://example.edu/ada/"))

            self.assertEqual(database.reprocess_candidate(candidate_id), school["id"])
            self.assertEqual(database.list_candidates(task_id)[0]["status"], "rejected")
            self.assertEqual(database.list_schools(task_id)[0]["status"], "pending")

    def test_reprocess_reviews_preserves_accepted_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            for name, status in (("Accepted Person", "accepted"), ("Review Person", "review")):
                database.add_candidate(
                    task_id, school["id"], CandidateExtraction(name=name),
                    direction="Physics", source_url="https://example.edu/faculty", status=status,
                )
            database.update_school(school["id"], status="review")

            count, school_ids = database.reprocess_reviews(task_id)

            self.assertEqual((count, school_ids), (1, (school["id"],)))
            rows = {row["name"]: row for row in database.list_candidates(task_id)}
            self.assertEqual(rows["Accepted Person"]["status"], "accepted")
            self.assertEqual(rows["Accepted Person"]["decision_note"], "")
            self.assertEqual(rows["Review Person"]["status"], "rejected")
            self.assertEqual(rows["Review Person"]["decision_note"], "superseded_by_review_reprocess")
            self.assertEqual(database.list_schools(task_id)[0]["status"], "pending")
            self.assertTrue(database.has_accepted_candidate_name(task_id, school["id"], "Accepted Person"))

    def test_review_attempt_limit_moves_active_review_to_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            extraction = CandidateExtraction(name="Ada Lovelace", homepage="https://example.edu/ada")
            database.add_candidate(task_id, school["id"], extraction, direction="Physics", source_url="https://example.edu/ada", status="review", review_reason="missing_email")

            first = database.begin_review_generation(task_id)
            database.complete_review_generation(first["id"], {})
            database.add_candidate(task_id, school["id"], extraction, direction="Physics", source_url="https://example.edu/ada", status="review", review_reason="missing_email")
            second = database.begin_review_generation(task_id)
            database.complete_review_generation(second["id"], {})
            database.add_candidate(task_id, school["id"], extraction, direction="Physics", source_url="https://example.edu/ada", status="review", review_reason="missing_email")

            third = database.begin_review_generation(task_id)

            self.assertEqual(third["status"], "completed")
            self.assertEqual(database.list_candidates(task_id, ["unresolved"])[0]["review_reason"], "missing_email")

    def test_unchanged_review_result_becomes_unresolved_before_attempt_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            extraction = CandidateExtraction(name="Ada Lovelace", homepage="https://example.edu/ada")
            database.add_candidate(task_id, school["id"], extraction, direction="Physics", source_url="https://example.edu/ada", status="review", review_reason="missing_email")
            generation = database.begin_review_generation(task_id)
            database.add_candidate(task_id, school["id"], extraction, direction="Physics", source_url="https://example.edu/ada", status="review", review_reason="missing_email")

            self.assertEqual(database.close_unchanged_reviews(task_id, generation["id"]), 1)
            self.assertEqual(database.list_candidates(task_id, ["unresolved"])[0]["decision_note"], f"unchanged_review:{generation['id']}")

    def test_reopen_unresolved_preserves_accepted_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            database.add_candidate(task_id, school["id"], CandidateExtraction(name="Grace Hopper"), direction="Physics", source_url="https://example.edu/grace", status="accepted")
            unresolved_id = database.add_candidate(task_id, school["id"], CandidateExtraction(name="Ada Lovelace"), direction="Physics", source_url="https://example.edu/ada", status="unresolved", review_reason="missing_email")

            count, school_ids = database.reopen_unresolved(task_id, [unresolved_id], "decoder upgraded")

            self.assertEqual((count, school_ids), (1, (school["id"],)))
            self.assertEqual(database.list_candidates(task_id, ["accepted"])[0]["name"], "Grace Hopper")
            self.assertEqual(database.list_candidates(task_id, ["unresolved"]), [])

    def test_reprocess_school_supersedes_all_active_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            task_id = database.create_task(
                DisciplinePolicy("Physics", ("physics",), ()),
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            for name, email in (("Ada Lovelace", "ada@example.edu"), ("Grace Hopper", "grace@example.edu")):
                database.add_candidate(
                    task_id,
                    school["id"],
                    CandidateExtraction(name=name, email=email, homepage=f"https://example.edu/{name.split()[0].lower()}"),
                    direction="Physics",
                    source_url="https://example.edu/faculty",
                    status="review",
                    review_reason="old_parser",
                )
            database.update_school(school["id"], status="review")

            database.reprocess_school(school["id"])

            self.assertEqual(database.list_schools(task_id)[0]["status"], "pending")
            rows = database.list_candidates(task_id)
            self.assertTrue(all(row["status"] == "rejected" for row in rows))
            self.assertTrue(all(row["decision_note"] == "superseded_by_school_reprocess" for row in rows))
            self.assertFalse(database.has_candidate_homepage(task_id, school["id"], "https://example.edu/ada"))

    def test_access_review_survives_restart_and_only_requeues_when_user_allows_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "workflow.db"
            database = WorkflowDatabase(database_path)
            policy = DisciplinePolicy("Physics", ("physics",), ())
            task_id = database.create_task(
                policy,
                [SchoolInput("Example University", official_domain="example.edu")],
                output_dir=temp_dir,
                policy_confirmed=True,
            )
            school = database.list_schools(task_id)[0]
            database.update_school(school["id"], status="blocked_access", failure_reason="verification required")
            review_id = database.create_access_review(
                task_id, school["id"], "https://example.edu/faculty", "verification required"
            )

            reopened = WorkflowDatabase(database_path)
            self.assertEqual(reopened.list_access_reviews(task_id)[0]["status"], "pending")
            reopened.resolve_access_review(review_id, retry=True)
            self.assertEqual(reopened.list_access_reviews(task_id)[0]["status"], "ready_to_retry")
            self.assertEqual(reopened.list_schools(task_id)[0]["status"], "pending")

    def test_interrupted_active_school_is_recoverable_without_losing_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = WorkflowDatabase(Path(temp_dir) / "workflow.db")
            policy = DisciplinePolicy("Physics", ("physics",), ())
            task_id = database.create_task(
                policy, [SchoolInput("Example University")], output_dir=temp_dir, policy_confirmed=True
            )
            school = database.list_schools(task_id)[0]
            database.update_task(task_id, status="running")
            database.update_school(school["id"], status="extracting")

            self.assertEqual(database.recover_interrupted_task(task_id), 1)
            self.assertEqual(database.get_task(task_id)["status"], "ready")
            restored = database.list_schools(task_id)[0]
            self.assertEqual(restored["status"], "failed")
            self.assertEqual(restored["failure_reason"], "interrupted_before_completion")


if __name__ == "__main__":
    unittest.main()
