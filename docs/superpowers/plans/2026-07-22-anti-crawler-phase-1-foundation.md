# Anti-Crawler Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed crawl outcomes, page-state classification, crash-safe run persistence, and structured privacy-safe diagnostics without changing extraction behavior.

**Architecture:** New focused modules define stable data contracts consumed by later phases. `crawler/batch.py` keeps orchestration but delegates persistence and diagnostics, while `FacultyCrawler` continues returning faculty records until the final integration task switches it to a typed outcome.

**Tech Stack:** Python 3.11 dataclasses/enums, JSON, atomic `os.replace`, threading lock, `unittest`.

## Global Constraints

- No AI, CAPTCHA solving, proxy rotation, fingerprint spoofing, or access-control bypass.
- Persist every task transition without placing cookies or page bodies in run state.
- Keep current CLI, parser, Excel export, and batch tests passing.
- Use standard-library modules only in this phase.

---

## File Map

- Create `crawler/models.py`: enums and immutable result contracts.
- Create `crawler/page_state.py`: pure page classification.
- Create `crawler/app_paths.py`: operating-system application-data paths.
- Create `crawler/task_store.py`: atomic JSON run persistence and recovery.
- Create `crawler/privacy.py`: URL and secret redaction shared without circular imports.
- Create `crawler/diagnostics.py`: structured diagnostic events and ZIP white-list generation.
- Modify `crawler/batch.py`: use shared models, emit diagnostics, and persist transitions.
- Modify `crawler/faculty_crawler.py`: produce a `CrawlOutcome` at a new compatibility boundary.
- Create `tests/test_page_state.py`, `tests/test_task_store.py`, and `tests/test_diagnostics.py`.
- Modify `tests/test_batch.py` and `tests/test_crawler_diagnostics.py`.

### Task 1: Stable models and page-state classifier

**Files:**
- Create: `crawler/models.py`
- Create: `crawler/page_state.py`
- Test: `tests/test_page_state.py`

**Interfaces:**
- Produces: `TaskStatus`, `PageKind`, `RecommendedAction`, `PageEvidence`, `PageAssessment`, `CrawlOutcome`.
- Produces: `classify_page(*, url: str, status: int | None, title: str, text: str, html_length: int, candidate_count: int) -> PageAssessment`.

- [ ] **Step 1: Write classifier tests**

```python
import unittest

from crawler.models import PageKind, RecommendedAction
from crawler.page_state import classify_page


class PageStateTests(unittest.TestCase):
    def assess(self, *, status=200, title="", text="", html_length=400, candidate_count=0):
        return classify_page(
            url="https://example.edu/faculty",
            status=status,
            title=title,
            text=text,
            html_length=html_length,
            candidate_count=candidate_count,
        )

    def test_candidates_take_precedence_over_generic_security_words(self):
        result = self.assess(text="Faculty security research", candidate_count=12)
        self.assertEqual(result.kind, PageKind.DIRECTORY)
        self.assertEqual(result.action, RecommendedAction.PARSE)

    def test_429_is_rate_limited(self):
        result = self.assess(status=429, text="Too many requests")
        self.assertEqual(result.kind, PageKind.RATE_LIMITED)
        self.assertEqual(result.action, RecommendedAction.RETRY_LATER)

    def test_challenge_enters_human_queue(self):
        result = self.assess(title="Just a moment", text="Verify you are human")
        self.assertEqual(result.kind, PageKind.HUMAN_VERIFICATION)
        self.assertEqual(result.action, RecommendedAction.QUEUE_VERIFICATION)

    def test_403_without_challenge_stops_after_policy_decision(self):
        result = self.assess(status=403, title="Access denied", text="Forbidden")
        self.assertEqual(result.kind, PageKind.ACCESS_DENIED)
        self.assertEqual(result.action, RecommendedAction.RETRY_OR_STOP)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `python -m unittest tests.test_page_state -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'crawler.models'`.

- [ ] **Step 3: Add the model contracts**

```python
# crawler/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from crawler.parsers import FacultyRecord, TitlePendingRecord


class TaskStatus(StrEnum):
    PENDING = "pending"
    FETCHING = "fetching"
    EXPANDING = "expanding"
    PARSING = "parsing"
    RETRY_WAIT = "retry_wait"
    VERIFICATION_REQUIRED = "verification_required"
    READY_TO_RESUME = "ready_to_resume"
    SUCCEEDED = "succeeded"
    REVIEW_RECOMMENDED = "review_recommended"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PageKind(StrEnum):
    DIRECTORY = "directory"
    DELAYED_SHELL = "delayed_shell"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    HUMAN_VERIFICATION = "human_verification"
    LOGIN_REQUIRED = "login_required"
    ACCESS_DENIED = "access_denied"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class RecommendedAction(StrEnum):
    PARSE = "parse"
    WAIT_FOR_CONTENT = "wait_for_content"
    RETRY_LATER = "retry_later"
    QUEUE_VERIFICATION = "queue_verification"
    RETRY_OR_STOP = "retry_or_stop"
    STOP_WITH_DIAGNOSTICS = "stop_with_diagnostics"


@dataclass(frozen=True)
class PageEvidence:
    code: str
    detail: str


@dataclass(frozen=True)
class PageAssessment:
    kind: PageKind
    action: RecommendedAction
    evidence: tuple[PageEvidence, ...] = ()


@dataclass(frozen=True)
class CrawlOutcome:
    status: TaskStatus
    records: tuple[FacultyRecord, ...] = ()
    pending_titles: tuple[TitlePendingRecord, ...] = ()
    diagnostics: dict[str, object] = field(default_factory=dict)
```

- [ ] **Step 4: Add the pure classifier**

```python
# crawler/page_state.py
from __future__ import annotations

from crawler.models import PageAssessment, PageEvidence, PageKind, RecommendedAction


def classify_page(*, url: str, status: int | None, title: str, text: str, html_length: int, candidate_count: int) -> PageAssessment:
    del url
    haystack = f"{title}\n{text}".casefold()
    if candidate_count > 0:
        return PageAssessment(PageKind.DIRECTORY, RecommendedAction.PARSE, (PageEvidence("candidates", str(candidate_count)),))
    if status == 429 or "too many requests" in haystack or "rate limit" in haystack:
        return PageAssessment(PageKind.RATE_LIMITED, RecommendedAction.RETRY_LATER, (PageEvidence("rate_limit", str(status or "text")),))
    challenge_markers = ("verify you are human", "security check", "just a moment", "captcha", "turnstile")
    if any(marker in haystack for marker in challenge_markers):
        return PageAssessment(PageKind.HUMAN_VERIFICATION, RecommendedAction.QUEUE_VERIFICATION, (PageEvidence("challenge_text", title or "matched body text"),))
    login_markers = ("sign in to continue", "log in to continue", "login required")
    if any(marker in haystack for marker in login_markers):
        return PageAssessment(PageKind.LOGIN_REQUIRED, RecommendedAction.QUEUE_VERIFICATION, (PageEvidence("login_text", title or "matched body text"),))
    if status == 403 or "access denied" in haystack or "forbidden" in haystack:
        return PageAssessment(PageKind.ACCESS_DENIED, RecommendedAction.RETRY_OR_STOP, (PageEvidence("access_denied", str(status or "text")),))
    if status is not None and 500 <= status < 600:
        return PageAssessment(PageKind.TEMPORARY_FAILURE, RecommendedAction.RETRY_LATER, (PageEvidence("server_error", str(status)),))
    if not html_length:
        return PageAssessment(PageKind.EMPTY, RecommendedAction.RETRY_LATER, (PageEvidence("empty", "0"),))
    if html_length < 100:
        return PageAssessment(PageKind.DELAYED_SHELL, RecommendedAction.WAIT_FOR_CONTENT, (PageEvidence("short_html", str(html_length)),))
    return PageAssessment(PageKind.UNKNOWN, RecommendedAction.STOP_WITH_DIAGNOSTICS, (PageEvidence("no_candidates", str(candidate_count)),))
```

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.test_page_state -v`

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add crawler/models.py crawler/page_state.py tests/test_page_state.py
git commit -m "feat: classify crawler page states"
```

### Task 2: Application paths and crash-safe task persistence

**Files:**
- Create: `crawler/app_paths.py`
- Create: `crawler/task_store.py`
- Test: `tests/test_task_store.py`

**Interfaces:**
- Produces: `AppPaths.for_user(base: Path | None = None) -> AppPaths`.
- Produces: `StoredTask`, `StoredRun`, `TaskStore.save(run: StoredRun)`, `TaskStore.load(run_id: str)`, and `TaskStore.recover_interrupted()`.

- [ ] **Step 1: Write persistence tests**

```python
import tempfile
import unittest
from pathlib import Path

from crawler.models import TaskStatus
from crawler.task_store import StoredRun, StoredTask, TaskStore


class TaskStoreTests(unittest.TestCase):
    def test_round_trip_and_recover_running_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TaskStore(Path(temp_dir))
            run = StoredRun("run-1", [StoredTask("task-1", "https://example.edu/faculty", "out.xlsx", TaskStatus.FETCHING)])
            store.save(run)
            loaded = store.load("run-1")
            recovered = store.recover_interrupted()
        self.assertEqual(loaded.tasks[0].status, TaskStatus.FETCHING)
        self.assertEqual(recovered[0].tasks[0].status, TaskStatus.PENDING)

    def test_state_file_never_contains_cookie_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = TaskStore(root)
            store.save(StoredRun("run-2", [StoredTask("task-2", "https://example.edu", "out.xlsx", TaskStatus.PENDING)]))
            text = (root / "run-2.json").read_text(encoding="utf-8")
        self.assertNotIn("cookie", text.casefold())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m unittest tests.test_task_store -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'crawler.task_store'`.

- [ ] **Step 3: Add application paths**

```python
# crawler/app_paths.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    tasks: Path
    sessions: Path
    runs: Path
    logs: Path
    reports: Path
    screenshots: Path
    settings: Path

    @classmethod
    def for_user(cls, base: Path | None = None) -> "AppPaths":
        root = base or Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "FacultyCrawler"
        paths = cls(root, root / "tasks", root / "sessions", root / "runs", root / "logs", root / "reports", root / "screenshots", root / "settings")
        for path in paths.__dict__.values():
            Path(path).mkdir(parents=True, exist_ok=True)
        return paths
```

- [ ] **Step 4: Add atomic task persistence**

```python
# crawler/task_store.py
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from crawler.models import TaskStatus


@dataclass
class StoredTask:
    task_id: str
    url: str
    output_path: str
    status: TaskStatus
    record_count: int = 0
    error: str = ""


@dataclass
class StoredRun:
    run_id: str
    tasks: list[StoredTask]
    schema_version: int = 1


class TaskStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, run: StoredRun) -> None:
        target = self.directory / f"{run.run_id}.json"
        temporary = target.with_suffix(".json.tmp")
        payload = asdict(run)
        payload["tasks"] = [{**task, "status": task["status"].value} for task in payload["tasks"]]
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target)

    def load(self, run_id: str) -> StoredRun:
        payload = json.loads((self.directory / f"{run_id}.json").read_text(encoding="utf-8"))
        return StoredRun(payload["run_id"], [StoredTask(**{**item, "status": TaskStatus(item["status"])}) for item in payload["tasks"]], payload["schema_version"])

    def recover_interrupted(self) -> list[StoredRun]:
        running = {TaskStatus.FETCHING, TaskStatus.EXPANDING, TaskStatus.PARSING, TaskStatus.RETRY_WAIT}
        recovered: list[StoredRun] = []
        for path in sorted(self.directory.glob("*.json")):
            run = self.load(path.stem)
            changed = False
            for task in run.tasks:
                if task.status in running:
                    task.status = TaskStatus.PENDING
                    changed = True
            if changed:
                self.save(run)
                recovered.append(run)
        return recovered
```

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.test_task_store -v`

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add crawler/app_paths.py crawler/task_store.py tests/test_task_store.py
git commit -m "feat: persist recoverable crawl tasks"
```

### Task 3: Structured diagnostics and report white-list

**Files:**
- Create: `crawler/privacy.py`
- Create: `crawler/diagnostics.py`
- Test: `tests/test_diagnostics.py`
- Modify: `crawler/batch.py`
- Modify: `tests/test_batch.py`

**Interfaces:**
- Produces: `DiagnosticEvent`, `DiagnosticRecorder.record(event)`, and `build_problem_report(run_id, events, output_path, screenshots=()) -> Path`.
- Produces: `safe_url_for_log`, `redact_log_text`, and `safe_exception_message` in `crawler/privacy.py` with their existing behavior.

- [ ] **Step 1: Write report security tests**

```python
import tempfile
import unittest
import zipfile
from pathlib import Path

from crawler.diagnostics import DiagnosticEvent, build_problem_report


class DiagnosticsTests(unittest.TestCase):
    def test_report_has_only_white_list_files_and_redacts_secrets(self):
        event = DiagnosticEvent("run-1", "task-1", "fetch", "access_denied", "Cookie: SECRET", {"status": 403})
        with tempfile.TemporaryDirectory() as temp_dir:
            report = build_problem_report("run-1", [event], Path(temp_dir) / "report.zip")
            with zipfile.ZipFile(report) as archive:
                names = sorted(archive.namelist())
                combined = b"\n".join(archive.read(name) for name in names).decode("utf-8")
        self.assertEqual(names, ["application.log", "diagnostics.json", "failed-tasks.csv", "summary.txt"])
        self.assertNotIn("SECRET", combined)
        self.assertIn("<redacted>", combined)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m unittest tests.test_diagnostics -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'crawler.diagnostics'`.

- [ ] **Step 3: Implement structured report generation**

```python
# crawler/diagnostics.py
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from crawler.privacy import redact_log_text


@dataclass(frozen=True)
class DiagnosticEvent:
    run_id: str
    task_id: str
    stage: str
    category: str
    message: str
    details: dict[str, object]


def build_problem_report(run_id: str, events: list[DiagnosticEvent], output_path: Path, screenshots: tuple[Path, ...] = ()) -> Path:
    safe_events = []
    for event in events:
        item = asdict(event)
        item["message"] = redact_log_text(event.message)
        item["details"] = {key: redact_log_text(str(value)) for key, value in event.details.items() if key.casefold() not in {"cookie", "authorization", "token", "password"}}
        safe_events.append(item)
    summary = f"批次 {run_id}\n问题任务：{len({item['task_id'] for item in safe_events})}\n"
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["task_id", "stage", "category", "message"])
    writer.writerows((item["task_id"], item["stage"], item["category"], item["message"]) for item in safe_events)
    log_text = "\n".join(f"{item['task_id']} {item['stage']} {item['category']} {item['message']}" for item in safe_events)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("summary.txt", summary)
        archive.writestr("diagnostics.json", json.dumps(safe_events, ensure_ascii=False, indent=2))
        archive.writestr("failed-tasks.csv", csv_buffer.getvalue())
        archive.writestr("application.log", log_text)
        for screenshot in screenshots:
            archive.write(screenshot, f"screenshots/{screenshot.name}")
    return output_path
```

- [ ] **Step 4: Move the existing redaction functions without changing them**

Move `safe_url_for_log`, `redact_log_text`, and `safe_exception_message` from `crawler/batch.py` into `crawler/privacy.py`. Import them back into `crawler/batch.py` so its public imports remain compatible, and make `crawler/diagnostics.py` import only from `crawler/privacy.py`. This prevents a `batch -> diagnostics -> batch` cycle.

- [ ] **Step 5: Run report tests**

Run: `python -m unittest tests.test_diagnostics tests.test_batch -v`

Expected: all diagnostics and existing batch tests pass.

- [ ] **Step 6: Add one batch diagnostic event at each terminal task state**

Modify `run_tasks` to accept `on_diagnostic: Callable[[DiagnosticEvent], None] | None = None`, create stable `run_id` and `task_id` inputs at the caller boundary, and emit a redacted event before notifying a failed task. Preserve all current defaults so existing callers remain valid.

```python
def _emit_diagnostic(callback, event):
    if callback is not None:
        callback(event)
```

Add a test asserting a failed task emits exactly one terminal event and that its message contains no cookie value.

- [ ] **Step 7: Run phase tests**

Run: `python -m unittest tests.test_page_state tests.test_task_store tests.test_diagnostics tests.test_batch tests.test_crawler_diagnostics -v`

Expected: all selected tests pass.

- [ ] **Step 8: Run the full suite**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 9: Commit**

```bash
git add crawler/privacy.py crawler/diagnostics.py crawler/batch.py tests/test_diagnostics.py tests/test_batch.py
git commit -m "feat: create safe structured problem reports"
```

### Task 4: Typed crawl outcome compatibility boundary

**Files:**
- Modify: `crawler/faculty_crawler.py`
- Modify: `crawler/batch.py`
- Modify: `main.py`
- Modify: `tests/test_crawler_diagnostics.py`
- Modify: `tests/test_batch.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `FacultyCrawler.crawl_outcome(url: str) -> CrawlOutcome`.
- Keeps: `FacultyCrawler.crawl(url: str) -> list[FacultyRecord]` as a compatibility wrapper.

- [ ] **Step 1: Add a failing compatibility test**

```python
def test_crawl_outcome_wraps_records_and_diagnostics(self):
    crawler = FacultyCrawler()
    crawler._crawl_pages = lambda url, load_page, load_dynamic_pages=None: [FacultyRecord("Ada", "Professor", "https://example.edu/ada")]
    crawler.last_diagnostics = {"Failure stage": ""}
    outcome = crawler._outcome_from_records(crawler._crawl_pages("https://example.edu", lambda url: ("", 200)))
    self.assertEqual(outcome.status, TaskStatus.SUCCEEDED)
    self.assertEqual(outcome.records[0].name, "Ada")
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m unittest tests.test_crawler_diagnostics.CrawlerDiagnosticsTests.test_crawl_outcome_wraps_records_and_diagnostics -v`

Expected: FAIL because `_outcome_from_records` does not exist.

- [ ] **Step 3: Add the compatibility boundary**

```python
def _outcome_from_records(self, records: list[FacultyRecord]) -> CrawlOutcome:
    status = TaskStatus.SUCCEEDED if records else TaskStatus.FAILED
    if records and self.last_diagnostics.get("Failure stage") == "low_coverage_warning":
        status = TaskStatus.REVIEW_RECOMMENDED
    return CrawlOutcome(status, tuple(records), tuple(self.title_pending_records), dict(self.last_diagnostics))

def crawl_outcome(self, url: str) -> CrawlOutcome:
    return self._outcome_from_records(self.crawl(url))
```

- [ ] **Step 4: Switch batch orchestration to `crawl_outcome` with a legacy fallback**

Use `crawl_outcome` when present; otherwise wrap the list returned by test fakes. Export records for both `SUCCEEDED` and `REVIEW_RECOMMENDED`; map other terminal outcomes to the existing safe error path.

- [ ] **Step 5: Run all phase tests**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 6: Commit**

```bash
git add crawler/faculty_crawler.py crawler/batch.py main.py tests/test_crawler_diagnostics.py tests/test_batch.py tests/test_cli.py
git commit -m "refactor: expose typed crawl outcomes"
```
