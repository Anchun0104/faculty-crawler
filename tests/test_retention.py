import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.app_paths import AppPaths
from crawler.retention import ReportRecord, RetentionService, RunRecord


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.paths = AppPaths.for_user(Path(self.temp_dir.name))
        self.now = datetime(2026, 7, 23, tzinfo=timezone.utc)
        self.service = RetentionService(self.paths, clock=lambda: self.now)
        self.output_dir = Path(self.temp_dir.name) / "output"
        self.output_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_report(self, *, submitted_at, age_days):
        path = self.paths.reports / f"report-{age_days}.zip"
        path.write_bytes(b"report")
        return ReportRecord("report", path, self.now - timedelta(days=age_days), submitted_at)

    def make_run(self, *, status, age_days):
        path = self.paths.runs / f"run-{age_days}.json"
        path.write_bytes(b"run")
        return RunRecord("run", path, self.now - timedelta(days=age_days), status)

    def test_unsubmitted_report_is_never_removed_by_retention(self):
        report = self.make_report(submitted_at=None, age_days=400)
        self.service.purge_due([report], [])
        self.assertTrue(report.path.exists())

    def test_submitted_report_is_removed_after_30_days(self):
        report = self.make_report(submitted_at=self.now - timedelta(days=31), age_days=31)
        self.service.purge_due([report], [])
        self.assertFalse(report.path.exists())

    def test_failed_run_is_kept_for_90_days(self):
        run = self.make_run(status="failed", age_days=89)
        self.service.purge_due([], [run])
        self.assertTrue(run.path.exists())

    def test_failed_run_is_removed_after_90_days(self):
        run = self.make_run(status="failed", age_days=91)
        self.service.purge_due([], [run])
        self.assertFalse(run.path.exists())

    def test_clear_internal_data_does_not_touch_output_directory(self):
        excel = self.output_dir / "faculty.xlsx"
        excel.write_bytes(b"xlsx")
        self.service.clear_internal_data()
        self.assertTrue(excel.exists())

    def test_clear_internal_data_removes_only_internal_files(self):
        (self.paths.sessions / "session.session").write_bytes(b"x")
        (self.paths.tasks / "task.json").write_bytes(b"x")
        (self.paths.logs / "run.log").write_bytes(b"x")
        (self.paths.runs / "verification-queue.json").write_bytes(b"x")
        report = self.make_report(submitted_at=None, age_days=400)
        self.service.clear_internal_data()
        self.assertFalse((self.paths.sessions / "session.session").exists())
        self.assertFalse((self.paths.tasks / "task.json").exists())
        self.assertFalse((self.paths.logs / "run.log").exists())
        self.assertFalse((self.paths.runs / "verification-queue.json").exists())
        self.assertTrue(report.path.exists())

    def test_deletion_target_outside_root_is_rejected(self):
        outside = Path(self.temp_dir.name).parent / "outside-report.zip"
        outside.write_bytes(b"x")
        report = ReportRecord("outside", outside, self.now - timedelta(days=100), self.now - timedelta(days=100))
        with self.assertRaises(ValueError):
            self.service.purge_due([report], [])
        outside.unlink()

    def test_excel_record_is_rejected_even_when_it_is_under_app_root(self):
        excel = self.paths.runs / "faculty.xlsx"
        excel.write_bytes(b"xlsx")
        run = RunRecord(
            "run", excel, self.now - timedelta(days=100), "failed"
        )
        with self.assertRaises(ValueError):
            self.service.purge_due([], [run])
        self.assertTrue(excel.exists())

    def test_clear_reports_unlink_failures(self):
        path = self.paths.logs / "run.log"
        path.write_bytes(b"x")
        original = Path.unlink
        try:
            Path.unlink = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied"))
            with self.assertRaises(OSError):
                self.service.clear_internal_data()
        finally:
            Path.unlink = original

    def test_clear_temporary_removes_screenshots_and_temporary_files(self):
        screenshot = self.paths.screenshots / "private.png"
        temporary = self.paths.logs / "write.tmp"
        kept = self.paths.logs / "run.log"
        screenshot.write_bytes(b"private")
        temporary.write_bytes(b"partial")
        kept.write_bytes(b"log")
        self.service.clear_temporary()
        self.assertFalse(screenshot.exists())
        self.assertFalse(temporary.exists())
        self.assertTrue(kept.exists())


if __name__ == "__main__":
    unittest.main()
