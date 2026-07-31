# Fast Workflow, Finite Review, and Diagnostic Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the fast directory path, bound review processing, and provide a compact report Codex can use to select the next optimisation.

**Architecture:** `PageFetcher` receives a source-specific policy. `WorkflowService` saves complete directory candidates before it fetches profiles, uses the short profile policy only for the remaining records, and passes bounded diagnostics into a report builder. SQLite records review attempts and converts repeated unchanged records to `unresolved`.

**Tech Stack:** Python 3, Playwright, SQLite, `openpyxl`, standard-library JSON, `unittest`.

## Global Constraints

- Only human-provided directory URLs may start collection; AI may not find or replace them.
- Every accepted email must be literal evidence on an already fetched page; no address may be guessed.
- Complete directory evidence skips profile requests.
- Directory policy remains 30 seconds and three attempts; profile policy is 10 seconds and one attempt.
- Accepted records remain unchanged during review-only processing.
- Normal runs emit only `run_report.json`, not a persisted normal log or `completed_evidence.xlsx`.
- Review gets at most two reprocesses after initial collection; unchanged results become `unresolved` earlier.

### Task 1: Source-aware fetch policies

**Files:**
- Modify: `faculty_workflow/fetcher.py`
- Test: `tests/test_workflow_fetcher.py`

**Interfaces:**
- Add `FetchPolicy(timeout_ms: int, max_attempts: int, expand_directory: bool)`.
- Add `FetchPolicy.directory() -> FetchPolicy` returning `(30000, 3, True)`.
- Add `FetchPolicy.person_profile() -> FetchPolicy` returning `(10000, 1, False)`.
- Change `PageFetcher.fetch(..., policy: FetchPolicy | None = None, on_event: Callable[[FetchEvent], None] | None = None)`.

- [ ] **Step 1: Write failing tests**

```python
def test_person_profile_policy_is_fast_fail():
    self.assertEqual(FetchPolicy.person_profile(), FetchPolicy(10_000, 1, False))

def test_directory_policy_keeps_coverage_defaults():
    self.assertEqual(FetchPolicy.directory(), FetchPolicy(30_000, 3, True))
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_fetcher.py -k "policy" -v`

Expected: `ImportError` because `FetchPolicy` is not defined.

- [ ] **Step 3: Implement the policy and diagnostics**

```python
@dataclass(frozen=True)
class FetchPolicy:
    timeout_ms: int
    max_attempts: int
    expand_directory: bool = False

    @classmethod
    def directory(cls): return cls(30_000, 3, True)

    @classmethod
    def person_profile(cls): return cls(10_000, 1, False)
```

Use the selected policy for navigation timeout, retry count, and directory expansion. Emit only `retry`, `failed`, and slow successful requests through a `FetchEvent` callback.

- [ ] **Step 4: Run the fetcher suite**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_fetcher.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add faculty_workflow/fetcher.py tests/test_workflow_fetcher.py; git commit -m "feat: add source-aware fetch policies"`

### Task 2: Literal email decoders

**Files:**
- Modify: `faculty_workflow/email_resolver.py`
- Test: `tests/test_workflow_email_resolver.py`

**Interfaces:**
- Add `_literal_email_sources(html: str) -> tuple[tuple[str, str], ...]`.
- Feed resulting values into existing `_score_email`; decoders cannot bypass official-domain, generic-address, or identity checks.

- [ ] **Step 1: Write failing tests**

```python
def test_resolves_literal_javascript_email():
    page = page_with_html("<h1>Ada Lovelace</h1><script>const e='ada'+'@'+'example.edu'</script>")
    self.assertEqual(resolve(page).email, "ada@example.edu")

def test_resolves_literal_data_attributes():
    page = page_with_html('<article><h1>Ada Lovelace</h1><span data-email-local="ada" data-email-domain="example.edu"></span></article>')
    self.assertEqual(resolve(page).email, "ada@example.edu")

def test_rejects_outside_or_generic_literal_email():
    page = page_with_html('<h1>Ada Lovelace</h1><span data-email-local="office" data-email-domain="other.edu"></span>')
    self.assertIsNone(resolve(page))
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_email_resolver.py -k "literal" -v`

Expected: FAIL because literal JavaScript and data attributes are ignored.

- [ ] **Step 3: Implement bounded decoders**

Match only quoted `local + '@' + domain` JavaScript strings and collect `data-email-local`/`data-email-domain` plus `data-user`/`data-domain` pairs via `HTMLParser`. Decode HTML entities before matching. Pass literal context and method names `javascript_literal` or `data_attribute` to `_score_email`; never evaluate arbitrary JavaScript.

- [ ] **Step 4: Run the email suite**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_email_resolver.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add faculty_workflow/email_resolver.py tests/test_workflow_email_resolver.py; git commit -m "feat: decode literal protected official emails"`

### Task 3: Directory-first service path

**Files:**
- Modify: `faculty_workflow/service.py`
- Test: `tests/test_workflow_service.py`

**Interfaces:**
- Directory seeds with a no-reason quality decision are saved as `accepted` before profile discovery.
- Remaining seeds fetch with `FetchPolicy.person_profile()`.
- Directory and secondary-directory sources fetch with `FetchPolicy.directory()`.

- [ ] **Step 1: Write failing tests**

```python
def test_complete_directory_person_does_not_fetch_profile():
    service.run_task(task_id)
    self.assertEqual(fetcher.profile_urls, [])
    self.assertEqual(accepted_rows(database, task_id)[0]["email"], "ada@example.edu")

def test_missing_directory_email_fetches_fast_fail_profile_and_reviews_on_error():
    service.run_task(task_id)
    self.assertEqual(fetcher.profile_policies, [FetchPolicy.person_profile()])
    self.assertIn("profile_fetch_failed", review_rows(database, task_id)[0]["review_reason"])
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_service.py -k "directory_person or fast_fail_profile" -v`

Expected: FAIL because profiles are pre-fetched before the directory fast path.

- [ ] **Step 3: Implement lazy profile work**

Evaluate and save directory candidates immediately after seed collection. Skip profiles for accepted candidates. Remove the all-seed prefetch loop; after fetching a non-fast-path profile, discover its linked research sources and then resolve its email. Attach the respective `FetchPolicy` at every fetch call.

- [ ] **Step 4: Run service tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add faculty_workflow/service.py tests/test_workflow_service.py; git commit -m "perf: fetch profiles only when directory evidence is incomplete"`

### Task 4: Finite review lifecycle

**Files:**
- Modify: `faculty_workflow/database.py`
- Modify: `faculty_workflow/quality.py`
- Modify: `faculty_workflow/service.py`
- Test: `tests/test_workflow_database.py`
- Test: `tests/test_workflow_service.py`

**Interfaces:**
- Add candidate status `unresolved`.
- Add `WorkflowDatabase.close_unchanged_reviews(task_id: str, generation_id: str) -> int`.
- Add `WorkflowDatabase.reopen_unresolved(task_id: str, candidate_ids: Iterable[int], reason: str) -> tuple[int, tuple[int, ...]]`.
- Add generation fields `attempt_number` and `reopened_reason`.

- [ ] **Step 1: Write failing tests**

```python
def test_unchanged_review_is_closed_as_unresolved():
    generation = database.begin_review_generation(task_id)
    add_same_review_result(database, task_id)
    self.assertEqual(database.close_unchanged_reviews(task_id, generation["id"]), 1)
    self.assertEqual(active_rows(database, task_id)[0]["status"], "unresolved")

def test_second_reprocess_is_the_last_automatic_attempt():
    complete_two_review_generations(database, task_id)
    generation = database.begin_review_generation(task_id)
    self.assertEqual(generation["status"], "completed")
    self.assertEqual(unresolved_rows(database, task_id).__len__(), 1)

def test_reopen_keeps_accepted_and_requeues_only_selected_school():
    self.assertEqual(database.reopen_unresolved(task_id, [unresolved_id], "decoder upgraded"), (1, (school_id,)))
    self.assertEqual(accepted_rows(database, task_id)[0]["name"], "Grace Hopper")
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_database.py -k "unchanged_review or last_automatic or reopen" -v`

Expected: FAIL because the status, tracking columns, and reopening API do not exist.

- [ ] **Step 3: Implement migrations and transitions**

Store `attempt_number` and `reopened_reason` in `reprocessing_generations`. Persist a deterministic review fingerprint containing sorted evidence source hashes, parser/email rules version, and sorted reasons. After a generation, convert a new review to `unresolved` when its fingerprint is unchanged from its superseded review. Before generation three, convert remaining active review rows to `unresolved` and return a completed no-work generation. Reopening requires a nonblank reason, preserves accepted rows, and records a new generation.

- [ ] **Step 4: Add manual-action mapping and service calls**

Add `recommended_manual_action(reason: str) -> str`: `missing_email` maps to `Check the official profile or leave unresolved`; `profile_fetch_failed` maps to `Verify access or retry after the site is available`; every other reason maps to `Inspect the source evidence and update the relevant rule`. Call `close_unchanged_reviews` when review-only work completes.

- [ ] **Step 5: Run lifecycle suites**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_database.py tests/test_workflow_service.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run: `git add faculty_workflow/database.py faculty_workflow/quality.py faculty_workflow/service.py tests/test_workflow_database.py tests/test_workflow_service.py; git commit -m "feat: bound review retries and retain unresolved records"`

### Task 5: One bounded run report and simplified exports

**Files:**
- Create: `faculty_workflow/reporting.py`
- Modify: `faculty_workflow/exporter.py`
- Modify: `faculty_workflow/service.py`
- Create: `tests/test_workflow_reporting.py`
- Modify: `tests/test_workflow_exporter.py`

**Interfaces:**
- Add `RunReporter(max_events_per_kind: int = 20)` with `record(FetchEvent)`, `record_phase(name: str, elapsed_ms: int)`, and `build(database, task_id) -> dict`.
- Change `export_task(...)` to return only `final`, `review`, and `report` paths.

- [ ] **Step 1: Write failing tests**

```python
def test_report_caps_failures_and_reports_profile_timeout_signal():
    reporter = RunReporter(max_events_per_kind=2)
    for number in range(3): reporter.record(FetchEvent("failed", f"https://example.edu/{number}", "person_profile", 10_000, 1, "timeout"))
    report = reporter.build(database, task_id)
    self.assertEqual(len(report["diagnostics"]["failed"]), 2)
    self.assertIn("profile_timeouts_dominate", {x["code"] for x in report["optimization_signals"]})

def test_export_only_writes_final_review_and_report():
    paths = export_task(database, task_id, root, reporter=RunReporter())
    self.assertEqual(set(paths), {"final", "review", "report"})
    self.assertFalse(any("completed_evidence" in path.name for path in root.iterdir()))
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_reporting.py tests/test_workflow_exporter.py -v`

Expected: FAIL because `RunReporter` and the new export contract do not exist.

- [ ] **Step 3: Implement report and exporter contract**

Report elapsed phase/source counts, accepted/review/unresolved/rejected counts, top reasons, review-generation history, and at most twenty entries each for retry, failed, dynamic-stop, and slow-source diagnostics. Emit codes `profile_timeouts_dominate`, `profile_fetch_volume_high`, `cache_reparse_overhead_high`, `email_missing_dominates_review`, `directory_detection_false_positive`, and `directory_coverage_incomplete` only when their measured thresholds apply. Export review and unresolved rows with status, retry count, terminal state, and manual action. Remove completed-evidence and audit output generation.

- [ ] **Step 4: Run report/export suites**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_reporting.py tests/test_workflow_exporter.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add faculty_workflow/reporting.py faculty_workflow/exporter.py faculty_workflow/service.py tests/test_workflow_reporting.py tests/test_workflow_exporter.py; git commit -m "feat: export compact optimisation run reports"`

### Task 6: Controls, documentation, and full verification

**Files:**
- Modify: `workflow.py`
- Modify: `workflow_desktop.py`
- Modify: `README.md`
- Modify: `README_WORKFLOW_AI.md`
- Modify: `tests/test_workflow_cli.py`

**Interfaces:**
- Add `reopen-unresolved --task TASK_ID --candidate IDS --reason TEXT`.
- Add `WorkflowService.reopen_unresolved(task_id: str, candidate_ids: list[int], reason: str) -> dict`.

- [ ] **Step 1: Write failing CLI test**

```python
def test_reopen_unresolved_calls_service_with_ids_and_reason():
    exit_code = workflow.main(["reopen-unresolved", "--task", "t1", "--candidate", "41", "42", "--reason", "decoder upgraded"])
    self.assertEqual(exit_code, 0)
    mock_reopen.assert_called_once_with("t1", candidate_ids=[41, 42], reason="decoder upgraded")
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workflow_cli.py -k "reopen_unresolved" -v`

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement action and docs**

Require a nonblank reopening reason in CLI and desktop UI. Document the accepted threshold, 10-second profile policy, literal-only email decoding, review versus unresolved, manual reopening, removal of `completed_evidence.xlsx`, and the exact `run_report.json` fields Codex should inspect before changing code.

- [ ] **Step 4: Run full verification**

Run: `.venv\\Scripts\\python.exe -m pytest -q; .venv\\Scripts\\python.exe -m compileall faculty_workflow workflow.py workflow_desktop.py; git diff --check`

Expected: all tests pass, compilation passes, and `git diff --check` emits no errors.

- [ ] **Step 5: Commit**

Run: `git add workflow.py workflow_desktop.py README.md README_WORKFLOW_AI.md tests/test_workflow_cli.py; git commit -m "docs: explain fast collection and finite review workflow"`

