# Official Evidence Fast Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avoid unnecessary official profile and email-source network visits when equivalent complete official evidence is already available or cached.

**Architecture:** Add a deterministic directory-completeness decision that reuses the existing extraction and evaluator, then route accepted directory records directly to persistence. Extend the email resolver fetch callback to reuse the existing successful-source snapshot loader before network access.

**Tech Stack:** Python 3, SQLite workflow database, `unittest`, existing `WorkflowService`, `PageFetcher`, and evidence evaluator.

## Global Constraints

- Never infer an email address or domain.
- Search results are discovery hints only.
- Preserve profile and research-source discovery for incomplete directory evidence.
- Reuse only successful, readable official snapshots.
- Work locally; do not commit or push.

---

### Task 1: Complete-directory fast path

**Files:**
- Modify: `faculty_workflow/service.py`
- Test: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: directory seed dictionaries, `DisciplinePolicy`, and `evaluate_candidate(...)`.
- Produces: `_directory_fast_path_decision(...) -> tuple[CandidateExtraction, CandidateDecision] | None` or an equivalent private helper.

- [ ] **Step 1: Write the failing integration test**

Create a directory fixture containing `Ada Lovelace | Professor | Physics | ada@example.edu` plus a profile URL. Use a fetcher that raises if the profile URL is requested. Assert the task has one accepted candidate, no review candidates, and the profile URL was never fetched.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_workflow_service.WorkflowServiceTests.test_complete_official_directory_evidence_skips_profile_fetch`

Expected: FAIL because the existing workflow requests the linked profile.

- [ ] **Step 3: Implement the minimal fast path**

Build a directory-only extraction, apply the title pipeline, set official-source status from the directory URL, and evaluate it with the existing evaluator. Skip prefetch/discovery for accepted directory seeds and persist their accepted decision before the profile-fetch branch. Keep hard exclusions ahead of this branch.

- [ ] **Step 4: Verify GREEN and incomplete-record behavior**

Run the new test and the existing profile extraction/failure tests. Add a focused assertion that a record missing title or discipline evidence still requests its profile and can complete from it.

### Task 2: Cached official-email follow-up reuse

**Files:**
- Modify: `faculty_workflow/service.py`
- Test: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `WorkflowDatabase.find_source(...)` and `_load_cached_source_page(...)`.
- Produces: email resolver callback behavior that returns cached `FetchedPage` objects before calling `self.fetcher.fetch(...)`.

- [ ] **Step 1: Write the failing cached-follow-up test**

Persist a successful official email-source snapshot, configure a profile that links to that URL, and use a fetcher that raises if the email-source URL is requested. Assert the candidate receives the page-present official email and is accepted.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_workflow_service.WorkflowServiceTests.test_cached_official_email_source_is_reused`

Expected: FAIL because the resolver callback currently always performs a network fetch.

- [ ] **Step 3: Implement minimal cache reuse**

In `fetch_email_source`, query the task source by URL, call `_load_cached_source_page`, and fetch only when no valid cached page exists. Record newly fetched pages as before and avoid creating duplicate fetched-source work for cache hits.

- [ ] **Step 4: Verify GREEN**

Run both new focused tests and all workflow service tests.

### Task 3: Regression and performance validation

**Files:**
- Modify only if a regression is found: `faculty_workflow/service.py`, `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: verified local implementation with unchanged evidence gates.

- [ ] **Step 1: Run the complete test suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: all tests pass with zero failures.

- [ ] **Step 2: Run a controlled Ghent cached rerun copy**

Use a copied Ghent workflow database or a fixture-based request counter; do not mutate task `67e246112066`. Compare profile/email-source network request counts against the pre-change behavior and validate accepted emails with `scripts.validate_task_acceptance`.

- [ ] **Step 3: Inspect the local diff**

Run: `git diff -- faculty_workflow/service.py tests/test_workflow_service.py docs/superpowers/specs/2026-07-30-official-evidence-fast-path-design.md docs/superpowers/plans/2026-07-30-official-evidence-fast-path.md`

Confirm the diff contains only the fast path, cache reuse, tests, and documentation.
