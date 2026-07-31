# PySide6 Modern Scientific Utility Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the packaged Tkinter workflow shell with a PySide6 desktop UI matching the approved Modern Scientific Utility design while preserving crawler behavior, adding clear multi-URL input, and exposing secure AI configuration and usage.

**Architecture:** Keep `crawler/` and `faculty_workflow/` as the business/data layer. Add a focused `desktop_ui/` PySide6 presentation package whose view models call framework-independent application services; move reusable workflow orchestration out of `workflow_desktop.py` instead of wrapping Tk widgets. Keep the Tkinter entry available for one release as a diagnostic fallback, but change the packaged entry only after parity tests pass.

**Tech Stack:** Python 3.11+, PySide6 6.11.1, Qt Widgets/QSS, SQLite, existing Playwright and workflow services, `unittest`, PyInstaller 6.16.x.

## Global Constraints

- Do not add QFluentWidgets; reproduce the visual language with native PySide6 and project-owned QSS.
- Main design canvas is 1440 × 900; minimum supported window is 1180 × 720.
- Navigation is 220 px expanded and 56 px collapsed; task inspector is 360 px.
- Base body text is 14 px and interactive text must not be smaller than 12 px.
- External AI remains opt-in and may only assist with already-fetched pages; it never discovers/replaces URLs, guesses email, or bypasses access control.
- API keys remain encrypted by Windows DPAPI and are never returned as plaintext to UI view models after initial save.
- Pasted URL input accepts one URL per line, has no artificial item limit, ignores duplicates, blocks invalid lines, and reports the exact task count.
- Preserve existing user databases, session data, task data, output files, settings paths, CLI entry points, and privacy redaction behavior.
- All visible states use icon/text plus color; keyboard focus must be visible and Windows DPI scaling must not clip controls.
- PySide6 licensing and third-party notices must be documented before release packaging.
- New Qt tests use `unittest.TestCase`, one shared offscreen `QApplication`, `QTest` for input, and `QSignalSpy` for signals; do not add pytest/pytest-qt solely for this migration.

---

## File Structure

### New presentation package

- `desktop_ui/__init__.py`: package marker and exported `run_desktop()` entry.
- `desktop_ui/app.py`: `QApplication` lifecycle, dependency assembly, and top-level startup.
- `desktop_ui/main_window.py`: title bar, navigation, stacked pages, responsive layout, tray state.
- `desktop_ui/tokens.py`: immutable design-token values used by Python widgets.
- `desktop_ui/theme.qss`: project-owned light-theme styling.
- `desktop_ui/icons.py`: project-owned/Qt-standard icon resolution and accessible labels.
- `desktop_ui/models.py`: immutable UI-facing dataclasses only.
- `desktop_ui/workflow_facade.py`: framework-independent facade over `WorkflowService`, `WorkflowDatabase`, `AiSettingsStore`, and existing stores.
- `desktop_ui/workers.py`: `QObject`/`QThreadPool` adapters for non-blocking commands and progress signals.
- `desktop_ui/widgets/`: reusable buttons, InfoBar, status badge, empty state, data table, and inspector.
- `desktop_ui/pages/`: overview, tasks, verification, runs, sessions, settings, AI, storage/diagnostics.
- `desktop_ui/dialogs/new_crawl.py`: multiline URL/XLSX task creation.
- `desktop_ui/dialogs/confirm.py`: destructive-action confirmation.

### Modified existing files

- `faculty_workflow/database.py`: query APIs for AI call usage summaries and per-task details.
- `faculty_workflow/ai_settings.py`: masked key status API; no plaintext-read addition.
- `desktop_app.py`: packaged entry delegates to PySide6 after parity gate.
- `faculty_crawler.spec`, `build_installer.ps1`, `requirements.txt`, `requirements-build.txt`, `THIRD_PARTY_NOTICES.md`: dependency and packaging integration.
- `README.md`, `使用说明.txt`: user-facing navigation, AI key, usage, and multi-URL instructions.

### Tests

- `tests/test_desktop_ui_tokens.py`
- `tests/test_desktop_ui_facade.py`
- `tests/test_desktop_ui_workers.py`
- `tests/test_desktop_ui_shell.py`
- `tests/test_desktop_ui_new_crawl.py`
- `tests/test_desktop_ui_ai_settings.py`
- `tests/test_desktop_ui_pages.py`
- `tests/test_desktop_ui_accessibility.py`
- Existing workflow, privacy, database, batch, build, and release tests remain required.

---

### Task 1: Add PySide6 dependency and deterministic design tokens

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-build.txt`
- Modify: `THIRD_PARTY_NOTICES.md`
- Create: `desktop_ui/__init__.py`
- Create: `desktop_ui/tokens.py`
- Create: `desktop_ui/theme.qss`
- Test: `tests/test_desktop_ui_tokens.py`

**Interfaces:**
- Produces: `DesignTokens`, `LIGHT_TOKENS`, `load_theme_qss() -> str`.

- [ ] **Step 1: Write the failing token and dependency tests**

```python
from pathlib import Path
from desktop_ui.tokens import LIGHT_TOKENS, load_theme_qss

def test_approved_light_tokens_are_stable():
    assert LIGHT_TOKENS.app_background == "#F4F7FA"
    assert LIGHT_TOKENS.primary == "#1769AA"
    assert LIGHT_TOKENS.nav_expanded == 220
    assert LIGHT_TOKENS.nav_collapsed == 56
    assert LIGHT_TOKENS.inspector_width == 360
    assert "@APP_BACKGROUND@" not in load_theme_qss()

def test_pyside6_and_notice_are_declared():
    assert "PySide6==6.11.1" in Path("requirements.txt").read_text("utf-8")
    assert "LGPL-3.0" in Path("THIRD_PARTY_NOTICES.md").read_text("utf-8")
```

- [ ] **Step 2: Run the test and confirm import/declaration failures**

Run: `python -m unittest tests.test_desktop_ui_tokens -v`

- [ ] **Step 3: Implement immutable tokens and QSS substitution**

```python
@dataclass(frozen=True)
class DesignTokens:
    app_background: str = "#F4F7FA"
    primary: str = "#1769AA"
    nav_expanded: int = 220
    nav_collapsed: int = 56
    inspector_width: int = 360

LIGHT_TOKENS = DesignTokens()

def load_theme_qss() -> str:
    source = resources.files("desktop_ui").joinpath("theme.qss").read_text("utf-8")
    return source.replace("@APP_BACKGROUND@", LIGHT_TOKENS.app_background).replace("@PRIMARY@", LIGHT_TOKENS.primary)
```

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_desktop_ui_tokens -v`

- [ ] **Step 5: Commit**

```powershell
git add requirements.txt requirements-build.txt THIRD_PARTY_NOTICES.md desktop_ui tests/test_desktop_ui_tokens.py
git commit -m "feat: add PySide6 UI foundation"
```

### Task 2: Extract a framework-independent workflow facade

**Files:**
- Create: `desktop_ui/models.py`
- Create: `desktop_ui/workflow_facade.py`
- Modify: `faculty_workflow/ai_settings.py`
- Test: `tests/test_desktop_ui_facade.py`

**Interfaces:**
- Consumes: `WorkflowService`, `WorkflowDatabase`, `AiSettingsStore`, `AppPaths`.
- Produces: `WorkflowFacade.prepare_urls(raw: str) -> UrlPreparation`, `create_direct_tasks(request: NewCrawlRequest) -> str`, `ai_settings() -> AiSettingsView`, `save_ai_settings(command: SaveAiSettings) -> AiSettingsView`.

- [ ] **Step 1: Write failing facade tests for validation and masked keys**

```python
def test_prepare_urls_reports_valid_duplicate_and_invalid_lines(facade):
    result = facade.prepare_urls("https://a.edu/faculty\nhttps://a.edu/faculty\nnot-a-url")
    assert result.valid_urls == ("https://a.edu/faculty",)
    assert result.duplicate_lines == ((2, "https://a.edu/faculty"),)
    assert result.invalid_lines == ((3, "not-a-url"),)
    assert not result.can_start

def test_ai_view_never_returns_plaintext_key(facade_with_key):
    view = facade_with_key.ai_settings()
    assert view.key_configured is True
    assert not hasattr(view, "api_key")
```

- [ ] **Step 2: Run the focused tests and confirm missing types**

Run: `python -m unittest tests.test_desktop_ui_facade -v`

- [ ] **Step 3: Implement UI dataclasses and facade methods**

```python
@dataclass(frozen=True)
class UrlPreparation:
    valid_urls: tuple[str, ...]
    duplicate_lines: tuple[tuple[int, str], ...]
    invalid_lines: tuple[tuple[int, str], ...]
    @property
    def can_start(self) -> bool:
        return bool(self.valid_urls) and not self.invalid_lines

@dataclass(frozen=True)
class AiSettingsView:
    enabled: bool
    provider: str
    base_url: str
    model: str
    key_configured: bool
```

Use existing URL normalization and `AiSettingsStore`; do not duplicate provider validation or add a plaintext key getter.

- [ ] **Step 4: Run facade, AI settings, batch, and privacy tests**

Run: `python -m unittest tests.test_desktop_ui_facade tests.test_workflow_ai_settings tests.test_batch tests.test_consent -v`

- [ ] **Step 5: Commit**

```powershell
git add desktop_ui/models.py desktop_ui/workflow_facade.py faculty_workflow/ai_settings.py tests/test_desktop_ui_facade.py
git commit -m "refactor: add desktop workflow facade"
```

### Task 3: Add AI usage queries without changing call accounting

**Files:**
- Modify: `faculty_workflow/database.py`
- Modify: `desktop_ui/models.py`
- Modify: `desktop_ui/workflow_facade.py`
- Test: `tests/test_workflow_database.py`
- Test: `tests/test_desktop_ui_ai_settings.py`

**Interfaces:**
- Produces: `WorkflowDatabase.ai_usage_summary(since: datetime | None) -> sqlite3.Row`, `WorkflowDatabase.list_ai_usage(task_id: str | None, limit: int = 200) -> list[sqlite3.Row]`, `WorkflowFacade.ai_usage() -> AiUsageView`.

- [ ] **Step 1: Write failing database aggregation tests**

```python
def test_ai_usage_summary_aggregates_success_failure_tokens_and_cost(database, task_id):
    database.record_api_call(task_id, operation="parse", model="model-a", response_id="r1", input_tokens=100, output_tokens=20, estimated_cost_usd=0.04, status="succeeded")
    database.record_api_call(task_id, operation="parse", model="model-a", input_tokens=10, estimated_cost_usd=0.0, status="failed", error="timeout")
    row = database.ai_usage_summary(since=None)
    assert dict(row) == {"calls": 2, "succeeded": 1, "failed": 1, "input_tokens": 110, "output_tokens": 20, "estimated_cost_usd": 0.04}
```

- [ ] **Step 2: Run tests and confirm missing query APIs**

Run: `python -m unittest tests.test_workflow_database tests.test_desktop_ui_ai_settings -v`

- [ ] **Step 3: Implement parameterized aggregate/detail SQL**

```python
def ai_usage_summary(self, since=None):
    where, params = ("", ()) if since is None else ("WHERE created_at >= ?", (since.isoformat(),))
    with closing(self.connect()) as connection:
        return connection.execute(f"""
        SELECT COUNT(*) calls,
               SUM(status = 'succeeded') succeeded,
               SUM(status != 'succeeded') failed,
               COALESCE(SUM(input_tokens), 0) input_tokens,
               COALESCE(SUM(output_tokens), 0) output_tokens,
               COALESCE(SUM(estimated_cost_usd), 0) estimated_cost_usd
        FROM api_calls {where}
        """, params).fetchone()
```

Match the actual model-call table name and connection helper already present in the schema; do not migrate or recalculate historical costs.

- [ ] **Step 4: Run database and reporting regression tests**

Run: `python -m unittest tests.test_workflow_database tests.test_workflow_reporting tests.test_desktop_ui_ai_settings -v`

- [ ] **Step 5: Commit**

```powershell
git add faculty_workflow/database.py desktop_ui/models.py desktop_ui/workflow_facade.py tests/test_workflow_database.py tests/test_desktop_ui_ai_settings.py
git commit -m "feat: expose AI usage summaries"
```

### Task 4: Build the reusable Qt shell and responsive navigation

**Files:**
- Create: `desktop_ui/app.py`
- Create: `desktop_ui/main_window.py`
- Create: `desktop_ui/icons.py`
- Create: `desktop_ui/widgets/status_badge.py`
- Create: `desktop_ui/widgets/info_bar.py`
- Test: `tests/test_desktop_ui_shell.py`
- Test: `tests/test_desktop_ui_accessibility.py`

**Interfaces:**
- Consumes: `WorkflowFacade`, `load_theme_qss()`.
- Produces: `MainWindow.navigate(page_id: str)`, `MainWindow.set_background_status(status: BackgroundStatus)`, `run_desktop() -> int`.

- [ ] **Step 1: Write offscreen shell and keyboard tests**

```python
def test_shell_has_six_primary_destinations(self):
    window = MainWindow(self.facade)
    self.addCleanup(window.close)
    self.assertEqual(window.minimumSize().width(), 1180)
    self.assertEqual(window.page_ids(), ("overview", "tasks", "verification", "runs", "sessions", "settings"))

def test_ctrl_comma_opens_settings(self):
    QTest.keyClick(self.window, Qt.Key_Comma, Qt.ControlModifier)
    self.assertEqual(self.window.current_page_id(), "settings")
```

- [ ] **Step 2: Run with `QT_QPA_PLATFORM=offscreen` and confirm failures**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_shell tests.test_desktop_ui_accessibility -v`

- [ ] **Step 3: Implement the title bar, grouped nav, page stack, shortcuts, and focus names**

Use `QMainWindow`, `QStackedWidget`, standard Windows window controls, `QShortcut`, accessible names, and Qt standard icons or project-owned SVGs. Keep native maximize/minimize/close behavior; do not fake system semantics.

- [ ] **Step 4: Run shell tests at 1440 × 900 and 1180 × 720**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_shell tests.test_desktop_ui_accessibility -v`

- [ ] **Step 5: Commit**

```powershell
git add desktop_ui/app.py desktop_ui/main_window.py desktop_ui/icons.py desktop_ui/widgets tests/test_desktop_ui_shell.py tests/test_desktop_ui_accessibility.py
git commit -m "feat: add responsive PySide6 application shell"
```

### Task 5: Implement multiline URL creation and XLSX source selection

**Files:**
- Create: `desktop_ui/dialogs/new_crawl.py`
- Modify: `desktop_ui/workflow_facade.py`
- Test: `tests/test_desktop_ui_new_crawl.py`

**Interfaces:**
- Consumes: `WorkflowFacade.prepare_urls`, `WorkflowFacade.create_direct_tasks`, existing XLSX importer.
- Produces: `NewCrawlDialog.requested: Signal[NewCrawlRequest]`.

- [ ] **Step 1: Write tests for 20 URLs, duplicate warnings, invalid blocking, and button copy**

```python
def test_twenty_valid_urls_enable_exact_task_count(self):
    urls = "\n".join(f"https://school-{i}.edu/faculty" for i in range(20))
    self.dialog.url_editor.setPlainText(urls)
    self.assertEqual(self.dialog.summary_label.text(), "20 个有效 · 将创建 20 个独立任务")
    self.assertEqual(self.dialog.start_button.text(), "开始 20 个任务")
    self.assertTrue(self.dialog.start_button.isEnabled())
```

- [ ] **Step 2: Run focused tests and confirm the dialog is absent**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_new_crawl -v`

- [ ] **Step 3: Implement `QPlainTextEdit`, line gutter, debounced validation, mode cards, and output picker**

Validation must call the facade, display all invalid line numbers, list duplicates as ignored, and emit a request only when `can_start` is true. XLSX mode must reuse existing importer validation rather than duplicating spreadsheet parsing.

- [ ] **Step 4: Run dialog, batch, importer, and workflow service tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_new_crawl tests.test_batch tests.test_workflow_service -v`

- [ ] **Step 5: Commit**

```powershell
git add desktop_ui/dialogs/new_crawl.py desktop_ui/workflow_facade.py tests/test_desktop_ui_new_crawl.py
git commit -m "feat: add multiline batch URL creation"
```

### Task 6: Implement AI settings, masked key lifecycle, and usage view

**Files:**
- Create: `desktop_ui/pages/ai_settings.py`
- Create: `desktop_ui/dialogs/api_key.py`
- Modify: `desktop_ui/pages/settings.py`
- Test: `tests/test_desktop_ui_ai_settings.py`

**Interfaces:**
- Consumes: `AiSettingsView`, `AiUsageView`, `SaveAiSettings`, facade save/delete/test methods.
- Produces: AI settings page matching the approved `ai.png` state.

- [ ] **Step 1: Write tests that prevent plaintext redisplay and verify usage metrics**

```python
def test_saved_key_is_masked_and_never_inserted_into_editor(self):
    self.page.refresh()
    self.assertEqual(self.page.key_status.text(), "已配置")
    self.page.open_replace_key_dialog()
    self.assertEqual(self.page.key_dialog.key_edit.text(), "")

def test_usage_cards_render_database_values(page, facade):
    page.refresh()
    assert page.calls_value.text() == "128"
    assert page.tokens_value.text() == "1.84M"
    assert page.cost_value.text() == "$2.74"
```

- [ ] **Step 2: Run focused tests and confirm missing page/dialog**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_ai_settings -v`

- [ ] **Step 3: Implement provider fields, key replacement/delete confirmation, async connection test, usage cards, details table, and budget input**

Never persist masked text as a key. A blank key during metadata-only edits means “retain existing encrypted key”; explicit deletion calls `delete_key()`.

- [ ] **Step 4: Run AI provider, settings, database, and privacy tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_ai_settings tests.test_workflow_ai_settings tests.test_workflow_provider tests.test_workflow_database tests.test_consent -v`

- [ ] **Step 5: Commit**

```powershell
git add desktop_ui/pages/ai_settings.py desktop_ui/dialogs/api_key.py desktop_ui/pages/settings.py tests/test_desktop_ui_ai_settings.py
git commit -m "feat: add secure AI settings and usage UI"
```

### Task 7: Implement overview, task inspector, verification, runs, sessions, and storage pages

**Files:**
- Create: `desktop_ui/pages/overview.py`
- Create: `desktop_ui/pages/tasks.py`
- Create: `desktop_ui/pages/verification.py`
- Create: `desktop_ui/pages/runs.py`
- Create: `desktop_ui/pages/sessions.py`
- Create: `desktop_ui/pages/settings.py`
- Create: `desktop_ui/pages/storage.py`
- Create: `desktop_ui/widgets/data_table.py`
- Create: `desktop_ui/widgets/inspector.py`
- Create: `desktop_ui/widgets/empty_state.py`
- Test: `tests/test_desktop_ui_pages.py`

**Interfaces:**
- Consumes: facade snapshot/query methods and existing safe view data.
- Produces: page `refresh()` methods and typed user-intent signals; pages do not access SQLite or filesystem paths directly.

- [ ] **Step 1: Write one behavior-focused failing test per page**

```python
def test_task_selection_opens_360px_inspector(self):
    self.tasks_page.select_task("task-1")
    self.assertTrue(self.tasks_page.inspector.isVisible())
    self.assertEqual(self.tasks_page.inspector.width(), 360)

def test_verification_page_states_compliance_boundary(verification_page):
    assert "不会自动破解 CAPTCHA" in verification_page.info_bar.text()

def test_session_clear_emits_exact_hostname(self):
    spy = QSignalSpy(self.sessions_page.clear_requested)
    self.sessions_page.request_clear("cs.stanford.edu")
    self.assertEqual(spy.count(), 1)
    self.assertEqual(spy.at(0), ["cs.stanford.edu"])
```

- [ ] **Step 2: Run the page suite and confirm missing widgets/pages**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_pages -v`

- [ ] **Step 3: Implement pages to the approved renderings using shared QSS components**

Use 40 px table rows, low-contrast separators, text/icon status badges, one primary action per region, 360 px inspector, InfoBars for actionable state, and confirmation dialogs for destructive cleanup.

- [ ] **Step 4: Run page, controller, verification, session, retention, and diagnostics tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_pages tests.test_ui_controller tests.test_verification tests.test_session_store tests.test_retention tests.test_diagnostics -v`

- [ ] **Step 5: Commit**

```powershell
git add desktop_ui/pages desktop_ui/widgets tests/test_desktop_ui_pages.py
git commit -m "feat: add modern scientific utility pages"
```

### Task 8: Add non-blocking workers, event polling, tray behavior, and shutdown safety

**Files:**
- Create: `desktop_ui/workers.py`
- Modify: `desktop_ui/app.py`
- Modify: `desktop_ui/main_window.py`
- Modify: `desktop_ui/workflow_facade.py`
- Test: `tests/test_desktop_ui_workers.py`
- Test: `tests/test_desktop_ui_shell.py`

**Interfaces:**
- Produces: `WorkerSignals(progress, succeeded, failed, verification_required)`, `WorkerPool.submit(command)`, graceful `MainWindow.request_close()`.

- [ ] **Step 1: Write tests for main-thread signal delivery, stop-after-current, verification, and close-with-active-task**

```python
def test_worker_failure_is_redacted_before_ui_signal(self):
    spy = QSignalSpy(self.worker_pool.failed)
    self.worker_pool.submit(lambda: (_ for _ in ()).throw(RuntimeError("token=secret")))
    self.assertTrue(spy.wait(2000))
    self.assertNotIn("secret", spy.at(0)[0])
```

- [ ] **Step 2: Run worker tests and confirm missing adapters**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_workers tests.test_desktop_ui_shell -v`

- [ ] **Step 3: Implement `QRunnable`/`QThreadPool` adapters and tray state**

All crawler/database work that may block runs outside the GUI thread. UI updates occur only through queued Qt signals. Closing with active work offers “最小化到托盘 / 完成当前任务后退出 / 取消”.

- [ ] **Step 4: Run worker and existing shutdown/desktop tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_desktop_ui_workers tests.test_desktop_ui_shell tests.test_desktop_app tests.test_workflow_desktop -v`

- [ ] **Step 5: Commit**

```powershell
git add desktop_ui/workers.py desktop_ui/app.py desktop_ui/main_window.py desktop_ui/workflow_facade.py tests/test_desktop_ui_workers.py tests/test_desktop_ui_shell.py
git commit -m "feat: add safe Qt background execution"
```

### Task 9: Switch packaging entry after parity and update documentation

**Files:**
- Modify: `desktop_app.py`
- Modify: `faculty_crawler.spec`
- Modify: `build_installer.ps1`
- Modify: `README.md`
- Modify: `使用说明.txt`
- Modify: `tests/test_release.py`
- Modify: `tests/test_handoff.py`
- Modify: `tests/test_desktop_app.py`

**Interfaces:**
- Consumes: `desktop_ui.run_desktop()`.
- Produces: packaged `FacultyCrawler.exe` starts the PySide6 shell; `FACULTY_CRAWLER_LEGACY_UI=1` starts the retained Tk diagnostic fallback for one release.

- [ ] **Step 1: Write failing entry, packaging-data, and documentation tests**

```python
def test_packaged_entry_uses_pyside6_by_default(monkeypatch):
    monkeypatch.delenv("FACULTY_CRAWLER_LEGACY_UI", raising=False)
    assert desktop_app.resolve_desktop_entry().__module__ == "desktop_ui"

def test_legacy_ui_requires_explicit_environment_opt_in(monkeypatch):
    monkeypatch.setenv("FACULTY_CRAWLER_LEGACY_UI", "1")
    assert desktop_app.resolve_desktop_entry().__module__ == "workflow_desktop"
```

- [ ] **Step 2: Run release tests and confirm the old entry is still selected**

Run: `python -m unittest tests.test_desktop_app tests.test_release tests.test_handoff -v`

- [ ] **Step 3: Implement entry resolution, bundle QSS/icons/Qt plugins, and document AI key plus multi-URL usage**

```python
def resolve_desktop_entry():
    if os.environ.get("FACULTY_CRAWLER_LEGACY_UI") == "1":
        from workflow_desktop import main
        return main
    from desktop_ui import run_desktop
    return run_desktop
```

Ensure PyInstaller collects `desktop_ui/theme.qss`, project icons, required Qt platform plugins, and no QFluentWidgets package.

- [ ] **Step 4: Run the full automated suite**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest discover -s tests -v`

- [ ] **Step 5: Build and smoke-test the Windows executable**

Run: `powershell -ExecutionPolicy Bypass -File .\build_installer.ps1`

Expected checks: executable opens at 1440 × 900, resizes to 1180 × 720, accepts 20 pasted URLs, saves/replaces/deletes a DPAPI key, shows recorded usage, starts a local-only task, handles a verification-required task, minimizes to tray, and exits without orphaning Chromium or translation processes.

- [ ] **Step 6: Commit**

```powershell
git add desktop_app.py faculty_crawler.spec build_installer.ps1 README.md 使用说明.txt tests/test_desktop_app.py tests/test_release.py tests/test_handoff.py
git commit -m "feat: ship the PySide6 desktop experience"
```

## Final Verification Gate

- [ ] Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest discover -s tests -v`
- [ ] Run: `git diff --check`
- [ ] Confirm `rg -n "QFluentWidgets|qfluentwidgets" requirements*.txt faculty_crawler.spec desktop_ui` returns no dependency/import.
- [ ] Confirm AI key plaintext is absent from JSON, logs, diagnostics ZIPs, database rows, screenshots, and test fixtures.
- [ ] Confirm nine approved mockup states are represented by the implemented pages/dialog.
- [ ] Complete real Windows QA at 100%, 125%, and 150% scaling and at both 1440 × 900 and 1180 × 720.
- [ ] Record installer size change, startup time, and idle memory compared with v2.1.0; treat the measurements as release notes, not pass/fail gates unless startup exceeds 5 seconds or idle memory exceeds 300 MB on the validation machine.
