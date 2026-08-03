# Faculty Crawler UI 完整视觉重做实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with checkpoints. Do not modify workflow business logic or release configuration.

**Goal:** 在不改变抓取、验证、会话、导出或 AI 业务行为的前提下，将 PySide6 Faculty Crawler 重做为已确认的 Modern Scientific Utility 中文界面，并用真实窗口截图完成视觉验收。

**Architecture:** 以 `desktop_ui/tokens.py` 和 `theme.qss` 作为唯一视觉令牌来源，以 `MainWindow` 负责中文外壳和导航，以共享 widgets 负责表格、状态、空状态、InfoBar、检查器和设置行，以各 page/dialog 负责页面组合。验收数据通过独立的内存 `FixtureFacade` 注入 `run_desktop`，默认生产启动仍使用 `WorkflowFacade`。

**Tech Stack:** Python 3.12 runtime, PySide6 6.11.1, native Qt widgets, project-owned QSS, `unittest`, `QTest`, `QSignalSpy`, Windows Computer Use screenshots.

## Global Constraints

- UI 基准窗口为 1440×900；最小正式支持窗口为 1180×720。
- 左侧导航展开 220px、折叠 56px；右侧检查器 360px；标题栏 48px；页面工具栏 64–76px。
- 正文和交互文字不低于 12px，使用 `Segoe UI Variable`, `Microsoft YaHei UI`, `Segoe UI` 字体栈。
- 所有用户可见应用名称、导航、按钮、状态、空状态、InfoBar、Toast、确认弹窗和设置标签使用简体中文。
- API、URL、Token、Excel/XLSX、DeepSeek、Windows DPAPI、robots、CAPTCHA、域名、模型 ID、任务 ID 和运行 ID 可保留英文。
- 只使用原生 PySide6 与项目自有 QSS；不引入 QFluentWidgets 或新的 UI 依赖。
- 不修改 workflow、数据库 schema、加密、网络请求、浏览器验证边界、导出格式、版本号或发布配置。
- 内存演示数据只在显式验收 fixture 启动路径中存在，不读取或写入生产数据库，不调用网络、AI 或浏览器。
- 每个任务先写失败测试，再实现最小改动，再运行该任务的专项测试；每个任务完成后单独提交。

---

## Task 1: 统一设计令牌、图标语义与主题 QSS

**Files:**
- Modify: `desktop_ui/tokens.py`
- Modify: `desktop_ui/theme.qss`
- Modify: `desktop_ui/icons.py`
- Test: `tests/test_desktop_ui_tokens.py`

**Interfaces:**
- `DesignTokens` 继续作为 `load_theme_qss()` 的唯一令牌来源，并新增颜色、尺寸、字体和圆角字段；现有 `LIGHT_TOKENS.nav_expanded`, `nav_collapsed`, `inspector_width` 保持可用。
- `navigation_item(page_id: str) -> NavigationItem` 返回中文 `label` 和稳定图标语义；页面 ID 不变。
- `load_theme_qss() -> str` 返回不含 `@TOKEN@` 占位符的完整 QSS。

- [ ] **Step 1: Write the failing token tests**

在 `tests/test_desktop_ui_tokens.py` 增加：

```python
def test_modern_tokens_match_approved_spec(self):
    self.assertEqual(LIGHT_TOKENS.app_background, "#F4F7FA")
    self.assertEqual(LIGHT_TOKENS.nav_background, "#EDF2F7")
    self.assertEqual(LIGHT_TOKENS.surface_primary, "#FFFFFF")
    self.assertEqual(LIGHT_TOKENS.primary, "#1769AA")
    self.assertEqual(LIGHT_TOKENS.nav_expanded, 220)
    self.assertEqual(LIGHT_TOKENS.nav_collapsed, 56)
    self.assertEqual(LIGHT_TOKENS.inspector_width, 360)

def test_theme_has_shared_control_and_table_contracts(self):
    qss = load_theme_qss()
    self.assertNotIn("@", qss)
    for selector in ("QPushButton", "QLineEdit", "QTableWidget", "QToolButton", "QTableWidget::item:selected"):
        self.assertIn(selector, qss)
    self.assertIn("#1769AA", qss)

def test_primary_navigation_labels_are_chinese(self):
    self.assertEqual(tuple(item.label for item in NAVIGATION_ITEMS), ("概览", "任务", "人工验证", "运行历史", "站点会话", "设置"))
```

- [ ] **Step 2: Run the focused tests and verify the new assertions fail**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_tokens.py -q`  
Expected: FAIL because the current token set lacks navigation background/surface values and navigation labels are English.

- [ ] **Step 3: Implement the token and QSS contract**

Extend `DesignTokens` with the approved background, surface, text, border, status, control, table, radius and shadow values. Replace QSS translucent surfaces and default Qt padding with explicit selectors for panels, cards, buttons, inputs, checkboxes, combo boxes, scroll bars, tables, focus rings and disabled states. Keep `load_theme_qss()` as the only token substitution path. Replace standard navigation labels with the Chinese labels while preserving page IDs.

- [ ] **Step 4: Run the focused tests and inspect QSS output**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_tokens.py -q`  
Expected: PASS with no unresolved `@TOKEN@` markers.

- [ ] **Step 5: Commit the token/theme unit**

Run:

```powershell
git add desktop_ui/tokens.py desktop_ui/theme.qss desktop_ui/icons.py tests/test_desktop_ui_tokens.py
git commit -m "feat: establish Chinese scientific utility theme tokens"
```

## Task 2: Rebuild the application shell, navigation and background status

**Files:**
- Modify: `desktop_ui/main_window.py`
- Modify: `desktop_ui/widgets/status_badge.py`
- Modify: `desktop_ui/widgets/info_bar.py`
- Test: `tests/test_desktop_ui_shell.py`
- Test: `tests/test_desktop_ui_accessibility.py`

**Interfaces:**
- `MainWindow.page_ids() -> tuple[str, ...]`, `navigate(page_id: str)`, `set_navigation_collapsed(bool)` and `background_status_text()` remain compatible with existing tests and page wiring.
- `StatusBadge.set_status(status: BackgroundStatus)` continues to update visible text and accessible name.
- Worker signals, shortcut bindings and close/tray semantics remain behaviorally unchanged.

- [ ] **Step 1: Write failing shell and accessibility assertions**

Add assertions for window title `教师目录采集器`, Chinese group labels `工作/记录/系统`, Chinese navigation accessible names, Chinese background text `空闲/运行中/等待人工验证`, and Chinese close-warning copy. Assert `Ctrl+N`, `Ctrl+,`, `Ctrl+F` and `Esc` remain wired.

- [ ] **Step 2: Run the shell tests and verify the failures**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_shell.py tests/test_desktop_ui_accessibility.py -q`  
Expected: FAIL on English title, group labels, status text and accessible names.

- [ ] **Step 3: Implement the shell copy and layout**

Change only shell presentation: use the Chinese application title, group labels, navigation names, tooltips, tray menu copy, background InfoBar copy and close confirmation copy. Keep page IDs, signal connections, worker pool, shortcuts and close decisions intact. Set content margins and spacing to the approved 220/48/64–76/360 layout tokens. Add explicit accessible names for title bar controls and the navigation toggle.

- [ ] **Step 4: Run the shell and accessibility tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_shell.py tests/test_desktop_ui_accessibility.py -q`  
Expected: PASS, including collapsed navigation at the existing breakpoint and the unchanged shortcut behavior.

- [ ] **Step 5: Commit the shell unit**

Run:

```powershell
git add desktop_ui/main_window.py desktop_ui/widgets/status_badge.py desktop_ui/widgets/info_bar.py tests/test_desktop_ui_shell.py tests/test_desktop_ui_accessibility.py
git commit -m "feat: rebuild Chinese desktop shell and navigation"
```

## Task 3: Replace shared data, empty-state and inspector presentation

**Files:**
- Modify: `desktop_ui/widgets/data_table.py`
- Modify: `desktop_ui/widgets/empty_state.py`
- Modify: `desktop_ui/widgets/inspector.py`
- Create: `desktop_ui/widgets/page_header.py`
- Create: `desktop_ui/widgets/settings_row.py`
- Test: `tests/test_desktop_ui_pages.py`

**Interfaces:**
- `DataTable(headers: Sequence[str])`, `set_rows(rows)`, `select_id(row_id: str)` and `selection_changed` remain compatible.
- `EmptyState(title: str, detail: str, action: str = "")` remains constructible by existing pages and exposes an optional primary action button.
- `Inspector(title: str)` remains fixed at `LIGHT_TOKENS.inspector_width` and accepts `show_details(Mapping[str, object])`.
- New `PageHeader(title: str, description: str, primary_text: str = "")` exposes `primary_clicked` and renders one primary action.
- New `SettingsRow(title: str, hint: str, control: QWidget)` aligns copy left and control right without changing control signals.

- [ ] **Step 1: Write failing widget tests**

Add tests that check 40px table rows, no vertical grid, selected-row soft background, empty-state title/detail/action alignment, inspector width 360px, and `PageHeader` Chinese title plus one primary button.

- [ ] **Step 2: Run the widget-focused tests and verify failure**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py -q -k "table or empty or inspector or header"`  
Expected: FAIL for missing page header, missing icon/action contract and the old default table presentation.

- [ ] **Step 3: Implement the shared widgets**

Add the new page header and settings row widgets. Add a small line icon to `EmptyState` using the project icon helper, preserve keyboard focus, and keep the existing signal names. Configure table header height 36px, row height 40px, right alignment for numeric cells, and selection behavior without changing row IDs.

- [ ] **Step 4: Run page/widget tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py -q`  
Expected: PASS for the shared component assertions and all existing page intent tests.

- [ ] **Step 5: Commit the shared presentation unit**

Run:

```powershell
git add desktop_ui/widgets tests/test_desktop_ui_pages.py
git commit -m "feat: add shared utility panels and data presentation"
```

## Task 4: Rebuild Overview, Tasks and Manual Verification pages

**Files:**
- Modify: `desktop_ui/pages/overview.py`
- Modify: `desktop_ui/pages/tasks.py`
- Modify: `desktop_ui/pages/verification.py`
- Test: `tests/test_desktop_ui_pages.py`
- Test: `tests/test_desktop_ui_shell.py`

**Interfaces:**
- Keep `OverviewPage.new_crawl_requested`, `TasksPage.export_requested`, `VerificationPage.start_requested`, `defer_requested` and `complete_requested` unchanged.
- Keep facade calls `task_rows`, `task_detail`, `verification_rows` and existing row IDs unchanged.

- [ ] **Step 1: Write failing page composition tests**

Using the existing `FakeFacade`, assert page headings are `概览/任务/人工验证`, Overview exposes quick-start/current-run/attention/recent-task object names, Tasks exposes search, status segments, table and a 360px inspector, and Verification exposes a Chinese compliance InfoBar, `MockBrowserCard`, three numbered instructions, and Chinese action buttons.

- [ ] **Step 2: Run page tests and verify failure**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py -q`  
Expected: FAIL on missing object names, English labels and absent page composition.

- [ ] **Step 3: Implement the page compositions**

Use `PageHeader` and the shared widgets. Build Overview cards and recent table while retaining current `refresh()` and `new_crawl_requested` behavior. Build Tasks toolbar/segments/table/inspector while retaining task selection and export signal. Build Verification queue/detail/mock browser/steps while retaining start/defer/complete signals and the explicit no-bypass compliance copy. Map all statuses through one Chinese status formatter; do not alter facade records or workers.

- [ ] **Step 4: Run page and shell tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py tests/test_desktop_ui_shell.py -q`  
Expected: PASS, including the existing 360px inspector, export intent and manual verification signal tests.

- [ ] **Step 5: Commit the work pages**

Run:

```powershell
git add desktop_ui/pages/overview.py desktop_ui/pages/tasks.py desktop_ui/pages/verification.py tests/test_desktop_ui_pages.py tests/test_desktop_ui_shell.py
git commit -m "feat: redesign overview tasks and manual verification pages"
```

## Task 5: Rebuild Run History and Site Sessions pages

**Files:**
- Modify: `desktop_ui/pages/runs.py`
- Modify: `desktop_ui/pages/sessions.py`
- Test: `tests/test_desktop_ui_pages.py`

**Interfaces:**
- Keep `RunsPage.export_requested`, `SessionsPage.clear_requested`, `task_rows`, `session_rows` and selection IDs unchanged.
- Destructive session confirmation remains a `QMessageBox` decision followed by the existing signal; no cleanup call moves into the page.

- [ ] **Step 1: Write failing history/session tests**

Assert Chinese headings, run list/detail/timeline object names, metric labels, session expiry warning, search field, table columns and Chinese danger confirmation text. Assert selecting a completed run still emits its task ID and selecting a session still emits its exact hostname only after confirmation.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py -q -k "run or session"`  
Expected: FAIL on English copy and missing detail/timeline widgets.

- [ ] **Step 3: Implement the two page compositions**

Render fixture-compatible list/detail panes. Use a Chinese status badge, three metrics and a four-event timeline for a selected run. Use a Chinese InfoBar, search, expiry-aware table and top-level batch-clean action plus row-level clear for sessions. Keep export and clear signals and all facade calls intact.

- [ ] **Step 4: Run page tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py -q -k "run or session"`  
Expected: PASS.

- [ ] **Step 5: Commit the records pages**

Run:

```powershell
git add desktop_ui/pages/runs.py desktop_ui/pages/sessions.py tests/test_desktop_ui_pages.py
git commit -m "feat: redesign run history and site sessions"
```

## Task 6: Rebuild Settings, AI and Storage/Diagnostics pages

**Files:**
- Modify: `desktop_ui/pages/settings.py`
- Modify: `desktop_ui/pages/ai_settings.py`
- Modify: `desktop_ui/pages/storage.py`
- Test: `tests/test_desktop_ui_pages.py`
- Test: `tests/test_desktop_ui_ai_settings.py`

**Interfaces:**
- `SettingsPage.current_section()`, `navigate(section_id)`, `search_edit`, `ai_page` and `storage_page` remain compatible.
- `AiSettingsPage` keeps `save_settings`, `delete_key`, `test_connection`, `budget_changed` and existing facade methods.
- `StoragePage` keeps the three existing signals and confirmation boundaries.

- [ ] **Step 1: Write failing settings tests**

Assert the internal navigation is Chinese (`翻译与 AI`, `存储与诊断`), AI labels and settings rows are Chinese except the technical whitelist, API Key text never exposes plaintext, usage cards and table headers are Chinese, storage renders a segmented usage bar and grouped cleanup rows, and dangerous cleanup confirmation is Chinese.

- [ ] **Step 2: Run settings tests and verify failure**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py tests/test_desktop_ui_ai_settings.py -q`  
Expected: FAIL on English settings accessible names, flat storage actions and missing usage/storage composition.

- [ ] **Step 3: Implement settings layouts without changing facade behavior**

Use the shared `SettingsRow` and `SettingsGroup`. Keep only the two backed sections visible; do not add nonfunctional “常规/采集/关于” controls. Render AI provider, Base URL, model and API Key states with technical names preserved and all operator copy in Chinese. Render usage metrics, budget and details table. Render storage capacity bar, retention copy, separate cleanup rows and diagnostics export. Keep worker-triggered signals and QMessageBox confirmations unchanged in meaning.

- [ ] **Step 4: Run settings and AI tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_pages.py tests/test_desktop_ui_ai_settings.py -q`  
Expected: PASS, including encryption-safe API Key behavior and existing save/delete/test signals.

- [ ] **Step 5: Commit settings pages**

Run:

```powershell
git add desktop_ui/pages/settings.py desktop_ui/pages/ai_settings.py desktop_ui/pages/storage.py tests/test_desktop_ui_pages.py tests/test_desktop_ui_ai_settings.py
git commit -m "feat: redesign Chinese AI and storage settings"
```

## Task 7: Rebuild the New Crawl dialog states

**Files:**
- Modify: `desktop_ui/dialogs/new_crawl.py`
- Test: `tests/test_desktop_ui_new_crawl.py`

**Interfaces:**
- Keep `NewCrawlDialog.requested`, `xlsx_requested`, `select_url_mode()`, `select_xlsx_mode()`, `set_xlsx_path()`, `request` generation and `facade.prepare_urls()` behavior.
- Keep invalid URL blocking, duplicate URL reporting, XLSX validation, school override semantics and budget propagation unchanged.

- [ ] **Step 1: Write failing dialog visual/state tests**

Assert the dialog title/description, source choice cards, Chinese field labels, line-number editor, output directory row, compliance InfoBar and batch button are present. Add a test with 20 valid URLs plus one duplicate and assert the Chinese summary reports 20 valid URLs and one ignored duplicate; add a test that an invalid line disables the start button.

- [ ] **Step 2: Run dialog tests and verify failure**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_new_crawl.py -q`  
Expected: FAIL on missing choice-card structure and visual object names; existing validation tests must remain green or fail only on the new assertions.

- [ ] **Step 3: Implement the dialog composition**

Use a 700px dialog surface, Chinese title and description, two source cards, the existing line-number editor, `SettingsRow`-style fields, summary badges, compliance InfoBar and right-aligned cancel/primary actions. Preserve the existing request and validation methods; update only copy and presentation.

- [ ] **Step 4: Run dialog tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_new_crawl.py -q`  
Expected: PASS for URL/XLSX mode switching, duplicate/invalid validation and request payloads.

- [ ] **Step 5: Commit the dialog unit**

Run:

```powershell
git add desktop_ui/dialogs/new_crawl.py tests/test_desktop_ui_new_crawl.py
git commit -m "feat: redesign Chinese new crawl dialog"
```

## Task 8: Add an isolated in-memory visual fixture entry point

**Files:**
- Create: `desktop_ui/fixture.py`
- Modify: `desktop_ui/app.py`
- Test: `tests/test_desktop_ui_fixture.py`
- Test: `tests/test_desktop_ui_shell.py`

**Interfaces:**
- Create `FixtureFacade` with the page-facing methods `task_rows`, `task_detail`, `verification_rows`, `session_rows`, `storage_summary`, `ai_settings`, `ai_usage`, `ai_usage_details`, and `prepare_urls`.
- Create `build_fixture_facade() -> FixtureFacade` returning fixed rows for four tasks, one verification queue, three sessions, AI usage and storage.
- Extend `run_desktop(facade: object | None = None, *, fixture: bool = False) -> int`; when `fixture=True`, use `build_fixture_facade()`, otherwise retain `build_workflow_facade()`.
- `desktop_ui/app.py` reads only an explicit `FACULTY_CRAWLER_UI_FIXTURE=1` environment flag for fixture mode; default production startup remains unchanged.

- [ ] **Step 1: Write failing fixture tests**

Assert `build_fixture_facade().task_rows()` returns exactly four stable rows with statuses `running`, `needs_verification`, `completed`, `queued`; `verification_rows()` returns one row; `session_rows()` returns three rows with one warning expiry; `ai_usage()` and `storage_summary()` return deterministic nonzero values; and no fixture method accesses `AppPaths` or the database.

- [ ] **Step 2: Run fixture tests and verify failure**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_fixture.py -q`  
Expected: FAIL because the fixture module and explicit run option do not exist.

- [ ] **Step 3: Implement the in-memory facade and opt-in wiring**

Add immutable fixture dictionaries and methods returning copies/tuples so page rendering cannot mutate the fixture. Add the opt-in flag at the UI assembly boundary only; do not add environment checks to workflow or database code. Keep the production application name and normal facade assembly paths unchanged except for the already-approved Chinese shell title.

- [ ] **Step 4: Run fixture and shell tests**

Run: `.\.venv\Scripts\pytest.exe tests/test_desktop_ui_fixture.py tests/test_desktop_ui_shell.py -q`  
Expected: PASS, with production shell tests still constructing from their existing fake facades.

- [ ] **Step 5: Commit the fixture unit**

Run:

```powershell
git add desktop_ui/fixture.py desktop_ui/app.py tests/test_desktop_ui_fixture.py tests/test_desktop_ui_shell.py
git commit -m "test: add opt-in in-memory UI visual fixture"
```

## Task 9: Run full regression, Chinese whitelist checks and real screenshot acceptance

**Files:**
- Modify: `tests/test_desktop_ui_accessibility.py` if final object names require additional assertions.
- Create: `validation_output/ui-visual-audit/` screenshot artifacts outside tracked source, or use the approved visualizations directory.

**Interfaces:**
- No production interfaces change in this task.
- The fixture launch command is `$env:FACULTY_CRAWLER_UI_FIXTURE='1'; .\.venv\Scripts\pythonw.exe desktop_app.py` from the audit worktree.

- [ ] **Step 1: Run the complete UI regression suite**

Run:

```powershell
.\.venv\Scripts\pytest.exe tests/test_desktop_ui_tokens.py tests/test_desktop_ui_shell.py tests/test_desktop_ui_accessibility.py tests/test_desktop_ui_pages.py tests/test_desktop_ui_ai_settings.py tests/test_desktop_ui_new_crawl.py tests/test_desktop_ui_fixture.py tests/test_desktop_ui_facade.py tests/test_desktop_ui_verification_executor.py -q
```

Expected: PASS with no workflow or release tests modified.

- [ ] **Step 2: Run the English UI whitelist check**

Add a test helper in `tests/test_desktop_ui_accessibility.py` that walks visible text and accessible names for the shell and all pages, removes the explicit technical whitelist (`API`, `URL`, `Token`, `Excel`, `XLSX`, `DeepSeek`, `Windows DPAPI`, `robots`, `CAPTCHA`, IDs, domains and user-entered URLs), and fails on remaining English UI phrases.

- [ ] **Step 3: Launch the fixture in the real Windows GUI**

Run from the isolated worktree:

```powershell
$env:FACULTY_CRAWLER_UI_FIXTURE='1'
Start-Process -FilePath '.\.venv\Scripts\pythonw.exe' -ArgumentList 'desktop_app.py' -WorkingDirectory (Get-Location)
```

Use Windows Computer Use to select the returned `教师目录采集器` window, resize to 1440×900, and capture Overview, Tasks + inspector, Manual verification, Run history, Site sessions, Settings/AI, Storage, New Crawl single URL and New Crawl 20 URL states. Capture 1180×720 after verifying navigation collapse and inspector behavior. Do not click actions that start crawl, test AI, launch browser, clear data or export files.

- [ ] **Step 4: Compare screenshots with the approved mockup**

For each state verify title, navigation, primary action, content hierarchy, spacing, status text/icon/color, empty state, panel width, dialog bounds and absence of unintended English. Record any visual mismatch before claiming completion; do not replace screenshots with source/QSS inspection.

- [ ] **Step 5: Run the full repository regression suite**

Run: `.\.venv\Scripts\pytest.exe -q`  
Expected: all existing tests and new UI tests pass; if an unrelated baseline failure appears, report it separately and do not alter non-UI code to hide it.

- [ ] **Step 6: Commit only UI and test changes after screenshot acceptance**

Run:

```powershell
git status --short
git diff --name-only main...HEAD
```

Expected changed paths are limited to `desktop_ui/**`, `tests/test_desktop_ui_*.py`, the design/plan docs and screenshot artifacts outside tracked source. Do not commit generated `.venv`, user data, API keys, workflow database files or release files.

## Plan self-review

- Spec coverage: the plan covers the shell, tokens, shared widgets, all eight requested pages/states, New Crawl single/batch states, Chinese whitelist, responsive breakpoints, accessibility, in-memory fixture and real screenshot acceptance.
- Business safety: every page task preserves existing facade methods/signals; fixture mode is opt-in and in-memory; no workflow or database files are modified.
- Placeholder scan: no step requires a future decision, unspecified component, or “implement later” action; every task names exact files, tests and commands.
- Interface consistency: `MainWindow` keeps page IDs and shortcuts; `WorkflowFacade` methods remain unchanged; `FixtureFacade` supplies the page-facing read methods; page intent signals remain the existing names.

After this plan is approved for execution, use `superpowers:executing-plans` and complete tasks in order with the stated test and commit checkpoints.
