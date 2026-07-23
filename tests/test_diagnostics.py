import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from crawler.diagnostics import (
    DiagnosticEvent,
    DiagnosticRecorder,
    ReportRecord,
    build_problem_report,
    load_report_metadata,
    mark_report_submitted,
    write_report_metadata,
)


class DiagnosticsTests(unittest.TestCase):
    def test_report_metadata_is_written_and_submission_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.zip"
            report = build_problem_report("run-1", [], path)
            record = load_report_metadata(report)
            metadata_before = json.loads(
                report.with_suffix(".zip.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(metadata_before),
                {"report_id", "path", "created_at", "submitted_at"},
            )
            self.assertEqual(record.report_id, "report")
            self.assertIsNone(record.submitted_at)
            submitted_at = datetime(2026, 7, 23, tzinfo=timezone.utc)
            marked = mark_report_submitted(record, submitted_at)
            metadata_after = json.loads(
                report.with_suffix(".zip.json").read_text(encoding="utf-8")
            )
            unchanged_before = {
                key: value
                for key, value in metadata_before.items()
                if key != "submitted_at"
            }
            unchanged_after = {
                key: value
                for key, value in metadata_after.items()
                if key != "submitted_at"
            }
            self.assertEqual(unchanged_after, unchanged_before)
            self.assertEqual(metadata_after["submitted_at"], submitted_at.isoformat())
            self.assertEqual(marked.path, path)

    def test_report_metadata_does_not_include_storage_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.zip"
            record = ReportRecord(
                "report-1", path, datetime.now(timezone.utc), None
            )
            path.write_bytes(b"zip")
            metadata = write_report_metadata(record)
            metadata_text = metadata.read_text(encoding="utf-8").casefold()
            self.assertNotIn("storage", metadata_text)

    def test_submission_rejects_sidecar_path_and_report_id_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = build_problem_report("run-1", [], root / "report.zip")
            record = load_report_metadata(report)
            metadata_path = report.with_suffix(".zip.json")
            original = json.loads(metadata_path.read_text(encoding="utf-8"))
            other_report = root / "other.zip"

            mismatches = (
                {**original, "path": str(other_report)},
                {**original, "report_id": "other-report"},
            )
            for payload in mismatches:
                with self.subTest(payload=payload):
                    metadata_path.write_text(
                        json.dumps(payload), encoding="utf-8"
                    )
                    with self.assertRaises(ValueError):
                        mark_report_submitted(record)
                    self.assertEqual(
                        json.loads(metadata_path.read_text(encoding="utf-8")),
                        payload,
                    )
                    self.assertFalse(other_report.with_suffix(".zip.json").exists())

    def test_credential_vocabulary_applies_to_all_event_fields_and_nested_details(self):
        cases = (
            ("client_secret", "CLIENT-UNDERSCORE-SECRET"),
            ("clientSecret", "CLIENT-CAMEL-SECRET"),
            ("client-secret", "CLIENT-DASH-SECRET"),
            ("auth_token", "AUTH-UNDERSCORE-SECRET"),
            ("authToken", "AUTH-CAMEL-SECRET"),
            ("auth-token", "AUTH-DASH-SECRET"),
            ("credentials", "CREDENTIALS-SECRET"),
            ("x-api-key", "X-API-KEY-SECRET"),
            ("private_key", "PRIVATE-KEY-SECRET"),
        )
        events = []
        for alias, seed in cases:
            assignment = f"{alias}={seed}"
            events.append(
                DiagnosticEvent(
                    assignment,
                    assignment,
                    assignment,
                    assignment,
                    assignment,
                    {
                        "nested": [
                            {alias: seed},
                            {"value": assignment},
                        ]
                    },
                )
            )

        recorder = DiagnosticRecorder()
        for event in events:
            recorder.record(event)
        recorded = json.dumps(
            [event.__dict__ for event in recorder.events],
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_problem_report(
                "clientSecret=SUMMARY-SECRET",
                events,
                Path(temp_dir) / "report.zip",
            )
            with zipfile.ZipFile(report) as archive:
                report_text = b"\n".join(
                    archive.read(name) for name in archive.namelist()
                ).decode("utf-8")

        for _, seed in cases:
            self.assertNotIn(seed, recorded)
            self.assertNotIn(seed, report_text)
        self.assertNotIn("SUMMARY-SECRET", report_text)

    def test_report_recursively_sanitizes_nested_detail_structures(self):
        event = DiagnosticEvent(
            "run-1",
            "task-1",
            "fetch",
            "failed",
            "Request failed",
            {
                "attempts": [
                    {"client_secret": "CLIENT-SECRET", "status": 403},
                    {
                        "items": [
                            {"auth_token": "AUTH-SECRET"},
                            {"credentials": "CREDENTIAL-SECRET", "retry": True},
                        ]
                    },
                ],
                "meta": {
                    "count": 2,
                    "paths": [
                        "C:/Users/ReportAlice/private/file.txt",
                        r"\\server\share\ReportBob\private\file.txt",
                    ],
                },
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_problem_report(
                "run-1",
                [event],
                Path(temp_dir) / "report.zip",
            )
            with zipfile.ZipFile(report) as archive:
                payload = json.loads(archive.read("diagnostics.json"))

        self.assertEqual(
            payload[0]["details"],
            {
                "attempts": [
                    {"status": 403},
                    {"items": [{}, {"retry": True}]},
                ],
                "meta": {
                    "count": 2,
                    "paths": ["<local_path>", "<local_path>"],
                },
            },
        )

    def test_recorder_keeps_redacted_events(self):
        recorder = DiagnosticRecorder()

        recorder.record(
            DiagnosticEvent(
                "run-1",
                "task-1",
                "fetch",
                "access_denied",
                "Authorization: Bearer SECRET",
                {
                    "cookie": "SECRET",
                    "access_token": "TOKEN-SECRET",
                    "api_key": "KEY-SECRET",
                    "apikey": "COMPACT-KEY-SECRET",
                    "auth_token": "AUTH-TOKEN-SECRET",
                    "accessToken": "CAMEL-TOKEN-SECRET",
                    "client_secret": "CLIENT-SECRET",
                    "credentials": "CREDENTIAL-SECRET",
                    "status": 403,
                },
            )
        )

        self.assertEqual(len(recorder.events), 1)
        self.assertNotIn("SECRET", recorder.events[0].message)
        self.assertEqual(recorder.events[0].details, {"status": 403})

    def test_report_has_only_white_list_files_and_redacts_secrets(self):
        event = DiagnosticEvent(
            "run-1",
            "task-1",
            "fetch",
            "access_denied",
            "Cookie: SECRET",
            {"status": 403},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_problem_report(
                "run-1",
                [event],
                Path(temp_dir) / "report.zip",
            )
            with zipfile.ZipFile(report) as archive:
                names = sorted(archive.namelist())
                combined = b"\n".join(
                    archive.read(name) for name in names
                ).decode("utf-8")
        self.assertEqual(
            names,
            [
                "application.log",
                "diagnostics.json",
                "failed-tasks.csv",
                "summary.txt",
            ],
        )
        self.assertNotIn("SECRET", combined)
        self.assertIn("<redacted>", combined)

    def test_report_omits_html_page_body_from_event_message(self):
        event = DiagnosticEvent(
            "run-1",
            "task-1",
            "fetch",
            "failed",
            "Request failed <html>PRIVATE PAGE BODY</html>",
            {},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_problem_report(
                "run-1",
                [event],
                Path(temp_dir) / "report.zip",
            )
            with zipfile.ZipFile(report) as archive:
                combined = b"\n".join(
                    archive.read(name) for name in archive.namelist()
                ).decode("utf-8")

        self.assertNotIn("PRIVATE PAGE BODY", combined)
        self.assertIn("[HTML omitted]", combined)

    def test_report_redacts_adversarial_secrets_and_html_in_all_event_fields(self):
        event = DiagnosticEvent(
            "run <html>RUN BODY</html>",
            "task <html>TASK BODY</html>",
            "fetch <html>STAGE BODY</html>",
            "failed <html>CATEGORY BODY</html>",
            "Bearer BEARER-SECRET",
            {
                "auth": "AUTH-SECRET",
                "url": "https://example.edu/?q=password=URL-SECRET",
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_problem_report(
                "run <html>SUMMARY BODY</html>",
                [event],
                Path(temp_dir) / "report.zip",
            )
            with zipfile.ZipFile(report) as archive:
                combined = b"\n".join(
                    archive.read(name) for name in archive.namelist()
                ).decode("utf-8")

        for private_text in (
            "RUN BODY",
            "TASK BODY",
            "STAGE BODY",
            "CATEGORY BODY",
            "SUMMARY BODY",
            "BEARER-SECRET",
            "AUTH-SECRET",
            "URL-SECRET",
        ):
            self.assertNotIn(private_text, combined)


if __name__ == "__main__":
    unittest.main()
