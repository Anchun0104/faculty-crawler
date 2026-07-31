# 版本演进文档与 2.1.0 候选发布实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可维护的版本演进文档，并将现有经过验证的 2.1.0 工作流改动整理为可供后续正式发布的本地候选提交。

**Architecture:** `README.md` 提供简短的用户入口与版本概览，`CHANGELOG.md` 作为版本功能的完整索引，`RELEASE_NOTES_2.1.0.md` 只描述该版本的发布内容。脚本用户继续在 `README_WORKFLOW_AI.md` 获取操作细节；四份文档通过明确的状态与相互链接避免重复说明漂移。

**Tech Stack:** Markdown、Git、Python unittest、PyInstaller 发布脚本、GitHub Releases（仅在用户另行批准后使用）。

## Global Constraints

- `2.1.0` 标签和 GitHub Release 尚未创建，所有文档必须标为待发布，不提供不存在的 2.1.0 下载链接。
- 当前稳定安装包链接必须指向已经验证资产的 `v2.0.0` Release。
- 文档不得承诺 AI 自动发现目录 URL、猜测邮箱，或尚未完成的安装包体积优化。
- 不修改或删除历史 `v1.0.0`、`v2.0.0` 标签和 Release 资产。
- 不创建、推送标签或对 GitHub 发布公开内容，除非用户在候选产物验证后明确授权。

---

### Task 1: 建立版本功能的规范索引

**Files:**
- Create: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `RELEASE_NOTES_2.1.0.md`
- Modify: `README_WORKFLOW_AI.md`
- Modify: `build_release.py`

**Interfaces:**
- Consumes: `VERSION` 中的 `2.1.0`、已确认的 `v1.0.0`/`v2.0.0` 标签和 2.1.0 工作流行为。
- Produces: README 版本摘要、完整 CHANGELOG、待发布的 2.1.0 说明，以及包含 CHANGELOG 的源码发布包。

- [ ] **Step 1: 写出文档验收清单**

建立下列固定检查点：README 同时出现 `v1.0.0`、`v2.0.0` 和 `v2.1.0`；2.0.0 下载链接使用 `/releases/download/v2.0.0/`；CHANGELOG 的 2.1.0 明确为待发布；AI README 只列出正式结果、`review_queue.xlsx` 和 `run_report.json`；源码包列表包含 `CHANGELOG.md`。

- [ ] **Step 2: 先运行验收检查，确认现有文档不满足它**

Run:

```powershell
rg -n "releases/download/FacultyCrawler|completed_evidence|audit\.json" README.md README_WORKFLOW_AI.md
Test-Path CHANGELOG.md
```

Expected: README 仍使用旧 `FacultyCrawler` 下载标签，AI README 仍提到旧证据表和 `audit.json`，且尚无 CHANGELOG。

- [ ] **Step 3: 做最小文档实现**

在 `CHANGELOG.md` 按 `2.1.0（待发布）`、`2.0.0（已发布）`、`1.0.0（已归档）` 倒序写入真实功能。README 增加简明版本演进、入口选择和发布/回退小节，并修正 2.0.0 资产 URL。2.1.0 Release Notes 写入速度策略、有限 review、运行报告与 AI 边界。AI README 链接版本演进，修正导出清单。把 `CHANGELOG.md` 加入 `build_release.py` 的根发布文件清单。

- [ ] **Step 4: 运行文档验收检查**

Run:

```powershell
rg -n "v1\.0\.0|v2\.0\.0|v2\.1\.0|releases/download/v2\.0\.0" README.md CHANGELOG.md RELEASE_NOTES_2.1.0.md
rg -n "completed_evidence|audit\.json" README_WORKFLOW_AI.md
python -m py_compile build_release.py
git diff --check
```

Expected: 三个版本均可检索；只出现规范化的 2.0.0 资产链接；AI README 不再宣称旧导出；Python 编译和 diff 检查通过。

- [ ] **Step 5: 提交文档索引改动**

```powershell
git add README.md README_WORKFLOW_AI.md CHANGELOG.md RELEASE_NOTES_2.1.0.md build_release.py
git commit -m "docs: document release evolution and 2.1 workflow"
```

### Task 2: 验证并归档 2.1.0 工作流候选代码

**Files:**
- Modify: `desktop_app.py`, `workflow.py`, `workflow_desktop.py`, `build_installer.ps1`, `faculty_crawler.spec`
- Modify: `faculty_workflow/ai_settings.py`, `database.py`, `fetcher.py`, `importers.py`, `providers.py`, `reporting.py`, `service.py`
- Modify: `tests/test_workflow_ai_settings.py`, `tests/test_workflow_desktop.py`, `tests/test_workflow_provider.py`, `tests/test_workflow_reporting.py`, `tests/test_workflow_service.py`
- Include: existing specs and plan under `docs/superpowers/`

**Interfaces:**
- Consumes: 2.1.0 workflow modifications already present in the isolated worktree.
- Produces: 一个可回退、可审计的本地 2.1.0 候选提交；不改变远程 `main` 或 GitHub Release。

- [ ] **Step 1: 审核候选差异范围**

Run:

```powershell
git diff --stat
git diff --check
git status --short
```

Expected: 改动仅涉及已批准的统一工作流、AI 设置、速度/review/report、打包入口、测试和设计记录；不包含运行数据、密钥、浏览器缓存或构建产物。

- [ ] **Step 2: 执行完整回归与静态检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall crawler faculty_workflow scripts workflow.py workflow_desktop.py desktop_app.py build_release.py
git diff --check
```

Expected: 所有可执行测试通过，编译无错误，且 diff 无空白问题。

- [ ] **Step 3: 构建并检查源码候选包**

Run:

```powershell
.\.venv\Scripts\python.exe build_release.py
.\.venv\Scripts\python.exe -c "import zipfile; z=zipfile.ZipFile('dist/faculty-crawler-windows.zip'); assert any(n.endswith('CHANGELOG.md') for n in z.namelist()); print(len(z.namelist()))"
```

Expected: 可重复的源码 ZIP 生成，且归档中包含 CHANGELOG、2.1.0 文档、工作流源码和测试；不含本地任务数据库、快照、密钥或构建缓存。

- [ ] **Step 4: 提交候选实现**

```powershell
git add desktop_app.py workflow.py workflow_desktop.py build_installer.ps1 faculty_crawler.spec build_release.py faculty_workflow tests docs/superpowers README.md README_WORKFLOW_AI.md RELEASE_NOTES_2.1.0.md CHANGELOG.md
git commit -m "feat: prepare evidence workflow 2.1.0 candidate"
```

Expected: 工作树只剩下 `dist/` 等被忽略的候选产物；提交记录可用于创建 `v2.1.0` 标签或安全回退。

### Task 3: 准备正式发布的验证交接（不公开发布）

**Files:**
- Read: `VERSION`, `build_installer.ps1`, `installer/faculty-crawler.iss`, `RELEASE_NOTES_2.1.0.md`
- Output: 本地安装器、SHA-256 和验证记录（仅在用户明确要求构建时生成）

**Interfaces:**
- Consumes: Task 2 的候选提交与通过的回归结果。
- Produces: 用户可审阅的候选发布证据；后续正式发布只需在用户授权后创建 `v2.1.0` 标签、上传资产并校验 Release。

- [ ] **Step 1: 核对版本与候选提交**

Run:

```powershell
Get-Content VERSION
git log -1 --oneline
git status --short
```

Expected: 版本为 `2.1.0`，工作树无待提交源代码或文档改动。

- [ ] **Step 2: 在用户授权后构建 Windows 安装器并计算哈希**

Run:

```powershell
.\build_installer.ps1
Get-FileHash dist\installer\FacultyCrawler-Setup-2.1.0.exe -Algorithm SHA256
```

Expected: 安装器文件名与 VERSION 一致，生成 SHA-256；构建过程不读取或写入 API key、任务数据库或结果文件。

- [ ] **Step 3: 记录发布前门槛**

在用户可见的交接中列出：候选提交、完整测试结果、源码 ZIP 检查、安装器 SHA-256、最终 Release Notes 内容。只有用户明确批准后，才执行 `git tag -a v2.1.0`、推送和 GitHub Release 资产上传。
