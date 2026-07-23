# Anti-Crawler Phase 4 Desktop Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved zero-knowledge desktop workflow, assisted Feishu report handoff, retention controls, and a Windows installer.

**Architecture:** Split the current monolithic Tkinter window into small page frames backed by an `AppController`. UI consumes typed events and services from Phases 1–3; it contains no page-classification rules. Build a PyInstaller one-folder application and wrap it with Inno Setup.

**Tech Stack:** Python 3.11, Tkinter/ttk, Playwright, PyInstaller, Inno Setup, `unittest`.

## Global Constraints

- Use the approved archive-blue, data-teal, paper-white, line-gray, amber, and failure-red tokens.
- Use Microsoft YaHei UI with system fallbacks; use Segoe UI for URLs and numeric data.
- Keep technical timeout and debug options under advanced settings.
- Never display or log raw cookie values.
- Feishu handoff opens a configured shared-folder URL and selects the local ZIP; it never calls a Feishu API.
- Destructive local-data actions require explicit confirmation and never delete exported Excel files.

---

## File Map

- Create `ui/theme.py`: visual tokens and ttk styles.
- Create `ui/controller.py`: services, state, and UI event routing.
- Create `ui/start_page.py`, `ui/tasks_page.py`, `ui/verification_page.py`, `ui/sessions_page.py`, `ui/runs_page.py`, and `ui/settings_page.py`.
- Create `crawler/settings_store.py`: local settings including output path and Feishu folder URL.
- Create `crawler/retention.py`: size accounting and retention actions.
- Modify `desktop_app.py`: shell window and navigation only.
- Modify `crawler/diagnostics.py`: submitted-report metadata and safe screenshot opt-in.
- Create UI/service tests.
- Create `faculty_crawler.spec`, `build_installer.ps1`, and `installer/faculty-crawler.iss`.
- Create `requirements-build.txt`; modify `build_release.py`, `README.md`, `使用说明.txt`, and release tests.

### Task 1: Settings, retention, and report handoff services

**Files:**
- Create: `crawler/settings_store.py`
- Create: `crawler/retention.py`
- Modify: `crawler/diagnostics.py`
- Create: `tests/test_settings_store.py`
- Create: `tests/test_retention.py`
- Modify: `tests/test_diagnostics.py`

**Interfaces:**
- Produces: `AppSettings(output_dir: str, feishu_folder_url: str, detailed_logs: bool)`.
- Produces: `SettingsStore.load/save`.
- Produces: `RetentionService.usage`, `purge_due`, `clear_temporary`, and `clear_internal_data`.
- Produces: `ReportRecord(report_id, path, created_at, submitted_at)` and `mark_report_submitted`.

- [ ] **Step 1: Write settings and retention tests**

```python
def test_settings_round_trip_and_reject_non_https_feishu_url(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SettingsStore(Path(temp_dir) / "settings.json")
        settings = AppSettings("D:/results", "https://example.feishu.cn/drive/folder/abc", False)
        store.save(settings)
        self.assertEqual(store.load(), settings)
        with self.assertRaises(ValueError):
            store.save(AppSettings("D:/results", "http://example.feishu.cn/folder", False))

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

def test_clear_internal_data_does_not_touch_output_directory(self):
    excel = self.output_dir / "faculty.xlsx"; excel.write_bytes(b"xlsx")
    self.service.clear_internal_data()
    self.assertTrue(excel.exists())
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `python -m unittest tests.test_settings_store tests.test_retention tests.test_diagnostics -v`

- [ ] **Step 3: Implement atomic JSON settings**

Validate the Feishu URL as HTTPS with a non-empty hostname. Store only display settings and paths; reject keys named cookie, token, password, authorization, or secret.

- [ ] **Step 4: Implement retention from explicit records**

Retention must operate only under `AppPaths.root`. Resolve every deletion target and verify `target.is_relative_to(paths.root)` before deletion. Unsubmitted reports have no deletion deadline. Exported Excel paths are never inputs to retention methods.

- [ ] **Step 5: Add submitted metadata to reports**

Write a sidecar metadata record after ZIP creation and update only `submitted_at` when the user clicks “标记为已提交”. Do not infer submission merely because the Feishu URL opened.

- [ ] **Step 6: Run tests and commit**

Run: `python -m unittest tests.test_settings_store tests.test_retention tests.test_diagnostics -v`

```bash
git add crawler/settings_store.py crawler/retention.py crawler/diagnostics.py tests/test_settings_store.py tests/test_retention.py tests/test_diagnostics.py
git commit -m "feat: manage report retention and handoff settings"
```

### Task 2: Desktop shell, theme, and start page

**Files:**
- Create: `ui/__init__.py`
- Create: `ui/theme.py`
- Create: `ui/controller.py`
- Create: `ui/start_page.py`
- Modify: `desktop_app.py`
- Create: `tests/test_ui_controller.py`
- Modify: `tests/test_desktop_app.py`

**Interfaces:**
- Produces: `AppController.prepare(raw_urls)`, `start_batch()`, `stop_after_current()`, and observable `AppViewState`.
- Produces: `apply_theme(root) -> None` and `StartPage` callbacks.

- [ ] **Step 1: Write controller tests without creating a real window**

```python
def test_prepare_reports_invalid_input_line_numbers(self):
    state = self.controller.prepare("https://example.edu/faculty\ninvalid")
    self.assertEqual(state.invalid_lines, ((2, "invalid"),))

def test_start_batch_uses_default_settings_without_timeout_input(self):
    self.controller.prepare("https://example.edu/faculty")
    self.controller.start_batch()
    self.assertEqual(self.runner.calls[0]["timeout"], 30000)

def test_controller_maps_internal_status_to_plain_chinese_copy(self):
    self.assertEqual(self.controller.status_label(TaskStatus.VERIFICATION_REQUIRED), "等待人工验证")
    self.assertEqual(self.controller.status_label(TaskStatus.REVIEW_RECOMMENDED), "已完成，建议检查")
```

- [ ] **Step 2: Run and verify missing-module failures**

Run: `python -m unittest tests.test_ui_controller tests.test_desktop_app -v`

- [ ] **Step 3: Implement the approved theme tokens**

```python
COLORS = {
    "archive_blue": "#17324D",
    "data_teal": "#177E89",
    "paper_white": "#F7F9FC",
    "line_gray": "#D7E0E8",
    "verification_amber": "#D88917",
    "failure_red": "#B84A4A",
}
```

Define visible keyboard focus, disabled-state contrast, sidebar navigation, primary action, warning action, and task-status styles. Do not encode status by color alone; always pair color with text and a symbol.

- [ ] **Step 4: Implement the controller boundary**

Move worker creation, queue draining, task preparation, and plain-language status mapping out of `DesktopApp`. Preserve `run_batch_worker` as a tested adapter until all pages use the controller.

- [ ] **Step 5: Build the start page**

Include multiline URLs, inline line-number validation, identified URL count, output directory, “更改位置”, and a single “检查并开始采集” action. Move timeout and detailed logs to settings.

- [ ] **Step 6: Run tests and commit**

Run: `python -m unittest tests.test_ui_controller tests.test_desktop_app -v`

```bash
git add ui desktop_app.py tests/test_ui_controller.py tests/test_desktop_app.py
git commit -m "feat: add zero-knowledge desktop shell"
```

### Task 3: Task, verification, session, run, and settings pages

**Files:**
- Create: `ui/tasks_page.py`
- Create: `ui/verification_page.py`
- Create: `ui/sessions_page.py`
- Create: `ui/runs_page.py`
- Create: `ui/settings_page.py`
- Modify: `ui/controller.py`
- Modify: `desktop_app.py`
- Create: `tests/test_ui_workflows.py`

**Interfaces:**
- Consumes typed task, verification, session, run, report, settings, and retention services.
- Produces page actions without direct crawler imports.

- [ ] **Step 1: Write workflow tests against controller fakes**

```python
def test_verification_badge_counts_only_pending_items(self):
    self.verifications.items = [self.item("a", "pending"), self.item("b", "ready"), self.item("c", "pending")]
    self.assertEqual(self.controller.verification_badge_count(), 2)

def test_process_all_verifications_runs_one_at_a_time(self):
    self.controller.process_all_verifications()
    self.assertEqual(self.verifier.maximum_concurrent_calls, 1)

def test_clear_one_session_and_clear_all_require_confirmation(self):
    self.controller.clear_session("example.edu", confirmed=False)
    self.controller.clear_all_sessions(confirmed=False)
    self.assertEqual(self.sessions.clear_calls, [])

def test_problem_report_handoff_opens_folder_and_feishu_url(self):
    self.controller.open_report_handoff(self.report)
    self.assertEqual(self.opener.paths, [self.report.path.parent])
    self.assertEqual(self.opener.urls, ["https://example.feishu.cn/drive/folder/abc"])

def test_mark_submitted_is_separate_from_open_feishu(self):
    self.controller.open_report_handoff(self.report)
    self.assertIsNone(self.report.submitted_at)
    self.controller.mark_report_submitted(self.report.report_id)
    self.assertIsNotNone(self.reports.by_id(self.report.report_id).submitted_at)

def test_cleanup_summary_excludes_excel_outputs(self):
    summary = self.controller.storage_usage()
    self.assertNotIn("Excel", summary.categories)
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m unittest tests.test_ui_workflows -v`

- [ ] **Step 3: Implement the task-status track**

Show URL/site label, plain status, record count, output filename, and next action. Provide “打开结果文件夹” and “停止后续任务”. Put stack traces and HTTP data under “查看技术信息”.

- [ ] **Step 4: Implement verification and sessions pages**

Verification offers “开始验证”, “逐个处理全部任务”, “暂不处理”, and “我已完成验证”. Sessions show hostname, saved time, last used, cleanup date, per-site clear, and clear all; never render storage-state bytes.

- [ ] **Step 5: Implement runs, report handoff, and settings pages**

Runs show batch summary, result folder, report generation, local ZIP selection, Feishu URL open, and explicit submission marking. Settings show output directory, Feishu URL, advanced timeout/log controls, storage usage, and safe cleanup actions.

- [ ] **Step 6: Run UI and full tests**

Run: `python -m unittest tests.test_ui_workflows tests.test_ui_controller tests.test_desktop_app -v`

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 7: Commit**

```bash
git add ui desktop_app.py tests/test_ui_workflows.py tests/test_ui_controller.py tests/test_desktop_app.py
git commit -m "feat: complete desktop recovery workflows"
```

### Task 4: Windows one-folder build and installer

**Files:**
- Create: `requirements-build.txt`
- Create: `faculty_crawler.spec`
- Create: `build_installer.ps1`
- Create: `installer/faculty-crawler.iss`
- Modify: `build_release.py`
- Modify: `tests/test_release.py`
- Modify: `README.md`
- Modify: `使用说明.txt`

**Interfaces:**
- Produces: `dist/FacultyCrawler/FacultyCrawler.exe` and `dist/installer/FacultyCrawler-Setup.exe`.

- [ ] **Step 1: Write release-configuration tests**

```python
def test_installer_sources_exist_and_do_not_embed_session_data(self):
    paths = [PROJECT_ROOT / "faculty_crawler.spec", PROJECT_ROOT / "build_installer.ps1", PROJECT_ROOT / "installer/faculty-crawler.iss"]
    self.assertTrue(all(path.is_file() for path in paths))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    self.assertNotIn("sessions/", combined)
    self.assertNotIn("output/", combined)

def test_pyinstaller_spec_bundles_ui_and_playwright_browser_assets(self):
    text = (PROJECT_ROOT / "faculty_crawler.spec").read_text(encoding="utf-8")
    self.assertIn("ui", text)
    self.assertIn("ms-playwright", text)

def test_inno_script_installs_per_user_and_creates_start_menu_shortcut(self):
    text = (PROJECT_ROOT / "installer/faculty-crawler.iss").read_text(encoding="utf-8")
    self.assertIn("PrivilegesRequired=lowest", text)
    self.assertIn("{group}", text)
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m unittest tests.test_release -v`

- [ ] **Step 3: Add reproducible PyInstaller build**

Pin a compatible PyInstaller major version in `requirements-build.txt`. In `build_installer.ps1`, create a clean build environment, set a task-specific Playwright browser directory, install Chromium there, run PyInstaller with `--noconfirm --clean`, and fail if the executable or bundled Chromium is missing.

- [ ] **Step 4: Add the Inno Setup script**

Use per-user installation, no administrator requirement, a start-menu shortcut, an optional desktop shortcut, uninstall support, and an application-data preservation notice. The installer must never package local `output`, `logs`, `reports`, `sessions`, `.venv`, or Git files.

- [ ] **Step 5: Update user documentation**

Document install, start, batch collection, verification queue, session clearing, problem report handoff, data retention, and uninstall. Use plain Chinese and screenshots only after the final UI is stable.

- [ ] **Step 6: Run automated verification**

Run: `python -m unittest discover -s tests -v`

Run: `python build_release.py`

Run: `powershell -ExecutionPolicy Bypass -File build_installer.ps1`

Expected: zero test failures, a reproducible source ZIP, a runnable one-folder app, and `FacultyCrawler-Setup.exe`.

- [ ] **Step 7: Perform clean-account acceptance**

Install as a standard Windows user, launch from the Start menu, crawl one controlled static fixture served locally, open the verification queue using a controlled fixture, clear one session, generate a problem report, open the configured Feishu link, uninstall, and verify exported Excel remains.

- [ ] **Step 8: Commit**

```bash
git add requirements-build.txt faculty_crawler.spec build_installer.ps1 installer build_release.py tests/test_release.py README.md 使用说明.txt
git commit -m "build: add Windows desktop installer"
```

### Task 5: Final specification acceptance

**Files:**
- Modify: `README.md`
- Modify: `使用说明.txt`
- Test: all tests and manual acceptance records.

**Interfaces:**
- Consumes all previous phase interfaces.
- Produces a release candidate satisfying the approved design.

- [ ] **Step 1: Run the full automated suite fresh**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 2: Inspect one report ZIP**

List its members and scan extracted text for cookie values, authorization values, tokens, passwords, local user names, session-state JSON, and private page body samples. Expected: only white-listed members and no seeded secret values.

- [ ] **Step 3: Exercise representative controlled pages**

Verify static, delayed JavaScript, ordinary pagination, page-size control, `Load more`, window scroll, internal scroll, virtual list, Cookie dialog, 403, 429, 5xx, timeout, login, and human challenge cases at conservative rates.

- [ ] **Step 4: Complete zero-knowledge user acceptance**

Ask a user who has not seen the code to install, paste URLs, run a batch, interpret the summary, process a verification, clear a session, and prepare a Feishu report handoff without command-line help. Record any point where technical explanation was required as a release blocker.

- [ ] **Step 5: Commit final documentation corrections**

```bash
git add README.md 使用说明.txt
git commit -m "docs: finalize crawler desktop usage"
```
