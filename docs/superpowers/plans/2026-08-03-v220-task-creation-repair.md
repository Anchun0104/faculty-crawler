# v2.2.0 Task Creation Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make direct-URL batches persist as visible tasks before crawling, and make pre-persistence failures diagnosable without exposing sensitive data.

**Architecture:** Split the desktop direct-batch command into create and run phases. The facade retains sanitized desktop-operation failures for inclusion in diagnostic ZIPs. The UI refreshes after creation and only then schedules execution.

**Tech Stack:** Python, PySide6, SQLite, pytest, existing diagnostic ZIP builder.

## Global Constraints

- Preserve v2.2.0 crawling, AI, and verification behavior.
- Do not log cookies, secrets, URL query values, or page content.
- Do not automatically rerun or migrate legacy `tasks/*.json` records.
- PySide6 remains the default desktop entry; Tk remains explicit opt-in only.

---

### Task 1: Persist desktop-operation diagnostics

**Files:**
- Modify: `desktop_ui/workflow_facade.py`
- Test: `tests/test_desktop_ui_facade.py`

**Interface:** Add `record_operation_failure(operation: str, error: Exception) -> None`; `export_diagnostics()` appends retained sanitized events.

- [ ] Write `test_export_diagnostics_includes_sanitized_create_failure`: inject `RuntimeError("token=secret")`, export the ZIP, assert `create_direct_batch` and `RuntimeError` appear and `secret` does not.
- [ ] Run `.venv\\Scripts\\python.exe -m pytest tests/test_desktop_ui_facade.py::WorkflowFacadeTests::test_export_diagnostics_includes_sanitized_create_failure -v`; expect missing-method failure.
- [ ] Add the smallest in-memory event list and append it to `export_diagnostics` input events.
- [ ] Rerun `.venv\\Scripts\\python.exe -m pytest tests/test_desktop_ui_facade.py -v`; expect PASS.
- [ ] Commit `fix: retain desktop operation diagnostics`.

### Task 2: Split direct creation and execution

**Files:**
- Modify: `desktop_ui/main_window.py`
- Test: `tests/test_desktop_ui_shell.py`

**Interface:** `_start_direct_batch(request)` first creates one task, refreshes task pages, and then schedules `run_task(task_id, ...)`; a creation exception calls `record_operation_failure("create_direct_batch", error)` and does not run the crawler.

- [ ] Write a failing test proving a valid URL creates before the run worker starts; write a second failing test where `create_direct_tasks` raises and `run_task` is not called.
- [ ] Run only those tests; expect failure because v2.2 combines create and run.
- [ ] Split `_create_and_run_direct` into minimal create and run callbacks; keep widget updates in signal handlers.
- [ ] Rerun `tests/test_desktop_ui_shell.py tests/test_desktop_ui_facade.py`; expect PASS.
- [ ] Commit `fix: persist direct batches before crawling`.

### Task 3: Explain legacy records without executing them

**Files:**
- Modify: `desktop_ui/workflow_facade.py`
- Modify: `desktop_ui/pages/tasks.py`
- Test: `tests/test_desktop_ui_pages.py`
- Test: `tests/test_desktop_app.py`

**Interface:** Add `legacy_task_notice() -> str | None`, which only counts `AppPaths.tasks/*.json`; task page renders the returned informational text.

- [ ] Write a failing facade/page test with one JSON file that expects an old-format notice and no database write; retain the existing default-entry test.
- [ ] Run the targeted tests; expect missing API/display failure.
- [ ] Implement count-only notice and informational banner; do not parse or run JSON.
- [ ] Rerun targeted tests; expect PASS.
- [ ] Commit `fix: clarify legacy task compatibility`.

### Task 4: Verify and package

**Files:**
- Modify: `CHANGELOG.md`
- Test: `tests/test_release_notes.py`

- [ ] Write a failing test requiring a changelog entry that mentions task creation and diagnostics.
- [ ] Run it and observe the expected failure.
- [ ] Add one concise unreleased changelog entry and the minimal test.
- [ ] Run targeted desktop tests, then the full suite. If only Playwright browser binaries are absent, install Chromium and rerun.
- [ ] Build with `build_release.py`, calculate SHA-256, and launch the packaged executable without `FACULTY_CRAWLER_LEGACY_UI` to verify the PySide6 title.
- [ ] Commit `docs: describe task creation repair`.
