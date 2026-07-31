# Minimal Workflow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct snapshot persistence, review-only scope, and audit duplicate reporting before the 2.1.0 merge.

**Architecture:** Keep the existing workflow interfaces. Add one optional school-ID filter to task execution, make snapshot persistence fail explicitly before writing incomplete cache data, and derive audit duplicate counts from normalized active identities.

**Tech Stack:** Python 3, `unittest`, SQLite, gzip, openpyxl.

## Global Constraints

- Do not make network requests in tests.
- Keep normal task execution behavior unchanged when no school filter is provided.
- Preserve completed candidate rows during review reprocessing.
- Never silently treat a truncated HTML snapshot as reusable cache input.

---

### Task 1: Preserve deterministic HTML snapshots

**Files:**
- Modify: `faculty_workflow/fetcher.py`
- Test: `tests/test_workflow_fetcher.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fetch_rejects_html_that_exceeds_snapshot_limit(self) -> None:
    fetcher = PageFetcher(max_snapshot_bytes=10, ...)
    with self.assertRaisesRegex(FetchError, "snapshot limit"):
        fetcher.fetch("https://example.edu/directory", snapshot_dir)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_workflow_fetcher.WorkflowFetcherTests.test_fetch_rejects_html_that_exceeds_snapshot_limit`

- [ ] **Step 3: Write the minimal implementation**

```python
if len(raw) > self.max_snapshot_bytes:
    raise FetchError("HTML exceeds snapshot limit")
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m unittest tests.test_workflow_fetcher.WorkflowFetcherTests.test_fetch_rejects_html_that_exceeds_snapshot_limit`

### Task 2: Constrain review-generation execution

**Files:**
- Modify: `faculty_workflow/service.py`
- Test: `tests/test_workflow_service.py`

- [ ] **Step 1: Write the failing test**

```python
summary = service.run_review_generation(task_id)
self.assertEqual(fetcher.requested_school_names, ["Reviewed School"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_workflow_service.WorkflowServiceTests.test_review_generation_does_not_run_unrelated_pending_school`

- [ ] **Step 3: Write the minimal implementation**

```python
def run_task(self, task_id, *, school_ids=None, on_progress=None):
    schools = self.database.list_schools(task_id, ["pending", "failed"])
    if school_ids is not None:
        schools = [school for school in schools if int(school["id"]) in school_ids]
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m unittest tests.test_workflow_service.WorkflowServiceTests.test_review_generation_does_not_run_unrelated_pending_school`

### Task 3: Report active duplicate counts

**Files:**
- Modify: `faculty_workflow/exporter.py`
- Test: `tests/test_workflow_database.py`

- [ ] **Step 1: Write the failing test**

```python
audit = _build_audit(database, task_id, [], active_rows)
self.assertEqual(audit["school_coverage"][0]["active_duplicate_count"], 1)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_workflow_database.WorkflowDatabaseTests.test_audit_counts_duplicate_active_identities`

- [ ] **Step 3: Write the minimal implementation**

```python
identities = [normalized_identity(row) for row in active]
duplicate_count = len(identities) - len(set(identities))
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m unittest tests.test_workflow_database.WorkflowDatabaseTests.test_audit_counts_duplicate_active_identities`

### Task 4: Validate the release candidate

**Files:**
- Test: `tests/`

- [ ] **Step 1: Run all tests**

Run: `python -m unittest discover -s tests`

- [ ] **Step 2: Compile production modules**

Run: `python -m compileall -q crawler faculty_workflow scripts workflow.py workflow_desktop.py`

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check`
