# Anti-Crawler Phase 3 Verification and Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Queue human verification without blocking the batch, resume verified tasks, and protect reusable site sessions for 30 days.

**Architecture:** A persistent verification repository stores task references but no credentials. A session store encrypts Playwright storage-state bytes with a platform protector; a synchronous verification service runs in a dedicated UI worker and returns a typed result.

**Tech Stack:** Python 3.11, Playwright, Windows DPAPI via `ctypes`, JSON, `unittest`.

## Global Constraints

- Verification requires explicit user action and never attempts automated solving.
- Passwords and user input are never read or stored by the application.
- Session files are isolated by exact hostname and expire after 30 days.
- No session bytes may appear in logs, reports, tests, or task-state JSON.

---

## File Map

- Create `crawler/session_store.py`: protection interface, Windows DPAPI implementation, expiry, listing, and deletion.
- Create `crawler/verification.py`: persistent queue and visible-browser verification service.
- Modify `crawler/faculty_crawler.py`: load and update storage state.
- Modify `crawler/batch.py`: map verification outcomes without stopping later tasks.
- Modify `desktop_app.py`: verification worker events only; full visual redesign remains Phase 4.
- Create `tests/test_session_store.py` and `tests/test_verification.py`.
- Modify `tests/test_batch.py`, `tests/test_desktop_app.py`, and `tests/test_crawler_diagnostics.py`.

### Task 1: Protected, expiring session store

**Files:**
- Create: `crawler/session_store.py`
- Test: `tests/test_session_store.py`

**Interfaces:**
- Produces: `DataProtector.protect(data: bytes) -> bytes`, `unprotect(data: bytes) -> bytes`.
- Produces: `SessionInfo(hostname, saved_at, last_used_at, expires_at)`.
- Produces: `SessionStore.save`, `load`, `list_sessions`, `clear_site`, `clear_all`, and `purge_expired`.

- [ ] **Step 1: Write tests with an injected protector and clock**

```python
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.session_store import SessionStore


class ReversingProtector:
    def protect(self, data): return data[::-1]
    def unprotect(self, data): return data[::-1]


class SessionStoreTests(unittest.TestCase):
    def test_round_trip_does_not_leave_plain_cookie_on_disk(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("faculty.example.edu", b'{"cookies":[{"value":"SECRET"}]}')
            disk = next(root.glob("*.session")).read_bytes()
            loaded = store.load("faculty.example.edu")
        self.assertNotIn(b"SECRET", disk)
        self.assertIn(b"SECRET", loaded)

    def test_purge_removes_sessions_after_30_days(self):
        current = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir), ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"state")
            current[0] += timedelta(days=31)
            removed = store.purge_expired()
        self.assertEqual(removed, ["example.edu"])
```

- [ ] **Step 2: Run and verify missing-module failure**

Run: `python -m unittest tests.test_session_store -v`

- [ ] **Step 3: Implement metadata plus encrypted payload files**

Use a SHA-256 hostname digest for filenames, store non-sensitive timestamps and exact hostname in `.json`, store only protected bytes in `.session`, write atomically, and compute expiry as `saved_at + timedelta(days=30)`.

- [ ] **Step 4: Implement `WindowsDpapiProtector`**

Wrap `CryptProtectData` and `CryptUnprotectData` with `ctypes`, set the optional description to `FacultyCrawler session`, free returned buffers with `LocalFree`, and raise `SessionProtectionError` on failure. Do not provide a plaintext fallback.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_session_store -v`

Expected: session tests pass, including clear-site and clear-all cases.

```bash
git add crawler/session_store.py tests/test_session_store.py
git commit -m "feat: protect and expire site sessions"
```

### Task 2: Persistent non-blocking verification queue

**Files:**
- Create: `crawler/verification.py`
- Test: `tests/test_verification.py`
- Modify: `crawler/batch.py`
- Modify: `tests/test_batch.py`

**Interfaces:**
- Produces: `VerificationItem(task_id, url, hostname, detected_at, reason, attempts, status)`.
- Produces: `VerificationQueue.enqueue`, `pending`, `mark_ready`, `defer`, and `mark_failed`.

- [ ] **Step 1: Write queue and batch tests**

```python
class FakeOutcomeCrawler:
    def __init__(self, outcomes):
        self.outcomes = outcomes
    def crawl_outcome(self, url):
        return next(self.outcomes)

def test_enqueue_survives_repository_reload(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "queue.json"
        queue = VerificationQueue(path)
        queue.enqueue(VerificationItem("task-1", "https://example.edu", "example.edu", "2026-07-22T10:00:00Z", "challenge"))
        loaded = VerificationQueue(path).pending()
    self.assertEqual([item.task_id for item in loaded], ["task-1"])

def test_duplicate_task_id_updates_instead_of_duplicating(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        queue = VerificationQueue(Path(temp_dir) / "queue.json")
        first = VerificationItem("task-1", "https://example.edu", "example.edu", "2026-07-22T10:00:00Z", "challenge")
        second = VerificationItem("task-1", "https://example.edu", "example.edu", "2026-07-22T10:01:00Z", "login")
        queue.enqueue(first)
        queue.enqueue(second)
        loaded = queue.pending()
    self.assertEqual(len(loaded), 1)
    self.assertEqual(loaded[0].reason, "login")

def test_verification_required_task_does_not_stop_next_batch_task(self):
    outcomes = iter([
        CrawlOutcome(TaskStatus.SUCCEEDED, (FacultyRecord("Ada", "Professor", "https://one.edu/ada"),)),
        CrawlOutcome(TaskStatus.VERIFICATION_REQUIRED),
        CrawlOutcome(TaskStatus.SUCCEEDED, (FacultyRecord("Grace", "Professor", "https://two.edu/grace"),)),
    ])
    tasks = [CrawlTask("https://one.edu", Path("one.xlsx")), CrawlTask("https://verify.edu", Path("verify.xlsx")), CrawlTask("https://two.edu", Path("two.xlsx"))]
    run_tasks(tasks, crawler_factory=lambda timeout: FakeOutcomeCrawler(outcomes), exporter=lambda records, path: None)
    self.assertEqual([task.status for task in tasks], ["succeeded", "verification_required", "succeeded"])
```

The batch test must use three tasks and assert statuses `succeeded`, `verification_required`, `succeeded` in that order.

- [ ] **Step 2: Run focused tests and verify failures**

Run: `python -m unittest tests.test_verification tests.test_batch -v`

- [ ] **Step 3: Implement the JSON queue through `TaskStore`-style atomic writes**

Keep queue fields non-sensitive. Store sanitized URLs through `safe_url_for_log`; preserve the original URL only in the protected task repository that already owns it.

- [ ] **Step 4: Update batch terminal-state mapping**

When `CrawlOutcome.status` is `VERIFICATION_REQUIRED`, enqueue it, notify the UI, and continue. Do not raise `EmptyCrawlResultError` for this outcome.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_verification tests.test_batch -v`

```bash
git add crawler/verification.py crawler/batch.py tests/test_verification.py tests/test_batch.py
git commit -m "feat: queue human verification tasks"
```

### Task 3: Visible-browser verification service and resume

**Files:**
- Modify: `crawler/verification.py`
- Modify: `crawler/faculty_crawler.py`
- Modify: `desktop_app.py`
- Modify: `tests/test_verification.py`
- Modify: `tests/test_crawler_diagnostics.py`
- Modify: `tests/test_desktop_app.py`

**Interfaces:**
- Produces: `VerificationResult(status: TaskStatus, storage_state: bytes | None, assessment: PageAssessment)`.
- Produces: `VerificationService.verify(item, *, completion_event, cancel_event) -> VerificationResult`.

- [ ] **Step 1: Write service tests using a fake browser context**

```python
def test_verified_directory_returns_ready_to_resume_and_storage_state(self):
    service = VerificationService(browser_runner=lambda item, done, cancel: (True, b'{"cookies":[]}'))
    result = service.verify(self.item, completion_event=Event(), cancel_event=Event())
    self.assertEqual(result.status, TaskStatus.READY_TO_RESUME)
    self.assertEqual(result.storage_state, b'{"cookies":[]}')

def test_closed_browser_keeps_item_pending(self):
    service = VerificationService(browser_runner=lambda item, done, cancel: (False, None))
    result = service.verify(self.item, completion_event=Event(), cancel_event=Event())
    self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)

def test_cancel_defers_without_losing_queue_item(self):
    cancel = Event(); cancel.set()
    service = VerificationService(browser_runner=lambda item, done, cancel: (False, None))
    result = service.verify(self.item, completion_event=Event(), cancel_event=cancel)
    self.assertEqual(result.status, TaskStatus.VERIFICATION_REQUIRED)

def test_storage_state_is_not_logged(self):
    service = VerificationService(browser_runner=lambda item, done, cancel: (True, b'SECRET-STATE'))
    with self.assertLogs("crawler.verification", level="INFO") as captured:
        service.verify(self.item, completion_event=Event(), cancel_event=Event())
    self.assertNotIn("SECRET-STATE", "\n".join(captured.output))
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `python -m unittest tests.test_verification tests.test_desktop_app -v`

- [ ] **Step 3: Implement the visible verification loop**

Launch `headless=False`, load saved storage state when present, navigate to the item URL, and poll page assessment until candidates appear, the user signals completion, the user cancels, or the browser closes. On success serialize `context.storage_state()` to bytes and return it without logging.

- [ ] **Step 4: Integrate session loading into normal crawl**

`FacultyCrawler` receives an optional `SessionStore`. Before creating its context it loads state for `urlparse(url).hostname`; after a successful verified resume it saves new state. Corrupt or expired state is deleted and produces a non-secret diagnostic event.

- [ ] **Step 5: Add desktop worker events**

Add `verification_started`, `verification_ready`, `verification_deferred`, and `verification_failed` UI events. Run verification in its own worker thread only after the user chooses to process the queue.

- [ ] **Step 6: Run the full suite**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 7: Commit**

```bash
git add crawler/verification.py crawler/faculty_crawler.py desktop_app.py tests/test_verification.py tests/test_crawler_diagnostics.py tests/test_desktop_app.py
git commit -m "feat: resume crawls after human verification"
```
